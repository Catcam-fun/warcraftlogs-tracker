"""The list of checks, in run order. Each entry is (name, family, check function)."""

from checks import (rules_counting, rules_defensives, rules_labels, rules_slots, rules_verdicts, source_deaths,
                    source_durations, source_mitigation, source_participation, source_selection, source_state)

CHECKS = [
    ("deaths", "source", source_deaths.check),
    ("selection", "source", source_selection.check),
    ("participation", "source", source_participation.check),
    ("state", "source", source_state.check),
    ("durations", "source", source_durations.check),
    ("mitigation", "source", source_mitigation.check),
    ("slots", "rules", rules_slots.check),
    ("counting", "rules", rules_counting.check),
    ("labels", "rules", rules_labels.check),
    ("verdicts", "rules", rules_verdicts.check),
    ("defensives", "rules", rules_defensives.check),
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
