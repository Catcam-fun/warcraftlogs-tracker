"""Source check: what each counted death row shows (active, ready, health) against WCL's auras, casts and Deaths table."""
import defensives
from checks.common import TableCapped
from checks.verdict import PASS, fail, skip
from defensives import CDR_TOLERANCE_MS, ENCOUNTER_RESET_MS

BAND_TOLERANCE_MS, HP_TOLERANCE = 100, 0.01
ENTRY_TOLERANCE_MS = 50
CONSUMABLE_KINDS = ("healthstone", "potion")


def active_mismatches(active_names, auras, death_ts):
    """Active names with no same-named aura band around death_ts (within BAND_TOLERANCE_MS)."""
    out = []
    for name in active_names:
        covered = any(b["startTime"] - BAND_TOLERANCE_MS <= death_ts <= b["endTime"] + BAND_TOLERANCE_MS
                      for a in auras if a.get("name") == name for b in a.get("bands") or [])
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


def _killing_event(entry):
    """The damage event with overkill > 0 and the greatest timestamp (events are newest-first, so ties keep the newest)."""
    kills = [e for e in entry.get("events") or [] if e.get("type") == "damage" and (e.get("overkill") or 0) > 0]
    return max(kills, key=lambda e: e.get("timestamp", 0)) if kills else None


def health_mismatch(survival, entry):
    """What differs between the site's health before the killing blow / overkill and WCL's, or None."""
    max_hp = survival["maxHp"]
    site_hp = survival["hpBeforePct"] * max_hp / 100
    out = []
    kill = _killing_event(entry)
    if kill is None:
        out.append(f"health before {round(site_hp)} vs wcl none (no killing hit, max {max_hp})")
    elif abs(kill["amount"] - site_hp) > HP_TOLERANCE * max_hp:
        out.append(f"health before {round(site_hp)} vs wcl {kill['amount']} (max {max_hp})")
    if entry.get("overkill") != survival.get("overkill"):
        out.append(f"overkill site {survival.get('overkill')} vs wcl {entry.get('overkill')}")
    return "; ".join(out) if out else None


def _talents(run, rid, fid, pid):
    for c in run.combatants(rid, fid):
        if c.get("sourceID") == pid and c.get("fight", fid) == fid:
            return {t["id"]: t.get("rank") or 1 for t in c.get("talentTree") or []}
    return None


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
    start = max(0, fight_start - max(cd * charges for *_, cd, charges in judged))
    casts = [e for e in run.casts(rid, pid, start, death_ts) if e.get("type", "cast") == "cast"]
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
            for name in active_mismatches(active, run.buffs(rid, fid, pid), death_ts):
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
