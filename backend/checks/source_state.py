"""Source check: what each counted death row shows (active, ready, health) against WCL's auras, casts and Deaths table.

The ready / on-cooldown recompute (ability_state, written separately from the site's replay) follows
the same rules: the encounter reset (long cooldowns reset when the encounter starts; short ones keep
the report's whole cast history), each press with the loadout of its own pull, resets from the
catalog's reset_by (Cold Snap, Black Ox Brew), and the cooldown-reduction inference (a one-charge
ability pressed again sooner than its cooldown, no reset in between, takes the shortest gap as its
cooldown). It therefore validates the casts data the site read, not the inference itself.
"""
import defensives
from checks.common import TableCapped
from checks.verdict import PASS, fail, skip
from defensives import CDR_TOLERANCE_MS, ENCOUNTER_RESET_MS

BAND_TOLERANCE_MS, HP_TOLERANCE = 100, 0.01
ENTRY_TOLERANCE_MS = 50
STRIP_LOOKBACK_MS, STRIP_CLUSTER_MS, STRIP_MIN_BANDS = 1000, 150, 2
CONSUMABLE_KINDS = ("healthstone", "potion")


def death_strip(auras, death_ts, fight_start):
    """When the death stripped the player's auras, or the death event itself when no strip shows.

    Death removes every aura at once, and WCL's death event can come after that (live 2026-10-08,
    dreamrift pull 1: Chickenism's 19 auras, Fortitude and Battle Shout among them, ended at
    1244582-1244684, the death event at 1244690; the same Rallying Cry stayed up on the living until
    1247448). The strip is a cluster: at least STRIP_MIN_BANDS bands up since the pull started (raid
    buffs, forms) ending within STRIP_CLUSTER_MS of each other in the STRIP_LOOKBACK_MS before the death
    event, and more than half of those that end there. One such band ending alone (a form dropped, an
    aura cancelled) is not a strip. The strip is the cluster's earliest end."""
    ends = sorted(b["endTime"] for a in auras for b in a.get("bands") or []
                  if b["startTime"] <= fight_start + BAND_TOLERANCE_MS
                  and death_ts - STRIP_LOOKBACK_MS <= b["endTime"] <= death_ts)
    for first in ends:
        together = sum(1 for e in ends if first <= e <= first + STRIP_CLUSTER_MS)
        if together >= STRIP_MIN_BANDS and together * 2 > len(ends):
            return first
    return death_ts


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


def kept_pulls(run, rid, fid):
    """The report's pulls the site kept (the keys of pullParticipation), or the death's own pull."""
    return sorted({int(k.rsplit("_", 1)[1]) for keys in (run.result.get("pullParticipation") or {}).values()
                   for k in keys if k.rsplit("_", 1)[0] == rid} or {fid})


def report_span(run, rid, fid):
    """The span the site reads a report's casts over: from 3 minutes before its first kept pull
    to the end of its last. Without any kept pull listed for the report, the death's own pull."""
    fights = [run.fight(rid, f) for f in kept_pulls(run, rid, fid)]
    return (max(0, min(f["start_time"] for f in fights) - ENCOUNTER_RESET_MS),
            max(f["end_time"] for f in fights))


def report_casts(run, rid, fid, pid):
    """The player's casts over the whole report span the site reads (report_span): cooldown
    reduction shows up as a short gap anywhere in the report, not only near this death."""
    return [e for e in run.casts(rid, pid, *report_span(run, rid, fid)) if e.get("type", "cast") == "cast"]


def report_encounters(run, rid):
    """[(start, end)] of every boss encounter in the report, kept or not (each resets long cooldowns)."""
    return [(f["start_time"], f["end_time"]) for f in run.meta_for(rid)["fights"] if f.get("boss")]


def pull_loadouts(run, rid, fid, pid):
    """[(pull start, talents, spec name or None)] for each kept pull of the report the player has a
    loadout in, oldest first (WCL records a loadout only at pull start)."""
    out = []
    for c in run.report_combatants(rid, kept_pulls(run, rid, fid)):
        if c.get("sourceID") != pid or c.get("talentTree") is None:
            continue
        talents = {t["id"]: t.get("rank") or 1 for t in c["talentTree"]}
        out.append((run.fight(rid, c["fight"])["start_time"], talents, defensives.SPEC_NAMES.get(c.get("specID"))))
    return sorted(out, key=lambda x: x[0])


def ability_state(entry, sid, casts, loadouts, this_pull, fight_start, at, encounters=()):
    """(charges left at `at`, when a charge last came back after none were left; None if it never ran
    out) for one catalog ability, from the player's WCL casts.

    - A long cooldown (base ENCOUNTER_RESET_MS or more) resets when the encounter starts: only presses
      since the pull started count, with this pull's talents (`this_pull` = (talents, spec)).
    - A shorter one counts every press of the report. Each press uses the loadout of the latest KEPT
      pull that had started by then (a press in an unkept pull or between pulls: the previous kept
      pull's), else the first kept pull's (talents change only out of combat).
    - Each press spends a charge; charges return one at a time, one cooldown after the previous one
      returned or after the spend that started the recharge.
    - A cast of a spell in the entry's reset_by gives back every charge ("all") or one ("one").
    - A one-charge press repeated sooner than its cooldown (that press's own loadout), with no reset
      cast in between and, for a long cooldown, no boss encounter start or end in between
      (`encounters`: [(start, end)] of every boss encounter in the report): the shortest such gap is
      taken as the cooldown (reduction the catalog can't see).
    """
    long = entry["cooldown_ms"] >= ENCOUNTER_RESET_MS

    def talents_at(t, own_pull=None):
        if (long if own_pull is None else not own_pull) or not loadouts:
            return this_pull
        started = [lo for lo in loadouts if lo[0] <= t]
        start, talents, spec = started[-1] if started else loadouts[0]
        return talents, spec or this_pull[1]

    def cooldown(t, own_pull=None):
        talents, spec = talents_at(t, own_pull)
        return defensives._talented_cooldown(entry, talents, spec)

    def most(t, own_pull=None):
        talents, spec = talents_at(t, own_pull)
        return defensives._talented_charges(entry, talents, spec)

    gives = {r["spell"]: r["restores"] for r in entry.get("reset_by") or ()}
    presses = sorted(e["timestamp"] for e in casts if e.get("abilityGameID") == sid)
    reset_casts = sorted((e["timestamp"], gives[e.get("abilityGameID")]) for e in casts
                         if e.get("abilityGameID") in gives)
    walls = [r for r, _ in reset_casts]
    if long:
        walls += [t for start, end in encounters for t in (start, end)] + [fight_start]
    shortest = None
    for a, b in zip(presses, presses[1:]):
        if any(a < w <= b for w in walls) or most(a, True) != 1:
            continue
        if b - a < cooldown(a, True) - CDR_TOLERANCE_MS:
            shortest = b - a if shortest is None else min(shortest, b - a)

    def recharge(t):
        return cooldown(t) if shortest is None else min(cooldown(t), shortest)

    first = fight_start if long else 0
    timeline = [(t, "press") for t in presses if first <= t <= at] + \
               [(t, how) for t, how in reset_casts if first <= t <= at]
    timeline.sort(key=lambda x: (x[0], x[1] == "press"))   # a reset logged with a press came first
    left = most(timeline[0][0] if timeline else at)
    next_back, back_from_none = None, None
    for t, what in timeline + [(at, "end")]:
        while next_back is not None and next_back <= t:
            back_from_none = next_back if left == 0 else back_from_none
            left += 1
            next_back = next_back + recharge(next_back) if left < most(next_back) else None
        if what == "end":
            break
        left = min(left, most(t))
        if what == "press":
            left = max(left - 1, 0)
            next_back = t + recharge(t) if next_back is None else next_back
        else:
            back_from_none = t if left == 0 else back_from_none
            left = most(t) if what == "all" else min(left + 1, most(t))
            next_back = None if left >= most(t) else next_back
    return left, back_from_none


def _ready_items(run, rid, fid, pid, who, ev, fight_start, death_ts):
    d = ev["defensives"]
    site_ready = {a["name"] for a in d.get("available") or []}
    judged = []
    for name in [a["name"] for a in d.get("available") or []] + [a["name"] for a in d.get("cooldown") or []]:
        sid = run.cat.name_to_id.get(name)
        entry = run.cat.all.get(sid) if sid is not None else None
        if entry is None or entry.get("kind") in CONSUMABLE_KINDS:
            continue
        judged.append((name, sid, entry))
    if not judged:
        return []
    this_pull = (_talents(run, rid, fid, pid), ev.get("spec"))
    loadouts = pull_loadouts(run, rid, fid, pid)
    casts = report_casts(run, rid, fid, pid)
    items = []
    for name, sid, entry in judged:
        wcl_ready = ability_state(entry, sid, casts, loadouts, this_pull, fight_start, death_ts,
                                  report_encounters(run, rid))[0] > 0
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
