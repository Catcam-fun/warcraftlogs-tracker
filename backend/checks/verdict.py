"""Outcomes and verdicts of the WarcraftLogs checks, and how they print."""
from dataclasses import dataclass, field

MAX_ITEMS = 10


@dataclass
class Outcome:
    status: str                                  # "pass" | "fail" | "skip"
    items: list = field(default_factory=list)    # first MAX_ITEMS mismatches
    total: int = 0                               # mismatches found in all
    reason: str = ""                             # for skip, or a fail with no items


PASS = Outcome("pass")


def fail(items, reason=""):
    items = list(items)
    return Outcome("fail", items[:MAX_ITEMS], len(items), reason)


def skip(reason):
    return Outcome("skip", reason=reason)


@dataclass
class Verdict:
    name: str
    family: str
    rule: str
    outcome: Outcome


def _points_text(points):
    if points is None:
        return "unknown"
    return f"{points:.0f}" if float(points).is_integer() else f"{points:g}"


def format_lines(verdicts, points):
    lines = []
    for v in verdicts:
        o = v.outcome
        label = {"pass": "pass", "fail": "FAIL", "skip": "skip"}[o.status]
        line = f"{v.family:<7} {v.name:<15} {label:<5} {v.rule}"
        if o.status == "fail" and o.total:
            line += f"  ({o.total} mismatches; {o.reason})" if o.reason else f"  ({o.total} mismatches)"
        elif o.reason:
            line += f"  ({o.reason})"
        lines.append(line)
        for item in o.items:
            lines.append(" " * 8 + item)
    lines.append(f"points spent: {_points_text(points)}")
    return "\n".join(lines) + "\n"


def to_json(verdicts, points):
    return {
        "verdicts": [
            {"name": v.name, "family": v.family, "rule": v.rule,
             "status": v.outcome.status, "items": list(v.outcome.items),
             "total": v.outcome.total, "reason": v.outcome.reason}
            for v in verdicts
        ],
        "points": points,
    }


def exit_code(verdicts):
    return 1 if any(v.outcome.status == "fail" for v in verdicts) else 0
