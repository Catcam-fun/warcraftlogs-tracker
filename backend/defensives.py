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
from max_health_auras import MAX_HEALTH, STACKING
from features import KILLING_HIT_HEALS
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


def _who_lists(terms):
    """Every "entries" / "specs" holder in an aura's max-health terms and their modifiers."""
    for t in terms:
        yield t
        yield from t.get("mods", ())


# Talent entries that change any aura's max health, in any patch.
MAX_HEALTH_ENTRIES = frozenset(e for h in MAX_HEALTH.values() for _, terms in h for w in _who_lists(terms)
                               for e in w.get("entries", ()))
# Auras whose max-health size depends on a loadout (talents or spec) in some patch: sized with their
# CASTER's (a warrior's Battlefield Commander raises the Rallying Cry on everyone).
LOADOUT_SIZED = frozenset(a for a, h in MAX_HEALTH.items() for _, terms in h for w in _who_lists(terms)
                          if w.get("entries") or w.get("specs"))
# Stacking auras that can change max health in some patch (a share, a flat amount, or talents that fill it).
STACK_SIZED = frozenset(a for a in STACKING if any(t.get("flat") or (t.get("share") is not None and
                                                                    (t.get("share") or t.get("mods")))
                                                   for _, terms in MAX_HEALTH[a] for t in terms))


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
        # Spells that bring a tracked defensive back early (Cold Snap, Black Ox Brew): their casts are read too.
        self.reset_ids = frozenset(r["spell"] for d in self.tracked.values() for r in d.get("reset_by", ()))
        self.cast_ids = sorted(set(self.tracked) | set(self.consumable) | self.reset_ids)
        self.longest_cooldown_ms = max((d["cooldown_ms"] for d in self.tracked.values()), default=0)
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
        # And every talent that changes how much an aura raises max health (max_health_auras.py: Foul
        # Bulwark on Bone Shield, Battlefield Commander on Rallying Cry), whoever cast the aura.
        entries.update(MAX_HEALTH_ENTRIES)
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
DATA_SHAPE = 5
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

    Also the cheapest first query on a cold report: about 2 points on fresh
    Mythic logs, while Deaths or Casts sent first cost 4-17. The report stays
    warm for 10-30 seconds, and queries sent in that time cost about 1-3
    each."""
    return _paged(token, report_code, "CombatantInfo", None, fight_ids=fight_ids, start_time=start_time,
                  end_time=end_time + 1, shape=_loadout)


def cast_lookback(cat, first_start, prev_end=0):
    """How far back a report's casts are read: 3 minutes before the first kept pull for short
    cooldowns (ENCOUNTER_RESET_MS: they carry over), and for long ones back to the end of the last
    boss encounter before it (they reset when an encounter ends, so a press after that carries into
    the pull), but never more than the longest tracked cooldown back."""
    long_from = max(prev_end or 0, first_start - cat.longest_cooldown_ms)
    return max(0, min(first_start - ENCOUNTER_RESET_MS, long_from))


def fetch_defensive_raw(token, report_code, fight_ids, start_time, end_time, cat=None, combatants=None,
                        prev_end=0):
    """Defensive casts, defensive auras, talent loadouts and consumable heals for one report,
    for every player (the queries run one after another). Keep only the players who
    died with filter_defensive_raw.

    - Casts cover the whole time range (trash and time between pulls included)
      from cast_lookback: 3 minutes before the first pull, or back to the end
      of the last boss encounter before it (`prev_end`, report-relative ms)
      for long cooldowns, at most the longest tracked cooldown. Auras cover it
      from 3 minutes before the first pull. Both are filtered to the players who died
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
    casts_from = cast_lookback(cat, start_time, prev_end)
    cast_filter = f"type = \"cast\" and ability.id in ({', '.join(map(str, cat.cast_ids))})"
    buff_filter = "ability.name in (" + ", ".join(f'"{n}"' for n in cat.buff_names) + ")"
    heal_filter = f"ability.id in ({', '.join(map(str, sorted(cat.consumable)))})"
    jobs = {
        "casts": ("Casts", cast_filter, None, casts_from, False),
        "buffs": ("Buffs", buff_filter, None, lookback, False),
        "heals": ("Healing", heal_filter, fight_ids, start_time, True),
    }
    # One at a time: measured on fresh Mythic logs, after the first query on a report
    # the next ones cost about a quarter less sent one by one than all at once.
    out = {}
    if combatants is None:
        out["combatants"] = fetch_combatants(token, report_code, fight_ids, start_time, end_time)
    for k, (dt, flt, ids, start, res) in jobs.items():
        out[k] = _paged(token, report_code, dt, flt, fight_ids=ids, start_time=start, end_time=end_time + 1,
                        resources=res)
    if combatants is not None:
        out["combatants"] = combatants
    return out


def filter_defensive_raw(raw, player_ids, cat=None):
    """fetch_defensive_raw's casts, buffs and heals of the given players and every player's loadout, indexed."""
    players = set(player_ids)
    if not players:
        return {"casts": {}, "buffs": {}, "talents": {}, "heals": {}}
    return index_defensive_events({
        "casts": [e for e in raw.get("casts", []) if e.get("sourceID") in players],
        "buffs": [e for e in raw.get("buffs", []) if e.get("targetID") in players],
        # Every player's loadout (trimmed to the entries read): an aura someone else cast on a player who
        # died is sized with the caster's talents.
        "combatants": raw.get("combatants", []),
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
        if e.get("type") == "cast" and (sid in cat.all or sid in cat.reset_ids) and e.get("sourceID") is not None:
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
    Improved Barkskin): checked on live logs, e.g. Anti-Magic Shell 5s -> 7s, Barkskin 8s -> 12s.
    A mastery's stretch (Mastery: Timewalker on Renewing Blaze) depends on the player's
    mastery stat and isn't added: the base duration stands."""
    ms = entry.get("aura_ms")
    if not ms or ms < 0:
        return ms
    mult = 1.0
    for m in entry.get("duration_mods", ()):
        if m.get("mastery"):
            continue
        rank = _mod_rank(m, talent_entries, spec)
        if rank and "add_ms" in m:
            ms += m["add_ms"] * rank
        elif rank:
            mult *= 1 + (m["mult"] - 1) * rank
    return max(ms * mult, 0)


def _talented_charges(entry, talent_entries, spec):
    return entry["charges"] + sum(m["add"] * _mod_rank(m, talent_entries, spec)
                                  for m in entry.get("charge_mods", ()))


def _inferred_cooldown(own_casts_of_spell, reset_times, loadout):
    """The cooldown a player's presses prove they have when it is shorter than their talents allow
    (cooldown reduction the catalog can't see), or None: their shortest gap between two presses of a
    one-charge ability, leaving out gaps a reset falls in, since the reset, not the cooldown, ended
    those. `reset_times`: casts of a spell that resets it (Cold Snap, Black Ox Brew) and, for a long
    cooldown, the end of every boss encounter (the encounter reset). `loadout(t)` ->
    (cooldown, charges) at a press."""
    best = None
    for a, b in zip(own_casts_of_spell, own_casts_of_spell[1:]):
        cd, charges = loadout(a)
        if charges != 1 or any(a < r <= b for r in reset_times):
            continue
        if b - a < cd - CDR_TOLERANCE_MS and (best is None or b - a < best):
            best = b - a
    return best


def _replay(casts, resets, at, loadout, inferred=None):
    """(charges left at `at`, ms until the next one comes back, when it last came back after none
    were left or None if it never ran out), replayed the way the game counts charges.

    Each press spends a charge; charges come back one at a time, the recharge starting at the first
    spend and lasting the cooldown of the talents the player had then (`loadout(t)` -> (cooldown,
    charges)), or `inferred` when that is shorter (_inferred_cooldown). `resets`: [(time, "all" |
    "one")] presses of a spell that brings it back: "all" = every charge back at once, "one" = one
    charge back (the running recharge goes on)."""
    def cd_at(t):
        cd = loadout(t)[0]
        return min(cd, inferred) if inferred is not None else cd

    events = sorted([(t, 1, None) for t in casts if t <= at] + [(t, 0, how) for t, how in resets if t <= at])
    have = loadout(events[0][0] if events else at)[1]
    back_at, since = None, None

    def refill(until):
        nonlocal have, back_at, since
        while back_at is not None and back_at <= until:
            if have == 0:
                since = back_at
            have += 1
            back_at = back_at + cd_at(back_at) if have < loadout(back_at)[1] else None

    for t, is_press, how in events:
        refill(t)
        most = loadout(t)[1]
        have = min(have, most)
        if not is_press:
            if have == 0:
                since = t
            have = most if how == "all" else min(have + 1, most)
            if have >= most:
                back_at = None
            continue
        have = max(have - 1, 0)
        if back_at is None:
            back_at = t + cd_at(t)
    refill(at)
    return have, (back_at - at if back_at is not None else 0), since


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
                  aoe_known=True, armor_k=None, soulwell=False, pull_starts=None, encounters=None):
    """Defensive picture for one death. All timestamps are report-relative ms.

    `pull_starts`: {fight ID: start} of the report's kept pulls, so presses in other pulls are
    replayed with the talents the player had in them: those of the latest KEPT pull that had
    started by then (a press in a pull the site didn't keep, or between pulls, uses the previous
    kept pull's talents; before the first kept pull, the first one's).
    `encounters`: [(start, end)] of every boss encounter in the report, kept or not. Long cooldowns
    reset when each one ends (wipe or kill): a press after the previous encounter ended carries into
    this pull, and a gap between presses that spans an encounter's end is not cooldown reduction.

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
    # The talents (and spec) the player had at a moment: those of the latest KEPT pull that started
    # by then (talents change only out of combat, so a press between pulls, or in a pull the site
    # didn't keep, was made with the last loadout the log recorded), else the first kept pull's.
    # Without pull starts or any recorded loadout: this pull's.
    loadouts = sorted(((start, indexed["talents"][(f, player_id)],
                        (indexed.get("specs") or {}).get((f, player_id)) or spec)
                       for f, start in (pull_starts or {}).items() if (f, player_id) in indexed["talents"]),
                      key=lambda lo: lo[0])

    def loadout_at(t):
        if not loadouts:
            return talent_entries, spec
        before = [lo for lo in loadouts if lo[0] <= t]
        _, talents, pull_spec_ = before[-1] if before else loadouts[0]
        return talents, pull_spec_
    # Long cooldowns reset when a boss encounter ends (wipe or kill): presses since the last one that
    # ended before this pull count (a press between pulls carries into this one), and a gap between
    # presses that spans an encounter's end is the reset, not cooldown reduction. Without the
    # report's encounters (their ends unknown): from this pull's start, and gaps across any kept
    # pull's start are dropped instead. A gap that spans an encounter's end in the report also spans
    # the next pull's start, so this drops every gap the end rule drops, plus gaps from a press
    # between pulls into the next pull (safe: it only loses evidence of cooldown reduction).
    if encounters:
        long_since = max([end for _, end in encounters if end <= fight_start], default=0)
        long_resets = sorted(end for _, end in encounters)
    else:
        long_since = fight_start
        long_resets = sorted(set((pull_starts or {}).values()) | {fight_start})
    for sid, entry in cat.tracked.items():
        if not _has_ability(sid, entry, player_class, spec, talent_entries, casts_by_spell, pressed_this_pull):
            continue
        name = entry["name"]
        if name in active_names:
            result["active"].append({"name": name, "kind": "personal", "major": entry["major"]})
            continue
        all_casts = casts_by_spell.get(sid, [])
        # Long cooldowns reset when an encounter ends (above). Short ones carry over, and charges come
        # back one at a time from the first spend, so every earlier cast in the report counts:
        # the cast that put a one-charge ability on cooldown is always more than one cooldown back
        # when it is ready again, and it decides when it came back. Each press counts with the
        # talents the player had then (loadout_at), and a reset (Cold Snap) brings it back at once.
        long = entry["cooldown_ms"] >= ENCOUNTER_RESET_MS
        lookback = long_since if long else 0
        how = {r["spell"]: r["restores"] for r in entry.get("reset_by", ())}
        resets = [(t, how[s]) for t, s in own_casts if s in how and lookback <= t <= death_ts]

        def per_press(t, entry=entry):
            talents, pull_spec_ = loadout_at(t)
            return _talented_cooldown(entry, talents, pull_spec_), _talented_charges(entry, talents, pull_spec_)
        ended = [t for t, s in own_casts if s in how] + (long_resets if long else [])
        inferred = _inferred_cooldown(all_casts, ended, per_press)
        window = [t for t in all_casts if lookback <= t <= death_ts]
        left, ready_in, since = _replay(window, resets, death_ts, per_press, inferred)
        if left > 0:
            result["available"].append({"name": name, "major": entry["major"]})
            ready_entries.append(entry)
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

    def caster_loadout(caster):
        # Another player's talents and spec in this pull (CombatantInfo), for an aura they cast.
        talents = indexed["talents"].get((fight_id, caster))
        if talents is None:
            return None
        return talents, (indexed.get("specs") or {}).get((fight_id, caster))

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
                                             forms=forms, armor_k=armor_k, form_armor=form_armor,
                                             aura_size=_aura_sizer(cat, player_class, spec, talent_entries,
                                                                   ability_names, player_id, caster_loadout))

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
# A death is a one-shot or a burst when they were at high health no more than
# this long before the killing blow (owner's rule, 2026-10-08). Otherwise they
# had been low for a while (set up, or worn down).
BURST_WINDOW_MS = 1_500
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
# The heals a killing hit can set off and their cheat-death auras the death windows read
# (fetch_death_windows).
WINDOW_HEAL_IDS = frozenset(set(KILLING_HIT_HEALS) | {a for a in KILLING_HIT_HEALS.values() if a})
# What the windows' extras block reads besides: the aura events of stacking max-health auras (their
# stacks) and of auras sized by a loadout (who cast them).
WINDOW_EXTRAS_IDS = sorted(WINDOW_HEAL_IDS | STACK_SIZED | LOADOUT_SIZED)
# For the windows' cache key in app.py.
WINDOW_EXTRAS_KEY = hashlib.sha1(repr(WINDOW_EXTRAS_IDS).encode()).hexdigest()[:12]
AURA_EVENTS = {"applybuff", "applybuffstack", "removebuffstack", "removebuff",
               "applydebuff", "applydebuffstack", "removedebuffstack", "removedebuff"}
WINDOW_TYPES = {"damage", "heal", "absorbed"} | AURA_EVENTS
# What is kept of a heal or aura event (fetch_death_windows).
HEAL_FIELDS = ("timestamp", "type", "sourceID", "targetID", "abilityGameID", "fight", "amount", "stack")
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


def fetch_death_windows(token, report_code, pulls, heals=True):
    """Every hit the given players took in the seconds before their deaths, and the heals a
    killing hit can set off with their cheat-death auras (features.KILLING_HIT_HEALS).

    `pulls`: [(fightID, [(death_ts, log name)])], the deaths that can count.
    WCL charges about a point per page of events and at least one per block,
    so pulls within WINDOW_BLOCK_SPAN_MS of each other share a block: from
    LETHAL_WINDOW_MS before its first death to its last, for the players who
    died (WCL filters by name; `target.id` and timestamps return nothing in a
    filter), scoped to those pulls. Measured on live Mythic logs: 19 -> 8 and
    11 -> 5 points for a night's reports, each block still one page. Only the
    hits inside a death's window are kept. Returns {targetID: [hits, by time]}.
    With `heals`, one more block over all those pulls, from WCL's All stream, reads on the players who
    died (WINDOW_EXTRAS_IDS): the heals a killing hit can set off with their cheat-death auras' absorbs
    and removals, and the aura events of stacking max-health auras (their stacks) and of auras sized
    by a loadout (who cast them), in the same lists (type "heal" / "absorbed" / aura events with
    "stack" and "sourceID"). Measured on a live Mythic report (k9mC7RxjKPt1TgZW, 27 pulls, 86 deaths,
    14 blocks), alternating old and new on a warm cache: 15.0 -> 19.4 points with the block (Healing
    alone: 16.7; Buffs and Debuffs blocks beside it: 19.5; one Healing block per pull group: 29).
    The aura IDs are a small part of it: most of its events are heals (Embrace the Shadow, Defy
    Fate's ticks). Reading only the auras the dying players' hits list, in a second request after the
    hits, saved nothing (25 pulls, 116 deaths, warm: 16.5 / 16.9 / 16.6 points with every stacking
    aura, 17.4 / 20.1 / 18.3 with the second request, 17.2 / 20.5 with this list). The All stream can't replace
    DamageTaken itself: it leaves the aura list off its damage events.
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

    if heals:
        every = [d for _, ds in pulls for d in ds]
        names = sorted({n for _, n in every if n})
        flt = ("target.name in (" + ", ".join(json.dumps(n, ensure_ascii=False) for n in names) + ")"
               f" and ability.id in ({', '.join(map(str, WINDOW_EXTRAS_IDS))})")
        blocks["extras"] = ([fid for fid, _ in pulls], max(min(t for t, _ in every) - LETHAL_WINDOW_MS, 0),
                            max(t for t, _ in every) + KILLING_BLOW_AFTER_MS + 1, "All", flt)

    def in_a_window(ts):
        # Windows are all as long: the one starting last at or before ts ends last too.
        i = bisect_right(windows, (ts, float("inf"))) - 1
        return i >= 0 and ts <= windows[i][1]

    def keep(e):
        return e.get("type") in WINDOW_TYPES and in_a_window(e.get("timestamp", 0))

    events = [e for evs in _fetch_blocks(token, report_code, blocks, keep).values() for e in evs]
    out = index_hits(events)
    for e in events:
        if e.get("type") in WINDOW_TYPES - {"damage"} and e.get("targetID") is not None:
            out.setdefault(e["targetID"], []).append({k: e[k] for k in HEAL_FIELDS if k in e})
    for hits in out.values():
        hits.sort(key=lambda e: e["timestamp"])
    return out


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
# Stagger (115069, a Brewmaster passive) is an absorb aura (EffectAura 69): the game cuts a hit by the
# player's damage reductions first, then Stagger delays a share of what is left (logged as `absorbed`
# on the hit) into ticks of STAGGER_TICK every 0.5 s over 10 s (124255 EffectAuraPeriod 500, 124273-5
# duration 10000). A tick is damage already reduced: defensives up while it ticks never change it (Weavi,
# Undermine, 2026-10-08: 246 ticks under Fortifying Brew and 26 under Dampen Harm read 0.600 through, as
# every tick does), while shields absorb ticks (1194 of Weavi's 6137 ticks were partly absorbed).
STAGGER_TICK = 124255
STAGGER_SPEC = "Brewmaster"


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


def _stagger_tick(hit):
    """A Brewmaster's own Stagger tick (STAGGER_TICK)."""
    return hit.get("abilityGameID") == STAGGER_TICK


def _ignores_reduction(hit):
    """The hit ignores damage reduction: nothing at all was mitigated (not even versatility), or it is
    a Stagger tick (reduced when the hit it came from was staggered, never while it ticks).

    WCL leaves `mitigated` out when it's 0; `unmitigatedAmount` shows the log has the data.
    """
    if _stagger_tick(hit):
        return True
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
    """A death's replayed hits with what every replay reads from them, worked out once.

    `staggers`: the player is a Brewmaster, so what a hit logs as absorbed is (mostly) the share
    Stagger delayed into later ticks. A reduction pressed before the hit shrinks that share too, but
    how much of it would have ticked before the death the log can't give (the pool mixes every hit's
    share, and Purifying Brew takes part of it off), so the replay counts only the part taken at once
    (amount and overkill) and leaves the staggered part to the ticks, as they really landed. That never
    credits more than the game would; it can credit less.
    """

    def __init__(self, hits, ability_schools, staggers=False):
        self.hits = hits
        self.schools = ability_schools
        self.points = _Points(_health_points(hits))
        self.full = [(h.get("amount") or 0) + (h.get("overkill") or 0) if staggers and not _stagger_tick(h)
                     else _full_hit(h) for h in hits]
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
            elif (m.get("dr") or m.get("armor")) and _stagger_tick(hit):
                out["why"] = "stagger"
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


# The death strips the player's auras just before WCL logs the killing hit: measured on 587 killing
# hits in six Mythic logs (2026-10-08), the strip's removals come 0-39 ms before it (210 within
# 10 ms, 57 at 10-19, 17 at 20-29, 5 at 30-39); the next removals are 70+ ms out, auras running
# out on their own. An aura that came up within this span before the killing hit, after the hit
# before it and not on the killing hit's own aura list, came from the killing hit itself.
DEATH_STRIP_MS = 50


def max_health_size(aura_id, patch, talents=None, spec=None):
    """(share, flat) an aura changes this player's max health by in a patch (max x (1 + share) + flat),
    from game data (max_health_auras.py): every term of the aura that applies to them (a term needing a
    talent only with that talent in `talents`, {entry: rank}; a spec's only for that spec), its share
    with the talents and spec passives that change it. (0.0, 0) for an aura that doesn't change max
    health; None when an applying term isn't in the data."""
    terms = []
    key = [int(x) for x in patch.split(".")]
    for first, ts in MAX_HEALTH.get(aura_id, ()):
        if [int(x) for x in first.split(".")] <= key:
            terms = ts
    talents = talents or {}

    def rank(who):
        if "entries" in who:
            return max((talents.get(e, 0) if isinstance(talents, dict) else int(e in talents)
                        for e in who["entries"]), default=0)
        if "specs" in who:
            return int(bool(spec) and _spec_matches(spec, who["specs"]))
        return 1

    mult, flat = 1.0, 0
    for t in terms:
        if not rank(t):
            continue
        if "flat" in t:
            flat += t["flat"]
            continue
        if t["share"] is None:
            return None
        share = t["share"]
        for m in t.get("mods", ()):
            r = rank(m)
            if r:
                share = share + m["add"] * r if "add" in m else share * m["mult"]
        mult *= 1 + share
    return (round(mult - 1, 6), flat)


def _aura_sizer(cat, player_class, spec, talent_entries, ability_names=None, player_id=None, loadout_of=None):
    """aura ID -> (share, flat) or None for this player, from game data with their talents and spec
    (max_health_size). Sized by aura ID, wherever the game data puts the effect: Havoc's
    Metamorphosis (162264) has none, Vengeance's (187827) +40%; Bear Form's +25% Stamina is on its
    passive 1178 (any druid); Fount of Strength puts +10% on Frenzied Regeneration.
    `size.by_caster(aid, caster)`: sized with the loadout of whoever cast it (`loadout_of(caster)` ->
    (talents, spec) or None): talents raise an aura from its caster (Battlefield Commander's +2% on a
    warrior's Rallying Cry reads x1.12 on every player it lands on). None for an aura sized by a loadout
    when its caster's isn't known."""
    patch = getattr(cat, "patch", None) or LATEST

    def size(aid):
        return max_health_size(aid, patch, talent_entries or {}, spec)

    def by_caster(aid, caster):
        if caster is None or player_id is None or caster == player_id or aid not in LOADOUT_SIZED:
            return size(aid)
        lo = loadout_of(caster) if loadout_of else None
        if lo is None:
            return None
        return max_health_size(aid, patch, lo[0] or {}, lo[1])
    size.by_caster = by_caster

    def stacks(aid):
        n = 1
        key = [int(x) for x in patch.split(".")]
        for first, m in STACKING.get(aid, ()):
            if [int(x) for x in first.split(".")] <= key:
                n = m
        return n
    size.stacks = stacks
    return size


def _own_health(h):
    return h.get("resourceActor") == 2 and bool(h.get("maxHitPoints")) and h.get("type") == "damage"


def _set_off_heal(heals, prev_t, t1):
    """Health the killing hit itself healed (heals: the player's KILLING_HIT_HEALS heals and their
    cheat-death auras' absorbs and removals, from fetch_death_windows). A heal counts only with its
    aura's absorb, or its removal (used up), logged after the hit before the killing hit: an absorb
    logged then took part of the killing hit (its absorbs sum to the hit's `absorbed`). Live: Arzoker,
    Quel'Danas p89, Stretch Time absorbed at 13395294, Defy Fate healed at 13395295 and absorbed at
    13395314, Terminate logged at 13395315 with both absorbs; a Defy Fate heal 1 ms after the hit
    before and 31 ms before the killing hit, with no Defy Fate absorb of it (Alemonk, Quel'Danas p32),
    was health they had. Guardian Spirit logs no absorb: its aura 47788 is removed 1 ms before its heal
    48153 (Manaforge 2VtyDR4CF6PGLjbd p75, 25624450 / 25624451)."""
    window = [h for h in heals if prev_t < h["timestamp"] <= t1]
    total = 0
    for h in window:
        if h.get("type") != "heal" or h.get("abilityGameID") not in KILLING_HIT_HEALS:
            continue
        aura = KILLING_HIT_HEALS[h["abilityGameID"]]
        if any(a.get("abilityGameID") == aura and a.get("type") in ("absorbed", "removebuff", "removedebuff")
               for a in window):
            total += h.get("amount") or 0
    return total


def _stacks_at(events, aura_id, t):
    """Stacks of an aura on the player at time t from its aura events (fetch_death_windows), or None
    when they can't be told (no event of it, or only its removal after t)."""
    evs = [e for e in events if e.get("abilityGameID") == aura_id]
    before = [e for e in evs if e["timestamp"] <= t]
    if before:
        e = before[-1]
        if e["type"] in ("removebuff", "removedebuff"):
            return 0
        if e["type"] in ("applybuff", "applydebuff"):
            return e.get("stack") or 1
        return e.get("stack")
    after = [e for e in evs if e["timestamp"] > t]
    if not after:
        return None
    e = after[0]
    if e["type"] in ("applybuff", "applydebuff"):
        return 0
    if e["type"] in ("applybuffstack", "applydebuffstack") and e.get("stack"):
        return e["stack"] - 1
    if e["type"] in ("removebuffstack", "removedebuffstack") and e.get("stack") is not None:
        return e["stack"] + 1
    return None


def _max_hp_before(window, kb_index, aura_size=None, heals=(), aura_events=()):
    """(max health, health) the player had just before the killing blow window[kb_index] landed.

    WCL logs the killing hit after the death removed the player's auras, so its maxHitPoints has
    lost every max-health aura they had (live 2026-10-08, four deaths read 105% from it: Strikepal,
    Nerub-ar p16, auras removed at 1910329-1910332, the hit logged at 1910349 with max 10061382
    against 11198315 on every hit and heal before). Instead:
      - the max on their last own-health hit before it, with the auras that came up or ran out
        between that hit and the killing blow taken in or out: each hit lists the auras up on it,
        before the death's strip (aura_size: game data with their talents and spec). Live: Black
        Attunement (+2%) ran out before the killing blow of WgYbA1r7fXdZKtPF actor 137 at 8775890 and
        bpQCAqm89GhTLW7Z actor 19 at 3055954, Fortitude of the Bear (+20%) before gZBT7Y1j8dNCbwqp
        actor 14's at 3182550; each killing hit's own max is exactly that.
      - when that last hit's list changed against the own-health hit before it but its max did not,
        the max had not caught up yet (seen on 26 of 258 such changes in six logs, up to about a
        second): the hit before is the reference;
      - what the killing hit itself healed (_set_off_heal: a cheat death's heal, Defy Fate,
        Cauterize, Guardian Spirit, Ardent Defender; Embrace the Shadow's heal of the shadow damage it
        absorbed; Last Resort's Metamorphosis) is not health they had before it: WCL's amount on the
        killing hit includes it. Live: Arzoker, Quel'Danas p34, Defy Fate healed 136670 inside
        Terminate, 507980 -> 371310 (73%); Padflash, Manaforge p79, Cauterize healed 2919591, which
        leaves exactly the 2903317 of his hit before. An aura the killing hit brought (Metamorphosis)
        is not on its list, so its max health never counts either;
      - a stacking aura counts once per stack (game data: SpellAuraOptions.CumulativeAura; "increasing
        your maximum health by $s11% ... per stack": Sentinel; Bone Shield +1% a charge with Foul
        Bulwark): its stacks on that hit and at the killing blow come from its aura events
        (`aura_events`); when they can't be told, it is left as it was;
      - an aura is sized with its caster's loadout (aura_size.by_caster, the caster from its aura
        events): a warrior's Rallying Cry with Battlefield Commander is +12% on everyone;
      - never below the killing hit's own max (the death only takes max health away), nor below the
        health they had.
    """
    kb = window[kb_index]
    kb_max, amount = kb.get("maxHitPoints") or 0, kb.get("amount") or 0
    t1 = kb["timestamp"]
    prev_t = window[kb_index - 1]["timestamp"] if kb_index else float("-inf")
    on_kb = _auras(kb)
    own = [h for h in window[:kb_index] if _own_health(h)]
    stacks = getattr(aura_size, "stacks", lambda aid: 1)
    by_caster = getattr(aura_size, "by_caster", None)

    def size(aid):
        if aura_size is None:
            return (0.0, 0)
        if by_caster is None:
            return aura_size(aid)
        # Who cast it: the last of its aura events up to the killing hit (fetch_death_windows reads them
        # for an aura sized by a loadout that came or went in the window).
        src = [e.get("sourceID") for e in aura_events
               if e.get("abilityGameID") == aid and e["timestamp"] <= t1 and e.get("sourceID") is not None]
        return by_caster(aid, src[-1] if src else None)

    def sized(aids):
        return [a for a in aids if size(a) not in ((0.0, 0), None)]

    if not own:
        value = float(kb_max)
    else:
        ref = own[-1]
        if len(own) > 1 and own[-2]["maxHitPoints"] == ref["maxHitPoints"] and \
                sized(_auras(own[-2]) ^ _auras(ref)):
            ref = own[-2]
        value = float(ref["maxHitPoints"])
        before = _auras(ref)
        for aid in sorted(on_kb - before):
            v = size(aid)
            if v and stacks(aid) == 1:
                value = value * (1 + v[0]) + v[1]
        for aid in sorted(before - on_kb):
            v = size(aid)
            if v and stacks(aid) == 1:
                value = (value - v[1]) / (1 + v[0])
        for aid in sorted(before | on_kb):
            v = size(aid)
            if not v or v == (0.0, 0) or stacks(aid) == 1:
                continue
            n0 = _stacks_at(aura_events, aid, ref["timestamp"]) if aid in before else 0
            n1 = _stacks_at(aura_events, aid, t1 - DEATH_STRIP_MS) if aid in on_kb else 0
            if n0 is not None and n1 is not None and n0 != n1:
                value = value * (1 + v[0] * n1) / (1 + v[0] * n0)
    health = max(amount - _set_off_heal(heals, prev_t, t1), 0)
    return max(round(value), kb_max, health), health


def assess_survival(hits, death_ts, available, consumables, ability_names, ability_schools,
                    talent_entries=None, observed_absorbs=None, spec=None, aoe_known=True,
                    ready_since=None, aura_ms=None, forms=None, armor_k=None, form_armor=None,
                    aura_size=None):
    """How they died, and whether the defensives they had ready would have saved them.

    `hits`: this player's hits (lethal windows, instant kills); the killing blow
    of this death is matched by time and the seconds before it are replayed
    (_simulate) with each option pressed at its best moment: no earlier than
    it was ready (`ready_since`, else the start of the window) and at least
    REACTION_MS before the killing blow. `available` / `consumables`: catalog
    entries ready at death (consumables only if carried and unused this pull).
    `aura_size` (_aura_sizer): for the max health they had just before the killing blow
    (_max_hp_before). `hits` may hold the heals a killing hit can set off (fetch_death_windows,
    type "heal" / "absorbed"); they are read only for that.
    """
    heal_events = [h for h in hits or () if h.get("type") in ("heal", "absorbed")
                   or (h.get("type") in AURA_EVENTS and h.get("abilityGameID") in WINDOW_HEAL_IDS)]
    aura_events = [h for h in hits or () if h.get("type") in AURA_EVENTS]
    hits = [h for h in hits or () if h.get("type") not in ("heal", "absorbed") and h.get("type") not in AURA_EVENTS]
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
    if not killing.get("maxHitPoints"):
        return None
    overkill = killing.get("overkill") or 0
    # Verified on live logs: the killing blow's `amount` equals the health the
    # player had left (matches the previous hit's recorded health), and
    # `overkill` is the damage beyond that.
    hit_size = _full_hit(killing)

    tag = {"armorK": armor_k, "formArmor": form_armor, **({} if aoe_known else {"aoeKnown": False})}
    window = [dict(h, **tag) for h in _lethal_hits(hits, killing)]
    kb_index = len(window) - 1
    # The killing blow's own max health is logged after the death stripped their auras; every
    # figure below (and the replay's health points) uses the max they had just before it.
    max_hp, hp_before = _max_hp_before(window, kb_index, aura_size, heal_events, aura_events)
    window[kb_index]["maxHitPoints"] = max_hp
    killing = window[kb_index]
    win = _Window(window, ability_schools, staggers=spec == STAGGER_SPEC)
    if hp_before != (killing.get("amount") or 0):
        # Health before the blow, without what the blow itself set off (_max_hp_before).
        win.before[kb_index] = (hp_before, max_hp)
        at = max(i for i, p in enumerate(win.points) if p[0] == killing["timestamp"] - 0.5)
        win.points[at] = (killing["timestamp"] - 0.5, hp_before, max_hp)
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
    #   - one-shot: that was BURST_WINDOW_MS ago or less and a single hit took
    #     ONE_SHOT_SHARE of their max health or more (Sever);
    #   - burst: BURST_WINDOW_MS or less, but no single hit that big
    #     (several hits at once, not one hit);
    #   - wasLow: they had been below high health for longer.
    # Each hit is measured against the max health they had when it landed: its own on a hit with
    # their health, else the last one before it; the killing blow's is _max_hp_before's.
    def share(h):
        if h is killing:
            top = max_hp
        elif _own_health(h):
            top = h["maxHitPoints"]
        else:
            top = _health_at(points, h["timestamp"])[1] or max_hp
        return _full_hit(h) / top

    high = [p for p in points if p[0] < kb_ts - 0.5 and p[1] >= FULL_HEALTH * p[2]]
    since = high[-1][0] if high else float("-inf")
    if hp_before >= FULL_HEALTH * max_hp:
        since, high = kb_ts - 0.5, high + [(kb_ts - 0.5, hp_before, max_hp)]
    run = [h for h in window if h["timestamp"] > since]
    quick = bool(high) and kb_ts - since <= BURST_WINDOW_MS
    one_shot = quick and any(share(h) >= ONE_SHOT_SHARE for h in run)
    death_type = "oneShot" if one_shot else "burst" if quick else "wasLow"
    from_pct = round(100 * high[-1][1] / high[-1][2]) if quick else None
    # A one-shot's hit: the biggest since they were last at high health. Named
    # (oneShotHit) only when it isn't the killing blow, which has its own row:
    # a big hit, then a small one finishing them.
    one_shot_hit = None
    if one_shot:
        top = max(range(len(window)), key=lambda i: (window[i]["timestamp"] > since, _full_hit(window[i])))
        if top != kb_index and _full_hit(window[top]) > _full_hit(killing):
            one_shot_hit = window[top]
    # The hit that set the death up (only when it was neither a one-shot nor a
    # burst): the biggest one since they were last at high health (before
    # that, healers had already undone it).
    biggest = None if quick else max((h for h in window[:kb_index] if h["timestamp"] > since
                                      and share(h) >= SETUP_HIT_SHARE), key=_full_hit, default=None)
    # Rot: worn down by one raid-wide ability's repeated damage (what the
    # healers have to keep up with; raid_wide_damage.py, measured from Mythic
    # kills), not set up by a single hit. Soaks and mechanics a player walks
    # into are never rot, and neither is a one-shot or a burst (high health
    # within BURST_WINDOW_MS before).
    by_ability = defaultdict(list)
    for h in run:
        by_ability[h.get("abilityGameID")].append(h)
    rot = None
    if by_ability:
        aid, hs = max(by_ability.items(), key=lambda kv: sum(_full_hit(h) for h in kv[1]))
        total = sum(_full_hit(h) for h in run) or 1
        if not quick and aid in RAID_WIDE and len(hs) >= ROT_MIN_HITS \
                and sum(_full_hit(h) for h in hs) >= ROT_SHARE * total \
                and max(share(h) for h in hs) < ROT_MAX_HIT:
            rot = {"name": ability_names.get(aid, "Unknown"), "abilityId": aid, "school": ability_schools.get(aid),
                   "hits": len(hs), "total": sum(_full_hit(h) for h in hs),
                   "pctOfMax": round(100 * sum(share(h) for h in hs)),
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
    if one_shot_hit is not None:
        result["oneShotHit"] = {
            "name": ability_names.get(one_shot_hit.get("abilityGameID"), "Unknown"),
            "abilityId": one_shot_hit.get("abilityGameID"),
            "size": _full_hit(one_shot_hit),
            "pctOfMax": round(100 * share(one_shot_hit)),
            "school": ability_schools.get(one_shot_hit.get("abilityGameID")),
            "ago": round((kb_ts - one_shot_hit["timestamp"]) / 1000, 1),
        }
    if biggest is not None:
        result["biggestHit"] = {
            "name": ability_names.get(biggest.get("abilityGameID"), "Unknown"),
            "abilityId": biggest.get("abilityGameID"),
            "size": _full_hit(biggest),
            "pctOfMax": round(100 * share(biggest)),
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
