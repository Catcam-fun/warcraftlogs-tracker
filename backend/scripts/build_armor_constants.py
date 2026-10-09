"""Regenerate backend/armor_constants.py from real boss pulls on WarcraftLogs.

Armor reduces physical damage by armor / (armor + K). K depends on the
attacker's level and on the season's tuning of each boss (game data:
ExpectedStat.ArmorConstant x the boss's ExpectedStatMod), which the client
data doesn't link to bosses, so it's measured here instead, per boss and
difficulty, from the logs:

  - A boss's melee swing is always reduced by armor; a magic hit never is.
  - Both are reduced alike by everything else (Versatility, damage-reduction
    buffs), so for the same player with the same auras up, their ratio is
    armor's share alone: keep = K / (armor + K), and every hit carries the
    player's armor at that moment.

The median over the top-ranked Mythic, Heroic and Normal kills of each boss
is stored. Checked against the game data on Midnight Season 1 (base 3430 at
level 93 x the season's modifier, 4,050 to 4,320; measured the same).
Used for Bear Form: how much more a druid's own armor, raised 220%, would
have reduced a physical killing blow.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/build_armor_constants.py

Rerun when a new raid comes out (it reads the bosses from analysis.RAID_ENCOUNTERS).
"""
import os
import pprint
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from analysis import RAID_ENCOUNTERS  # noqa: E402
from warcraftlogs import get_access_token, graphql_query  # noqa: E402

DIFFICULTIES = (5, 4, 3)          # Mythic, Heroic, Normal
REPORTS_PER_BOSS = 5
MIN_SAMPLES = 10                  # fewer pairs than this: the boss uses its raid's value
MELEE = 1
PHYSICAL = 1
NORMAL_HIT, CRIT = 1, 2
SPELL_SAMPLES = 5                 # hits needed to say whether armor reduces a physical spell
IGNORES_ARMOR_SHARE = 0.97        # armor let through at least this share: it ignores armor
REDUCED_SHARE = 0.9               # at most this: armor reduces it


def _events(token, code, fight):
    # With fightIDs, WCL needs an endTime or it returns an empty second page.
    bounds = graphql_query(token, """query($c: String!, $f: [Int]) { reportData { report(code: $c) {
        fights(fightIDs: $f) { startTime endTime } } } }""", {"c": code, "f": [fight]})
    end = bounds["reportData"]["report"]["fights"][0]["endTime"]
    out, start = [], None
    for _ in range(40):
        data = graphql_query(token, """query($c: String!, $f: [Int], $s: Float, $e: Float) { reportData { report(code: $c) {
            events(fightIDs: $f, startTime: $s, endTime: $e, dataType: DamageTaken, includeResources: true, limit: 10000)
            { data nextPageTimestamp } } } }""", {"c": code, "f": [fight], "s": start, "e": end})
        block = data["reportData"]["report"]["events"]
        out += block["data"] or []
        start = block.get("nextPageTimestamp")
        if not start:
            return out
    return out


def _schools(token, code):
    data = graphql_query(token, """query($c: String!) { reportData { report(code: $c) {
        masterData { abilities { gameID type } } } } }""", {"c": code})
    return {a["gameID"]: int(a["type"] or 0) for a in data["reportData"]["report"]["masterData"]["abilities"]}


def measure(token, code, fight, spells=None):
    """K from one pull: melee swings against magic hits on the same player with the same auras.

    `spells`: a dict that collects, per physical boss spell other than melee,
    the share of each hit armor let through, to tell which spells armor
    reduces at all.
    """
    schools = _schools(token, code)
    groups = {}
    for e in _events(token, code, fight):
        if e.get("resourceActor") != 2 or not e.get("unmitigatedAmount") or e.get("tick") \
                or e.get("hitType") not in (NORMAL_HIT, CRIT) or e.get("blocked"):
            continue
        spell = e["abilityGameID"]
        mask = schools.get(spell, 0)
        kind = "melee" if spell == MELEE else "physical" if mask == PHYSICAL else "magic" if mask and not mask & PHYSICAL else None
        if kind is None:
            continue
        keep = (e.get("amount", 0) + e.get("absorbed", 0) + e.get("overkill", 0)) / e["unmitigatedAmount"]
        groups.setdefault((e["targetID"], e.get("buffs")), []).append((kind, keep, e.get("armor") or 0, spell))
    found = []
    for hits in groups.values():
        magic = [k for kind, k, _, _ in hits if kind == "magic"]
        # Two or more magic hits that agree: nothing hit-specific (a partial absorb) skews them.
        if len(magic) < 2 or max(magic) - min(magic) > 0.02:
            continue
        base = statistics.median(magic)
        for kind, k, armor, spell in hits:
            if kind == "magic" or not armor:
                continue
            share = k / base
            if kind == "physical":
                if spells is not None and 0.05 < share < 1.05:
                    spells.setdefault(spell, []).append(share)
            elif 0.05 < share < 0.99:
                found.append(armor * share / (1 - share))
    return found


def main():
    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    out, spells = {}, {}
    for difficulty in DIFFICULTIES:
        per_boss = {}
        for raid, encounters in RAID_ENCOUNTERS.items():
            for enc in sorted(encounters):
                if enc in per_boss:
                    continue
                data = graphql_query(token, """query($e: Int!, $d: Int) { worldData { encounter(id: $e) {
                    fightRankings(difficulty: $d) } } }""", {"e": enc, "d": difficulty})
                ranks = (((data.get("worldData") or {}).get("encounter") or {}).get("fightRankings") or {}).get("rankings") or []
                samples = []
                for r in ranks[:REPORTS_PER_BOSS]:
                    try:
                        samples += measure(token, r["report"]["code"], r["report"]["fightID"], spells)
                    except Exception as ex:        # private or deleted report
                        print(f"  skip {r['report']['code']}: {str(ex)[:80]}")
                per_boss[enc] = samples
                print(f"difficulty {difficulty} boss {enc}: {len(samples)} pairs"
                      + (f", K {statistics.median(samples):.0f}" if samples else ""), flush=True)
        table = {}
        for raid, encounters in RAID_ENCOUNTERS.items():
            pooled = [k for enc in encounters for k in per_boss.get(enc, ())]
            for enc in encounters:
                own = per_boss.get(enc, ())
                pick = own if len(own) >= MIN_SAMPLES else pooled
                if len(pick) >= MIN_SAMPLES:
                    table.setdefault(enc, round(statistics.median(pick)))
        out[difficulty] = dict(sorted(table.items()))
    # A physical spell whose hits armor let through whole ignores armor; one it
    # reduced like a melee swing doesn't. Too few hits, or in between: not listed.
    ignores, reduced = [], []
    for spell, shares in spells.items():
        if len(shares) < SPELL_SAMPLES:
            continue
        mid = statistics.median(shares)
        if mid >= IGNORES_ARMOR_SHARE:
            ignores.append(spell)
        elif mid <= REDUCED_SHARE:
            reduced.append(spell)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "armor_constants.py")
    with open(path, "w", newline="\n") as f:
        f.write('"""GENERATED by scripts/build_armor_constants.py from real boss pulls. Do not edit by hand.\n\n'
                'Armor constant K per boss (encounter ID), by difficulty (5 Mythic, 4 Heroic, 3 Normal):\n'
                'armor reduces physical damage by armor / (armor + K)."""\n\n')
        f.write("ARMOR_K = " + pprint.pformat(out, width=110) + "\n\n")
        f.write("# Physical boss spells measured to ignore armor, and to be reduced by it (melee swings always are).\n")
        f.write("IGNORES_ARMOR = " + pprint.pformat(sorted(ignores), width=110, compact=True) + "\n")
        f.write("REDUCED_BY_ARMOR = " + pprint.pformat(sorted(reduced), width=110, compact=True) + "\n")
    print(f"Wrote {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
