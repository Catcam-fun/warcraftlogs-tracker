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
included. For the killing blow, max HP and health are max_hp_before's (its own maxHitPoints is logged after the
death removed the player's max-health auras): its aura list against the last own-health hit's, sized from the
game data, written separately from the site. Every hit counts against the max HP they had when it landed. Only hits whose resources are the player's own (resourceActor 2, or 1 on self-damage) carry the player's health.
The 1.5 s is inclusive: the killing blow is at most BURST_WINDOW_MS after that moment. It is the owner's
description window (2026-10-08), not the 1 s press cutoff (REACTION_MS) of the defensive replay.
"""
from collections import defaultdict

from checks.verdict import PASS, fail, skip
from defensive_catalog import PATCHES
from max_health_auras import MAX_HEALTH
from raid_wide_damage import RAID_WIDE

HIGH, ONE_SHOT, SETUP, BURST_WINDOW_MS = 0.85, 0.80, 0.10, 1500
ROT_MIN_HITS, ROT_SHARE, ROT_MAX_HIT = 3, 0.6, 0.35
KILL_SLACK_MS = 50


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


# The death strips the player's auras 0-39 ms before WCL logs the killing hit (587 killing hits, six logs,
# 2026-10-08). An aura that came up within this span, after the hit before, and is not on the killing
# hit's own list was set off by the killing hit itself.
DEATH_STRIP_MS = 50


def patch_of(report_start_ms):
    """The game patch live when a report was logged (defensive_catalog.PATCHES: first day live)."""
    from datetime import datetime, timezone
    day = datetime.fromtimestamp(report_start_ms / 1000, tz=timezone.utc).date().isoformat()
    live = [p for first, p in PATCHES if first <= day]
    return live[-1] if live else PATCHES[0][1]


def aura_size(aura_id, patch):
    """(share, flat) an aura changes max health by in a patch, from the game data (max_health_auras);
    (0.0, 0) when it doesn't, None when the data doesn't hold the size."""
    found = (0.0, 0)
    for first, value in MAX_HEALTH.get(aura_id, ()):
        if tuple(map(int, first.split("."))) <= tuple(map(int, patch.split("."))):
            found = value
    return found


def _listed(h):
    return {int(x) for x in str(h.get("buffs") or "").split(".") if x.isdigit()}


def max_hp_before(hits, kb_index, patch=None, bands=(), heals=()):
    """(max HP, health) just before the killing blow hits[kb_index] landed (hits: this death's, time
    order); (0, 0) when the killing hit doesn't carry the player's health.

    WCL logs the killing hit after the death stripped the player's auras, so its own maxHitPoints has
    lost their max-health auras (live 2026-10-08: Strikepal, Nerub-ar p16, auras removed at
    1910329-1910332, killing hit at 1910349 with max 10061382; 11198315 on every hit and heal before).
    Instead, from the player's last own-health hit before it (or the one before that when the last one's
    aura list changed but its max did not yet: WCL's max lags the list, 26 of 258 changes in six logs):
    its max, with every aura on the killing hit's list and not on that hit's (came up) multiplied in and
    every one the other way (ran out) divided out, sized from the game data for `patch` (aura_size;
    unsizable ones are left out). Each hit's list is the auras up on it, before the death's strip.
    An aura the killing hit set off (`bands`: [(start, end, aura ID)] from WCL's Buffs table; came up
    after the hit before it, within DEATH_STRIP_MS of the killing hit, not on its list) is not max HP
    they had before the blow, and the heals logged from its start up to the killing hit (`heals`:
    [(ts, amount)]) are not health they had: Soulcleavi, Manaforge p54, Last Resort's Metamorphosis
    healed 11748168 at 8002681, 18995479 -> 30743647, and Oblivion read 30743644 taken.
    Never below the killing hit's own max (the death only takes max health away) nor below the health.
    """
    kb = hits[kb_index]
    if not _own_hp(kb):
        return 0, 0
    t1 = kb["timestamp"]
    prev_t = hits[kb_index - 1]["timestamp"] if kb_index else float("-inf")
    on_kb = _listed(kb)
    own = [h for h in hits[:kb_index] if _own_hp(h)]

    def size(aid):
        return aura_size(aid, patch) if patch else (0.0, 0)

    if not own:
        value = float(kb["maxHitPoints"])
    else:
        ref = own[-1]
        if len(own) > 1 and own[-2]["maxHitPoints"] == ref["maxHitPoints"] and \
                any(size(a) not in ((0.0, 0), None) for a in _listed(own[-2]) ^ _listed(ref)):
            ref = own[-2]
        value = float(ref["maxHitPoints"])
        for aid in on_kb - _listed(ref):
            v = size(aid)
            if v:
                value = value * (1 + v[0]) + v[1]
        for aid in _listed(ref) - on_kb:
            v = size(aid)
            if v:
                value = (value - v[1]) / (1 + v[0])
    set_off = [start for start, end, aid in bands
               if prev_t < start <= t1 and t1 - start <= DEATH_STRIP_MS and aid not in on_kb
               and size(aid) not in ((0.0, 0), None)]
    health = kb.get("amount") or 0
    if set_off:
        health -= sum(amount for ts, amount in heals if min(set_off) <= ts <= t1)
    health = max(health, 0)
    return max(round(value), kb["maxHitPoints"], health), health


def aura_bands(auras):
    """[(start, end, aura ID)] from a Buffs table's auras (guid, bands)."""
    return sorted((b["startTime"], b.get("endTime"), a.get("guid"))
                  for a in auras if a.get("guid") is not None for b in a.get("bands") or [])


def run_max_hp_before(run, rid, fid, pid, hits, kb_index):
    """max_hp_before for one death, with the report's patch. WCL's Buffs table and the player's heals
    around the killing hit are read only when the lists can't explain the killing hit: the health it
    took is more than the max they give (an aura the killing hit set off: Soulcleavi, Last Resort's
    Metamorphosis), a test of WCL's own data, not of the site's numbers."""
    patch = patch_of(run.meta_for(rid)["report_start"])
    value, health = max_hp_before(hits, kb_index, patch)
    kb = hits[kb_index]
    listed_max = max_hp_before(hits[:kb_index] + [dict(kb, amount=0)], kb_index, patch)[0]
    if not value or (kb.get("amount") or 0) <= listed_max:
        return value, health
    t1 = kb["timestamp"]
    heals = [(e["timestamp"], e.get("amount") or 0) for e in run.heals_taken(rid, pid, t1 - DEATH_STRIP_MS, t1 + 1)
             if e.get("type") == "heal"]
    return max_hp_before(hits, kb_index, patch, aura_bands(run.buffs(rid, fid, pid)), heals)


def max_at(hits, i, kb_index, max_hp):
    """The max HP the player had when hits[i] landed: the killing blow's is `max_hp`; a hit with their
    own health carries it; otherwise the last own-health hit before it."""
    if i == kb_index:
        return max_hp
    for h in hits[i::-1]:
        if _own_hp(h):
            return h["maxHitPoints"]
    return max_hp


def label(hits, kb_index, max_hp=None, health=None):
    """{"deathType", "rot", "biggestHit", "oneShotHit"} for the killing blow at hits[kb_index] (hits: one player's,
    time order). `max_hp` / `health`: what they had just before it (default: max_hp_before without the patch's
    aura sizes). Every hit is measured against the max HP they had when it landed (max_at)."""
    kb = hits[kb_index]
    if max_hp is None:
        max_hp, health = max_hp_before(hits, kb_index)
    health = (kb.get("amount") or 0) if health is None else health
    share = {id(h): full_hit(h) / (max_at(hits, i, kb_index, max_hp) or 1) for i, h in enumerate(hits)}
    since_i, since_ts = -1, None      # index of the latest high-health hit before the killing blow
    for i in range(kb_index + 1):
        h = hits[i]
        if not _own_hp(h):
            continue
        after = h.get("hitPoints") or 0
        if i < kb_index and after >= HIGH * h["maxHitPoints"]:
            since_i, since_ts = i, h["timestamp"]                 # high just after this hit
        elif i == kb_index and health >= HIGH * max_hp:
            since_i, since_ts = i - 1, h["timestamp"]             # high just before the killing blow
        elif i < kb_index and after + (h.get("amount") or 0) >= HIGH * h["maxHitPoints"]:
            since_i, since_ts = i - 1, h["timestamp"]             # high just before this hit
    run = hits[since_i + 1:kb_index + 1]
    quick = since_ts is not None and kb["timestamp"] - since_ts <= BURST_WINDOW_MS
    one_shot = quick and any(share[id(h)] >= ONE_SHOT for h in run)
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
                    and max(share[id(h)] for h in hs) < ROT_MAX_HIT:
                rot = aid
        biggest = None
        if rot is None:
            cands = [h for h in run[:-1] if share[id(h)] >= SETUP]
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
        if got is None or not max_hp_before(*got)[0]:
            continue
        compared += 1
        max_hp, health = run_max_hp_before(run, rid, fid, pid, *got)
        rule = label(*got, max_hp=max_hp, health=health)
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
