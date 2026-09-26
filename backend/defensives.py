"""
defensives.py - What defensive options a player had when they died.

For every death this answers, per defensive the player actually had:
  - active:     its aura was on them when they died
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

from boss_spell_flags import IGNORES_IMMUNITY
from defensive_catalog import CATALOG
from warcraftlogs import graphql_query

# Cooldowns at or above this length reset when a boss pull ends, so only
# presses during the pull count. Shorter ones can carry over from before it.
ENCOUNTER_RESET_MS = 180_000

# A single-charge ability recast this much faster than its base cooldown
# means talents shortened it; trust the observed interval instead.
CDR_TOLERANCE_MS = 1_000

PERSONAL = {sid: d for sid, d in CATALOG.items() if d["kind"] == "personal"}
EXTERNAL = {sid: d for sid, d in CATALOG.items() if d["kind"] == "external"}
CONSUMABLE = {sid: d for sid, d in CATALOG.items() if d["kind"] in ("healthstone", "potion")}

# Every personal defensive is tracked (accuracy over API cost, the owner's
# call); the per-player summary counts only major (60s+) ones.
TRACKED = PERSONAL
CAST_IDS = sorted(set(TRACKED) | set(CONSUMABLE))
BUFF_NAMES = sorted({d["name"] for d in list(PERSONAL.values()) + list(EXTERNAL.values())})

# Death strips auras at (or a few ms after) the death event; an aura removed
# this close to the death was still up when they died.
DEATH_AURA_GRACE_MS = 250
NAME_TO_ID = {}
for _sid, _d in list(PERSONAL.items()) + list(EXTERNAL.items()):
    NAME_TO_ID.setdefault(_d["name"], _sid)


# =============================================================================
# FETCHING (one report)
# =============================================================================

def _paged(token, report_code, data_type, flt, fight_ids=None, start_time=None, end_time=None):
    """All pages of one event query, scoped either to boss pulls or to a time range."""
    events, start = [], start_time
    for _ in range(50):
        args, decl, variables = [], ["$c: String!"], {"c": report_code}
        if fight_ids is not None:
            args.append("fightIDs: $ids"); decl.append("$ids: [Int]"); variables["ids"] = list(fight_ids)
        if start is not None:
            args.append("startTime: $s"); decl.append("$s: Float"); variables["s"] = start
        if end_time is not None:
            args.append("endTime: $e"); decl.append("$e: Float"); variables["e"] = end_time
        if flt:
            args.append("filterExpression: $f"); decl.append("$f: String"); variables["f"] = flt
        query = (f"query({', '.join(decl)}) {{ reportData {{ report(code: $c) {{ "
                 f"events({', '.join(args)}, dataType: {data_type}, limit: 10000) "
                 f"{{ data nextPageTimestamp }} }} }} }}")
        block = ((graphql_query(token, query, variables).get("reportData") or {}).get("report") or {}).get("events") or {}
        events += block.get("data") or []
        start = block.get("nextPageTimestamp")
        if not start:
            break
    return events


def fetch_defensive_events(token, report_code, fight_ids, start_time, end_time, player_ids):
    """Defensive casts, defensive auras and talent loadouts for one report.

    - Casts and auras cover the whole time range (trash and time between pulls
      included, from 3 minutes before the first pull) so a defensive pressed
      just before a pull counts. They're kept only for `player_ids` (the
      players who died; nobody else is analyzed). That filtering happens
      here, not in the query: WCL returns nothing for `source.id in (...)` /
      `target.id in (...)` on Casts and Buffs (verified on a live log), and
      the unfiltered query costs fewer points anyway.
    - Talent loadouts are only recorded at pull start, so they're scoped to
      the boss pulls.
    """
    players = set(player_ids)
    if not players:
        return {"casts": {}, "buffs": {}, "talents": {}}
    lookback = max(0, start_time - ENCOUNTER_RESET_MS)
    cast_filter = f"type = \"cast\" and ability.id in ({', '.join(map(str, CAST_IDS))})"
    buff_filter = "ability.name in (" + ", ".join(f'"{n}"' for n in BUFF_NAMES) + ")"
    casts = _paged(token, report_code, "Casts", cast_filter, start_time=lookback, end_time=end_time)
    buffs = _paged(token, report_code, "Buffs", buff_filter, start_time=lookback, end_time=end_time)
    return index_defensive_events({
        "casts": [e for e in casts if e.get("sourceID") in players],
        "buffs": [e for e in buffs if e.get("targetID") in players],
        "combatants": _paged(token, report_code, "CombatantInfo", None, fight_ids=fight_ids),
    })


def index_defensive_events(raw):
    """Group raw WCL events by player so per-death lookups are cheap."""
    casts = defaultdict(list)           # sourceID -> [(ts, spellID)]
    for e in raw.get("casts", []):
        sid = e.get("abilityGameID")
        if e.get("type") == "cast" and sid in CATALOG and e.get("sourceID") is not None:
            casts[e["sourceID"]].append((e["timestamp"], sid))
    buffs = defaultdict(list)           # targetID -> [(ts, type, abilityGameID, sourceID, shield size)]
    for e in raw.get("buffs", []):
        if e.get("targetID") is not None:
            buffs[e["targetID"]].append((e["timestamp"], e.get("type"), e.get("abilityGameID"),
                                         e.get("sourceID"), e.get("absorb") or 0))
    talents = {}                        # (fightID, sourceID) -> {trait node entry ID: rank}
    for e in raw.get("combatants", []):
        tree = e.get("talentTree")
        if tree is None or e.get("sourceID") is None:
            continue
        talents[(e.get("fight"), e["sourceID"])] = {t["id"]: t.get("rank") or 1 for t in tree if t.get("id")}
    for lst in casts.values():
        lst.sort()
    for lst in buffs.values():
        lst.sort(key=lambda x: x[0])
    return {"casts": dict(casts), "buffs": dict(buffs), "talents": talents}


# =============================================================================
# PER-DEATH ANALYSIS
# =============================================================================

def _has_ability(sid, entry, player_class, spec, talent_entries, cast_ids_in_report, pressed_this_pull=()):
    if talent_entries is not None:
        talent_entries = set(talent_entries)
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
    for ts, typ, aid, src, *_ in buff_events:
        if ts > death_ts:
            break
        if typ in ("applybuff", "refreshbuff", "applybuffstack"):
            up[aid] = src
        elif typ == "removebuff" and ts < death_ts - DEATH_AURA_GRACE_MS:
            up.pop(aid, None)
    return up


def _killing_blow(killing_blows, death_ts):
    """The player's overkill hit that caused this death, if one was recorded."""
    found = None
    for h in killing_blows or ():
        if death_ts - 2_000 <= h["timestamp"] <= death_ts + 50:
            found = h
    return found


def _auras(hit):
    """Aura IDs WCL lists on a damage event ("108416.1022." -> {108416, 1022})."""
    return {int(a) for a in str(hit.get("buffs") or "").split(".") if a.isdigit()}


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

    # Auras on the player at death, matched to the catalog by name (aura IDs
    # often differ from the button's spell ID) -> who applied them. From the
    # aura events when we have them; otherwise from the killing blow's aura list.
    killing = _killing_blow(killing_blows, death_ts)
    active = {}
    buff_events = indexed.get("buffs")
    if buff_events is not None:
        for aid, src in _buffs_active_at(death_ts, buff_events.get(player_id, [])).items():
            if ability_names.get(aid) in NAME_TO_ID:
                active[ability_names.get(aid)] = src
    elif killing:
        for aid in _auras(killing):
            if ability_names.get(aid) in NAME_TO_ID:
                active[ability_names.get(aid)] = None
    active_names = set(active)

    result = {"active": [], "available": [], "cooldown": [], "talentsKnown": talent_entries is not None,
              "activeKnown": buff_events is not None or killing is not None}
    ready_entries = []

    pressed_this_pull = {sid for t, sid in own_casts if fight_start <= t <= death_ts}
    for sid, entry in TRACKED.items():
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

    shown = {a["name"] for a in result["active"]}
    for name in sorted(active_names - shown):
        entry = CATALOG[NAME_TO_ID[name]]
        if entry["kind"] == "external":
            src = active.get(name)
            result["active"].append({"name": name, "kind": "external",
                                     "by": actor_names.get(src) if src not in (None, player_id) else None})
        elif entry["class"] == player_class:   # a short-cooldown personal that was up
            result["active"].append({"name": name, "kind": "personal", "major": entry["major"]})

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

    # Real shield sizes this player got from their own shields in this log
    # (latest before the death, else any): exact, gear and talents included.
    observed = {}
    for ts, typ, aid, src, amount in (e + (0,) * (5 - len(e)) for e in (buff_events or {}).get(player_id, [])):
        name = ability_names.get(aid)
        if amount and src == player_id and typ in ("applybuff", "refreshbuff") and name in NAME_TO_ID:
            if ts <= death_ts or name not in observed:
                observed[name] = amount

    boosts = {e["name"]: _resolve(e, talent_entries, observed)[1] for e in ready_entries}
    for a in result["available"]:
        if boosts.get(a["name"]):
            a["boostedBy"] = boosts[a["name"]]

    if killing_blows is not None:
        result["survival"] = assess_survival(killing_blows, death_ts, ready_entries, unused_consumables,
                                             ability_names, ability_schools or {},
                                             talent_entries=talent_entries, observed_absorbs=observed)

    for key in ("active", "available", "cooldown"):
        result[key].sort(key=lambda d: (not d.get("major", True), d["name"]))
    return result


# =============================================================================
# WOULD A DEFENSIVE HAVE SAVED THEM?
# =============================================================================
#
# Uses only the killing blow of each death: one request per report returns
# every hit with overkill in its boss pulls, with the player's health and max
# health attached (about 1 WCL point per pull; fetching the seconds before
# every death costs more and returns far more data). From the killing blow
# we know:
#   - how they died: one-shot from near full health, or already low
#   - how big the hit was and how much it overkilled by
#   - whether each defensive they had ready would have covered that hit
#     (reductions/immunities applied to it, absorbs, extra max health, and
#     heals up to the health they were missing).
# It is deliberately cautious: a defensive is only credited against the
# killing blow, not the hits before it.

FULL_HEALTH = 0.85           # at or above this before the killing blow = one-shot (88% reads as full)
PHYSICAL = 1
KILLING_BLOW_FILTER = "overkill > 0"


def fetch_killing_blows(token, report_code, fight_ids):
    """Every hit on a player with overkill in the given pulls, with health values.

    Scoped with fightIDs so WCL only scans boss pulls (not trash or downtime);
    a filtered query over a whole report pages through mostly-empty time
    chunks. Cost measured on live logs: about 1 API point per pull.
    """
    query = """query($c: String!, $ids: [Int], $f: String, $s: Float) { reportData { report(code: $c) {
        events(fightIDs: $ids, startTime: $s, dataType: DamageTaken, filterExpression: $f,
               includeResources: true, limit: 10000) { data nextPageTimestamp } } } }"""
    events, start = [], None
    for _ in range(50):
        variables = {"c": report_code, "ids": list(fight_ids), "f": KILLING_BLOW_FILTER}
        if start:
            variables["s"] = start
        data = graphql_query(token, query, variables)
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


MELEE_SWING = 1             # WCL's ability ID for auto-attacks ("Melee")


def _school_applies(school, hit, ability_schools, immunity=False):
    """Does an effect limited to `school` apply to this hit?

    Reductions and absorbs limited to magic apply when any school of the hit
    is magic; an immunity only when every school is (the game's rules for
    mixed-school hits such as shadow + physical).
    """
    if school in (None, "all"):
        return True
    if school == "aoe":
        return bool(hit.get("isAoE"))
    if school == "melee":
        return hit.get("abilityGameID") == MELEE_SWING
    mask = ability_schools.get(hit.get("abilityGameID"), 0)
    if school == "magic":
        if immunity:
            return mask != 0 and not mask & PHYSICAL
        return bool(mask & ~PHYSICAL)
    if school == "physical":
        return mask == PHYSICAL if immunity else bool(mask & PHYSICAL)
    return True


def _ignores_reduction(hit):
    """Nothing at all was mitigated (not even versatility): the hit ignores damage reduction.

    WCL leaves `mitigated` out when it's 0; `unmitigatedAmount` shows the log has the data.
    """
    return not hit.get("mitigated") and (hit.get("unmitigatedAmount") or 0) > 0


def _rank(talent_entries, entries):
    if not talent_entries:
        return 0
    if isinstance(talent_entries, dict):
        return max((talent_entries.get(e, 0) for e in entries), default=0)
    return 1 if set(entries) & set(talent_entries) else 0


def _resolve(entry, talent_entries, observed_absorbs):
    """This player's version of an ability's effect: talents applied, real shield sizes.

    Returns (components or None if it can't be scored, [talents that changed it]).
    Each component: {"dr" | "absorb" (fraction of max health) | "absorb_amount" |
    "hp" | "heal" | "immune": value, "school"?}.
    """
    comps = entry.get("mitigation")
    if comps is None:
        return None, []
    if isinstance(comps, dict):          # older catalog shape
        comps = [comps]
    out, boosted = [], []
    for c in comps:
        field = next(f for f in ("immune", "dr", "absorb", "hp", "heal") if f in c)
        value = c[field]
        if field == "absorb" and c.get("observed") and observed_absorbs.get(entry["name"]):
            out.append({"absorb_amount": observed_absorbs[entry["name"]], "school": c.get("school")})
            continue
        if value is None:
            return None, []              # only scored from a real shield size, and none was seen
        for m in c.get("mods", ()):
            rank = _rank(talent_entries, m["entries"])
            if not rank:
                continue
            if "add" in m:
                value = value + m["add"] * rank
            else:
                value = value * (1 + (m["mult"] - 1) * rank)
            boosted.append(m["talent"])
        if field == "dr":
            value = min(value, 1.0)
        if value:
            out.append({field: value, "school": c.get("school")})
    return out, boosted


def _full_hit(hit):
    """Whole killing blow: WCL's `amount` is only the health it took (the rest is `overkill`)."""
    return (hit.get("amount") or 0) + (hit.get("overkill") or 0) + (hit.get("absorbed") or 0)


def _prevented(options, hit, max_hp, missing_hp, ability_schools):
    """Damage the given defensives would have prevented (or healed) against the killing blow.

    `options`: resolved components (see _resolve). Reductions apply first, then
    shields soak what's left, as in the game. Reductions are skipped for a hit
    that ignored them, and immunities for spells that pierce them.
    """
    dmg = _full_hit(hit)
    keep, absorb = 1.0, 0.0
    no_reduction = _ignores_reduction(hit)
    pierces = hit.get("abilityGameID") in IGNORES_IMMUNITY
    for m in options:
        immune = bool(m.get("immune"))
        if not _school_applies(m.get("school"), hit, ability_schools, immunity=immune):
            continue
        if immune:
            if not pierces:
                keep = 0.0
        elif m.get("dr"):
            if not no_reduction:
                keep *= 1 - m["dr"]
        absorb += m.get("absorb", 0) * max_hp + m.get("absorb_amount", 0)
    extra_hp = sum(m.get("hp", 0) for m in options)
    # A heal only helps up to the health they were missing before the killing blow.
    heal = min(sum(m.get("heal", 0) for m in options) * max_hp, missing_hp)
    return min(dmg, dmg * (1 - keep) + absorb) + extra_hp * max_hp + heal


def assess_survival(killing_blows, death_ts, available, consumables, ability_names, ability_schools,
                    talent_entries=None, observed_absorbs=None):
    """How they died, and whether the defensives they had ready would have saved them.

    `killing_blows`: this player's hits with overkill (any time); the one at
    this death is matched by time. `available` / `consumables`: catalog
    entries ready at death (consumables only if carried and unused this pull).
    """
    killing = _killing_blow(killing_blows, death_ts)
    if killing is None or killing.get("resourceActor") != 2:
        return None   # no recorded killing blow with health data (instant-kill mechanic, etc.)
    max_hp = killing.get("maxHitPoints") or 0
    if not max_hp:
        return None
    overkill = killing.get("overkill") or 0
    # Verified on live logs: the killing blow's `amount` equals the health the
    # player had left (matches the previous hit's recorded health), and
    # `overkill` is the damage beyond that.
    hp_before = killing.get("amount") or 0
    hit_size = _full_hit(killing)
    missing_hp = max(max_hp - hp_before, 0)

    def verdict(options):
        return _prevented(options, killing, max_hp, missing_hp, ability_schools) > overkill

    per_button, scored = {}, []
    for entry in list(available) + list(consumables):
        comps, _ = _resolve(entry, talent_entries, observed_absorbs or {})
        per_button[entry["name"]] = None if comps is None else verdict(comps)
        scored += comps or []

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
        "allTogetherWouldSave": verdict(scored) if scored else None,
        # Why a defensive might not help against this particular hit.
        "ignoresReduction": _ignores_reduction(killing),
        "ignoresImmunity": killing.get("abilityGameID") in IGNORES_IMMUNITY,
    }
