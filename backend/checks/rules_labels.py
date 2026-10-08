"""Death labels follow the rules: one-shot, burst, rot (raid-wide only) or set up by

The owner's rule, from the hits since the player was last at 85%+ health:
  one-shot: that was at most 1.5 s before death and a single hit took 80%+ of max HP; when that hit
    (the biggest since last high) is not the killing blow, it is named as the one-shot hit (oneShotHit);
  burst: at most 1.5 s, but no single hit that big;
  worn down by (rot): only from a raid-wide ability in raid_wide_damage.py hitting them repeatedly
    (3+ hits of one RAID_WIDE ability, that ability 60%+ of the damage since last high, none of its
    hits 35%+ of max HP);
  set up by: otherwise (neither one-shot nor burst), the biggest hit (at least 10% of max HP) since they
    were last at high health.
"Last at high health" is the latest moment before the killing blow with health >= 0.85 * maxHitPoints: just
after a hit (hitPoints) or just before one (hitPoints + amount; heals land between hits), the killing blow
included. For the killing blow, max HP is max_hp_before's (its own maxHitPoints is logged after the death
removed the player's max-health auras), with WCL's Buffs-table max-health auras read when the site's max HP
differs from the one without them (run_max_hp_before). Only hits whose resources are the player's own (resourceActor 2, or 1 on self-damage) carry the player's health.
The 1.5 s is inclusive: the killing blow is at most BURST_WINDOW_MS after that moment. It is the owner's
description window (2026-10-08), not the 1 s press cutoff (REACTION_MS) of the defensive replay.
"""
from collections import defaultdict

import defensives

from checks.verdict import PASS, fail, skip
from raid_wide_damage import RAID_WIDE

HIGH, ONE_SHOT, SETUP, BURST_WINDOW_MS = 0.85, 0.80, 0.10, 1500
ROT_MIN_HITS, ROT_SHARE, ROT_MAX_HIT = 3, 0.6, 0.35
KILL_SLACK_MS = 50
HP_SLACK = 0.01           # max HP within 1% is the same max


def full_hit(h):
    return (h.get("amount") or 0) + (h.get("overkill") or 0) + (h.get("absorbed") or 0)


def _own_hp(h):
    """The hit carries the player's own health. With includeResources, resourceActor 2 is the target's
    (the player's); resourceActor 1 is the attacker's, which on self-damage (source = target: Touch of
    Death, Set Fire to the Pain) is the player too."""
    if not h.get("maxHitPoints"):
        return False
    if h.get("resourceActor") == 2:
        return True
    return h.get("resourceActor") == 1 and h.get("sourceID") is not None and h.get("sourceID") == h.get("targetID")


# A max-health aura ending this close before the killing hit was removed by the death itself.
DEATH_STRIP_MS = 100


def max_hp_before(hits, kb_index, bands=()):
    """Max HP just before the killing blow hits[kb_index] (hits: this death's, time order), 0 if unknown.

    WCL logs the killing hit after the death stripped the player's auras, so its own maxHitPoints has
    lost their max-health auras (live 2026-10-08: Strikepal, Nerub-ar p16, auras removed at
    1910329-1910332, killing hit at 1910349 with max 10061382; 11198315 on every hit and heal before).
    So: the max on the player's last own-health hit before it, times each max-health aura in `bands`
    ([(start, end or None, share)]) that came up after that hit and was still up at the killing hit
    (ending at most DEATH_STRIP_MS before it: the strip), divided by each that was up then and ran out
    before. Never below the killing hit's own max (the death only takes max health away) nor below the
    health it took (health never exceeds max). Without an earlier own-health hit: the larger of those two.
    """
    kb = hits[kb_index]
    if not _own_hp(kb):
        return 0
    floor = max(kb["maxHitPoints"], kb.get("amount") or 0)
    last = next((h for h in hits[:kb_index][::-1] if _own_hp(h)), None)
    if last is None:
        return floor
    t0, t1 = last["timestamp"], kb["timestamp"]
    value = float(last["maxHitPoints"])
    for start, end, share in bands:
        before = start <= t0 and (end is None or end > t0)
        at_kill = start <= t1 and (end is None or end >= t1 - DEATH_STRIP_MS)
        if at_kill and not before:
            value *= 1 + share
        elif before and not at_kill:
            value /= 1 + share
    return max(round(value), floor)


def max_health_shares(cat, talents, spec):
    """{aura name: share} of the catalog's max-health increases (an "hp" component) for this player's
    talents and spec: increases multiply, "current and maximum health" ones (Fortifying Brew) add."""
    out = {}
    for entry in cat.all.values():
        if entry.get("kind") not in ("personal", "external"):
            continue
        comps, _ = defensives._resolve(entry, talents, {}, spec)
        share = 1.0
        for c in comps or ():
            if c.get("hp") and not c.get("current"):
                share *= 1 + c["hp"]
        share += sum(c["hp"] for c in comps or () if c.get("hp") and c.get("current"))
        if share > 1:
            out[entry["name"]] = share - 1
    return out


def aura_bands(auras, shares):
    """[(start, end, share)] from a Buffs table's auras (name, bands) for the names in `shares`."""
    return sorted((b["startTime"], b.get("endTime"), shares[a["name"]])
                  for a in auras if a.get("name") in shares for b in a.get("bands") or [])


def run_max_hp_before(run, ev, rid, fid, pid, hits, kb_index):
    """max_hp_before with the player's max-health auras from WCL's Buffs table, read only when the
    site's max HP differs from the one without them (HP_SLACK): a gain or loss right before the
    killing hit that no hit recorded (Soulcleavi, Manaforge p54: Last Resort's Metamorphosis, +40%,
    16 ms before Oblivion)."""
    plain = max_hp_before(hits, kb_index)
    site = (((ev.get("defensives") or {}).get("survival")) or {}).get("maxHp") or 0
    if not plain or not site or abs(site - plain) <= HP_SLACK * plain:
        return plain
    talents = None
    for c in run.combatants(rid, fid):
        if c.get("sourceID") == pid and c.get("fight", fid) == fid:
            talents = {t["id"]: t.get("rank") or 1 for t in c.get("talentTree") or []}
    shares = max_health_shares(run.cat, talents, ev.get("spec"))
    return max_hp_before(hits, kb_index, aura_bands(run.buffs(rid, fid, pid), shares))


def label(hits, kb_index, max_hp=None):
    """{"deathType", "rot", "biggestHit", "oneShotHit"} for the killing blow at hits[kb_index] (hits: one player's,
    time order). `max_hp`: their max HP just before it (default: max_hp_before without aura bands)."""
    kb = hits[kb_index]
    max_hp = max_hp or max_hp_before(hits, kb_index)
    since_i, since_ts = -1, None      # index of the latest high-health hit before the killing blow
    for i in range(kb_index + 1):
        h = hits[i]
        if not _own_hp(h):
            continue
        after = h.get("hitPoints") or 0
        top = max_hp if i == kb_index else h["maxHitPoints"]     # the killing hit's own max is post-death
        if i < kb_index and after >= HIGH * top:
            since_i, since_ts = i, h["timestamp"]                 # high just after this hit
        elif after + (h.get("amount") or 0) >= HIGH * top:
            since_i, since_ts = i - 1, h["timestamp"]             # high just before this hit
    run = hits[since_i + 1:kb_index + 1]
    quick = since_ts is not None and kb["timestamp"] - since_ts <= BURST_WINDOW_MS
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
                "biggestHit": biggest.get("abilityGameID") if biggest else None, "oneShotHit": None}
    shot = None
    if one_shot:
        top = max(run[:-1], key=full_hit, default=None)
        if top is not None and full_hit(top) > full_hit(kb):
            shot = top.get("abilityGameID")
    return {"deathType": death_type, "rot": None, "biggestHit": None, "oneShotHit": shot}


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
        if got is None or not max_hp_before(*got):
            continue
        compared += 1
        rule = label(*got, max_hp=run_max_hp_before(run, ev, rid, fid, pid, *got))
        site = (s.get("deathType"), (s.get("rot") or {}).get("abilityId"), (s.get("biggestHit") or {}).get("abilityId"),
                (s.get("oneShotHit") or {}).get("abilityId"))
        want = (rule["deathType"], rule["rot"], rule["biggestHit"], rule["oneShotHit"])
        if site != want:
            items.append(f"{name} pull {fid}: site {'/'.join(map(str, site))}, rule {'/'.join(map(str, want))}")
    if not seen:
        return skip("no counted deaths with a survival block")
    if not compared:
        return skip("no counted death has a killing hit in WCL's damage taken")
    return fail(items) if items else PASS
