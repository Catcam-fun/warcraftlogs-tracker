"""The list of checks, in run order. Each entry is (name, family, check function)."""

from checks import rules_counting, rules_defensives, rules_slots, rules_verdicts, source_deaths, source_durations, source_mitigation

CHECKS = [
    ("deaths", "source", source_deaths.check),
    ("durations", "source", source_durations.check),
    ("mitigation", "source", source_mitigation.check),
    ("defensives", "rules", rules_defensives.check),
    ("slots", "rules", rules_slots.check),
    ("counting", "rules", rules_counting.check),
    ("verdicts", "rules", rules_verdicts.check),
]


def rule_of(check):
    doc = (check.__doc__ or "").strip()
    return doc.splitlines()[0].strip() if doc else ""


def select(what):
    if what == "all":
        return list(CHECKS)
    if what in ("source", "rules"):
        return [c for c in CHECKS if c[1] == what]
    named = [c for c in CHECKS if c[0] == what]
    if not named:
        raise ValueError(f"unknown check: {what}")
    return named
