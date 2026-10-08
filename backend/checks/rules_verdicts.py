"""Would-save verdicts obey the press, overkill, immunity and instant-kill rules

A press is never less than 1s before the killing blow, nor before the ability was ready: its ready
time is recomputed from WCL's casts (source_state.cooldown_window over the report's whole cast
history, then ready_since; the catalog cooldown and charges with the pull's talents). A Healthstone
or potion is ready from its last use this pull plus its cooldown; unused this pull it is ready all
along. A name whose ready time can't be
determined (no killing hit found, not in the catalog, on cooldown at the killing blow) is skipped.
Whether the killing hit ignores immunity is read from WCL's killing ability (the death event's
abilityId, else the report's abilities named like the killing hit) against
boss_spell_flags.IGNORES_IMMUNITY, not from the site's own flag.
"""
from boss_spell_flags import IGNORES_IMMUNITY
from checks import source_state
from checks.rules_counting import is_counted
from checks.verdict import PASS, fail, skip

REACTION_S = 1.0
HP_TOLERANCE = 0.01      # hpBeforePct is a whole percent
READY_TOLERANCE_MS = 100  # pressAgo is rounded to 0.1s
KILL_AFTER_MS = 50        # the killing hit can be logged just after the death event


def _immune(cat, name):
    sid = cat.name_to_id.get(name)
    if sid is None:
        return False
    return any(c.get("immune") for c in (cat.all[sid].get("mitigation") or []))


def violations(defensives, cat, ignores_immunity=False):
    """The rule breaks visible in one death's defensives. `ignores_immunity`: WCL's killing ability
    is on IGNORES_IMMUNITY (killing_ability_ignores_immunity)."""
    s = defensives["survival"]
    would, details = s.get("wouldSave") or {}, s.get("details") or {}
    overkill, max_hp = s.get("overkill") or 0, s.get("maxHp") or 0
    out = []
    ready = {a["name"] for a in defensives.get("available", [])} | set(s.get("consumables") or {})
    cooling = {a["name"] for a in defensives.get("cooldown", [])}
    # A healthstone / potion dict carries a name only when it was used and is on cooldown.
    cooling |= {defensives[k]["name"] for k in ("healthstone", "potion")
                if (defensives.get(k) or {}).get("name") and "readyIn" in defensives[k]}
    for name, det in details.items():
        if det.get("pressAgo") is not None and det["pressAgo"] < REACTION_S:
            out.append(f"{name}: pressed {det['pressAgo']}s before the killing blow (rule: at least 1s)")
    for name in would:
        if name in cooling:
            out.append(f"{name}: judged but on cooldown")
        elif name not in ready:
            out.append(f"{name}: judged but not ready")
    for name, det in details.items():
        verdict = would.get(name)
        if verdict is None:
            continue
        amount = det.get("amount") or 0
        # details["amount"] is rounded, so an amount equal to the overkill can fall either way.
        if verdict is True and (amount < overkill or "why" in det):
            out.append(f"{name}: amount {amount} vs overkill {overkill} but marked saves")
        elif verdict is False and amount > overkill and "why" not in det:
            out.append(f"{name}: amount {amount} vs overkill {overkill} but marked not saves")
    # Extra health only counts up to what was missing before the killing blow, and the killing
    # blow itself can be cut by at most its whole size: a reduction on a 30M one-shot saves 9M,
    # well above max HP, and that is right.
    kb = (s.get("killingHit") or {}).get("size")
    if kb is not None and s.get("hpBeforePct") is not None:
        # Never below 0: a site hpBeforePct above 100 (max HP read after the killing blow, Strikepal
        # live 2026-10-08) is a health mismatch the state check reports, not negative missing health.
        missing = max(max_hp * (100 - s["hpBeforePct"]) / 100, 0)
        for name, det in details.items():
            amount = det.get("amount") or 0
            if amount > missing + kb + HP_TOLERANCE * max_hp:
                out.append(f"{name}: amount {amount} above missing health {round(missing)} "
                           f"plus the killing hit {kb}")
    else:
        # Without the killing hit's size or the health before it, only max HP bounds the amount.
        for name, det in details.items():
            if (det.get("amount") or 0) > max_hp:
                out.append(f"{name}: amount above max HP")
    if s.get("deathType") == "instakill":
        out += [f"{name}: instant kill but marked saves" for name, v in would.items() if v is not False]
    if ignores_immunity:
        out += [f"{name}: immunity marked saves against a hit that ignores immunity"
                for name, v in would.items() if v is True and _immune(cat, name)]
    return out


def early_presses(details, kb_ts, ready):
    """Judged presses made before the ability was ready. `ready`: name -> when it last became
    ready before the killing blow at kb_ts (absent: unknown or ready all along)."""
    out = []
    for name, det in details.items():
        if det.get("pressAgo") is None or ready.get(name) is None:
            continue
        if kb_ts - det["pressAgo"] * 1000 < ready[name] - READY_TOLERANCE_MS:
            out.append(f"{name}: pressed {det['pressAgo']}s before the killing blow "
                       f"but only ready {round((kb_ts - ready[name]) / 1000, 1)}s before")
    return out


def killing_hit_ts(hits, death_ts):
    """When WCL's killing hit landed: the last hit with overkill (or an instant kill) up to
    KILL_AFTER_MS after the death event; None when there is none."""
    kills = [h["timestamp"] for h in hits if h["timestamp"] <= death_ts + KILL_AFTER_MS
             and ((h.get("overkill") or 0) > 0 or h.get("type") == "instakill")]
    return max(kills) if kills else None


def ready_times(run, ev, rid, fid, pid, fight_start, kb_ts, names):
    """name -> when it last became ready before kb_ts, from WCL's casts (see the module docstring)."""
    survival = ev["defensives"]["survival"]
    consumables = survival.get("consumables") or {}
    cat = run.cat
    talents = source_state._talents(run, rid, fid, pid)
    casts = source_state.report_casts(run, rid, fid, pid)
    out = {}
    for name in names:
        if name in consumables:
            kind = consumables[name]
            used = [(e["timestamp"], e["abilityGameID"]) for e in casts
                    if (cat.all.get(e.get("abilityGameID")) or {}).get("kind") == kind
                    and fight_start <= e["timestamp"] <= kb_ts]
            if used:
                t, sid = max(used)
                back = t + cat.all[sid]["cooldown_ms"]
                if back <= kb_ts:
                    out[name] = back
            continue
        sid = cat.name_to_id.get(name)
        entry = cat.all.get(sid) if sid is not None else None
        if entry is None:
            continue
        times, cd, charges = source_state.cooldown_window(entry, sid, casts, talents, ev.get("spec"),
                                                          fight_start, kb_ts)
        ok, since = source_state.ready_since(times, kb_ts, cd, charges)
        if ok and since is not None:
            out[name] = since
    return out


def killing_ability_ignores_immunity(run, ev, rid):
    """Whether WCL's killing ability is one that hits through immunities."""
    if ev.get("abilityId"):
        return ev["abilityId"] in IGNORES_IMMUNITY
    name = (ev["defensives"]["survival"].get("killingHit") or {}).get("name")
    abilities = run.meta_for(rid).get("abilities") or {}
    return any(int(aid) in IGNORES_IMMUNITY for aid, n in abilities.items() if n == name)


def _press_items(run, ev, player):
    details = ev["defensives"]["survival"].get("details") or {}
    names = [n for n, det in details.items() if det.get("pressAgo") is not None]
    if not names:
        return []
    rid, fid = ev.get("reportId"), ev["fightId"]
    pid = run.actor_id(rid, ev.get("originalCharacter") or player)
    if pid is None:
        return []
    fight_start = run.fight(rid, fid)["start_time"]
    death_ts = ev["timestamp"] + fight_start
    kb_ts = killing_hit_ts(run.hits_before(rid, fid, pid, death_ts), death_ts)
    if kb_ts is None:
        return []
    return early_presses(details, kb_ts, ready_times(run, ev, rid, fid, pid, fight_start, kb_ts, names))


def check(run):
    """Would-save verdicts obey the press, overkill, immunity and instant-kill rules"""
    max_cut = run.result["meta"]["maxCutoff"]
    items, seen = [], 0
    for player, evs in run.result["events"].items():
        for ev in evs:
            d = ev.get("defensives")
            if not d or not d.get("survival") or not is_counted(ev, max_cut):
                continue
            seen += 1
            where = f"{player} pull {ev['fightId']} {ev['timestamp']}"
            would = d["survival"].get("wouldSave") or {}
            # Only resolved when an immunity is marked saves, the one case it changes.
            immune_saves = any(v is True and _immune(run.cat, n) for n, v in would.items())
            ignores = immune_saves and killing_ability_ignores_immunity(run, ev, ev.get("reportId"))
            items += [f"{where}: {v}" for v in violations(d, run.cat, ignores) + _press_items(run, ev, player)]
    if not seen:
        return skip("no counted deaths with a would-save judgement")
    return fail(items) if items else PASS
