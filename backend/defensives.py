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
from bisect import bisect_right
import json
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from armor_constants import ARMOR_K, IGNORES_ARMOR, REDUCED_BY_ARMOR
from boss_spell_flags import IGNORES_IMMUNITY
from raid_wide_damage import RAID_WIDE
from defensive_catalog import CATALOGS, HEALING_TAKEN, LATEST, PATCHES
from spell_icons import DESCRIPTIONS as CATALOG_DESCRIPTIONS, ICONS as CATALOG_ICONS
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
        # Shields a talent adds to a button (Matted Fur): scored from their real size in the log.
        self.observed_auras = sorted({c["aura"] for d in self.all.values() for c in d.get("mitigation") or ()
                                      if isinstance(c, dict) and c.get("aura")})
        self.buff_names = sorted({d["name"] for d in list(self.personal.values()) + list(self.external.values())}
                                 | set(self.observed_auras))
        heal = HEALING_TAKEN.get(patch, {})
        self.heal_talents = heal.get("talents", [])
        self.heal_auras = {int(k): v for k, v in heal.get("auras", {}).items()}
        # Talent entries the analysis ever looks at: granting, replacing or
        # modifying a tracked ability, or changing healing taken. Loadouts are
        # trimmed to these (nothing else is read).
        entries = set()
        for d in self.all.values():
            entries.update(d["talent_entries"], d.get("replaced_by_entries", ()))
            entries.update(((d.get("needs_form") or {}).get("unless") or {}).get("entries", ()))
            for c in d.get("mitigation") or []:
                if isinstance(c, dict) and c.get("needs"):
                    entries.update(c["needs"].get("entries", ()))
            for m in [m for c in (d.get("mitigation") or []) for m in _mods(c)] \
                    + d.get("cooldown_mods", []) + d.get("charge_mods", []) + d.get("duration_mods", []):
                entries.update(m.get("entries", ()))
        for m in self.heal_talents:
            entries.update(m.get("entries", ()))
        self.relevant_talent_entries = frozenset(entries)
        self.name_to_id = {}
        for sid, d in list(self.personal.items()) + list(self.external.items()):
            self.name_to_id.setdefault(d["name"], sid)
        demonic = [v for p, v in DEMONIC_HEALTHSTONE_MEASURED if _patch_key(p) <= _patch_key(patch)]
        self.demonic_healthstone = demonic[-1] if demonic else None
        # What a Soulwell hands out (Demonic Healthstones are the Warlock's own, by talent).
        self.soulwell_stone = next((sid for sid, d in self.consumable.items() if d["name"] == "Healthstone"), None)
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
    return clean_icon((report_icons or {}).get(name))


def clean_icon(icon):
    """A report's icon file name ("warlock_-healthstone.jpg") as the icon servers name it."""
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
            **({"typicalHeal": typical} if typical else {}),
            **({"description": CATALOG_DESCRIPTIONS[name]} if name in CATALOG_DESCRIPTIONS else {})}


# Changes whenever what gets fetched or kept for defensives changes, so cached
# data from an older catalog is never reused. Bump DATA_SHAPE when the
# indexed layout changes.
DATA_SHAPE = 4
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
           resources=False, shape=None):
    """All pages of one event query, scoped either to boss pulls or to a time range.
    `shape(event)`, if given, is what's kept of each event as its page arrives."""
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
        page = block.get("data") or []
        events += page if shape is None else [shape(e) for e in page]
        start = block.get("nextPageTimestamp")
        if not start:
            break
    return events


def _loadout(e):
    """What index_defensive_events reads from a CombatantInfo event (who, which pull, spec, talent
    picks), not the gear, stats and auras each one also carries."""
    out = {k: e[k] for k in ("type", "timestamp", "fight", "sourceID", "specID") if k in e}
    if e.get("talentTree") is not None:
        out["talentTree"] = [{k: t[k] for k in ("id", "rank") if k in t} for t in e["talentTree"]]
    return out


def fetch_combatants(token, report_code, fight_ids, start_time, end_time):
    """Talent loadouts recorded at the start of each boss pull (CombatantInfo).

    Also the cheapest first query on a report WarcraftLogs hasn't read lately:
    measured on fresh Mythic logs, it costs about 2 points there and the
    queries after it about 1 each, while Deaths or Casts sent first cost 4-17
    and queries sent at the same moment each pay that first price."""
    return _paged(token, report_code, "CombatantInfo", None, fight_ids=fight_ids, start_time=start_time,
                  end_time=end_time + 1, shape=_loadout)


def fetch_defensive_raw(token, report_code, fight_ids, start_time, end_time, cat=None, combatants=None):
    """Defensive casts, defensive auras, talent loadouts and consumable heals for one report,
    for every player (the four queries run at once). Keep only the players who
    died with filter_defensive_raw.

    - Casts and auras cover the whole time range (trash and time between pulls
      included, from 3 minutes before the first pull) so a defensive pressed
      just before a pull counts. They're filtered to the players who died
      afterwards, not in the query: WCL returns nothing for `source.id in (...)`
      / `target.id in (...)` on Casts and Buffs (verified on a live log), and
      the unfiltered query costs fewer points anyway.
    - Talent loadouts are only recorded at pull start, so they're scoped to
      the boss pulls.
    - Healthstone and potion heals in the boss pulls, with max health: how
      much each player's own consumables really heal (potion rank, talents
      and buffs included). Scoped to boss pulls, which costs least.
    `combatants`: talent loadouts already read (fetch_combatants), not fetched again.
    """
    cat = cat or _LATEST
    lookback = max(0, start_time - ENCOUNTER_RESET_MS)
    cast_filter = f"type = \"cast\" and ability.id in ({', '.join(map(str, cat.cast_ids))})"
    buff_filter = "ability.name in (" + ", ".join(f'"{n}"' for n in cat.buff_names) + ")"
    heal_filter = f"ability.id in ({', '.join(map(str, sorted(cat.consumable)))})"
    jobs = {
        "casts": ("Casts", cast_filter, None, lookback, False),
        "buffs": ("Buffs", buff_filter, None, lookback, False),
        "heals": ("Healing", heal_filter, fight_ids, start_time, True),
    }
    with ThreadPoolExecutor(max_workers=len(jobs) + 1) as pool:
        futures = {k: pool.submit(_paged, token, report_code, dt, flt, fight_ids=ids, start_time=start,
                                  end_time=end_time + 1, resources=res)
                   for k, (dt, flt, ids, start, res) in jobs.items()}
        if combatants is None:
            futures["combatants"] = pool.submit(fetch_combatants, token, report_code, fight_ids, start_time, end_time)
        out = {k: f.result() for k, f in futures.items()}
    if combatants is not None:
        out["combatants"] = combatants
    return out


def filter_defensive_raw(raw, player_ids, cat=None):
    """fetch_defensive_raw's events for the given players only, indexed (index_defensive_events)."""
    players = set(player_ids)
    if not players:
        return {"casts": {}, "buffs": {}, "talents": {}, "heals": {}}
    return index_defensive_events({
        "casts": [e for e in raw.get("casts", []) if e.get("sourceID") in players],
        "buffs": [e for e in raw.get("buffs", []) if e.get("targetID") in players],
        "combatants": [e for e in raw.get("combatants", []) if e.get("sourceID") in players],
        "heals": [e for e in raw.get("heals", []) if e.get("targetID") in players],
    }, cat or _LATEST)


def fetch_defensive_events(token, report_code, fight_ids, start_time, end_time, player_ids, cat=None):
    """Defensive casts, auras, talent loadouts and consumable heals for the given players (see fetch_defensive_raw)."""
    if not set(player_ids):
        return {"casts": {}, "buffs": {}, "talents": {}, "heals": {}}
    return filter_defensive_raw(fetch_defensive_raw(token, report_code, fight_ids, start_time, end_time, cat),
                                player_ids, cat)


# WCL's specID (CombatantInfo, recorded at the start of every pull) -> spec name
# as WCL's playerDetails and the catalog write it.
SPEC_NAMES = {
    250: "Blood", 251: "Frost", 252: "Unholy",
    577: "Havoc", 581: "Vengeance", 1480: "Devourer",
    102: "Balance", 103: "Feral", 104: "Guardian", 105: "Restoration",
    1467: "Devastation", 1468: "Preservation", 1473: "Augmentation",
    253: "BeastMastery", 254: "Marksmanship", 255: "Survival",
    62: "Arcane", 63: "Fire", 64: "Frost",
    268: "Brewmaster", 269: "Windwalker", 270: "Mistweaver",
    65: "Holy", 66: "Protection", 70: "Retribution",
    256: "Discipline", 257: "Holy", 258: "Shadow",
    259: "Assassination", 260: "Outlaw", 261: "Subtlety",
    262: "Elemental", 263: "Enhancement", 264: "Restoration",
    265: "Affliction", 266: "Demonology", 267: "Destruction",
    71: "Arms", 72: "Fury", 73: "Protection",
}


_UNKNOWN_SPECS = set()


def pull_spec(indexed, fight_id, player_id, fallback=None):
    """The spec a player played in one pull (they swap between pulls); `fallback` (the report's) if not recorded."""
    return ((indexed or {}).get("specs") or {}).get((fight_id, player_id)) or fallback


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
    specs = {}                          # (fightID, sourceID) -> spec name that pull (players swap between pulls)
    for e in raw.get("combatants", []):
        if e.get("sourceID") is not None and SPEC_NAMES.get(e.get("specID")):
            specs[(e.get("fight"), e["sourceID"])] = SPEC_NAMES[e["specID"]]
        elif e.get("specID") and e["specID"] not in _UNKNOWN_SPECS:
            _UNKNOWN_SPECS.add(e["specID"])     # a new spec: falls back to the report's until added
            print(f"[WARN] Unknown specID {e['specID']}: add it to defensives.SPEC_NAMES")
    for e in raw.get("combatants", []):
        tree = e.get("talentTree")
        if tree is None or e.get("sourceID") is None:
            continue
        talents[(e.get("fight"), e["sourceID"])] = {t["id"]: t.get("rank") or 1 for t in tree
                                                     if t.get("id") in cat.relevant_talent_entries}
    # targetID -> [(ts, spellID, healed incl. overheal, max health, healing-taken buffs multiplier,
    #              Versatility in hundredths of a percent, fightID)]
    heals = defaultdict(list)
    for e in raw.get("heals", []):
        full = (e.get("amount") or 0) + (e.get("overheal") or 0) + (e.get("absorbed") or 0)
        if e.get("type") == "heal" and not e.get("tick") and full > 0 and e.get("targetID") is not None \
                and e.get("sourceID") == e.get("targetID"):
            heals[e["targetID"]].append((e["timestamp"], e.get("abilityGameID"), full, e.get("maxHitPoints") or 0,
                                         round(_heal_taken_mult(_auras(e), cat), 4),
                                         e.get("versatility") if e.get("resourceActor") == 1 else None,
                                         e.get("fight")))
    for lst in casts.values():
        lst.sort()
    for lst in buffs.values():
        lst.sort(key=lambda x: x[0])
    return {"casts": dict(casts), "buffs": dict(buffs), "talents": talents, "heals": dict(heals), "specs": specs}


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


def _talented_duration(entry, talent_entries, spec):
    """How long the aura lasts after the player's talents and spec passives (Anti-Magic Barrier,
    Improved Barkskin): checked on live logs, e.g. Anti-Magic Shell 5s -> 7s, Barkskin 8s -> 12s."""
    ms = entry.get("aura_ms")
    if not ms or ms < 0:
        return ms
    mult = 1.0
    for m in entry.get("duration_mods", ()):
        rank = _mod_rank(m, talent_entries, spec)
        if rank and "add_ms" in m:
            ms += m["add_ms"] * rank
        elif rank:
            mult *= 1 + (m["mult"] - 1) * rank
    return max(ms * mult, 0)


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


def _ready_since(death_ts, casts_in_window, charges, recharge_ms):
    """When an ability that is ready at the death last came off cooldown (None: ready all along)."""
    have, recharge_done, since = charges, None, None
    for t in list(casts_in_window) + [death_ts]:
        while recharge_done is not None and recharge_done <= t:
            if have == 0:
                since = recharge_done
            have += 1
            recharge_done = recharge_done + recharge_ms if have < charges else None
        if t == death_ts:
            break
        have = max(have - 1, 0)
        if recharge_done is None:
            recharge_done = t + recharge_ms
    return since


# Heals over time among the scored defensives, by tick count: their heal lands
# over the aura's duration, not at once. Same tick counts as EFFECTS in
# scripts/build_defensive_catalog.py (tested).
HEAL_OVER_TIME = {"Frenzied Regeneration": 3, "Crimson Vial": 4}


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
    """The player's overkill hit (or instant kill) that caused this death, if one was recorded."""
    found = None
    for h in killing_blows or ():
        if death_ts - 2_000 <= h["timestamp"] <= death_ts + KILLING_BLOW_AFTER_MS and \
                (h.get("type") == "instakill" or (h.get("overkill") or 0) > 0):
            found = h
    return found


def _auras(hit):
    """Aura IDs WCL lists on a damage event ("108416.1022." -> {108416, 1022})."""
    return {int(a) for a in str(hit.get("buffs") or "").split(".") if a.isdigit()}


def analyze_death(player_id, player_class, spec, fight_id, fight_start, death_ts,
                  indexed, ability_names, actor_names, hits=None, ability_schools=None, cat=None,
                  aoe_known=True, armor_k=None, soulwell=False):
    """Defensive picture for one death. All timestamps are report-relative ms.

    With `hits` (the player's hits in the seconds before their deaths, and
    instant kills: fetch_death_windows, fetch_instakills) it also estimates
    whether the defensives they had ready would have saved them.
    `cat`: the catalog of the patch the report was logged on (catalog_for).
    `aoe_known`: whether this report marks AoE hits at all (logs_mark_aoe).
    `armor_k`: the boss's armor constant (armor_constant), for armor increases.
    `soulwell`: a Warlock was in this pull, so a Soulwell's Healthstones were
    there for everyone, used in this log or not.
    """
    cat = cat or _LATEST
    own_casts = indexed["casts"].get(player_id, [])
    casts_by_spell = defaultdict(list)
    for t, sid in own_casts:
        casts_by_spell[sid].append(t)
    talent_entries = indexed["talents"].get((fight_id, player_id))
    talents_by_fight = {f: t for (f, p), t in indexed["talents"].items() if p == player_id}

    # Auras on the player at death, matched to the catalog by name (aura IDs
    # often differ from the button's spell ID) -> who applied them.
    # The killing blow's aura list is the game's snapshot at the moment of the
    # hit (verified on live logs: no list means no auras), so it decides what
    # was up; the aura events add who cast externals. Without a killing blow,
    # the aura events decide, capped by each aura's duration.
    killing = _killing_blow(hits, death_ts)
    if killing is not None and killing.get("type") == "instakill":
        killing = None       # an instant kill carries no aura snapshot; aura events decide
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
    ready_entries, ready_since = [], {}

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
            since = _ready_since(death_ts, window, charges, recharge)
            ready_since[name] = max(fight_start, since if since is not None else fight_start)
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

    # Healthstones (60s) and health potions (5 min, shared between health
    # potions, not with combat potions) are on cooldown from their last use
    # this pull; the cooldown resets between pulls. Measured on live logs:
    # repeat uses within a pull are always at least that far apart, and
    # several per pull are common.
    unused_consumables, from_soulwell = [], None
    for kind in ("healthstone", "potion"):
        used = [(t, sid) for t, sid in own_casts
                if cat.consumable.get(sid, {}).get("kind") == kind and fight_start <= t <= death_ts]
        cooldown = cat.all[used[-1][1]]["cooldown_ms"] if used else 0
        if used and death_ts - used[-1][0] < cooldown:
            result[kind] = {"usedAgo": round((death_ts - used[-1][0]) / 1000), "name": cat.all[used[-1][1]]["name"],
                            "readyIn": round((used[-1][0] + cooldown - death_ts) / 1000)}
            rank = potion_rank(used[-1][1], cat, (indexed.get("heals") or {}).get(player_id, []),
                               talent_entries, spec, talents_by_fight) if kind == "potion" else None
            if rank:
                result[kind]["rank"] = rank
            continue
        result[kind] = {"usedAgo": None}
        ready_at = fight_start
        if used:
            result[kind]["lastUsedAgo"] = round((death_ts - used[-1][0]) / 1000)
            ready_at = used[-1][0] + cooldown
        # Only assume they carry one if they used that kind somewhere in this log,
        # or, for a Healthstone, a Warlock in the pull had a Soulwell for them.
        carried = [sid for _, sid in own_casts if cat.consumable.get(sid, {}).get("kind") == kind]
        if carried:
            unused_consumables.append(carried[-1])
        elif kind == "healthstone" and soulwell and cat.soulwell_stone:
            unused_consumables.append(cat.soulwell_stone)
            from_soulwell = cat.soulwell_stone
        if unused_consumables and cat.consumable[unused_consumables[-1]]["kind"] == kind:
            ready_since[cat.all[unused_consumables[-1]]["name"]] = ready_at

    # Real shield sizes this player got from their own shields in this log
    # (latest before the death, else any): exact, gear and talents included.
    observed = {}
    for ts, typ, aid, src, amount in (e + (0,) * (5 - len(e)) for e in (buff_events or {}).get(player_id, [])):
        name = ability_names.get(aid)
        if amount and src == player_id and typ in ("applybuff", "refreshbuff") and \
                (name in cat.name_to_id or name in cat.observed_auras):
            if ts <= death_ts or name not in observed:
                observed[name] = amount

    boosts = {e["name"]: _resolve(e, talent_entries, observed, spec)[1] for e in ready_entries}
    for a in result["available"]:
        if boosts.get(a["name"]):
            a["boostedBy"] = boosts[a["name"]]

    # Buttons that need a form the player wasn't in (Frenzied Regeneration needs
    # Bear Form unless a talent lifts that): judged as shifting, then pressing.
    forms = {}
    for e in ready_entries:
        need = e.get("needs_form")
        if not need or need["form"] in active_names or _mod_rank(need.get("unless") or {}, talent_entries, spec):
            continue
        form = next((f for f in ready_entries if f["name"] == need["form"]), None)
        if form is not None:
            forms[e["name"]] = form
    for a in result["available"]:
        if a["name"] in forms:
            a["withForm"] = forms[a["name"]]["name"]
    # The armor bonus of the form they were in (Moonkin Form), from the killing blow's aura snapshot.
    form_armor = 1.0
    for e in ready_entries:
        for aid, mult in (e.get("form_armor") or {}).items():
            if killing is not None and int(aid) in _auras(killing):
                form_armor *= mult

    if hits is not None:
        death_mult = _heal_taken_mult(_auras(killing), cat) if killing is not None else 1.0
        own_heals = (indexed.get("heals") or {}).get(player_id, [])
        consumables = [consumable_estimate(sid, cat, own_heals, death_mult, talent_entries, spec, talents_by_fight)
                       for sid in unused_consumables]
        for sid, c in zip(unused_consumables, consumables):
            if sid == from_soulwell:
                c["soulwell"] = True
        result["survival"] = assess_survival(hits, death_ts, ready_entries, consumables,
                                             ability_names, ability_schools or {},
                                             talent_entries=talent_entries, observed_absorbs=observed, spec=spec,
                                             aoe_known=aoe_known, ready_since=ready_since,
                                             aura_ms={e["name"]: _talented_duration(e, talent_entries, spec) for e in ready_entries},
                                             forms=forms, armor_k=armor_k, form_armor=form_armor)

    for key in ("active", "available", "cooldown"):
        result[key].sort(key=lambda d: (not d.get("major", True), d["name"]))
    return result


# =============================================================================
# WOULD A DEFENSIVE HAVE SAVED THEM?
# =============================================================================
#
# Judged against the seconds before the death, not only the killing blow: the
# last hit is often a small tick or a bit of residual damage that finished off
# a player a big hit had left low, and a defensive pressed before that big hit
# would have kept them alive. For every death that can count, every hit the
# player took in the LETHAL_WINDOW_MS before it is fetched, with their health
# after each one (one request per report, one block per pull: about 1 WCL
# point per pull with counted deaths). Those seconds are then replayed with the
# defensive pressed at its best moment (assess_survival).

FULL_HEALTH = 0.85           # at or above this = high health (88% reads as full)
PHYSICAL = 1
INSTAKILL_FILTER = "type = 'instakill'"
# How far before a death its hits are fetched and replayed. Longer than every
# common defensive lasts (Fortifying Brew, 15s, is among the longest).
LETHAL_WINDOW_MS = 15_000
# A press counts only this long before the killing blow or earlier: nobody can
# react to a hit faster, so a heal can't land between a big hit and a tick that
# follows it within a second.
REACTION_MS = 1_000
# A one-shot: a single hit of at least this share of max health, from high health.
ONE_SHOT_SHARE = 0.80
# A hit before the killing blow is named with the death (biggestHit) when it's
# at least this share of max health and came after they were last at high health.
SETUP_HIT_SHARE = 0.10
# Rot: since they were last at high health, one raid-wide ability (RAID_WIDE)
# hit them at least this many times for at least this share of the damage, and
# none of its hits was a big chunk (this share of max health or more).
ROT_MIN_HITS = 3
ROT_SHARE = 0.6
ROT_MAX_HIT = 0.35
# A killing blow can be logged this long after the death event.
KILLING_BLOW_AFTER_MS = 50
# Pulls whose death windows fall within this span share one event block.
WINDOW_BLOCK_SPAN_MS = 900_000
# Event blocks per request: WCL caps a query's complexity.
WINDOW_BLOCKS_PER_REQUEST = 20

# Everything the survival assessment reads from a hit (the rest, like
# positions and stats, is dropped so cached reports stay small).
HIT_FIELDS = ("timestamp", "type", "sourceID", "targetID", "abilityGameID", "fight", "buffs",
              "hitType", "amount", "overkill", "absorbed", "mitigated", "unmitigatedAmount",
              "isAoE", "resourceActor", "hitPoints", "maxHitPoints", "armor")


def _events_query(blocks):
    """One request for several event blocks: {alias: (fightIDs, start, end, dataType, filter)}."""
    parts = []
    for alias, (ids, start, end, data_type, flt) in blocks.items():
        parts.append(f"{alias}: events(fightIDs: {json.dumps(list(ids))}, startTime: {start}, endTime: {end}, "
                     f"dataType: {data_type}, filterExpression: {json.dumps(flt, ensure_ascii=False)}, includeResources: true, "
                     f"limit: 10000) {{ data nextPageTimestamp }}")
    return "query($c: String!) { reportData { report(code: $c) { " + " ".join(parts) + " } } }"


def _fetch_blocks(token, report_code, blocks, keep=None):
    """All events of several blocks, fetched together; blocks that don't fit one page are followed up.
    `keep(event)`, if given, picks the events kept as each block's page arrives, so the
    others aren't held in memory while the rest download.

    Always with an endTime: WCL returns an empty second page for a block scoped
    by fightIDs without one (verified on a live log).
    """
    out = {alias: [] for alias in blocks}
    pending = dict(blocks)
    for _ in range(50):
        if not pending:
            break
        nxt = {}
        items = list(pending.items())
        for i in range(0, len(items), WINDOW_BLOCKS_PER_REQUEST):
            chunk = dict(items[i:i + WINDOW_BLOCKS_PER_REQUEST])
            data = graphql_query(token, _events_query(chunk), {"c": report_code})
            report = (data.get("reportData") or {}).get("report") or {}
            del data
            for alias, spec in chunk.items():
                block = report.pop(alias, None) or {}
                events = block.get("data") or []
                out[alias] += events if keep is None else [e for e in events if keep(e)]
                del events
                if block.get("nextPageTimestamp"):
                    nxt[alias] = (spec[0], block["nextPageTimestamp"]) + tuple(spec[2:])
        pending = nxt
    return out


def fetch_death_windows(token, report_code, pulls):
    """Every hit the given players took in the seconds before their deaths.

    `pulls`: [(fightID, [(death_ts, log name)])], the deaths that can count.
    WCL charges about a point per page of events and at least one per block,
    so pulls within WINDOW_BLOCK_SPAN_MS of each other share a block: from
    LETHAL_WINDOW_MS before its first death to its last, for the players who
    died (WCL filters by name; `target.id` and timestamps return nothing in a
    filter), scoped to those pulls. Measured on live Mythic logs: 19 -> 8 and
    11 -> 5 points for a night's reports, each block still one page. Only the
    hits inside a death's window are kept. Returns {targetID: [hits, by time]}.
    """
    pulls = sorted(((fid, sorted(d)) for fid, d in pulls if d and any(n for _, n in d)), key=lambda p: p[1][0][0])
    groups = []
    for fid, deaths in pulls:
        if groups and deaths[-1][0] - (groups[-1][0][1][0][0] - LETHAL_WINDOW_MS) <= WINDOW_BLOCK_SPAN_MS:
            groups[-1].append((fid, deaths))
        else:
            groups.append([(fid, deaths)])
    blocks, windows = {}, []
    for group in groups:
        deaths = [d for _, ds in group for d in ds]
        names = sorted({n for _, n in deaths if n})
        # Names as they are in the log, accents and all (an escaped é matches nobody).
        flt = "target.name in (" + ", ".join(json.dumps(n, ensure_ascii=False) for n in names) + ")"
        start = max(min(t for t, _ in deaths) - LETHAL_WINDOW_MS, 0)
        # A killing blow can be logged a few ms after the death (_killing_blow).
        end = max(t for t, _ in deaths) + KILLING_BLOW_AFTER_MS + 1
        blocks[f"p{group[0][0]}"] = ([fid for fid, _ in group], start, end, "DamageTaken", flt)
        windows += [(t - LETHAL_WINDOW_MS, t + KILLING_BLOW_AFTER_MS) for t, _ in deaths]
    if not blocks:
        return {}
    windows.sort()

    def in_a_window(ts):
        # Windows are all as long: the one starting last at or before ts ends last too.
        i = bisect_right(windows, (ts, float("inf"))) - 1
        return i >= 0 and ts <= windows[i][1]

    def keep(e):
        return e.get("type") == "damage" and in_a_window(e.get("timestamp", 0))

    events = [e for evs in _fetch_blocks(token, report_code, blocks, keep).values() for e in evs]
    return index_hits(events)


def fetch_instakills(token, report_code, fight_ids, start_time, end_time):
    """Instant kills in the given pulls (a mechanic that kills outright, like
    Eternal Venom at max stacks): they deal no damage, so they're only in the
    full event stream. About 1 WCL point per report."""
    blocks = {"k": (list(fight_ids), start_time, end_time + 1, "All", INSTAKILL_FILTER)}
    return index_hits(_fetch_blocks(token, report_code, blocks)["k"])


def logs_mark_aoe(hits_by_player):
    """Does this report mark AoE hits? Older logs (The War Within) have isAoE
    false on every hit, so a report with no AoE hit at all doesn't."""
    return any(h.get("isAoE") for hits in (hits_by_player or {}).values() for h in hits)


def index_hits(events):
    """{targetID: [hits and instant kills, sorted by time]}

    Health and armor are kept only when they're the target's own: WCL attaches
    the source's (resourceActor 1) to some hits, which for self-damage
    (Refraction) is the same player and for anything else is someone else.
    """
    idx = defaultdict(list)
    for e in events:
        if e.get("targetID") is None or e.get("type") not in ("damage", "instakill"):
            continue
        h = {k: e[k] for k in HIT_FIELDS if k in e}
        if h.get("resourceActor") == 1:
            if e.get("sourceID") == e["targetID"]:
                h["resourceActor"] = 2
            else:
                for k in ("resourceActor", "hitPoints", "maxHitPoints", "armor"):
                    h.pop(k, None)
        idx[e["targetID"]].append(h)
    for hits in idx.values():
        hits.sort(key=lambda e: e["timestamp"])
    return dict(idx)


def merge_hits(*indexes):
    """Several {targetID: [hits]} indexes as one, each player's hits by time.

    No de-duplication: identical hits at the same millisecond are real (three
    Toxic Droplets soaked at once), and the indexes never overlap (windows are
    damage in separate pulls, instant kills aren't damage).
    """
    out = defaultdict(list)
    for idx in indexes:
        for pid, hits in (idx or {}).items():
            out[pid] += hits
    return {pid: sorted(hs, key=lambda e: e["timestamp"]) for pid, hs in out.items()}


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
    if isinstance(school, int):           # a set of schools from the game data (Bear Form: arcane)
        if immunity:
            return mask != 0 and not mask & ~school
        return bool(mask & school)
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


ARMOR_CAP = 0.85                     # armor never reduces a hit by more than this


def armor_constant(encounter_id, difficulty):
    """K in armor / (armor + K) for a boss's hits (armor_constants.py; Mythic's when a difficulty wasn't measured)."""
    for d in (difficulty, 5, 4, 3):
        k = (ARMOR_K.get(d) or {}).get(encounter_id)
        if k:
            return k
    return None


def _armor_reduction(hit, ability_schools):
    """Does armor reduce this hit: True / False, or None when that isn't known.

    Only purely physical hits; boss melee swings always, other physical spells
    as measured in the logs (some ignore armor).
    """
    ability = hit.get("abilityGameID")
    if ability == MELEE_SWING:
        return True
    if ability_schools.get(ability, 0) != PHYSICAL:
        return False
    if ability in IGNORES_ARMOR:
        return False
    return True if ability in REDUCED_BY_ARMOR else None


def _armor_dr(extra, hit):
    """Extra damage reduction from raising the player's armor by `extra` (2.2 = +220%) against this hit.

    From their real armor on the killing blow and the boss's armor constant:
    what armor already took off is in the hit, so only the added part counts.
    None when the armor or the constant isn't known.
    """
    armor, k = hit.get("armor"), hit.get("armorK")
    if not armor or not k:
        return None
    before = min(armor / (armor + k), ARMOR_CAP)
    raised = armor * (1 + extra)          # extra can be below 0 when a form's bonus comes off
    after = min(raised / (raised + k), ARMOR_CAP)
    return 1 - (1 - after) / (1 - before)


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
        field = next(f for f in FIELDS if f in c)
        value = c[field]
        needs = c.get("needs")
        seen = observed_absorbs.get(c.get("aura") or entry["name"]) if field == "absorb" and c.get("observed") else None
        if needs:
            # An effect a talent adds (Niuzao's Protection's shield on Fortifying
            # Brew): only for players who have it, scaled by its rank.
            rank = _mod_rank(needs, talent_entries, spec)
            if not rank or (value is None and not seen):
                continue                 # not talented, or a talent's shield that wasn't seen in the log
            boosted.append(needs["talent"])
            if applied is not None:
                applied.append({"talent": needs["talent"], "field": field, "rank": rank,
                                "adds": seen if value is None else value,
                                **({"school": c["school"]} if c.get("school") else {})})
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = value * rank
        extra = {k: c[k] for k in ("over_ms", "ticks", "current", "replaces_form") if k in c}
        if seen:
            out.append({"absorb_amount": seen, "school": c.get("school")})
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
            out.append({field: value, "school": c.get("school"), **extra})
    return out, boosted


# Component fields, in the order they're recognised (see _resolve).
FIELDS = ("immune", "dr", "dr_missing", "armor", "absorb", "hp", "heal", "heal_amount", "heal_taken")


def _heal_talent_mult(entry, cat, talent_entries, spec):
    """How much this player's talents raise a potion's heal: healing-taken talents and
    talents that boost potions (Iron Stomach). Returns (multiplier, [talent changes])."""
    mult, applied = 1.0, []
    mods = list(cat.heal_talents) + [m for c in entry.get("mitigation") or () for m in _mods(c)]
    for m in mods:
        rank = _mod_rank(m, talent_entries, spec)
        if rank and "mult" in m:
            mult *= 1 + (m["mult"] - 1) * rank
            applied.append({"talent": m["talent"], "field": "heal_amount", "rank": rank, "mult": m["mult"]})
    return mult, applied


# A heal a hair under a rank's tooltip still reaches it (rounding).
RANK_TOLERANCE = 0.005
# Potions are the drinker's own heal, so their class and spec healing bonuses
# raise it too, by up to this much for players who reach silver (measured on
# live Midnight logs, Versatility and buffs taken out: never above 16%). A rank
# is only claimed when the rank below heals at least this much less, so no
# bonus could make a lower rank look like it (Midnight: 17% apart; The War
# Within's ranks are 4% apart, so its ranks can't be told apart).
RANK_BONUS_MAX = 0.16


def potion_rank(sid, cat, own_heals, talent_entries, spec, talents_by_fight=None):
    """The quality rank of a potion this player drinks, from their own heals with it.

    A potion heals at least its rank's tooltip amount: Versatility (on each
    heal event), healing-taken buffs, talents and class healing bonuses only
    raise it. With Versatility, buffs and known talents taken out, the middle
    of their heals reaches the tooltip of the rank they drink and no higher
    one. Returns the rank; {"unknown": ...} when the ranks are too close to
    tell apart; None when the potion has no ranks in this patch, they didn't
    drink it in these boss pulls, or their heals are under every tooltip.

    Talents are recorded per pull and players swap them (and specs) between
    pulls, so each heal is judged with the talents of the pull it was drunk
    in (`talents_by_fight`: {fightID: talent entries}); `talent_entries` (the
    death's pull) stands in for a pull without a record.
    """
    entry = cat.all.get(sid) or {}
    ranks = entry.get("ranks")
    own = [h for h in own_heals if h[1] == sid]
    if not ranks or not own:
        return None
    talents_by_fight = talents_by_fight or {}
    _, applied = _heal_talent_mult(entry, cat, talent_entries, spec)
    talent_mult = [_heal_talent_mult(entry, cat, talents_by_fight.get(h[6] if len(h) > 6 else None, talent_entries),
                                     spec)[0] for h in own]
    vers = [(h[5] if len(h) > 5 and h[5] is not None else 0) / 10_000 for h in own]
    base = statistics.median(h[2] / (h[4] or 1.0) / (1 + v) / m for h, v, m in zip(own, vers, talent_mult))
    reached = [i for i, r in enumerate(ranks) if base >= r["heal"] * (1 - RANK_TOLERANCE)]
    info = {"of": len(ranks), "ranks": [{"rank": r["rank"], "heal": r["heal"]} for r in ranks], "n": len(own),
            "base": round(base), "raw": round(statistics.median(h[2] for h in own)),
            "vers": round(statistics.median(vers) * 100, 1), **({"talents": applied} if applied else {})}
    if not reached:
        return None
    i = reached[-1]
    if i > 0 and ranks[i]["heal"] < ranks[i - 1]["heal"] * (1 + RANK_BONUS_MAX):
        return {**info, "unknown": round((ranks[i]["heal"] / ranks[i - 1]["heal"] - 1) * 100, 1)}
    return {**info, "rank": ranks[i]["rank"], "heal": ranks[i]["heal"],
            "bonus": round((base / ranks[i]["heal"] - 1) * 100, 1)}


def consumable_estimate(sid, cat, own_heals, death_mult, talent_entries, spec, talents_by_fight=None):
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
    # Their own uses of this exact potion or Healthstone. The log names only the
    # spell, which both quality ranks of a potion share (different items and
    # item levels, different heals), so their own heals are what show the rank
    # they drink. Potions don't crit (none in 582 live heals).
    own = [h for h in own_heals if h[1] == sid]
    out = {"name": entry["name"], "kind": entry["kind"], "estimated": True, "boostedBy": []}
    if entry["kind"] == "healthstone":
        shares = [h[2] / h[3] for h in own if h[3]]
        extra = [c for c in (entry.get("mitigation") or []) if "hp" in c]     # Soulburn: Healthstone
        extra, boosted = _resolve({"mitigation": extra, "name": entry["name"]}, talent_entries, {}, spec)
        if shares:
            out["mitigation"] = [{"heal": statistics.median(shares)}] + (extra or [])
            out["source"] = "log"
            out["samples"] = {"n": len(shares), "minShare": round(min(shares), 3), "maxShare": round(max(shares), 3)}
        elif entry["name"] == "Demonic Healthstone" and cat.demonic_healthstone:
            out["mitigation"] = [{"heal": cat.demonic_healthstone}] + (extra or [])
            out["source"] = "typical"
        else:
            out["applied"] = []
            out["mitigation"], out["boostedBy"] = _resolve(entry, talent_entries, {}, spec, out["applied"])
            out["source"] = "gameData"
        return out
    if own:
        heals = [h[2] / (h[4] or 1.0) for h in own]
        amount = statistics.median(heals) * death_mult
        out["mitigation"] = [{"heal_amount": amount}]
        out["source"] = "log"
        # What their own potions healed (healing-taken buffs taken out), for the tooltip.
        out["samples"] = {"n": len(heals), "min": round(min(heals)), "max": round(max(heals))}
        rank = potion_rank(sid, cat, own_heals, talent_entries, spec, talents_by_fight)
        if rank:
            out["rank"] = rank
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
    if cat.all[sid].get("ranks"):
        out["ranks"] = [{"rank": r["rank"], "heal": r["heal"]} for r in cat.all[sid]["ranks"]]
    out["mitigation"] = [{"heal_amount": typical * talent_mult * death_mult}]
    out["applied"], out["typical"] = applied, typical
    out["boostedBy"], out["source"] = boosted, "typical"
    return out


def _full_hit(hit):
    """Whole hit: WCL's `amount` is only the health it took (the rest is `overkill`, or absorbed)."""
    return (hit.get("amount") or 0) + (hit.get("overkill") or 0) + (hit.get("absorbed") or 0)


def _effect_applies(m, hit, ability_schools):
    """Does one component apply to this hit: True / False / None (unknown)."""
    if m.get("armor"):
        return _armor_reduction(hit, ability_schools) and (True if _armor_dr(m["armor"], hit) is not None else None)
    return _school_applies(m.get("school"), hit, ability_schools, immunity=bool(m.get("immune")))


def _keep(comps, hit, max_hp, missing_hp, ability_schools):
    """Share of a hit that still lands through the given reductions and immunities (shields aside).

    Reductions are skipped for a hit that ignored them, immunities for spells
    that pierce them. Armor increases multiply (Bear Form x Ursine Vigor);
    shifting forms takes the current form's armor bonus off first.
    """
    keep, armor_up = 1.0, 1.0
    no_reduction = _ignores_reduction(hit)
    for m in comps:
        if not any(f in m for f in ("immune", "armor", "dr", "dr_missing")):
            continue
        if not _effect_applies(m, hit, ability_schools):
            continue           # doesn't apply, or unknown (counted as not helping)
        if m.get("immune"):
            if hit.get("abilityGameID") not in IGNORES_IMMUNITY:
                keep = 0.0
        elif m.get("armor"):
            armor_up *= 1 + m["armor"]
        elif not no_reduction:
            dr = m.get("dr") or 0
            if m.get("dr_missing"):              # up to its value at no health, by missing health
                dr += m["dr_missing"] * missing_hp / max_hp
            keep *= 1 - min(dr, 1.0)
    if armor_up > 1 and not no_reduction:
        if any(m.get("replaces_form") for m in comps):
            armor_up /= hit.get("formArmor") or 1.0
        keep *= 1 - _armor_dr(armor_up - 1, hit)
    return keep


def _health_points(hits):
    """[(ts, health, max health)] just before and just after every hit with the player's health on it.

    Between two hits only heals land, so these points bound the health they
    had at any moment (verified on live logs: health after a hit plus what it
    took equals the health after the one before, unless heals landed).
    """
    points = []
    for h in hits:
        if h.get("resourceActor") == 2 and h.get("maxHitPoints") and h.get("type") == "damage":
            after = h.get("hitPoints") or 0
            points.append((h["timestamp"] - 0.5, after + (h.get("amount") or 0), h["maxHitPoints"]))
            points.append((h["timestamp"], after, h["maxHitPoints"]))
    return points


def _health_at(points, t):
    """(health, max health) at time t: the last point at or before it (health only rises between hits)."""
    if not points:
        return (0, 0)
    times = points.times if isinstance(points, _Points) else [p[0] for p in points]
    i = bisect_right(times, t) - 1
    p = points[i if i >= 0 else 0]
    return (p[1], p[2])


class _Points(list):
    """Health points (_health_points) with their times, for lookups by time."""

    def __init__(self, points):
        super().__init__(points)
        self.times = [p[0] for p in points]


class _Window:
    """A death's replayed hits with what every replay reads from them, worked out once."""

    def __init__(self, hits, ability_schools):
        self.hits = hits
        self.schools = ability_schools
        self.points = _Points(_health_points(hits))
        self.full = [_full_hit(h) for h in hits]
        self.known = [h.get("resourceActor") == 2 and bool(h.get("maxHitPoints")) for h in hits]
        self.before = []
        for h, known in zip(hits, self.known):
            if known:
                self.before.append(((h.get("hitPoints") or 0) + (h.get("amount") or 0), h["maxHitPoints"]))
            else:
                self.before.append(_health_at(self.points, h["timestamp"]))
        self._keep = {}
        self._applies = {}

    def keep(self, comps, key, k, max_hp, missing_hp):
        """_keep for hit k, remembered under `key` (which comps) when it doesn't depend on health."""
        if key is None:
            return _keep(comps, self.hits[k], max_hp, missing_hp, self.schools)
        key = (key, k)
        if key not in self._keep:
            self._keep[key] = _keep(comps, self.hits[k], max_hp, missing_hp, self.schools)
        return self._keep[key]

    def applies(self, comp, k):
        key = (id(comp), k)
        if key not in self._applies:
            self._applies[key] = _effect_applies(comp, self.hits[k], self.schools)
        return self._applies[key]


def _option(entry_name, comps, dur_ms, legacy_ticks=None):
    """One button's effect, timed: {"name", "lasting": [(comp, ms or None)], "instant": [comp], "hots": [(comp, ticks, ms)]}.

    Effects last the aura's duration; without one (Bear Form, Soulburn's health)
    they're up until the death. Heals land when pressed, or over time.
    """
    opt = {"name": entry_name, "lasting": [], "instant": [], "hots": []}
    for c in comps or ():
        if "heal" in c or "heal_amount" in c:
            over = c.get("over_ms") or (dur_ms if legacy_ticks else None)
            if over:
                opt["hots"].append((c, c.get("ticks") or legacy_ticks or 1, over))
            else:
                opt["instant"].append(c)
        else:
            opt["lasting"].append((c, dur_ms))
    return opt


def _simulate(options, press, win, kb_index):
    """Health the player would have had on top of their real health right after the killing blow,
    with every option pressed at `press`. Returns (extra health, HoT ticks landed).

    Walks the hits in time order (hits[kb_index] is the killing blow):
      - reductions, immunities and armor take their share off every hit they
        cover; shields soak what's left of it until they run out;
      - max health increases add health when pressed (keeping the health share)
        and take it back when they run out;
      - heals add health when they land (instantly, or tick by tick);
      - all of it is health the player only keeps while they are below max:
        before each hit, the extra is capped by what they were missing then
        (their real heals would have overhealed the rest).
    The player lives if the extra is more than the killing blow's overkill.
    `win`: the death's hits, prepared (_Window).
    """
    hits, points = win.hits, win.points
    lasting = [(c, press + ms if ms else float("inf")) for o in options for c, ms in o["lasting"]]
    heal_taken = [(c["heal_taken"], until) for c, until in lasting if c.get("heal_taken")]
    hp_now, max_now = _health_at(points, press)
    extra, dmax = 0.0, 0.0

    def boost(t):
        return 1 + sum(v for v, until in heal_taken if until >= t)

    # Max health increases, grouped by how long they last (percent ones multiply).
    groups = defaultdict(lambda: [1.0, 0.0])
    for c, until in lasting:
        if c.get("hp"):
            if c.get("current"):
                groups[until][1] += c["hp"]
            else:
                groups[until][0] *= 1 + c["hp"]
    expiries = []
    for until, (share, flat) in groups.items():
        gain = hp_now * (share - 1) + flat * max_now
        grow = max_now * (share - 1 + flat)
        extra += gain
        dmax += grow
        expiries.append((until, gain, grow))
    shields = [[c.get("absorb", 0) * max_now + c.get("absorb_amount", 0), c, until]
               for c, until in lasting if c.get("absorb") or c.get("absorb_amount")]
    # Reductions, immunities and armor up, dropped as they run out (in that order).
    covering = [c for c, _ in lasting if any(f in c for f in ("immune", "armor", "dr", "dr_missing"))]
    ends = sorted(((until, c) for c, until in lasting if c in covering and until != float("inf")),
                  key=lambda x: x[0])
    sig = tuple(id(c) for c in covering)
    by_health = any(c.get("dr_missing") for c in covering)

    # Heals: (time, amount before healing-taken increases, boosted already?).
    heals = []
    for o in options:
        for c in o["instant"]:
            heals.append((press, (c.get("heal", 0) * max_now + c.get("heal_amount", 0)), c.get("boosted")))
        for c, ticks, over in o["hots"]:
            total = c.get("heal", 0) * max_now + c.get("heal_amount", 0)
            heals += [(press + over / ticks * (k + 1), total / ticks, c.get("boosted")) for k in range(ticks)]
    heals.sort(key=lambda x: x[0])
    kb_ts = hits[kb_index]["timestamp"]
    hot_ticks = sum(1 for o in options for _, ticks, over in o["hots"]
                    for k in range(ticks) if press + over / ticks * (k + 1) < kb_ts)
    hi = 0

    def land_heals(until_t):
        nonlocal extra, hi
        while hi < len(heals) and heals[hi][0] < until_t:
            t, amount, boosted = heals[hi]
            hi += 1
            hp, mx = _health_at(points, t)
            extra = min(extra + amount * (1 if boosted else boost(t)), max(mx + dmax - hp, 0))

    def expire(until_t):
        nonlocal extra, dmax
        for i, (until, gain, grow) in enumerate(expiries):
            if until < until_t and grow is not None:
                extra = max(extra - gain, 0)
                dmax -= grow
                expiries[i] = (until, gain, None)

    for k in range(kb_index + 1):
        t = hits[k]["timestamp"]
        if t <= press:
            continue
        if hi < len(heals):
            land_heals(t)
        if expiries:
            expire(t)
        hp_before, max_k = win.before[k]
        if win.known[k]:
            extra = min(extra, max(max_k + dmax - hp_before, 0))
        dmg = win.full[k]
        if not dmg:
            continue
        while ends and ends[0][0] < t:
            covering.remove(ends.pop(0)[1])
        if covering:
            key = None if by_health else (sig, len(ends))
            left = dmg * win.keep(covering, key, k, max_k, max(max_k + dmax - hp_before - extra, 0))
        else:
            left = dmg
        for sh in shields:
            if sh[0] > 0 and sh[2] >= t and left > 0 and win.applies(sh[1], k):
                took = min(sh[0], left)
                sh[0] -= took
                left -= took
        extra += dmg - left
    return extra, hot_ticks


def _prevented(options, hit, max_hp, missing_hp, ability_schools):
    """Health the given components would have saved against one hit, pressed just before it.

    `options`: resolved components (see _resolve). Reductions apply first, then
    shields soak what's left, as in the game. Max health: a percent increase
    keeps the health share (the game scales current health with it), "current"
    ones add the same amount to both (Fortifying Brew). Heals fill health
    missing, raised by any healing-received increase among the options.
    """
    hp = max_hp - missing_hp
    one = dict(hit, resourceActor=2, maxHitPoints=max_hp, hitPoints=hp - (hit.get("amount") or 0),
               timestamp=hit.get("timestamp") or 0)
    if "amount" not in hit:
        one["hitPoints"] = hp
    extra, _ = _simulate([_option(None, options, None)], one["timestamp"] - 1, _Window([one], ability_schools), 0)
    return extra


def _explain(entry, comps, applied, hit, amount, max_hp, missing_hp, ability_schools, missing_at_kb=None):
    """The numbers behind one button's verdict, for the results page.

    {"amount": health it would have saved by the killing blow (more than the
     overkill: they live), "why": when it saves nothing, the reason}. When
    talents changed it, or for an estimated consumable: "effect", this
    player's version of it, and "talents", the changes. Consumables also carry
    where their heal came from ("source": log / typical / gameData) and, for a
    typical potion, the untalented heal. The general effect of each ability is
    sent once per result (ability_info).
    """
    out = {"amount": round(amount)}
    talents = applied or entry.get("applied") or []
    if talents or entry.get("estimated"):
        out["effect"] = [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items() if v is not None}
                         for c in comps]
        if talents:
            out["talents"] = talents
    if entry.get("estimated"):
        out["source"] = entry.get("source")
        if entry.get("samples"):
            out["samples"] = entry["samples"]
        if entry.get("typical"):
            out["typical"] = round(entry["typical"])
        if entry.get("rank"):
            out["rank"] = entry["rank"]
        elif entry.get("ranks"):
            out["ranks"] = entry["ranks"]
        if entry.get("soulwell"):
            out["soulwell"] = True
    if amount <= 0:
        for m in comps:
            immune = bool(m.get("immune"))
            applies = _effect_applies(m, hit, ability_schools)
            if applies is None and m.get("armor"):
                out["why"] = "armorUnknown"
            elif applies is None:
                out["why"] = "aoeUnknown"
            elif not applies and m.get("armor"):
                out["why"] = "notArmor"
            elif not applies:
                out["why"], out["school"] = "school", m.get("school")
            elif immune and hit.get("abilityGameID") in IGNORES_IMMUNITY:
                out["why"] = "pierces"
            elif (m.get("dr") or m.get("armor")) and _ignores_reduction(hit):
                out["why"] = "noReduction"
            elif ("heal" in m or "heal_amount" in m or "heal_taken" in m) and \
                    (missing_hp if missing_at_kb is None else missing_at_kb) <= 0:
                out["why"] = "fullHealth"
            elif "heal" in m or "heal_amount" in m:
                out["why"] = "tooFast"           # missing health only in the last second, or healed back up
            else:
                continue
            break
    return out


def _lethal_hits(hits, killing):
    """The hits replayed for a death: from LETHAL_WINDOW_MS before its killing blow up to it,
    never reaching back past an earlier death of theirs (a battle res)."""
    kb_ts = killing["timestamp"]
    start = kb_ts - LETHAL_WINDOW_MS
    out = []
    for h in hits:
        if h["timestamp"] > kb_ts:
            break
        if h is killing:
            out.append(h)
            break
        if h["timestamp"] < start:
            continue
        if h.get("type") == "instakill" or (h.get("overkill") or 0) > 0:
            out = []                    # an earlier death: nothing before it carries over
            continue
        out.append(h)
    return out


def _press_times(earliest, win, kb_index, options=None):
    """Moments worth trying to press at, from `earliest` up to REACTION_MS before the killing blow.

    Health only rises between hits, so these are just after each hit (most
    health missing: heals, max health that keeps its share) and just before
    each (covers the most for effects that run out), plus the earliest and
    latest moments allowed. Given the options, only the moments that can
    matter for them: effects that last until the death and nothing else are
    best pressed as early as possible.
    """
    latest = win.hits[kb_index]["timestamp"] - REACTION_MS
    if earliest > latest:
        return []
    after = before = True
    if options is not None:
        heals = any(o["instant"] or o["hots"] for o in options)
        lasting = [(c, ms) for o in options for c, ms in o["lasting"]]
        timed = any(ms for _, ms in lasting)
        shield_or_hp = any(c.get("absorb") or c.get("absorb_amount") or c.get("hp") for c, _ in lasting)
        after = heals or shield_or_hp
        before = timed or shield_or_hp
        if not after and not before:
            return [earliest]            # up until the death either way: the earliest covers the most
    times = {earliest, latest}
    for h in win.hits[:kb_index]:
        if before and earliest <= h["timestamp"] - 1 <= latest:
            times.add(h["timestamp"] - 1)
        if after and earliest <= h["timestamp"] + 1 <= latest:
            times.add(h["timestamp"] + 1)
    return sorted(times)


def _best_press(options, earliest, win, kb_index):
    """(extra health, press time, HoT ticks) for the best moment to press (_press_times);
    None when it can't be pressed in time."""
    best = None
    for t in _press_times(earliest, win, kb_index, options):
        extra, ticks = _simulate(options, t, win, kb_index)
        if best is None or extra >= best[0] - 1e-6:
            best = (extra, t, ticks)          # the latest press that saves the most
    return best


def assess_survival(hits, death_ts, available, consumables, ability_names, ability_schools,
                    talent_entries=None, observed_absorbs=None, spec=None, aoe_known=True,
                    ready_since=None, aura_ms=None, forms=None, armor_k=None, form_armor=None):
    """How they died, and whether the defensives they had ready would have saved them.

    `hits`: this player's hits (lethal windows, instant kills); the killing blow
    of this death is matched by time and the seconds before it are replayed
    (_simulate) with each option pressed at its best moment: no earlier than
    it was ready (`ready_since`, else the start of the window) and at least
    REACTION_MS before the killing blow. `available` / `consumables`: catalog
    entries ready at death (consumables only if carried and unused this pull).
    """
    killing = _killing_blow(hits, death_ts)
    if killing is not None and killing.get("type") == "instakill":
        # Killed outright by a mechanic: no damage to reduce, absorb or heal.
        names = [e["name"] for e in list(available) + list(consumables)]
        return {
            "deathType": "instakill",
            "killingHit": {"name": ability_names.get(killing.get("abilityGameID"), "Unknown"),
                           "school": ability_schools.get(killing.get("abilityGameID"))},
            "wouldSave": {n: False for n in names},
            "details": {e["name"]: {"amount": 0, "why": "instakill",
                                    **{k: e[k] for k in ("source", "samples", "rank", "soulwell") if e.get(k)}}
                        for e in list(available) + list(consumables)},
            "consumables": {e["name"]: e["kind"] for e in consumables},
            "allTogetherWouldSave": False,
            "ignoresReduction": False,
            "ignoresImmunity": False,
        }
    if killing is None or killing.get("resourceActor") != 2:
        return None   # no recorded killing blow with health data
    max_hp = killing.get("maxHitPoints") or 0
    if not max_hp:
        return None
    overkill = killing.get("overkill") or 0
    # Verified on live logs: the killing blow's `amount` equals the health the
    # player had left (matches the previous hit's recorded health), and
    # `overkill` is the damage beyond that.
    hp_before = killing.get("amount") or 0
    hit_size = _full_hit(killing)

    tag = {"armorK": armor_k, "formArmor": form_armor, **({} if aoe_known else {"aoeKnown": False})}
    window = [dict(h, **tag) for h in _lethal_hits(hits, killing)]
    kb_index = len(window) - 1
    killing = window[kb_index]
    win = _Window(window, ability_schools)
    points = win.points
    kb_ts = killing["timestamp"]
    window_start = kb_ts - LETHAL_WINDOW_MS
    press_hp, _ = _health_at(points, kb_ts - REACTION_MS)
    missing_at_reaction = max(max_hp - press_hp, 0)

    def unknown(comps):
        return any(win.applies(m, k) is None for m in comps for k in range(len(window))
                   if not ("heal" in m or "heal_amount" in m))

    per_button, scored, details = {}, [], {}
    for entry in list(available) + list(consumables):
        applied = []
        comps, _ = _resolve(entry, talent_entries, observed_absorbs or {}, spec, applied)
        name = entry["name"]
        if comps is None:
            per_button[name] = None
            continue
        dur = (aura_ms or {}).get(name) if not entry.get("estimated") else None
        legacy = HEAL_OVER_TIME.get(name) if dur else None
        opts = [_option(name, comps, dur, legacy)]
        if name in (forms or {}):
            # Needs a form first (Frenzied Regeneration needs Bear Form): judged with it.
            form_comps, _ = _resolve(forms[name], talent_entries, observed_absorbs or {}, spec, applied)
            opts.append(_option(forms[name]["name"], form_comps or [], forms[name].get("aura_ms")))
            comps = comps + (form_comps or [])
        earliest = max((ready_since or {}).get(name, window_start), window_start)
        best = _best_press(opts, earliest, win, kb_index)
        amount = best[0] if best else 0.0
        scored.append((opts, earliest))
        if best is None or amount > overkill:
            per_button[name] = best is not None
        else:
            per_button[name] = None if unknown(comps) else False
        details[name] = _explain(entry, comps, applied, killing, amount, max_hp, missing_at_reaction,
                                 ability_schools, missing_at_kb=max(max_hp - hp_before, 0))
        if best is None:
            details[name]["why"] = "readyTooLate"
        else:
            details[name]["pressAgo"] = round((kb_ts - best[1]) / 1000, 1)
        if opts[0]["hots"]:
            full = sum((c.get("heal", 0) * max_hp + c.get("heal_amount", 0)) for c, _, _ in opts[0]["hots"])
            of = sum(t for _, t, _ in opts[0]["hots"])
            hot = {"full": round(full), "ticks": best[2] if best else 0, "of": of}
            if best and len(opts) > 1:
                hot["landed"] = round(_simulate(opts[:1], best[1], win, kb_index)[0])
            details[name]["hot"] = hot
            if best and not hot["ticks"] and not details[name]["amount"]:
                details[name]["why"] = "hotTooLate"

    together = None
    if scored:
        # Everything pressed at once, at the best moment (each only once it was ready).
        best_all = 0.0
        everything = [o for os, _ in scored for o in os]
        for t in _press_times(min(e for _, e in scored), win, kb_index, everything):
            opts = [o for os, e in scored if e <= t for o in os]
            if opts:
                best_all = max(best_all, _simulate(opts, t, win, kb_index)[0])
        all_comps = [c for os, _ in scored for o in os
                     for c in [x for x, _ in o["lasting"]] + o["instant"] + [x for x, _, _ in o["hots"]]]
        together = True if best_all > overkill else (None if unknown(all_comps) else False)

    # How they died, from the hits since they were last at high health:
    #   - one-shot: that was less than a reaction time ago and a single hit took
    #     ONE_SHOT_SHARE of their max health or more (Sever);
    #   - burst: less than a reaction time ago, but no single hit that big
    #     (several hits at once: no time to react, but not one hit);
    #   - wasLow: they had been below high health for longer.
    high = [p for p in points if p[0] < kb_ts - 0.5 and p[1] >= FULL_HEALTH * p[2]]
    since = high[-1][0] if high else float("-inf")
    if hp_before >= FULL_HEALTH * max_hp:
        since, high = kb_ts - 0.5, high + [(kb_ts - 0.5, hp_before, max_hp)]
    run = [h for h in window if h["timestamp"] > since]
    quick = bool(high) and kb_ts - since <= REACTION_MS
    one_shot = quick and any(_full_hit(h) >= ONE_SHOT_SHARE * max_hp for h in run)
    death_type = "oneShot" if one_shot else "burst" if quick else "wasLow"
    from_pct = round(100 * high[-1][1] / high[-1][2]) if quick else None
    # The hit that set the death up: the biggest one since they were last at
    # high health (before that, healers had already undone it).
    biggest = max((h for h in window[:kb_index] if h["timestamp"] > since
                   and _full_hit(h) >= SETUP_HIT_SHARE * max_hp), key=_full_hit, default=None)
    if one_shot and (biggest is None or _full_hit(biggest) < ONE_SHOT_SHARE * max_hp):
        biggest = None        # the killing blow was the one hit; nothing smaller set it up
    # Rot: worn down by one raid-wide ability's repeated damage (what the
    # healers have to keep up with; raid_wide_damage.py, measured from Mythic
    # kills), not set up by a single hit. Soaks and mechanics a player walks
    # into are never rot, and neither is a one-shot or a burst (high health
    # under a second before).
    by_ability = defaultdict(list)
    for h in run:
        by_ability[h.get("abilityGameID")].append(h)
    rot = None
    if by_ability:
        aid, hs = max(by_ability.items(), key=lambda kv: sum(_full_hit(h) for h in kv[1]))
        total = sum(_full_hit(h) for h in run) or 1
        if not quick and aid in RAID_WIDE and len(hs) >= ROT_MIN_HITS \
                and sum(_full_hit(h) for h in hs) >= ROT_SHARE * total \
                and max(_full_hit(h) for h in hs) < ROT_MAX_HIT * max_hp:
            rot = {"name": ability_names.get(aid, "Unknown"), "abilityId": aid, "school": ability_schools.get(aid),
                   "hits": len(hs), "total": sum(_full_hit(h) for h in hs),
                   "pctOfMax": round(100 * sum(_full_hit(h) for h in hs) / max_hp),
                   "seconds": round((kb_ts - hs[0]["timestamp"]) / 1000, 1)}
            biggest = None
    result = {
        "deathType": death_type,
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
        "allTogetherWouldSave": together,
        # Why a defensive might not help against this particular hit.
        "ignoresReduction": _ignores_reduction(killing),
        "ignoresImmunity": killing.get("abilityGameID") in IGNORES_IMMUNITY,
        # The seconds replayed: how many hits, from how long before the killing blow.
        "window": {"hits": len(window), "fromAgo": round((kb_ts - window[0]["timestamp"]) / 1000, 1)},
    }
    if quick and from_pct is not None and from_pct > result["hpBeforePct"]:
        result["fromPct"] = from_pct
        result["burstMs"] = round(kb_ts - since)
    if death_type == "burst":
        # Everything that hit them in it, by ability (most damage first).
        parts = defaultdict(lambda: [0, 0])
        for h in run:
            parts[h.get("abilityGameID")][0] += 1
            parts[h.get("abilityGameID")][1] += _full_hit(h)
        result["burst"] = {"hits": len(run), "total": sum(_full_hit(h) for h in run), "ms": round(kb_ts - since),
                           "abilities": [{"name": ability_names.get(a, "Unknown"), "school": ability_schools.get(a),
                                          "times": n} for a, (n, _) in sorted(parts.items(), key=lambda x: -x[1][1])]}
    if rot:
        result["rot"] = rot
    if biggest is not None:
        result["biggestHit"] = {
            "name": ability_names.get(biggest.get("abilityGameID"), "Unknown"),
            "abilityId": biggest.get("abilityGameID"),
            "size": _full_hit(biggest),
            "pctOfMax": round(100 * _full_hit(biggest) / max_hp),
            "school": ability_schools.get(biggest.get("abilityGameID")),
            "ago": round((kb_ts - biggest["timestamp"]) / 1000, 1),
        }
        # The same ability hitting them again and again since they were last high (soaking on).
        same = [h for h in window[:kb_index + 1] if h["timestamp"] > since
                and h.get("abilityGameID") == biggest.get("abilityGameID")]
        if len(same) > 1:
            result["biggestHit"].update(times=len(same), total=sum(_full_hit(h) for h in same),
                                        over=round((kb_ts - same[0]["timestamp"]) / 1000, 1))
    return result
