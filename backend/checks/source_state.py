"""Source check: what each counted death row shows (active, ready, health) against WCL's auras, casts and Deaths table."""
import defensives
from checks.common import TableCapped
from checks.verdict import PASS, fail, skip
from defensives import CDR_TOLERANCE_MS, ENCOUNTER_RESET_MS

BAND_TOLERANCE_MS, HP_TOLERANCE = 100, 0.01
ENTRY_TOLERANCE_MS = 50
STRIP_LOOKBACK_MS = 1000
CONSUMABLE_KINDS = ("healthstone", "potion")


def death_strip(auras, death_ts, fight_start):
    """When the death stripped the player's auras: the first end, in the STRIP_LOOKBACK_MS before the
    death event, of an aura band up since the pull started (raid buffs, forms: only death ends those).
    WCL's death event can come after the strip (live 2026-10-08, dreamrift pull 1: Chickenism's 19 auras,
    Fortitude and Battle Shout among them, ended at 1244582-1244684, the death event at 1244690; the same
    Rallying Cry stayed up on the living until 1247448). Without such a band, the death event itself."""
    ends = [b["endTime"] for a in auras for b in a.get("bands") or []
            if b["startTime"] <= fight_start + BAND_TOLERANCE_MS
            and death_ts - STRIP_LOOKBACK_MS <= b["endTime"] <= death_ts]
    return min(ends) if ends else death_ts


def active_mismatches(active_names, auras, death_ts, fight_start=None):
    """Active names with no same-named aura band around the death (within BAND_TOLERANCE_MS of the
    death event, or of the moment the death stripped the player's auras when fight_start is given)."""
    moments = {death_ts}
    if fight_start is not None:
        moments.add(death_strip(auras, death_ts, fight_start))
    out = []
    for name in active_names:
        covered = any(b["startTime"] - BAND_TOLERANCE_MS <= t <= b["endTime"] + BAND_TOLERANCE_MS
                      for a in auras if a.get("name") == name for b in a.get("bands") or [] for t in moments)
        if not covered:
            out.append(name)
    return out


def ready_at(cast_times, death_ts, cooldown_ms, charges):
    """Whether a charge is left at death_ts: each use spends one, and charges come back one per
    cooldown_ms, the recharge starting at the first use made with all charges full."""
    have, back_at = charges, None
    for t in sorted(t for t in cast_times if t <= death_ts):
        while back_at is not None and back_at <= t:
            have += 1
            back_at = back_at + cooldown_ms if have < charges else None
        have = max(have - 1, 0)
        if back_at is None:
            back_at = t + cooldown_ms
    while back_at is not None and back_at <= death_ts:
        have += 1
        back_at = back_at + cooldown_ms if have < charges else None
    return have > 0


def entry_for(entries, pid, death_ts):
    """This death's own Deaths table entry: same player, timestamp within 50 ms (a rezzed player dies twice)."""
    for e in entries:
        if e.get("id") == pid and abs(e["timestamp"] - death_ts) <= ENTRY_TOLERANCE_MS:
            return e
    return None


def killing_hit_auras(run, rid, fid, pid, death_ts):
    """Names of the auras WCL lists on the player's killing hit (the last overkill hit up to 50 ms after death)."""
    names = run.meta_for(rid).get("abilities") or {}
    kills = [h for h in run.hits_before(rid, fid, pid, death_ts)
             if (h.get("overkill") or 0) > 0 and h["timestamp"] <= death_ts + ENTRY_TOLERANCE_MS]
    if not kills:
        return set()
    return {names.get(a) for a in defensives._auras(kills[-1])}


def _killing_event(entry):
    """The damage event with overkill > 0 and the greatest timestamp (events are newest-first, so ties keep the newest)."""
    kills = [e for e in entry.get("events") or [] if e.get("type") == "damage" and (e.get("overkill") or 0) > 0]
    return max(kills, key=lambda e: e.get("timestamp", 0)) if kills else None


def health_mismatch(survival, entry):
    """What differs between the site's health before the killing blow / overkill and WCL's, or None.

    The site's "Died by" is the killing blow's overkill, so it is compared with WCL's killing event,
    not with the entry's own `overkill`: WCL sums every overkill in the death window there, non-fatal
    ones included (live 2026-10-08, Weavi, Brewmaster: two Stagger ticks overkilled for 662478 and
    299233 without killing him, and the entry read 3614972 against the killing hit's 2653261).
    Health before the killing blow can never be above max HP; the site showing more is a mismatch.
    """
    max_hp = survival["maxHp"]
    site_hp = survival["hpBeforePct"] * max_hp / 100
    out = []
    if survival["hpBeforePct"] > 100:
        out.append(f"health before {survival['hpBeforePct']}% of max HP {max_hp} (above 100%)")
    kill = _killing_event(entry)
    if kill is None:
        out.append(f"health before {round(site_hp)} vs wcl none (no killing hit, max {max_hp})")
    else:
        if abs(kill["amount"] - site_hp) > HP_TOLERANCE * max_hp:
            out.append(f"health before {round(site_hp)} vs wcl {kill['amount']} (max {max_hp})")
        if (kill.get("overkill") or 0) != (survival.get("overkill") or 0):
            out.append(f"overkill site {survival.get('overkill')} vs wcl {kill.get('overkill')}")
    return "; ".join(out) if out else None


def _talents(run, rid, fid, pid):
    for c in run.combatants(rid, fid):
        if c.get("sourceID") == pid and c.get("fight", fid) == fid:
            return {t["id"]: t.get("rank") or 1 for t in c.get("talentTree") or []}
    return None


def report_span(run, rid, fid):
    """The span the site reads a report's casts over: from 3 minutes before its first kept pull
    to the end of its last (the site's kept pulls are the keys of pullParticipation). Without any
    kept pull listed for the report, the death's own pull."""
    fids = {int(k.rsplit("_", 1)[1]) for keys in (run.result.get("pullParticipation") or {}).values()
            for k in keys if k.rsplit("_", 1)[0] == rid} or {fid}
    fights = [run.fight(rid, f) for f in sorted(fids)]
    return (max(0, min(f["start_time"] for f in fights) - ENCOUNTER_RESET_MS),
            max(f["end_time"] for f in fights))


def _ready_items(run, rid, fid, pid, who, ev, fight_start, death_ts):
    d = ev["defensives"]
    site_ready = {a["name"] for a in d.get("available") or []}
    judged = []
    talents = _talents(run, rid, fid, pid)
    for name in [a["name"] for a in d.get("available") or []] + [a["name"] for a in d.get("cooldown") or []]:
        sid = run.cat.name_to_id.get(name)
        entry = run.cat.all.get(sid) if sid is not None else None
        if entry is None or entry.get("kind") in CONSUMABLE_KINDS:
            continue
        cd = defensives._talented_cooldown(entry, talents, ev.get("spec"))
        charges = defensives._talented_charges(entry, talents, ev.get("spec"))
        judged.append((name, sid, entry, cd, charges))
    if not judged:
        return []
    # The whole report's casts, as the site reads them: cooldown reduction shows up as a short
    # gap anywhere in the report, not only near this death.
    casts = [e for e in run.casts(rid, pid, *report_span(run, rid, fid)) if e.get("type", "cast") == "cast"]
    items = []
    for name, sid, entry, cd, charges in judged:
        times = sorted(e["timestamp"] for e in casts if e.get("abilityGameID") == sid)
        # A one-charge ability pressed again sooner than its cooldown allows: the player has
        # cooldown reduction the catalog can't see, so their shortest gap is the cooldown.
        if charges == 1 and len(times) > 1:
            shortest = min(b - a for a, b in zip(times, times[1:]))
            if shortest < cd - CDR_TOLERANCE_MS:
                cd = shortest
        # Long cooldowns reset when the encounter starts; short ones carry over from before the pull.
        since = fight_start if entry["cooldown_ms"] >= ENCOUNTER_RESET_MS else death_ts - cd * charges
        wcl_ready = ready_at([t for t in times if max(since, 0) <= t <= death_ts], death_ts, cd, charges)
        if (name in site_ready) and not wcl_ready:
            items.append(f"{who} pull {fid} {name}: site ready, wcl casts say on cooldown")
        elif wcl_ready and name not in site_ready:
            items.append(f"{who} pull {fid} {name}: site on cooldown, wcl casts say ready")
    return items


def check(run):
    """Active, ready and health at death match WCL's auras, casts and Deaths table"""
    deaths = run.counted_deaths()
    if not deaths:
        return skip("no counted deaths")
    items, capped = [], set()
    for ev in deaths:
        rid, fid, who = ev["reportId"], ev["fightId"], ev["originalCharacter"]
        pid = run.actor_id(rid, who)
        if pid is None:
            items.append(f"{who} pull {fid}: not among report {rid}'s players")
            continue
        fight_start = run.fight(rid, fid)["start_time"]
        death_ts = ev["timestamp"] + fight_start
        d = ev.get("defensives") or {}

        active = [a["name"] for a in d.get("active") or []]
        if active:
            auras = run.buffs(rid, fid, pid)
            missing = active_mismatches(active, auras, death_ts, fight_start)
            # A defensive that is a debuff on the enemy (Fiery Brand) is never a band on the player;
            # WCL's killing hit lists it when it was up.
            not_buffs = [n for n in missing if not any(a.get("name") == n for a in auras)]
            if not_buffs:
                snapshot = killing_hit_auras(run, rid, fid, pid, death_ts)
                missing = [n for n in missing if n not in not_buffs or n not in snapshot]
            for name in missing:
                items.append(f"{who} pull {fid}: active {name} has no aura band at death")

        if d:
            items += _ready_items(run, rid, fid, pid, who, ev, fight_start, death_ts)

        survival = d.get("survival")
        if not survival or survival.get("deathType") == "instakill" or (rid, fid) in capped:
            continue
        try:
            entry = entry_for(run.deaths_table(rid, fid), pid, death_ts)
        except TableCapped:
            capped.add((rid, fid))
            items.append(f"pull {fid}: 200+ deaths, table capped")
            continue
        if entry is None:
            items.append(f"{who} pull {fid}: no WCL Deaths table entry at {death_ts}")
            continue
        diff = health_mismatch(survival, entry)
        if diff:
            items += [f"{who} pull {fid}: {part}" for part in diff.split("; ")]
    return fail(items) if items else PASS
