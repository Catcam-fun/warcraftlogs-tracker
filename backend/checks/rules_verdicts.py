"""Would-save verdicts obey the press, overkill, immunity and instant-kill rules"""
from checks.rules_counting import is_counted
from checks.verdict import PASS, fail, skip

REACTION_S = 1.0
HP_TOLERANCE = 0.01      # hpBeforePct is a whole percent


def _immune(cat, name):
    sid = cat.name_to_id.get(name)
    if sid is None:
        return False
    return any(c.get("immune") for c in (cat.all[sid].get("mitigation") or []))


def violations(defensives, cat):
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
    if s.get("ignoresImmunity"):
        out += [f"{name}: immunity marked saves against a hit that ignores immunity"
                for name, v in would.items() if v is True and _immune(cat, name)]
    return out


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
            items += [f"{where}: {v}" for v in violations(d, run.cat)]
    if not seen:
        return skip("no counted deaths with a would-save judgement")
    return fail(items) if items else PASS
