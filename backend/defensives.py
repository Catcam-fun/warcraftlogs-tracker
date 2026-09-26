"""
defensives.py - What defensive options a player had when they died.

For every death this answers, per defensive the player actually had:
  - active:     its buff was on them when they died
  - available:  they had it and it was off cooldown, but it wasn't pressed
  - cooldown:   it was pressed earlier and hadn't come back yet
plus whether they used a Healthstone / health potion this pull, and which raid
cooldowns or externals from other players were on them.

"Had it" comes from the talent loadout WarcraftLogs records at the start of
each pull (CombatantInfo), so nobody is blamed for a button they didn't take.
The ability list, cooldowns and talent mappings come from defensive_catalog.py,
generated from game data by scripts/build_defensive_catalog.py.
"""

from collections import defaultdict

from defensive_catalog import CATALOG
from warcraftlogs import graphql_query

# Cooldowns at or above this length reset when a boss pull ends, so only
# presses during the pull count. Shorter ones can carry over from before it.
ENCOUNTER_RESET_MS = 180_000

# Death strips auras at (or a few ms after) the death event; a buff removed
# this close to the death was still up when they died.
DEATH_AURA_GRACE_MS = 250

# A single-charge ability recast this much faster than its base cooldown
# means talents shortened it; trust the observed interval instead.
CDR_TOLERANCE_MS = 1_000

PERSONAL = {sid: d for sid, d in CATALOG.items() if d["kind"] == "personal"}
EXTERNAL = {sid: d for sid, d in CATALOG.items() if d["kind"] == "external"}
CONSUMABLE = {sid: d for sid, d in CATALOG.items() if d["kind"] in ("healthstone", "potion")}

CAST_IDS = sorted(set(PERSONAL) | set(CONSUMABLE))
BUFF_NAMES = sorted({d["name"] for d in list(PERSONAL.values()) + list(EXTERNAL.values())})
NAME_TO_ID = {}
for _sid, _d in list(PERSONAL.items()) + list(EXTERNAL.items()):
    NAME_TO_ID.setdefault(_d["name"], _sid)


# =============================================================================
# FETCHING (one report)
# =============================================================================

def _events_query(alias, data_type, filter_var):
    flt = f"filterExpression: ${filter_var}" if filter_var else ""
    return f"""
      {alias}: events(startTime: $startTime, endTime: $endTime, dataType: {data_type},
                      {flt} limit: 10000) {{ data nextPageTimestamp }}"""


def fetch_defensive_events(token, report_code, start_time, end_time, fetch_remaining):
    """Casts, defensive buffs and talent loadouts for one report, in one request.

    `fetch_remaining(token, code, data_type, filter, next_ts, end)` follows WCL
    pagination for any list that came back partial.
    """
    cast_filter = f"type = \"cast\" and ability.id in ({', '.join(map(str, CAST_IDS))})"
    buff_filter = "ability.name in (" + ", ".join(f'"{n}"' for n in BUFF_NAMES) + ")"
    query = """
    query($code: String!, $startTime: Float!, $endTime: Float!, $castFilter: String, $buffFilter: String) {
      reportData { report(code: $code) {""" + \
        _events_query("casts", "Casts", "castFilter") + \
        _events_query("buffs", "Buffs", "buffFilter") + \
        _events_query("combatants", "CombatantInfo", None) + """
      } }
    }"""
    data = graphql_query(token, query, {
        "code": report_code, "startTime": start_time, "endTime": end_time,
        "castFilter": cast_filter, "buffFilter": buff_filter,
    })
    report = (data.get("reportData") or {}).get("report") or {}
    out = {}
    for alias, data_type, flt in (("casts", "Casts", cast_filter), ("buffs", "Buffs", buff_filter),
                                  ("combatants", "CombatantInfo", None)):
        block = report.get(alias) or {}
        events = list(block.get("data") or [])
        if block.get("nextPageTimestamp"):
            events += fetch_remaining(token, report_code, data_type, flt, block["nextPageTimestamp"], end_time)
        out[alias] = events
    return index_defensive_events(out)


def index_defensive_events(raw):
    """Group raw WCL events by player so per-death lookups are cheap."""
    casts = defaultdict(list)           # sourceID -> [(ts, spellID)]
    for e in raw.get("casts", []):
        sid = e.get("abilityGameID")
        if e.get("type") == "cast" and sid in CATALOG and e.get("sourceID") is not None:
            casts[e["sourceID"]].append((e["timestamp"], sid))
    buffs = defaultdict(list)           # targetID -> [(ts, type, abilityGameID, sourceID)]
    for e in raw.get("buffs", []):
        if e.get("targetID") is not None:
            buffs[e["targetID"]].append((e["timestamp"], e.get("type"), e.get("abilityGameID"), e.get("sourceID")))
    talents = {}                        # (fightID, sourceID) -> set(trait node entry IDs)
    for e in raw.get("combatants", []):
        tree = e.get("talentTree")
        if tree is None or e.get("sourceID") is None:
            continue
        talents[(e.get("fight"), e["sourceID"])] = {t.get("id") for t in tree if t.get("id")}
    for lst in casts.values():
        lst.sort()
    for lst in buffs.values():
        lst.sort(key=lambda x: x[0])
    return {"casts": dict(casts), "buffs": dict(buffs), "talents": talents}


# =============================================================================
# PER-DEATH ANALYSIS
# =============================================================================

def _has_ability(sid, entry, player_class, spec, talent_entries, cast_ids_in_report, pressed_this_pull=()):
    if entry["class"] != player_class:
        return False
    if sid in pressed_this_pull:
        return True    # pressing it this pull proves they have it, whatever the talent record says
    if entry["specs"] and spec and spec not in entry["specs"]:
        return False
    if talent_entries and talent_entries & set(entry.get("replaced_by_entries", ())):
        return False   # a talent swapped this button for another one (Ice Cold replaces Ice Block)
    if entry["known"] == "baseline":
        # Without a known spec, only count spec-limited baselines if they were used.
        return not entry["specs"] or bool(spec) or sid in cast_ids_in_report
    if entry["known"] == "talent" and talent_entries is not None:
        return bool(talent_entries & set(entry["talent_entries"]))
    # "evidence" abilities, or talent data missing for this pull: pressed in this log = has it.
    return sid in cast_ids_in_report


def _effective_cooldown(entry, own_casts_of_spell):
    cd = entry["cooldown_ms"]
    if entry["charges"] == 1 and len(own_casts_of_spell) > 1:
        gaps = [b - a for a, b in zip(own_casts_of_spell, own_casts_of_spell[1:])]
        shortest = min(gaps)
        if shortest < cd - CDR_TOLERANCE_MS:
            cd = shortest
    return cd


def _charges_at(death_ts, casts_in_window, charges, recharge_ms):
    """Simulate charges up to the death. Returns (charges_left, ms_until_next)."""
    have, recharge_done = charges, None
    for t in casts_in_window:
        while recharge_done is not None and recharge_done <= t:
            have += 1
            recharge_done = recharge_done + recharge_ms if have < charges else None
        have = max(have - 1, 0)
        if recharge_done is None:
            recharge_done = t + recharge_ms
    while recharge_done is not None and recharge_done <= death_ts:
        have += 1
        recharge_done = recharge_done + recharge_ms if have < charges else None
    return have, (recharge_done - death_ts if recharge_done is not None else 0)


def _buffs_active_at(death_ts, buff_events):
    """abilityGameID -> sourceID for auras that were up when the player died."""
    up = {}
    for ts, typ, aid, src in buff_events:
        if ts > death_ts:
            break
        if typ in ("applybuff", "refreshbuff", "applybuffstack"):
            up[aid] = src
        elif typ == "removebuff" and ts < death_ts - DEATH_AURA_GRACE_MS:
            up.pop(aid, None)
    return up


def analyze_death(player_id, player_class, spec, fight_id, fight_start, death_ts,
                  indexed, ability_names, actor_names, killing_blows=None, ability_schools=None):
    """Defensive picture for one death. All timestamps are report-relative ms.

    With `killing_blows` (the player's overkill hits in this log) it also
    estimates whether the defensives they had ready would have saved them.
    """
    own_casts = indexed["casts"].get(player_id, [])
    casts_by_spell = defaultdict(list)
    for t, sid in own_casts:
        casts_by_spell[sid].append(t)
    talent_entries = indexed["talents"].get((fight_id, player_id))

    # Auras on the player at death, matched to the catalog by name (buff IDs
    # often differ from the button's spell ID).
    up = _buffs_active_at(death_ts, indexed["buffs"].get(player_id, []))
    active_names = {}
    for aid, src in up.items():
        name = ability_names.get(aid)
        if name in NAME_TO_ID:
            active_names[name] = src

    result = {"active": [], "available": [], "cooldown": [], "talentsKnown": talent_entries is not None}
    ready_entries = []

    pressed_this_pull = {sid for t, sid in own_casts if fight_start <= t <= death_ts}
    for sid, entry in PERSONAL.items():
        if not _has_ability(sid, entry, player_class, spec, talent_entries, casts_by_spell, pressed_this_pull):
            continue
        name = entry["name"]
        if name in active_names:
            result["active"].append({"name": name, "kind": "personal", "major": entry["major"]})
            continue
        all_casts = casts_by_spell.get(sid, [])
        recharge = _effective_cooldown(entry, all_casts)
        lookback = fight_start if entry["cooldown_ms"] >= ENCOUNTER_RESET_MS else death_ts - recharge * entry["charges"]
        window = [t for t in all_casts if max(lookback, 0) <= t <= death_ts]
        left, ready_in = _charges_at(death_ts, window, entry["charges"], recharge)
        if left > 0:
            result["available"].append({"name": name, "major": entry["major"]})
            ready_entries.append(entry)
        else:
            result["cooldown"].append({
                "name": name, "major": entry["major"],
                "readyIn": round(ready_in / 1000), "usedAgo": round((death_ts - window[-1]) / 1000),
            })

    for name, src in active_names.items():
        if EXTERNAL.get(NAME_TO_ID[name]):
            result["active"].append({"name": name, "kind": "external",
                                     "by": actor_names.get(src) if src != player_id else None})

    unused_consumables = []
    for kind in ("healthstone", "potion"):
        used = [t for t, sid in own_casts
                if CONSUMABLE.get(sid, {}).get("kind") == kind and fight_start <= t <= death_ts]
        result[kind] = {"usedAgo": round((death_ts - used[-1]) / 1000)} if used else {"usedAgo": None}
        if not used:
            # Only assume they carry one if they used that kind somewhere in this log.
            carried = [sid for _, sid in own_casts if CONSUMABLE.get(sid, {}).get("kind") == kind]
            if carried:
                unused_consumables.append(CONSUMABLE[carried[-1]])

    if killing_blows is not None:
        result["survival"] = assess_survival(killing_blows, death_ts, ready_entries, unused_consumables,
                                             ability_names, ability_schools or {})

    for key in ("active", "available", "cooldown"):
        result[key].sort(key=lambda d: (not d.get("major", True), d["name"]))
    return result


# =============================================================================
# WOULD A DEFENSIVE HAVE SAVED THEM?
# =============================================================================
#
# Uses only the killing blow of each death: WCL returns every hit with
# overkill for a whole report in one cheap request, with the player's health
# and max health attached. Fetching the seconds before every death costs about
# one API point per pull, which would use up a user's hourly WCL allowance on
# one big analysis. From the killing blow we know:
#   - how they died: one-shot from near full health, or already low
#   - how big the hit was and how much it overkilled by
#   - whether each defensive they had ready would have covered that hit
#     (reductions/immunities applied to it, absorbs, extra max health, and
#     heals up to the health they were missing).
# It is deliberately cautious: a defensive is only credited against the
# killing blow, not the hits before it.

FULL_HEALTH = 0.90           # at or above this before the killing blow = one-shot
PHYSICAL = 1
KILLING_BLOW_FILTER = "overkill > 0"


def fetch_killing_blows(token, report_code, start_time, end_time):
    """Every hit on a player with overkill in the window, with health values."""
    query = """query($c: String!, $s: Float!, $e: Float!, $f: String) { reportData { report(code: $c) {
        events(startTime: $s, endTime: $e, dataType: DamageTaken, filterExpression: $f,
               includeResources: true, limit: 10000) { data nextPageTimestamp } } } }"""
    events, start = [], start_time
    for _ in range(50):
        data = graphql_query(token, query, {"c": report_code, "s": start, "e": end_time, "f": KILLING_BLOW_FILTER})
        block = ((data.get("reportData") or {}).get("report") or {}).get("events") or {}
        events += block.get("data") or []
        start = block.get("nextPageTimestamp")
        if not start:
            break
    return index_killing_blows(events)


def index_killing_blows(events):
    """{targetID: [killing hits sorted by time]}"""
    idx = defaultdict(list)
    for e in events:
        if e.get("type") == "damage" and e.get("targetID") is not None and (e.get("overkill") or 0) > 0:
            idx[e["targetID"]].append(e)
    for hits in idx.values():
        hits.sort(key=lambda e: e["timestamp"])
    return dict(idx)


def _school_applies(school, hit, ability_schools):
    if school in (None, "all"):
        return True
    if school == "aoe":
        return bool(hit.get("isAoE"))
    mask = ability_schools.get(hit.get("abilityGameID"), 0)
    if school == "magic":
        return mask not in (0, PHYSICAL)
    if school == "physical":
        return mask == PHYSICAL
    return True


def _prevented(options, hit, max_hp, missing_hp, ability_schools):
    """Damage the given defensives would have prevented (or healed) against the killing blow."""
    dmg = (hit.get("amount") or 0) + (hit.get("absorbed") or 0)
    keep, absorb = 1.0, 0.0
    for m in options:
        if not _school_applies(m.get("school"), hit, ability_schools):
            continue
        if m.get("immune"):
            keep = 0.0
        elif m.get("dr"):
            keep *= 1 - m["dr"]
        absorb += m.get("absorb", 0)
    extra_hp = sum(m.get("hp", 0) for m in options)
    # A heal only helps up to the health they were missing before the killing blow.
    heal = min(sum(m.get("heal", 0) for m in options) * max_hp, missing_hp)
    return dmg * (1 - keep) + (absorb + extra_hp) * max_hp + heal


def assess_survival(killing_blows, death_ts, available, consumables, ability_names, ability_schools):
    """How they died, and whether the defensives they had ready would have saved them.

    `killing_blows`: this player's hits with overkill (any time); the one at
    this death is matched by time. `available` / `consumables`: catalog
    entries ready at death (consumables only if carried and unused this pull).
    """
    killing = None
    for h in killing_blows:
        if death_ts - 2_000 <= h["timestamp"] <= death_ts + 50:
            killing = h
    if killing is None or killing.get("resourceActor") != 2:
        return None   # no recorded killing blow with health data (instant-kill mechanic, etc.)
    max_hp = killing.get("maxHitPoints") or 0
    if not max_hp:
        return None
    overkill = killing.get("overkill") or 0
    hp_before = max((killing.get("amount") or 0) - overkill, 0)
    hit_size = (killing.get("amount") or 0) + (killing.get("absorbed") or 0)
    missing_hp = max(max_hp - hp_before, 0)

    def verdict(options):
        if not options:
            return None
        return _prevented(options, killing, max_hp, missing_hp, ability_schools) > overkill

    per_button, scored = {}, []
    for entry in list(available) + list(consumables):
        m = entry.get("mitigation")
        per_button[entry["name"]] = verdict([m]) if m else None
        if m:
            scored.append(m)

    return {
        "deathType": "oneShot" if hp_before >= FULL_HEALTH * max_hp else "wasLow",
        "killingHit": {
            "name": ability_names.get(killing.get("abilityGameID"), "Unknown"),
            "size": hit_size,
            "pctOfMax": round(100 * hit_size / max_hp),
        },
        "hpBeforePct": round(100 * hp_before / max_hp),
        "overkill": overkill,
        "maxHp": max_hp,
        "wouldSave": per_button,               # name -> True / False / None (can't estimate)
        "allTogetherWouldSave": verdict(scored),
    }
