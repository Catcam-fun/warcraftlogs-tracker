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

import hashlib
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from boss_spell_flags import IGNORES_IMMUNITY
from defensive_catalog import CATALOGS, HEALING_TAKEN, LATEST, PATCHES
from spell_icons import ICONS as CATALOG_ICONS
from warcraftlogs import graphql_query

# Cooldowns at or above this length reset when a boss pull ends, so only
# presses during the pull count. Shorter ones can carry over from before it.
ENCOUNTER_RESET_MS = 180_000

# A single-charge ability recast this much faster than its base cooldown
# means talents shortened it; trust the observed interval instead.
CDR_TOLERANCE_MS = 1_000

# Death strips auras at (or a few ms after) the death event; an aura removed
# this close to the death was still up when they died.
DEATH_AURA_GRACE_MS = 250

# Logs sometimes miss an aura's "removed" event (the player died, moved out of
# range...). An aura is never treated as still up past its longest duration
# from game data (catalog aura_ms) times this, plus a second, which leaves room
# for talents that extend it (Anti-Magic Barrier +40%, Improved Barkskin +4s).
AURA_DURATION_HEADROOM = 1.5

# Demonic Healthstone heals more in the logs than the game data says (a
# server-side change the data files don't carry). Measured medians per tier,
# used only for Warlocks who didn't use one in the report: (first patch, share of max health).
DEMONIC_HEALTHSTONE_MEASURED = [("11.0.2", 0.35), ("11.1.0", 0.65), ("12.0.0", 0.60)]

# The potion most raiders drank on bosses in each tier (from real logs). When a
# player's own potion heals aren't in the boss pulls (they drank only on trash,
# or one without a typical heal), this one stands in: (first patch, potion).
STANDARD_POTION = [("11.0.2", "Algari Healing Potion"), ("11.2.0", "Invigorating Healing Potion"),
                   ("12.0.0", "Silvermoon Health Potion"), ("12.1.0", "Concentrated Silvermoon Health Potion")]


def _patch_key(patch):
    return [int(x) for x in patch.split(".")]


def _mods(component):
    return [m for m in component.get("mods", ())] if isinstance(component, dict) else []


class Catalog:
    """Everything the analysis looks up for one game patch."""

    def __init__(self, patch):
        self.patch = patch
        self.all = CATALOGS[patch]
        self.personal = {sid: d for sid, d in self.all.items() if d["kind"] == "personal"}
        self.external = {sid: d for sid, d in self.all.items() if d["kind"] == "external"}
        self.consumable = {sid: d for sid, d in self.all.items() if d["kind"] in ("healthstone", "potion")}
        # Every personal defensive is tracked (accuracy over API cost, the
        # owner's call); the per-player summary counts only major (60s+) ones.
        self.tracked = self.personal
        self.cast_ids = sorted(set(self.tracked) | set(self.consumable))
        self.buff_names = sorted({d["name"] for d in list(self.personal.values()) + list(self.external.values())})
        heal = HEALING_TAKEN.get(patch, {})
        self.heal_talents = heal.get("talents", [])
        self.heal_auras = {int(k): v for k, v in heal.get("auras", {}).items()}
        # Talent entries the analysis ever looks at: granting, replacing or
        # modifying a tracked ability, or changing healing taken. Loadouts are
        # trimmed to these (nothing else is read).
        entries = set()
        for d in self.all.values():
            entries.update(d["talent_entries"], d.get("replaced_by_entries", ()))
            for m in [m for c in (d.get("mitigation") or []) for m in _mods(c)] \
                    + d.get("cooldown_mods", []) + d.get("charge_mods", []):
                entries.update(m.get("entries", ()))
        for m in self.heal_talents:
            entries.update(m.get("entries", ()))
        self.relevant_talent_entries = frozenset(entries)
        self.name_to_id = {}
        for sid, d in list(self.personal.items()) + list(self.external.items()):
            self.name_to_id.setdefault(d["name"], sid)
        demonic = [v for p, v in DEMONIC_HEALTHSTONE_MEASURED if _patch_key(p) <= _patch_key(patch)]
        self.demonic_healthstone = demonic[-1] if demonic else None
        standard = [n for p, n in STANDARD_POTION if _patch_key(p) <= _patch_key(patch)]
        self.standard_potion = next((sid for sid, d in self.consumable.items()
                                     if standard and d["name"] == standard[-1]), None)


_CATALOGS = {p: Catalog(p) for p in CATALOGS}


def catalog_for(report_start_ms=None):
    """The catalog of the patch that was live when a report was logged (latest if unknown)."""
    if not report_start_ms:
        return _CATALOGS[LATEST]
    day = datetime.fromtimestamp(report_start_ms / 1000, tz=timezone.utc).date().isoformat()
    live = [p for first, p in PATCHES if first <= day]
    return _CATALOGS[live[-1] if live else PATCHES[0][1]]


def icon_name(name, report_icons=None):
    """Icon file name of an ability (render.worldofwarcraft.com/us/icons/56/<icon>.jpg).

    Catalog abilities use the game data's icon (spell_icons.py); anything else
    (boss abilities) the report's own, which WCL spells with "-" for spaces.
    """
    if name in CATALOG_ICONS:
        return CATALOG_ICONS[name]
    icon = (report_icons or {}).get(name)
    return icon.rsplit(".", 1)[0].replace("-", "").lower() if icon else None


def ability_info(cat, name):
    """What a catalog ability does in general (no talents), for the results page tooltips."""
    entry = next((d for d in cat.all.values() if d["name"] == name), None)
    if entry is None:
        return None
    comps = None if entry["kind"] == "potion" else _resolve(entry, None, {}, None)[0]
    typical = next((c.get("heal_amount") for c in entry.get("mitigation") or () if c.get("heal_amount")), None)
    return {"kind": entry["kind"], "cooldownMs": entry.get("cooldown_ms"), "auraMs": entry.get("aura_ms"),
            "charges": entry.get("charges", 1),
            "effect": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items() if v is not None}
                       for c in comps or ()],
            **({"typicalHeal": typical} if typical else {})}


# Changes whenever what gets fetched or kept for defensives changes, so cached
# data from an older catalog is never reused. Bump DATA_SHAPE when the
# indexed layout changes.
DATA_SHAPE = 2
CATALOG_FINGERPRINT = hashlib.sha1(repr((DATA_SHAPE, [
    (c.patch, c.cast_ids, c.buff_names, sorted(c.relevant_talent_entries)) for c in _CATALOGS.values()
])).encode()).hexdigest()[:12]

# Latest patch, for callers and tests that don't pick one.
_LATEST = _CATALOGS[LATEST]
CATALOG = _LATEST.all
PERSONAL, EXTERNAL, CONSUMABLE = _LATEST.personal, _LATEST.external, _LATEST.consumable


# =============================================================================
# FETCHING (one report)
# =============================================================================

def _paged(token, report_code, data_type, flt, fight_ids=None, start_time=None, end_time=None,
           resources=False):
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
        if resources:
            args.append("includeResources: true")
        query = (f"query({', '.join(decl)}) {{ reportData {{ report(code: $c) {{ "
                 f"events({', '.join(args)}, dataType: {data_type}, limit: 10000) "
                 f"{{ data nextPageTimestamp }} }} }} }}")
        block = ((graphql_query(token, query, variables).get("reportData") or {}).get("report") or {}).get("events") or {}
        events += block.get("data") or []
        start = block.get("nextPageTimestamp")
        if not start:
            break
    return events


def fetch_defensive_events(token, report_code, fight_ids, start_time, end_time, player_ids, cat=None):
    """Defensive casts, defensive auras, talent loadouts and consumable heals for one report.

    - Casts and auras cover the whole time range (trash and time between pulls
      included, from 3 minutes before the first pull) so a defensive pressed
      just before a pull counts. They're kept only for `player_ids` (the
      players who died; nobody else is analyzed). That filtering happens
      here, not in the query: WCL returns nothing for `source.id in (...)` /
      `target.id in (...)` on Casts and Buffs (verified on a live log), and
      the unfiltered query costs fewer points anyway.
    - Talent loadouts are only recorded at pull start, so they're scoped to
      the boss pulls.
    - Healthstone and potion heals in the boss pulls, with max health: how
      much each player's own consumables really heal (potion rank, talents
      and buffs included). Scoped to boss pulls, which costs least.
    """
    cat = cat or _LATEST
    players = set(player_ids)
    if not players:
        return {"casts": {}, "buffs": {}, "talents": {}, "heals": {}}
    lookback = max(0, start_time - ENCOUNTER_RESET_MS)
    cast_filter = f"type = \"cast\" and ability.id in ({', '.join(map(str, cat.cast_ids))})"
    buff_filter = "ability.name in (" + ", ".join(f'"{n}"' for n in cat.buff_names) + ")"
    heal_filter = f"ability.id in ({', '.join(map(str, sorted(cat.consumable)))})"
    casts = _paged(token, report_code, "Casts", cast_filter, start_time=lookback, end_time=end_time)
    buffs = _paged(token, report_code, "Buffs", buff_filter, start_time=lookback, end_time=end_time)
    heals = _paged(token, report_code, "Healing", heal_filter, fight_ids=fight_ids, resources=True)
    return index_defensive_events({
        "casts": [e for e in casts if e.get("sourceID") in players],
        "buffs": [e for e in buffs if e.get("targetID") in players],
        "combatants": [e for e in _paged(token, report_code, "CombatantInfo", None, fight_ids=fight_ids)
                       if e.get("sourceID") in players],
        "heals": [e for e in heals if e.get("targetID") in players],
    }, cat)


def _heal_taken_mult(auras, cat):
    """Healing-taken multiplier from the buffs and debuffs in an event's aura list."""
    mult = 1.0
    for aid in auras:
        mult *= cat.heal_auras.get(aid, 1.0)
    return mult


def index_defensive_events(raw, cat=None):
    """Group raw WCL events by player so per-death lookups are cheap."""
    cat = cat or _LATEST
    casts = defaultdict(list)           # sourceID -> [(ts, spellID)]
    for e in raw.get("casts", []):
        sid = e.get("abilityGameID")
        if e.get("type") == "cast" and sid in cat.all and e.get("sourceID") is not None:
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
        talents[(e.get("fight"), e["sourceID"])] = {t["id"]: t.get("rank") or 1 for t in tree
                                                     if t.get("id") in cat.relevant_talent_entries}
    # targetID -> [(ts, spellID, healed incl. overheal, max health, healing-taken buffs multiplier)]
    heals = defaultdict(list)
    for e in raw.get("heals", []):
        full = (e.get("amount") or 0) + (e.get("overheal") or 0) + (e.get("absorbed") or 0)
        if e.get("type") == "heal" and not e.get("tick") and full > 0 and e.get("targetID") is not None \
                and e.get("sourceID") == e.get("targetID"):
            heals[e["targetID"]].append((e["timestamp"], e.get("abilityGameID"), full, e.get("maxHitPoints") or 0,
                                         round(_heal_taken_mult(_auras(e), cat), 4)))
    for lst in casts.values():
        lst.sort()
    for lst in buffs.values():
        lst.sort(key=lambda x: x[0])
    return {"casts": dict(casts), "buffs": dict(buffs), "talents": talents, "heals": dict(heals)}


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


def _spec_matches(spec, specs):
    norm = lambda x: (x or "").replace(" ", "").lower()
    return norm(spec) in {norm(s) for s in specs}


def _mod_rank(mod, talent_entries, spec):
    """How many times a modifier applies to this player: talent rank, or 1 for their spec's passive."""
    if mod.get("specs"):
        return 1 if spec and _spec_matches(spec, mod["specs"]) else 0
    return _rank(talent_entries, mod.get("entries", ()))


def _talented_cooldown(entry, talent_entries, spec):
    """Base cooldown (or recharge) after the player's talents and spec passives."""
    cd, mult = entry["cooldown_ms"], 1.0
    for m in entry.get("cooldown_mods", ()):
        rank = _mod_rank(m, talent_entries, spec)
        if rank and "add_ms" in m:
            cd += m["add_ms"] * rank
        elif rank:
            mult *= 1 + (m["mult"] - 1) * rank
    return max(cd * mult, 0)


def _talented_charges(entry, talent_entries, spec):
    return entry["charges"] + sum(m["add"] * _mod_rank(m, talent_entries, spec)
                                  for m in entry.get("charge_mods", ()))


def _effective_cooldown(entry, own_casts_of_spell, cd=None, charges=None):
    cd = entry["cooldown_ms"] if cd is None else cd
    charges = entry["charges"] if charges is None else charges
    if charges == 1 and len(own_casts_of_spell) > 1:
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


def _buffs_active_at(death_ts, buff_events, max_ms=None):
    """abilityGameID -> sourceID for auras that were up when the player died.

    `max_ms(abilityGameID)`: longest the aura can last (None = unknown), so an
    aura whose removal the log missed isn't counted as up forever.
    """
    up = {}
    for ts, typ, aid, src, *_ in buff_events:
        if ts > death_ts:
            break
        if typ in ("applybuff", "refreshbuff", "applybuffstack"):
            up[aid] = (src, ts)
        elif typ == "removebuff" and ts < death_ts - DEATH_AURA_GRACE_MS:
            up.pop(aid, None)
    active = {}
    for aid, (src, since) in up.items():
        longest = max_ms(aid) if max_ms else None
        if longest and death_ts - since > longest * AURA_DURATION_HEADROOM + 1_000:
            continue
        active[aid] = src
    return active


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
                  indexed, ability_names, actor_names, killing_blows=None, ability_schools=None, cat=None,
                  aoe_known=True):
    """Defensive picture for one death. All timestamps are report-relative ms.

    With `killing_blows` (the player's overkill hits in this log) it also
    estimates whether the defensives they had ready would have saved them.
    `cat`: the catalog of the patch the report was logged on (catalog_for).
    `aoe_known`: whether this report marks AoE hits at all (logs_mark_aoe).
    """
    cat = cat or _LATEST
    own_casts = indexed["casts"].get(player_id, [])
    casts_by_spell = defaultdict(list)
    for t, sid in own_casts:
        casts_by_spell[sid].append(t)
    talent_entries = indexed["talents"].get((fight_id, player_id))

    # Auras on the player at death, matched to the catalog by name (aura IDs
    # often differ from the button's spell ID) -> who applied them.
    # The killing blow's aura list is the game's snapshot at the moment of the
    # hit (verified on live logs: no list means no auras), so it decides what
    # was up; the aura events add who cast externals. Without a killing blow,
    # the aura events decide, capped by each aura's duration.
    killing = _killing_blow(killing_blows, death_ts)
    active = {}
    buff_events = indexed.get("buffs")
    own_events = (buff_events or {}).get(player_id, [])

    def max_ms(aid):
        sid = cat.name_to_id.get(ability_names.get(aid))
        return cat.all[sid].get("aura_ms") if sid else None

    if killing is not None:
        casters = {}
        for ts, typ, aid, src, *_ in own_events:
            if ts > death_ts:
                break
            if typ in ("applybuff", "refreshbuff", "applybuffstack"):
                casters[ability_names.get(aid)] = src
        for aid in _auras(killing):
            name = ability_names.get(aid)
            if name in cat.name_to_id:
                active[name] = casters.get(name)
    elif buff_events is not None:
        for aid, src in _buffs_active_at(death_ts, own_events, max_ms).items():
            if ability_names.get(aid) in cat.name_to_id:
                active[ability_names.get(aid)] = src
    active_names = set(active)

    result = {"active": [], "available": [], "cooldown": [], "talentsKnown": talent_entries is not None,
              "activeKnown": buff_events is not None or killing is not None}
    ready_entries = []

    pressed_this_pull = {sid for t, sid in own_casts if fight_start <= t <= death_ts}
    for sid, entry in cat.tracked.items():
        if not _has_ability(sid, entry, player_class, spec, talent_entries, casts_by_spell, pressed_this_pull):
            continue
        name = entry["name"]
        if name in active_names:
            result["active"].append({"name": name, "kind": "personal", "major": entry["major"]})
            continue
        all_casts = casts_by_spell.get(sid, [])
        charges = _talented_charges(entry, talent_entries, spec)
        recharge = _effective_cooldown(entry, all_casts, _talented_cooldown(entry, talent_entries, spec), charges)
        lookback = fight_start if entry["cooldown_ms"] >= ENCOUNTER_RESET_MS else death_ts - recharge * charges
        window = [t for t in all_casts if max(lookback, 0) <= t <= death_ts]
        left, ready_in = _charges_at(death_ts, window, charges, recharge)
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
        entry = cat.all[cat.name_to_id[name]]
        if entry["kind"] == "external":
            src = active.get(name)
            result["active"].append({"name": name, "kind": "external",
                                     "by": actor_names.get(src) if src not in (None, player_id) else None})
        elif entry["class"] == player_class:   # a short-cooldown personal that was up
            result["active"].append({"name": name, "kind": "personal", "major": entry["major"]})

    unused_consumables = []
    for kind in ("healthstone", "potion"):
        used = [(t, sid) for t, sid in own_casts
                if cat.consumable.get(sid, {}).get("kind") == kind and fight_start <= t <= death_ts]
        result[kind] = ({"usedAgo": round((death_ts - used[-1][0]) / 1000), "name": cat.all[used[-1][1]]["name"]}
                        if used else {"usedAgo": None})
        if not used:
            # Only assume they carry one if they used that kind somewhere in this log.
            carried = [sid for _, sid in own_casts if cat.consumable.get(sid, {}).get("kind") == kind]
            if carried:
                unused_consumables.append(carried[-1])

    # Real shield sizes this player got from their own shields in this log
    # (latest before the death, else any): exact, gear and talents included.
    observed = {}
    for ts, typ, aid, src, amount in (e + (0,) * (5 - len(e)) for e in (buff_events or {}).get(player_id, [])):
        name = ability_names.get(aid)
        if amount and src == player_id and typ in ("applybuff", "refreshbuff") and name in cat.name_to_id:
            if ts <= death_ts or name not in observed:
                observed[name] = amount

    boosts = {e["name"]: _resolve(e, talent_entries, observed, spec)[1] for e in ready_entries}
    for a in result["available"]:
        if boosts.get(a["name"]):
            a["boostedBy"] = boosts[a["name"]]

    if killing_blows is not None:
        death_mult = _heal_taken_mult(_auras(killing), cat) if killing is not None else 1.0
        own_heals = (indexed.get("heals") or {}).get(player_id, [])
        consumables = [consumable_estimate(sid, cat, own_heals, death_mult, talent_entries, spec)
                       for sid in unused_consumables]
        result["survival"] = assess_survival(killing_blows, death_ts, ready_entries, consumables,
                                             ability_names, ability_schools or {},
                                             talent_entries=talent_entries, observed_absorbs=observed, spec=spec,
                                             aoe_known=aoe_known)

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


# Everything the survival assessment reads from a killing blow (the rest,
# like positions and stats, is dropped so cached reports stay small).
KILLING_BLOW_FIELDS = ("timestamp", "type", "sourceID", "targetID", "abilityGameID", "fight", "buffs",
                       "hitType", "amount", "overkill", "absorbed", "mitigated", "unmitigatedAmount",
                       "isAoE", "resourceActor", "hitPoints", "maxHitPoints")


def logs_mark_aoe(killing_blows_by_player):
    """Does this report mark AoE hits? Older logs (The War Within) have isAoE
    false on every hit, so a report with no AoE killing blow at all doesn't."""
    return any(h.get("isAoE") for hits in (killing_blows_by_player or {}).values() for h in hits)


def index_killing_blows(events):
    """{targetID: [killing hits sorted by time]}"""
    idx = defaultdict(list)
    for e in events:
        if e.get("type") == "damage" and e.get("targetID") is not None and (e.get("overkill") or 0) > 0:
            idx[e["targetID"]].append({k: e[k] for k in KILLING_BLOW_FIELDS if k in e})
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
        # None: this log doesn't mark AoE hits (The War Within logs have
        # isAoE false on every hit), so whether it applies is unknown.
        return bool(hit.get("isAoE")) if hit.get("aoeKnown", True) else None
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


def _resolve(entry, talent_entries, observed_absorbs, spec=None, applied=None):
    """This player's version of an ability's effect: talents applied, real shield sizes.

    Returns (components or None if it can't be scored, [talents that changed it]).
    Each component: {"dr" | "absorb" (fraction of max health) | "absorb_amount" |
    "hp" | "heal" | "heal_amount" | "immune": value, "school"?}.
    Consumables arrive already estimated (consumable_estimate).
    `applied`: a list that gets each talent change, for the results page:
    {"talent", "field", "add" | "mult", "rank"}.
    """
    if entry.get("estimated"):
        return entry["mitigation"], entry.get("boostedBy", [])
    comps = entry.get("mitigation")
    if comps is None:
        return None, []
    if isinstance(comps, dict):          # older catalog shape
        comps = [comps]
    out, boosted = [], []
    for c in comps:
        field = next(f for f in ("immune", "dr", "absorb", "hp", "heal", "heal_amount") if f in c)
        value = c[field]
        if field == "absorb" and c.get("observed") and observed_absorbs.get(entry["name"]):
            out.append({"absorb_amount": observed_absorbs[entry["name"]], "school": c.get("school")})
            continue
        if value is None:
            return None, []              # only scored from a real shield size, and none was seen
        for m in c.get("mods", ()):
            rank = _mod_rank(m, talent_entries, spec)
            if not rank:
                continue
            if "add" in m:
                value = value + m["add"] * rank
            else:
                value = value * (1 + (m["mult"] - 1) * rank)
            boosted.append(m["talent"])
            if applied is not None:
                applied.append({"talent": m["talent"], "field": field, "rank": rank,
                                **({"add": m["add"]} if "add" in m else {"mult": m["mult"]})})
        if field == "dr":
            value = min(value, 1.0)
        if value:
            out.append({field: value, "school": c.get("school")})
    return out, boosted


def consumable_estimate(sid, cat, own_heals, death_mult, talent_entries, spec):
    """How much an unused Healthstone or potion would have healed this player, as a scorable entry.

    From the player's own uses of it in the same report when there are any:
      - Healthstones heal a share of max health that healing-taken buffs don't
        change (verified on live logs: 25% with Vampiric Blood or Divine Hymn up),
        so their own share is applied to their max health at death.
      - Potions heal a fixed amount (by quality rank) that healing-taken buffs
        do change: their own heals, with the buffs up at each one taken out,
        then the buffs up when they died put back in.
    Otherwise from the catalog: the Healthstone's game-data share with talents
    (Demonic Healthstone: the share measured in real logs of that tier), or a
    potion's typical heal with the player's healing-taken talents and buffs.
    """
    entry = cat.all[sid]
    own = [h for h in own_heals if h[1] == sid]
    out = {"name": entry["name"], "kind": entry["kind"], "estimated": True, "boostedBy": []}
    if entry["kind"] == "healthstone":
        shares = [full / max_hp for _, _, full, max_hp, _ in own if max_hp]
        extra = [c for c in (entry.get("mitigation") or []) if "hp" in c]     # Soulburn: Healthstone
        extra, boosted = _resolve({"mitigation": extra, "name": entry["name"]}, talent_entries, {}, spec)
        if shares:
            out["mitigation"] = [{"heal": statistics.median(shares)}] + (extra or [])
            out["source"] = "log"
        elif entry["name"] == "Demonic Healthstone" and cat.demonic_healthstone:
            out["mitigation"] = [{"heal": cat.demonic_healthstone}] + (extra or [])
            out["source"] = "typical"
        else:
            out["applied"] = []
            out["mitigation"], out["boostedBy"] = _resolve(entry, talent_entries, {}, spec, out["applied"])
            out["source"] = "gameData"
        return out
    if own:
        amount = statistics.median(full / (mult or 1.0) for _, _, full, _, mult in own) * death_mult
        out["mitigation"] = [{"heal_amount": amount}]
        out["source"] = "log"
        return out
    comps, boosted = _resolve(entry, talent_entries, {}, spec)
    typical = next((c["heal_amount"] for c in comps or () if "heal_amount" in c), None)
    if typical is None and cat.standard_potion and cat.standard_potion != sid:
        standard = cat.all[cat.standard_potion]
        comps, boosted = _resolve(standard, talent_entries, {}, spec)
        typical = next((c["heal_amount"] for c in comps or () if "heal_amount" in c), None)
    if typical is None:
        out["mitigation"] = None
        return out
    talent_mult, applied = 1.0, []
    for m in cat.heal_talents:
        rank = _mod_rank(m, talent_entries, spec)
        if rank:
            talent_mult *= 1 + (m["mult"] - 1) * rank
            boosted.append(m["talent"])
            applied.append({"talent": m["talent"], "field": "heal_amount", "rank": rank, "mult": m["mult"]})
    out["mitigation"] = [{"heal_amount": typical * talent_mult * death_mult}]
    out["applied"], out["typical"] = applied, typical
    out["boostedBy"], out["source"] = boosted, "typical"
    return out


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
            continue           # doesn't apply, or unknown (counted as not helping)
        if immune:
            if not pierces:
                keep = 0.0
        elif m.get("dr"):
            if not no_reduction:
                keep *= 1 - m["dr"]
        absorb += m.get("absorb", 0) * max_hp + m.get("absorb_amount", 0)
    extra_hp = sum(m.get("hp", 0) for m in options)
    # A heal only helps up to the health they were missing before the killing blow.
    heal = min(sum(m.get("heal", 0) for m in options) * max_hp + sum(m.get("heal_amount", 0) for m in options),
               missing_hp)
    return min(dmg, dmg * (1 - keep) + absorb) + extra_hp * max_hp + heal


def _explain(entry, comps, applied, hit, max_hp, missing_hp, ability_schools):
    """The numbers behind one button's verdict, for the results page.

    {"amount": damage it would have prevented or healed against the killing
     blow (more than the overkill: they live), "why": when it prevents
     nothing, the reason}. When talents changed it, or for an estimated
    consumable: "effect", this player's version of it, and "talents", the
    changes. Consumables also carry where their heal came from ("source":
    log / typical / gameData) and, for a typical potion, the untalented heal.
    The general effect of each ability is sent once per result (ability_info).
    """
    amount = _prevented(comps, hit, max_hp, missing_hp, ability_schools)
    out = {"amount": round(amount)}
    talents = applied or entry.get("applied") or []
    if talents or entry.get("estimated"):
        out["effect"] = [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items() if v is not None}
                         for c in comps]
        if talents:
            out["talents"] = talents
    if entry.get("estimated"):
        out["source"] = entry.get("source")
        if entry.get("typical"):
            out["typical"] = round(entry["typical"])
    if amount <= 0:
        for m in comps:
            immune = bool(m.get("immune"))
            applies = _school_applies(m.get("school"), hit, ability_schools, immunity=immune)
            if applies is None:
                out["why"] = "aoeUnknown"
            elif not applies:
                out["why"], out["school"] = "school", m.get("school")
            elif immune and hit.get("abilityGameID") in IGNORES_IMMUNITY:
                out["why"] = "pierces"
            elif m.get("dr") and _ignores_reduction(hit):
                out["why"] = "noReduction"
            elif ("heal" in m or "heal_amount" in m) and missing_hp <= 0:
                out["why"] = "fullHealth"
            else:
                continue
            break
    return out


def assess_survival(killing_blows, death_ts, available, consumables, ability_names, ability_schools,
                    talent_entries=None, observed_absorbs=None, spec=None, aoe_known=True):
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

    if not aoe_known:
        killing = dict(killing, aoeKnown=False)

    def verdict(options):
        """True / False, or None when it doesn't save them without parts whose effect on this hit is unknown."""
        if _prevented(options, killing, max_hp, missing_hp, ability_schools) > overkill:
            return True
        unknown = any(_school_applies(m.get("school"), killing, ability_schools) is None for m in options)
        return None if unknown else False

    per_button, scored, details = {}, [], {}
    for entry in list(available) + list(consumables):
        applied = []
        comps, _ = _resolve(entry, talent_entries, observed_absorbs or {}, spec, applied)
        per_button[entry["name"]] = None if comps is None else verdict(comps)
        scored += comps or []
        if comps is not None:
            details[entry["name"]] = _explain(entry, comps, applied, killing, max_hp, missing_hp,
                                              ability_schools)

    return {
        "deathType": "oneShot" if hp_before >= FULL_HEALTH * max_hp else "wasLow",
        "killingHit": {
            "name": ability_names.get(killing.get("abilityGameID"), "Unknown"),
            "size": hit_size,
            "pctOfMax": round(100 * hit_size / max_hp),
            "school": ability_schools.get(killing.get("abilityGameID")),
        },
        "hpBeforePct": round(100 * hp_before / max_hp),
        "overkill": overkill,
        "maxHp": max_hp,
        "wouldSave": per_button,               # name -> True / False / None (can't estimate)
        "details": details,                    # name -> the numbers behind each verdict (_explain)
        # Which scored names are the Healthstone / potion they carry.
        "consumables": {e["name"]: e["kind"] for e in consumables},
        "allTogetherWouldSave": verdict(scored) if scored else None,
        # Why a defensive might not help against this particular hit.
        "ignoresReduction": _ignores_reduction(killing),
        "ignoresImmunity": killing.get("abilityGameID") in IGNORES_IMMUNITY,
    }
