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

from checks.verdict import PASS, Outcome, fail, skip
from defensive_catalog import PATCHES
from defensives import SPEC_NAMES
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
SAME_MOMENT_MS = 2          # a cheat death's absorb and its heal (or the aura it brings) are logged within 2 ms


def patch_of(report_start_ms):
    """The game patch live when a report was logged (defensive_catalog.PATCHES: first day live)."""
    from datetime import datetime, timezone
    day = datetime.fromtimestamp(report_start_ms / 1000, tz=timezone.utc).date().isoformat()
    live = [p for first, p in PATCHES if first <= day]
    return live[-1] if live else PATCHES[0][1]


class Loadout:
    """What decides an aura's size for one player: the patch, their talents ({entry: rank} from WCL's
    CombatantInfo; None when the log has none) and spec name."""

    def __init__(self, patch, talents=None, spec=None):
        self.patch, self.talents, self.spec = patch, talents, spec


def aura_size(aura_id, loadout):
    """(share, flat) an aura changes max health by for this loadout, from the game data
    (max_health_auras: each term where the game puts the effect, with the talents and spec passives
    that change it); (0.0, 0) when it doesn't. A str (why) when it can't be sized: a term not in the
    data, or a term or modifier that needs a talent when the log has no loadout."""
    terms = []
    for first, value in MAX_HEALTH.get(aura_id, ()):
        if tuple(map(int, first.split("."))) <= tuple(map(int, loadout.patch.split("."))):
            terms = value

    def has(who):
        if "entries" in who:
            if loadout.talents is None:
                return None
            return max((loadout.talents.get(e, 0) for e in who["entries"]), default=0)
        if "specs" in who:
            if not loadout.spec:
                return None
            return int(loadout.spec.replace(" ", "").lower() in {x.replace(" ", "").lower() for x in who["specs"]})
        return 1

    total, flat = 1.0, 0
    for t in terms:
        rank = has(t)
        if rank is None:
            return f"aura {aura_id}: needs the player's loadout, none in the log"
        if not rank:
            continue
        if "flat" in t:
            flat += t["flat"]
            continue
        if t["share"] is None:
            return f"aura {aura_id}: size not in the game data"
        share = t["share"]
        for m in t.get("mods", ()):
            r = has(m)
            if r is None:
                return f"aura {aura_id}: a modifier needs the player's loadout, none in the log"
            if r:
                share = share + m["add"] * r if "add" in m else share * m["mult"]
        total *= 1 + share
    return (total - 1, flat)


def _listed(h):
    return {int(x) for x in str(h.get("buffs") or "").split(".") if x.isdigit()}


def max_hp_before(hits, kb_index, loadout=None, bands=(), heals=()):
    """(max HP, health, why not sized or None) just before the killing blow hits[kb_index] landed (hits:
    this death's, time order); (0, 0, None) when the killing hit doesn't carry the player's health.

    WCL logs the killing hit after the death stripped the player's auras, so its own maxHitPoints has
    lost their max-health auras (live 2026-10-08: Strikepal, Nerub-ar p16, auras removed at
    1910329-1910332, killing hit at 1910349 with max 10061382; 11198315 on every hit and heal before).
    Instead, from the player's last own-health hit before it (or the one before that when the last one's
    aura list changed but its max did not yet: WCL's max lags the list, 26 of 258 changes in six logs):
    its max, with every aura on the killing hit's list and not on that hit's (came up) multiplied in and
    every one the other way (ran out) divided out, sized for the player's `loadout` (aura_size). Each
    hit's list is the auras up on it, before the death's strip. An aura that can't be sized makes the
    whole result unknown (the third value says why).
    An aura the killing hit set off (`bands`: [(start, end, aura ID, name)] from WCL's Buffs table;
    came up after the hit before it, within DEATH_STRIP_MS, not on its list), or a cheat death that
    absorbed part of it (`heals`: WCL's [(ts, amount, ability ID, name, "heal" | "absorbed")] in that
    span, an absorb from an aura not on its list) is not max HP they had before the blow, and that
    aura's own heals are not health they had: Soulcleavi, Manaforge p54, Last Resort's Metamorphosis
    healed 11748168 at 8002681, 18995479 -> 30743647, and Oblivion read 30743644 taken; Padflash,
    Manaforge p79, Cauterize absorbed 33273760 of Oblivion and healed 2919591, 2903317 -> 5822908.
    Never below the killing hit's own max (the death only takes max health away) nor below the health.
    """
    kb = hits[kb_index]
    if not _own_hp(kb):
        return 0, 0, None
    t1 = kb["timestamp"]
    prev_t = hits[kb_index - 1]["timestamp"] if kb_index else float("-inf")
    on_kb = _listed(kb)
    own = [h for h in hits[:kb_index] if _own_hp(h)]
    why = []

    def size(aid):
        if loadout is None:
            return (0.0, 0)
        v = aura_size(aid, loadout)
        if isinstance(v, str):
            why.append(v)
            return (0.0, 0)
        return v

    if not own:
        value = float(kb["maxHitPoints"])
    else:
        ref = own[-1]
        if len(own) > 1 and own[-2]["maxHitPoints"] == ref["maxHitPoints"] and \
                any(size(a) != (0.0, 0) for a in _listed(own[-2]) ^ _listed(ref)):
            ref = own[-2]
        value = float(ref["maxHitPoints"])
        for aid in on_kb - _listed(ref):
            v = size(aid)
            value = value * (1 + v[0]) + v[1]
        for aid in _listed(ref) - on_kb:
            v = size(aid)
            value = (value - v[1]) / (1 + v[0])
    # What the killing hit set off. A cheat death absorbs part of it and heals in the same moment, under
    # the same name (Defy Fate, Cauterize, Embrace the Shadow: absorb and heal within SAME_MOMENT_MS); an
    # aura that came up in that moment and is not on its list came with it (Last Resort's
    # Metamorphosis, 1 ms before Last Resort's absorb). Their heals are not health the player had before
    # the blow; other heals landing then are (Leech, a healer's Reversion 24 ms before its own absorb).
    absorbs = [(ts, name) for ts, amount, aid, name, typ in heals if typ == "absorbed" and prev_t < ts <= t1]
    healed = [(ts, name) for ts, amount, aid, name, typ in heals if typ == "heal" and prev_t < ts <= t1]
    set_off = {name for ts, name in absorbs
               if any(n == name and abs(t - ts) <= SAME_MOMENT_MS for t, n in healed)}
    set_off |= {name for start, end, aid, name in bands
                if prev_t < start <= t1 and aid not in on_kb
                and any(abs(start - ts) <= SAME_MOMENT_MS for ts, _ in absorbs)}
    health = kb.get("amount") or 0
    health -= sum(amount for ts, amount, aid, name, typ in heals
                  if typ == "heal" and prev_t < ts <= t1 and name in set_off)
    health = max(health, 0)
    return max(round(value), kb["maxHitPoints"], health), health, ("; ".join(sorted(set(why))) or None)


def aura_bands(auras):
    """[(start, end, aura ID, name)] from a Buffs table's auras (guid, name, bands)."""
    return sorted((b["startTime"], b.get("endTime"), a.get("guid"), a.get("name"))
                  for a in auras if a.get("guid") is not None for b in a.get("bands") or [])


def loadout_of(run, rid, fid, pid):
    """The player's Loadout for one pull, from WCL's CombatantInfo (talents and spec) and the report's patch."""
    talents, spec = None, None
    for c in run.combatants(rid, fid):
        if c.get("sourceID") == pid and c.get("fight", fid) == fid:
            if c.get("talentTree") is not None:
                talents = {t["id"]: t.get("rank") or 1 for t in c["talentTree"]}
            spec = SPEC_NAMES.get(c.get("specID"))
    return Loadout(patch_of(run.meta_for(rid)["report_start"]), talents, spec)


def run_max_hp_before(run, rid, fid, pid, hits, kb_index):
    """max_hp_before for one death with the player's loadout. WCL's heals in the DEATH_STRIP_MS before
    the killing hit are read when the hit shows something may have been set off by it: it was partly
    absorbed (Last Resort, Cheat Death and Defy Fate absorb the lethal part), its aura list has an aura
    the last own-health hit's didn't, or it took more health than the list-based max allows. Only when
    a heal landed there is the Buffs table read, for the aura behind it. All from WCL's own data, never
    the site's numbers."""
    loadout = loadout_of(run, rid, fid, pid)
    value, health, why = max_hp_before(hits, kb_index, loadout)
    kb = hits[kb_index]
    if not value:
        return value, health, why
    own = [h for h in hits[:kb_index] if _own_hp(h)]
    listed_max = max_hp_before(hits[:kb_index] + [dict(kb, amount=0)], kb_index, loadout)[0]
    suspicious = (kb.get("absorbed") or 0) > 0 or (kb.get("amount") or 0) > listed_max or \
        (own and _listed(kb) - _listed(own[-1]))
    if not suspicious:
        return value, health, why
    t1 = kb["timestamp"]
    names = run.meta_for(rid).get("abilities") or {}
    heals = [(e["timestamp"], e.get("amount") or 0, e.get("abilityGameID"), names.get(e.get("abilityGameID")),
              e.get("type")) for e in run.heals_taken(rid, pid, t1 - DEATH_STRIP_MS, t1 + 1)
             if e.get("type") in ("heal", "absorbed")]
    if not any(typ == "heal" for *_, typ in heals):
        return value, health, why
    return max_hp_before(hits, kb_index, loadout, aura_bands(run.buffs(rid, fid, pid)), heals)


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
        max_hp, health, _ = max_hp_before(hits, kb_index)
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
    items, seen, compared, skipped = [], 0, 0, []
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
        max_hp, health, why = run_max_hp_before(run, rid, fid, pid, *got)
        if why:
            skipped.append(f"{name} pull {fid}: {why}")
            continue
        compared += 1
        rule = label(*got, max_hp=max_hp, health=health)
        site = (s.get("deathType"), (s.get("rot") or {}).get("abilityId"), (s.get("biggestHit") or {}).get("abilityId"),
                (s.get("oneShotHit") or {}).get("abilityId"))
        want = (rule["deathType"], rule["rot"], rule["biggestHit"], rule["oneShotHit"])
        if site != want:
            items.append(f"{name} pull {fid}: site {'/'.join(map(str, site))}, rule {'/'.join(map(str, want))}")
    if not seen:
        return skip("no counted deaths with a survival block")
    if not compared:
        return skip("no counted death has a killing hit in WCL's damage taken"
                    + (f"; {len(skipped)} not sized: {skipped[0]}" if skipped else ""))
    if items:
        return fail(items, reason=f"{len(skipped)} deaths skipped, max HP not sized" if skipped else "")
    return Outcome("pass", reason=f"{len(skipped)} deaths skipped, max HP not sized: {'; '.join(skipped[:3])}") \
        if skipped else PASS
