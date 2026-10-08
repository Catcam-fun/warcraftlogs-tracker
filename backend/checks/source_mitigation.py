"""Source check: the catalog's damage reductions against real hits.

What it can't measure, and leaves out (each verified on live logs, 2026-10-08):
  - Reductions that sit on the enemy (Fiery Brand cuts the branded enemy's damage done). WCL's
    unmitigatedAmount already has that cut in it, so the share of a hit that got through shows nothing
    (Lazelele, Nerub-ar: 0.02 "measured" on 115 hits, all from the branded unit, while the raw size of
    the same abilities from the branded unit was 30-47% smaller than unbranded).
  - Reductions that grow with the size of the hit (Dampen Harm: 20% to 50%, "larger attacks being
    reduced by more" in the game data): the catalog's single value can't be compared with a hit mix.
  - Stagger ticks (a Brewmaster's own delayed damage): they were reduced when the hit was staggered;
    defensives up at tick time never change them (Weavi: 246 ticks, through share 0.600 with or without).
  - A defensive on a spec the catalog doesn't give it to (Bear Form on a Guardian): the site never
    judges it there.
A reduction that grows with missing health (Icebound Fortitude with Bloody Fortitude: up to 20% more
at no health) is predicted hit by hit from the player's own health on that hit, as the site does; a hit
without it is left out (Sunnyvi, Quel'Danas, 2026-10-08: Icebound Fortitude read 0.323 at 90%+ health and
0.364 at 50-75%; judged against a flat 0.30 it was flagged as "measured 0.35").
Each (player, defensive) is judged by the median of its hits' gaps (measured minus predicted), not the
mean: a wrong catalog value is off on every ability, while one boss ability with an untracked modifier
(Sonic Ba-Boom's amplifiers, Entropic Barrage ticks) can pull a mean far off by itself.
"""
import statistics
from collections import defaultdict

import defensives
from checks.verdict import PASS, fail, skip

MIN_HITS = 3
FLAG_AT = 0.03
MIN_FLAG_HITS = 20            # fewer hits than this are too noisy to flag
ON_THE_ENEMY = {"Fiery Brand"}        # cuts the enemy's damage done: already inside unmitigatedAmount
SCALES_WITH_HIT = {"Dampen Harm"}     # 20% to 50% by hit size; the catalog keeps one value
STAGGER = 124255                      # a Brewmaster's Stagger ticks


def missing_share(hit):
    """Share of max health the player was missing just before this hit (its own health is on it
    when resourceActor is 2: health after the hit plus what it took), or None without it."""
    if hit.get("resourceActor") != 2 or not hit.get("maxHitPoints"):
        return None
    before = (hit.get("hitPoints") or 0) + (hit.get("amount") or 0)
    return min(max(1 - before / hit["maxHitPoints"], 0.0), 1.0)


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
                and d["name"] not in ON_THE_ENEMY | SCALES_WITH_HIT}
    tracked = set(cat.name_to_id)
    # A hit with the defensive up is compared only with hits carrying the same other auras:
    # players press defensives together with untracked reductions and versatility buffs
    # (Protective Light, Shifting Sands), which alone read as several points of extra reduction.
    # (player, ability, talents, other auras) -> [share of damage that got through, no defensive up]
    base = defaultdict(list)
    # (player, ability, talents) -> {defensive name: [(share that got through, other auras, the hit)]}
    shares = defaultdict(lambda: defaultdict(list))
    # Logs from before Midnight never mark AoE hits: there an AoE-only reduction can't be predicted.
    aoe_known = any(e.get("isAoE") for e in hits)
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
        talents = loadout.get((e.get("fight"), e["targetID"]))
        key = (e["targetID"], e.get("abilityGameID"), tuple(sorted((talents or {}).items())))
        others = frozenset(auras - {which})
        if which is None:
            base[key + (others,)].append(through)
        else:
            shares[key][which].append((through, others, e))

    schools = meta.get("ability_schools", {})
    # (player, defensive) -> [(measured, predicted)] per hit, from boss abilities with MIN_HITS or more
    rows = defaultdict(list)
    for (pid, ability, talents), groups in shares.items():
        for name, with_up in groups.items():
            comps, _ = defensives._resolve(dr_names[name], dict(talents), {}, spec.get(pid))
            # Each hit's own prediction: one ability's hits are not all marked AoE alike.
            by_predicted = defaultdict(list)
            for through, others, e in with_up:
                same = base.get((pid, ability, talents, others), [])
                if len(same) < MIN_HITS:
                    continue
                keep, by_health = 1.0, False
                for c in comps or []:
                    if not (c.get("dr") or c.get("dr_missing")):
                        continue
                    applies = defensives._school_applies(c.get("school"), dict(e, aoeKnown=aoe_known), schools)
                    if applies is None:
                        keep = None
                        break
                    if not applies:
                        continue
                    dr = c.get("dr") or 0
                    if c.get("dr_missing"):
                        missing = missing_share(e)
                        if missing is None:
                            keep = None      # no health on this hit: its reduction can't be predicted
                            break
                        dr += c["dr_missing"] * missing
                        by_health = True
                    keep *= 1 - min(dr, 1.0)
                if keep is not None:
                    # Hits judged by their own health each predict a different value: one group.
                    group = "by health" if by_health else round(1 - keep, 4)
                    by_predicted[group].append((1 - through / statistics.median(same), 1 - keep))
            for got in by_predicted.values():
                if len(got) >= MIN_HITS:
                    rows[(pid, name)] += got

    # The median gap between measured and predicted over every hit: a wrong catalog value shows on
    # every ability, while one boss ability with an untracked modifier doesn't move the median.
    items, measured = [], 0
    for (pid, name), per in sorted(rows.items(), key=lambda kv: (kv[0][1], players[kv[0][0]]["name"])):
        n = len(per)
        if n < MIN_FLAG_HITS:
            continue
        measured += 1
        predicted = sum(p for _, p in per) / n
        real = predicted + statistics.median(m - p for m, p in per)
        if abs(real - predicted) > FLAG_AT:
            items.append(f"{players[pid]['name']} {name}: measured {real:.2f}, catalog {predicted:.2f} over {n} hits")
    if not measured:
        return skip(f"no defensive had enough matched hits to measure ({len(rows)} rows compared)")
    return fail(items) if items else PASS
