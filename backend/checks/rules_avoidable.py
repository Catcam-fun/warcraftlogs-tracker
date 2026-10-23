"""Avoidable deaths follow the owner's rule B′, recomputed from WarcraftLogs' hits

The stretch is the hits since the player was last at 85%+ health (rules_labels.last_high; the whole
window when they weren't). A hit in it is avoidable by the ability's rule (avoidable.rule_for): "always",
or "non_tank" when their spec that pull isn't a tank's. Replayed without the avoidable hits, counting only
the health those hits took (amount + overkill, never a shield's part) and only while they were missing
health, they would have lived when that is more than the killing blow's overkill. A hit whose rule can't
be told (no spec) makes the verdict None when it alone would flip it. Written apart from the site's
defensives._avoidable.
"""
from avoidable import TANK_SPECS, rule_for
from checks.rules_labels import _own_hp, death_hits, last_high, loadout_of, max_hp_before, run_max_hp_before
from checks.verdict import PASS, Outcome, fail, skip


def pull_spec(run, rid, fid, pid):
    return loadout_of(run, rid, fid, pid).spec


def judge(hit, spec):
    entry = rule_for(hit.get("abilityGameID"))
    rule = entry and entry.get("rule")
    if rule == "always":
        return True
    if rule == "non_tank":
        return None if not spec else spec not in TANK_SPECS
    return False


def verdict(hits, kb_index, max_hp, health, spec):
    """(verdict, windowLimited) for the death whose killing blow is hits[kb_index]."""
    since_i, since_ts = last_high(hits, kb_index, max_hp, health)
    first = since_i + 1
    sure = {i for i in range(first, kb_index + 1) if judge(hits[i], spec)}
    unsure = {i for i in range(first, kb_index + 1) if judge(hits[i], spec) is None}
    overkill = hits[kb_index].get("overkill") or 0

    def lives(removed):
        extra = 0.0
        for i in range(first, kb_index + 1):
            h = hits[i]
            if i == kb_index:
                extra = min(extra, max(max_hp - health, 0))
            elif _own_hp(h):
                extra = min(extra, max(h["maxHitPoints"] - (h.get("hitPoints") or 0) - (h.get("amount") or 0), 0))
            if i in removed:
                extra += (h.get("amount") or 0) + (h.get("overkill") or 0)
        return extra > overkill

    v = lives(sure)
    if unsure and not v and lives(sure | unsure):
        v = None
    return v, since_ts is None


def check(run):
    """Avoidable deaths follow the owner's rule B′, recomputed from WarcraftLogs' hits"""
    items, seen, compared, skipped = [], 0, 0, []
    for ev in run.counted_deaths():
        s = (ev.get("defensives") or {}).get("survival") or {}
        a = s.get("avoidable")
        if a is None or s.get("deathType") == "instakill":
            continue
        seen += 1
        rid, fid, name = ev["reportId"], ev["fightId"], ev.get("originalCharacter")
        pid = run.actor_id(rid, name)
        if pid is None:
            skipped.append(f"{name} pull {fid}: not among report {rid}'s players")
            continue
        death_ts = ev["timestamp"] + run.fight(rid, fid)["start_time"]
        got = death_hits(run.hits_before(rid, fid, pid, death_ts), death_ts)
        if got is None:
            skipped.append(f"{name} pull {fid}: no killing hit in WCL's damage taken")
            continue
        if not max_hp_before(*got)[0]:
            skipped.append(f"{name} pull {fid}: WCL's hits carry none of the player's health")
            continue
        max_hp, health, why = run_max_hp_before(run, rid, fid, pid, *got)
        if why:
            skipped.append(f"{name} pull {fid}: {why}")
            continue
        compared += 1
        want = verdict(*got, max_hp, health, pull_spec(run, rid, fid, pid))
        site = (a.get("verdict"), bool(a.get("windowLimited")))
        if site != want:
            items.append(f"{name} pull {fid}: site verdict {site[0]} (window limited {site[1]}), "
                         f"rule {want[0]} (window limited {want[1]})")
    if not seen:
        return skip("no counted deaths with an avoidable verdict")
    note = ""
    if skipped:
        note = f"{len(skipped)} of {seen} deaths not compared: {'; '.join(skipped[:3])}" \
            + (f"; {len(skipped) - 3} more" if len(skipped) > 3 else "")
    if not compared:
        return skip("no counted death could be recomputed" + (f"; {note}" if note else ""))
    if items:
        return fail(items, reason=note)
    return Outcome("pass", reason=note) if note else PASS
