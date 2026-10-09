"""Source check: the catalog's damage reductions against real hits.

What it can't measure, and leaves out (each verified on live logs, 2026-10-08):
  - Stagger ticks (a Brewmaster's own delayed damage): they were reduced when the hit was staggered;
    defensives up at tick time never change them (Weavi: 246 ticks, through share 0.600 with or without).
  - A defensive on a spec the catalog doesn't give it to (Bear Form on a Guardian): the site never
    judges it there.
A reduction that sits on the enemy (The War Within's Fiery Brand cuts the branded enemy's damage done: the
catalog marks it `from_target`, from the game data's aura 269 on the enemy) is already inside
WCL's unmitigatedAmount, so the share of a hit that got through shows nothing (Lazelele, Nerub-ar: 0.02
on 115 hits). It is measured on the raw size instead: the same enemy unit's same ability, one hit
branded and the next not (or the other way round), at most BRAND_PAIR_MS apart, so a boss ability that
ramps over its cast can't pass for the brand (Liquefy's ticks grow, and players brand at its start: on
Lazelele, every branded hit against every unbranded one within 30 s read 0.374). Adjacent pairs read 0.400 median on
both logs tried, deciles 0.35-0.45 (Lazelele, Nerub-ar, 11.0.7: 123 pairs; Lunchay, Undermine, 11.1:
288 pairs), and hits from other units while a brand was up were not cut (0.00 median, 77 pairs).
Midnight's Fiery Brand (12.0.0 on) is a buff on the Demon Hunter that cuts every hit (aura 87, target the
caster), so it is measured like any other buff (Felvix, Voidspire, 2026-10-08: all three bosses' hits read
0.56-0.59 of unbranded).
A reduction that grows with the size of the hit (Dampen Harm: "20% to 50% ... larger attacks being
reduced by more"; game data 122278 has the two numbers as dummy effects and no curve) is predicted hit by
hit: the catalog's value at no damage, rising in a straight line to its `dr_hit` (game data 122278
effect 2: 50) at a hit of the player's whole max health, where x is the hit after the player's other reductions (unmitigated size x
the matched hits' median share through) over max health, and capped there. Fitted 2026-10-08: Atlai
(Brewmaster, Undermine) read 0.243/0.245, 0.285/0.285, 0.350/0.350, 0.355/0.355 (measured/rule) up to
x = 0.57, 81 hits, median residual -0.004; Weavi's Goblin Gun hits at x = 0.61-0.62 read 0.383/0.383 and
0.387/0.387. A hit without the player's health on it is left out.
A reduction that grows with missing health (Icebound Fortitude with Bloody Fortitude: up to 20% more
at no health) is predicted hit by hit from the player's own health on that hit, as the site does; a hit
without it is left out (Sunnyvi, Quel'Danas, 2026-10-08: Icebound Fortitude read 0.323 at 90%+ health and
0.364 at 50-75%; judged against a flat 0.30 it was flagged as "measured 0.35").
Each hit with a defensive up is measured against the nearest hit without it: one from the same enemy
unit (sourceID and sourceInstance) with the same ability, at most PAIR_MS away, with the same other
auras listed and the player missing within HEALTH_BAND of the same share of max health; never against
the pull's typical hit. Two things move the share of a hit that gets through and are on no aura list:
  - effects that drift over a pull: on Cauldron of Carnage pull 47 the share through drifted 0.865 ->
    0.937 from an effect the hits don't list, so Unending Resolve with Strength of Will (0.40; 0.4000 on
    148 adjacent pairs across five Warlocks) read 0.37 against the pull's median;
  - passives that grow with missing health: Blessing of Dusk (1241945, a Protection Paladin's "up to
    10%, increasing as your health decreases", sized at run time) made Ardent Defender (0.30, pressed
    at low health) read 0.33 against hits at any health (Deawina, Coiled Altar, 126 hits); with the
    missing health matched within 0.05 it read 0.300 (75 hits).
PAIR_MS is 10 s: twice the rows of 3 s get judged and no row moved by more than FLAG_AT; at 30 s the
drift came back (Ardent Defender 0.33). A hit that dealt damage without the player's own health on it
can't be matched by health and is left out.
A hit absorbed whole (amount 0) never carries the player's health either, and it is where the site's
claim that an AoE-only reduction (Feint) cuts a hit WCL didn't mark AoE shows. For reductions that don't
depend on health or on the hit's size, such hits are paired by unit, ability, other auras and time only
(nearest hit without the defensive within PAIR_MS) and judged in a row of their own, "(absorbed whole)".
Their share through is the absorbed amount over the unmitigated one; a hit with nothing taken at all
(immune, missed) is left out.
Each (player, defensive) is judged by the median of its hits' gaps (measured minus predicted), not the
mean: a wrong catalog value is off on every ability, while one boss ability with an untracked modifier
(Sonic Ba-Boom's amplifiers, Entropic Barrage ticks) can pull a mean far off by itself.
"""
import statistics
from bisect import bisect_left
from collections import defaultdict

import defensives
from checks.verdict import Outcome, fail, skip

MIN_HITS = 3
FLAG_AT = 0.03
MIN_FLAG_HITS = 20            # fewer hits than this are too noisy to flag
PAIR_MS = 10_000                      # a hit with and one without the defensive this close are compared
BRAND_PAIR_MS = 3000                  # The War Within's Fiery Brand pairs (Liquefy grows over its cast)
HEALTH_BAND = 0.05                    # ... with missing health this close (share of max health)
STAGGER = 124255                      # a Brewmaster's Stagger ticks


def on_the_enemy(entry):
    """Does the catalog entry cut the damage the unit it is cast on deals (`from_target`)? That cut is
    already inside unmitigatedAmount."""
    return any(c.get("from_target") for c in entry.get("mitigation") or [])


def report_aoe(hits):
    """(abilities marked AoE, abilities that dealt damage) in the report, or None when no hit of it is
    marked at all (no log tried, The War Within's included, is like that): an AoE-only reduction can't be
    predicted there. WCL marks only hits that dealt damage (a hit absorbed whole, immune or missed never
    is, of any ability), and the game counts those as AoE all the same: Feint took 0.400 off 54 unmarked
    hits absorbed whole of abilities marked elsewhere on Maar (AaM31gBWwFHmD7Rz) and 10 on Esra
    (2VtyDR4CF6PGLjbd), and 0.000 off abilities never marked."""
    dealt = [e for e in hits if e.get("type") == "damage" and e.get("amount")]
    aoe = {e.get("abilityGameID") for e in dealt if e.get("isAoE")}
    return (aoe, {e.get("abilityGameID") for e in dealt}) if aoe else None


def hit_is_aoe(e, status):
    """Is hit `e` area damage? A hit that dealt damage carries WCL's own mark; one that dealt none takes
    its ability's status in the report (report_aoe), and is unknown (None) when the ability never dealt
    damage in it (never marked, so the report can't tell)."""
    if status is None:
        return None
    if e.get("amount"):
        return bool(e.get("isAoE"))
    aoe, dealt = status
    a = e.get("abilityGameID")
    return True if a in aoe else (False if a in dealt else None)


def missing_share(hit):
    """Share of max health the player was missing just before this hit (its own health is on it
    when resourceActor is 2: health after the hit plus what it took), or None without it."""
    if hit.get("resourceActor") != 2 or not hit.get("maxHitPoints"):
        return None
    before = (hit.get("hitPoints") or 0) + (hit.get("amount") or 0)
    return min(max(1 - before / hit["maxHitPoints"], 0.0), 1.0)


def scales_with_hit(comps):
    """Does a component grow with the size of the hit (the catalog's `dr_hit`: Dampen Harm)?"""
    return any(c.get("dr_hit") is not None for c in comps or [])


def predicted_keep(comps, e, aoe, schools, size=None):
    """Share of hit `e` the components let through, and the group its prediction is judged in:
    (None, None) when it can't be predicted. `aoe`: report_aoe of the report. `size`: for a reduction that grows with the hit (`dr_hit`),
    the hit after the player's other reductions as a share of max health; it reduces by its value at
    no damage rising in a straight line to `dr_hit` at a hit of max health, capped there."""
    keep, by_hit = 1.0, False
    for c in comps or []:
        if not (c.get("dr") or c.get("dr_missing")):
            continue
        if c.get("school") == "aoe":
            applies = hit_is_aoe(e, aoe)
        else:
            applies = defensives._school_applies(c.get("school"), e, schools)
        if applies is None:
            return None, None
        if not applies:
            continue
        dr = c.get("dr") or 0
        if c.get("dr_hit") is not None and c.get("dr"):
            dr += (c["dr_hit"] - dr) * min(size, 1.0)
            by_hit = True
        if c.get("dr_missing"):
            missing = missing_share(e)
            if missing is None:
                return None, None        # no health on this hit: its reduction can't be predicted
            dr += c["dr_missing"] * missing
            by_hit = True
        keep *= 1 - min(dr, 1.0)
    # Hits judged by their own health or size each predict a different value: one group.
    return keep, ("by hit" if by_hit else round(1 - keep, 4))


def enemy_side(hits, players, names, cat, loadout, spec, pull_spec, aoe, schools):
    """(player, defensive) -> [(measured, predicted)] for reductions on the enemy (on_the_enemy).

    WCL lists the brand on a hit only when the hit came from the branded unit. Each pair is two
    consecutive hits on the player from the same unit (same instance) with the same ability, one listing
    the defensive and one not, at most BRAND_PAIR_MS apart; measured = 1 - branded raw / unbranded raw."""
    entries = {d["name"]: d for d in cat.all.values() if on_the_enemy(d)}
    by_unit = defaultdict(list)
    for e in hits:
        if e.get("type") != "damage" or e.get("targetID") not in players or not e.get("unmitigatedAmount"):
            continue
        if e.get("sourceID") == e.get("targetID"):
            continue                     # the player's own damage (Stagger ticks) never carries it
        by_unit[(e["targetID"], e.get("fight"), e.get("sourceID"), e.get("sourceInstance"),
                 e.get("abilityGameID"))].append(e)
    out = defaultdict(list)
    for (pid, fight, _, _, _), seq in by_unit.items():
        seq.sort(key=lambda e: e.get("timestamp") or 0)
        on = [entries.keys() & {names.get(a) for a in defensives._auras(e)} for e in seq]
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            if on[i] == on[i + 1] or len(on[i] | on[i + 1]) != 1:
                continue
            if (b.get("timestamp") or 0) - (a.get("timestamp") or 0) > BRAND_PAIR_MS:
                continue
            name = next(iter(on[i] | on[i + 1]))
            d = entries[name]
            if d.get("class") != players[pid].get("type"):
                continue
            who_spec = pull_spec.get((fight, pid)) or spec.get(pid)
            if d.get("specs") and who_spec and who_spec not in d["specs"]:
                continue
            branded, other = (a, b) if on[i] else (b, a)
            comps, _ = defensives._resolve(d, dict(loadout.get((fight, pid)) or {}), {}, spec.get(pid))
            keep, _ = predicted_keep(comps, branded, aoe, schools)
            if keep is not None:
                out[(pid, name)].append((1 - branded["unmitigatedAmount"] / other["unmitigatedAmount"], 1 - keep))
    return out


def check(run):
    """Catalog damage reductions match real hits with and without the defensive"""
    if not run.pulls:
        return skip(f"no Mythic pulls of {run.raid} in {run.code}")
    meta, cat = run.meta, run.cat
    fights = [p["id"] for p in run.pulls]
    names = meta["abilities"]
    players = {f["id"]: f for f in meta["friendlies"]}

    # A WCL event query scoped by fightIDs must also carry an endTime, or it drops events.
    start = min(p["start_time"] for p in run.pulls)
    end = max(p["end_time"] for p in run.pulls) + 1
    # Resources carry the player's own health on each hit, for reductions that grow with missing health.
    hits = defensives._paged(run.token, run.code, "DamageTaken", None, fight_ids=fights,
                             start_time=start, end_time=end, resources=True)
    combatants = [c for fid in fights for c in run.combatants(run.code, fid)]
    # Talents can change between pulls, so each hit is judged by its own pull's loadout.
    loadout = {(e["fight"], e["sourceID"]): {t["id"]: t.get("rank") or 1 for t in e.get("talentTree") or []
                                             if t["id"] in cat.relevant_talent_entries} for e in combatants}
    spec = {pid: (meta["player_details"].get(pid) or {}).get("spec") for pid in players}
    # Players swap specs between pulls: each pull's own spec where the log has it.
    pull_spec = {(e["fight"], e["sourceID"]): defensives.SPEC_NAMES.get(e.get("specID")) for e in combatants}

    dr_names = {d["name"]: d for d in cat.all.values()
                if d["kind"] in ("personal", "external") and any("dr" in c for c in d.get("mitigation") or [])
                and not on_the_enemy(d)}
    tracked = set(cat.name_to_id)
    # A hit with the defensive up is compared only with hits carrying the same other auras:
    # players press defensives together with untracked reductions and versatility buffs
    # (Protective Light, Shifting Sands), which alone read as several points of extra reduction.
    # (player, ability, talents, other auras, pull, enemy unit, its instance)
    #   -> [(time, missing health, share of damage that got through)], no defensive up, with health
    base = defaultdict(list)
    base_any = defaultdict(list)            # the same key -> [(time, share through)], any hit without it
    # (player, ability, talents) -> {defensive name: [(share that got through, other auras, the hit, missing health)]}
    shares = defaultdict(lambda: defaultdict(list))
    whole = defaultdict(lambda: defaultdict(list))   # the same, for hits absorbed whole (no health on them)
    no_health = 0                           # hits with a defensive up that dealt damage without health
    aoe = report_aoe(hits)
    for e in hits:
        if e.get("type") != "damage" or e.get("targetID") not in players or not e.get("unmitigatedAmount"):
            continue
        if not e.get("mitigated"):
            continue                       # ignored reductions entirely
        if e.get("abilityGameID") == STAGGER:
            continue                       # reduced when the hit was staggered, never at tick time
        if e.get("blocked"):
            continue                       # a block takes a random cut that _full_hit doesn't add back
        auras = {names.get(a) for a in defensives._auras(e)}
        up = auras & tracked
        if len(up) > 1:
            continue
        which = next(iter(up), None)
        if which is not None and which not in dr_names:
            continue
        # A personal defensive shared onto another class (an Evoker's Obsidian Scales on an ally)
        # is not the catalog's button, and the site never reads it for that player.
        if which is not None and dr_names[which]["kind"] == "personal" \
                and dr_names[which].get("class") != players[e["targetID"]].get("type"):
            continue
        # A defensive the catalog gives only to other specs (Bear Form on a Guardian, whose form it is):
        # the site never judges it for this player.
        who_spec = pull_spec.get((e.get("fight"), e["targetID"])) or spec.get(e["targetID"])
        if which is not None and dr_names[which].get("specs") and who_spec \
                and who_spec not in dr_names[which]["specs"]:
            continue
        through = defensives._full_hit(e) / e["unmitigatedAmount"]
        if not through:
            continue                       # nothing taken at all (immune, missed): nothing to compare
        talents = loadout.get((e.get("fight"), e["targetID"]))
        key = (e["targetID"], e.get("abilityGameID"), tuple(sorted((talents or {}).items())))
        others = frozenset(auras - {which})
        unit = (others, e.get("fight"), e.get("sourceID"), e.get("sourceInstance"))
        missing = missing_share(e)
        if which is None:
            base_any[key + unit].append((e.get("timestamp") or 0, through))
            if missing is not None:
                base[key + unit].append((e.get("timestamp") or 0, missing, through))
        elif missing is not None:
            shares[key][which].append((through, others, e, missing))
        elif not e.get("amount"):
            whole[key][which].append((through, others, e, None))
        else:
            no_health += 1                 # dealt damage, no health on it: can't be matched by health
    for seq in list(base.values()) + list(base_any.values()):
        seq.sort(key=lambda b: b[0])

    def nearest(key, e, missing):
        """Share through of the nearest hit without the defensive in `key`'s group from the hit's own
        unit, at most PAIR_MS away, with missing health within HEALTH_BAND (any health for a hit
        absorbed whole, `missing` None); None without one."""
        unit = (e.get("fight"), e.get("sourceID"), e.get("sourceInstance"))
        seq = (base if missing is not None else base_any).get(key + unit)
        if not seq:
            return None
        ts = e.get("timestamp") or 0
        best = None
        for row in seq[bisect_left(seq, (ts - PAIR_MS,)):]:
            t, through = row[0], row[-1]
            if t > ts + PAIR_MS:
                break
            if missing is not None and abs(row[1] - missing) > HEALTH_BAND + 1e-9:
                continue
            if best is None or abs(t - ts) < best[0]:
                best = (abs(t - ts), through)
        return best[1] if best else None

    schools = meta.get("ability_schools", {})
    # (player, defensive, row label) -> [(measured, predicted)] per hit, from boss abilities with
    # MIN_HITS or more; the label is "" or " (absorbed whole)"
    rows = defaultdict(list)
    per_hit_base = defaultdict(list)       # row -> the catalog's flat value, where each hit is predicted
    pairs = set()                          # rows made of back-to-back hit pairs
    no_base = 0                            # hits with a defensive up that found no hit to compare with
    for label, groups_by_key in (("", shares), (" (absorbed whole)", whole)):
        for (pid, ability, talents), groups in groups_by_key.items():
            for name, with_up in groups.items():
                comps, _ = defensives._resolve(dr_names[name], dict(talents), {}, spec.get(pid))
                if label and any(c.get("dr_missing") or c.get("dr_hit") is not None for c in comps or []):
                    continue               # depends on health or the hit's size: not without health
                # Each hit's own prediction: one ability's hits are not all marked AoE alike.
                by_predicted = defaultdict(list)
                for through, others, e, missing in with_up:
                    usual = nearest((pid, ability, talents, others), e, missing)
                    if not usual:
                        no_base += 1
                        continue
                    size = None
                    if scales_with_hit(comps):
                        # The hit after the player's other reductions, as a share of max health.
                        size = e["unmitigatedAmount"] * usual / e["maxHitPoints"]
                    keep, group = predicted_keep(comps, e, aoe, schools, size)
                    if keep is not None:
                        by_predicted[group].append((1 - through / usual, 1 - keep))
                        if group == "by hit":
                            flat = 1.0
                            for c in comps or []:
                                flat *= 1 - (c.get("dr") or 0)
                            per_hit_base[(pid, name, label)].append(1 - flat)
                for got in by_predicted.values():
                    if len(got) >= MIN_HITS:
                        rows[(pid, name, label)] += got

    # A reduction on the enemy: raw sizes of the same unit's same ability, branded next to unbranded.
    for (pid, name), got in enemy_side(hits, players, names, cat, loadout, spec, pull_spec,
                                       aoe, schools).items():
        rows[(pid, name, "")] += got
        pairs.add((pid, name, ""))

    # The median gap between measured and predicted over every hit: a wrong catalog value shows on
    # every ability, while one boss ability with an untracked modifier doesn't move the median.
    items, measured, under = [], 0, 0
    for (pid, name, label), per in sorted(rows.items(), key=lambda kv: (kv[0][1], players[kv[0][0]]["name"], kv[0][2])):
        n = len(per)
        if n < MIN_FLAG_HITS:
            under += 1
            continue
        measured += 1
        predicted = sum(p for _, p in per) / n
        real = predicted + statistics.median(m - p for m, p in per)
        if abs(real - predicted) > FLAG_AT:
            row = (pid, name, label)
            who = f"{players[pid]['name']} {name}{label}"
            if row in pairs:
                items.append(f"{who}: measured {real:.2f}, catalog {predicted:.2f} over {n} pairs")
            elif per_hit_base.get(row):
                # Each hit has its own prediction (it grows with the hit or with missing health): say so.
                base_value = statistics.mean(per_hit_base[row])
                items.append(f"{who}: measured {real:.2f}, predicted {predicted:.2f} (catalog {base_value:.2f}) over {n} hits")
            else:
                items.append(f"{who}: measured {real:.2f}, catalog {predicted:.2f} over {n} hits")
    # What was and wasn't judged, so a pass is never read as more than it is.
    reason = (f"{measured} defensives measured, {under} under {MIN_FLAG_HITS} matched hits, "
              f"{no_base} hits with no baseline, {no_health} without health")
    if not measured:
        return skip(f"no defensive had enough matched hits to measure ({reason})")
    return fail(items, reason=reason) if items else Outcome("pass", reason=reason)
