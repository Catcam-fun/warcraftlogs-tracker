"""Rules check: the CombatantInfo talent format still matches the catalog."""
from checks.verdict import PASS, fail, skip


def check(run):
    """Talent entry IDs in the log match the catalog"""
    if not run.pulls:
        return skip(f"no Mythic pulls of {run.raid} in {run.code}")
    loadouts = [c for p in run.pulls for c in run.combatants(run.code, p["id"])]
    if not loadouts:
        return skip("no talent loadouts in the log")
    entries = {e for d in run.cat.all.values() for e in d["talent_entries"]}
    for c in loadouts:
        if {t["id"] for t in c.get("talentTree") or []} & entries:
            return PASS
    return fail(["no loadout contains a catalog talent entry: the CombatantInfo talentTree format may have changed"])
