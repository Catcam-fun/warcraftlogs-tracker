"""Death labels follow the rules: one-shot, burst, rot (raid-wide only) or set up by

The owner's rule, from the hits since the player was last at 85%+ health:
  one-shot: that was under a second before death and a single hit took 80%+ of max HP;
  burst: under a second, but no single hit that big;
  worn down by (rot): only from a raid-wide ability in raid_wide_damage.py hitting them repeatedly
    (3+ hits of one RAID_WIDE ability, that ability 60%+ of the damage since last high, none of its
    hits 35%+ of max HP);
  set up by: otherwise, the biggest hit (at least 10% of max HP) since they were last at high health.
"Last at high health" is the latest moment before the killing blow with health >= 0.85 * maxHitPoints: just
after a hit (hitPoints) or just before one (hitPoints + amount; heals land between hits), the killing blow
included. Only hits whose resources are the player's own (resourceActor 2) carry the player's health.
"Under a second" is inclusive: the killing blow is at most REACTION_MS after that moment.
The Results page shows "set up by" only when deathType is not burst, so biggestHit is not compared for bursts.
"""
from collections import defaultdict

from checks.verdict import PASS, fail, skip
from raid_wide_damage import RAID_WIDE

HIGH, ONE_SHOT, SETUP, REACTION_MS = 0.85, 0.80, 0.10, 1000
ROT_MIN_HITS, ROT_SHARE, ROT_MAX_HIT = 3, 0.6, 0.35
KILL_SLACK_MS = 50


def full_hit(h):
    return (h.get("amount") or 0) + (h.get("overkill") or 0) + (h.get("absorbed") or 0)


def _own_hp(h):
    """The hit carries the player's own health (with includeResources, resourceActor 1 is the attacker's)."""
    return h.get("resourceActor") == 2 and bool(h.get("maxHitPoints"))


def _max_hp(hits, kb_index):
    for h in [hits[kb_index]] + hits[:kb_index][::-1]:
        if _own_hp(h):
            return h["maxHitPoints"]
    return 0


def label(hits, kb_index):
    """{"deathType", "rot", "biggestHit"} for the killing blow at hits[kb_index] (hits: one player's, time order)."""
    kb = hits[kb_index]
    max_hp = _max_hp(hits, kb_index)
    since_i, since_ts = -1, None      # index of the latest high-health hit before the killing blow
    for i in range(kb_index + 1):
        h = hits[i]
        if not _own_hp(h):
            continue
        after = h.get("hitPoints") or 0
        if i < kb_index and after >= HIGH * h["maxHitPoints"]:
            since_i, since_ts = i, h["timestamp"]                 # high just after this hit
        elif after + (h.get("amount") or 0) >= HIGH * h["maxHitPoints"]:
            since_i, since_ts = i - 1, h["timestamp"]             # high just before this hit
    run = hits[since_i + 1:kb_index + 1]
    quick = since_ts is not None and kb["timestamp"] - since_ts <= REACTION_MS
    one_shot = quick and any(full_hit(h) >= ONE_SHOT * max_hp for h in run)
    death_type = "oneShot" if one_shot else "burst" if quick else "wasLow"
    rot = None
    if death_type == "wasLow":
        by_ability = defaultdict(list)
        for h in run:
            by_ability[h.get("abilityGameID")].append(h)
        total = sum(full_hit(h) for h in run) or 1
        for aid, hs in by_ability.items():
            if aid in RAID_WIDE and len(hs) >= ROT_MIN_HITS \
                    and sum(full_hit(h) for h in hs) >= ROT_SHARE * total \
                    and max(full_hit(h) for h in hs) < ROT_MAX_HIT * max_hp:
                rot = aid
        biggest = None
        if rot is None:
            cands = [h for h in run[:-1] if full_hit(h) >= SETUP * max_hp]
            biggest = max(cands, key=full_hit, default=None)
        return {"deathType": death_type, "rot": rot,
                "biggestHit": biggest.get("abilityGameID") if biggest else None}
    return {"deathType": death_type, "rot": None, "biggestHit": None}


def death_hits(hits, death_ts):
    """(this death's hits, index of its killing blow), or None when no hit overkilled.

    The killing blow is the last overkill hit at or before death_ts + 50 ms; hits up to an earlier
    overkill hit belong to an earlier death of the same pull and are dropped.
    """
    hits = [h for h in hits if h.get("type") in (None, "damage")]
    kb = None
    for i, h in enumerate(hits):
        if (h.get("overkill") or 0) > 0 and h["timestamp"] <= death_ts + KILL_SLACK_MS:
            kb = i
    if kb is None:
        return None
    start = max((i for i in range(kb) if (hits[i].get("overkill") or 0) > 0), default=-1) + 1
    return hits[start:kb + 1], kb - start


def check(run):
    """Death labels follow the rules: one-shot, burst, rot (raid-wide only) or set up by"""
    items, seen, compared = [], 0, 0
    for ev in run.counted_deaths():
        s = (ev.get("defensives") or {}).get("survival")
        if not s or s.get("deathType") == "instakill":
            continue
        seen += 1
        rid, fid, name = ev["reportId"], ev["fightId"], ev.get("originalCharacter")
        pid = run.actor_id(rid, name)
        if pid is None:
            continue
        death_ts = ev["timestamp"] + run.fight(rid, fid)["start_time"]
        got = death_hits(run.hits_before(rid, fid, pid, death_ts), death_ts)
        if got is None or not _max_hp(*got):
            continue
        compared += 1
        rule = label(*got)
        site = (s.get("deathType"), (s.get("rot") or {}).get("abilityId"), (s.get("biggestHit") or {}).get("abilityId"))
        if rule["deathType"] == "burst" and site[0] == "burst":
            site = site[:2] + (None,)      # the page hides biggestHit on bursts
        if site != (rule["deathType"], rule["rot"], rule["biggestHit"]):
            items.append(f"{name} pull {fid}: site {site[0]}/{site[1]}/{site[2]}, "
                         f"rule {rule['deathType']}/{rule['rot']}/{rule['biggestHit']}")
    if not seen:
        return skip("no counted deaths with a survival block")
    if not compared:
        return skip("no counted death has a killing hit in WCL's damage taken")
    return fail(items) if items else PASS
