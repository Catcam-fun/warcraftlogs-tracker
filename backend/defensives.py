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

def _has_ability(sid, entry, player_class, spec, talent_entries, cast_ids_in_report):
    if entry["class"] != player_class:
        return False
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
                  indexed, ability_names, actor_names):
    """Defensive picture for one death. All timestamps are report-relative ms."""
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

    for sid, entry in PERSONAL.items():
        if not _has_ability(sid, entry, player_class, spec, talent_entries, casts_by_spell):
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
        else:
            result["cooldown"].append({
                "name": name, "major": entry["major"],
                "readyIn": round(ready_in / 1000), "usedAgo": round((death_ts - window[-1]) / 1000),
            })

    for name, src in active_names.items():
        if EXTERNAL.get(NAME_TO_ID[name]):
            result["active"].append({"name": name, "kind": "external",
                                     "by": actor_names.get(src) if src != player_id else None})

    for kind in ("healthstone", "potion"):
        used = [t for t, sid in own_casts
                if CONSUMABLE.get(sid, {}).get("kind") == kind and fight_start <= t <= death_ts]
        result[kind] = {"usedAgo": round((death_ts - used[-1]) / 1000)} if used else {"usedAgo": None}

    for key in ("active", "available", "cooldown"):
        result[key].sort(key=lambda d: (not d.get("major", True), d["name"]))
    return result
