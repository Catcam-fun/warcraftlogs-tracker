# WCL Validation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four `backend/scripts/check_*.py` scripts with one `backend/checks` package that runs the real analysis end to end and checks what the site shows against WarcraftLogs (source checks) and against the owner's rules (rules checks), then sweep every raid key with parallel subagents.

**Architecture:** `python -m checks <subcommand> <target> ...` from `backend/`. A `Run` object holds one report's data, lazy cached WCL fetchers and the real `/api/analyze` result (Flask test client). Each check is one function `check(run) -> Outcome` in its own module, listed in a registry; the runner prints one verdict line per check, points spent, and exits 1 on any fail.

**Tech Stack:** Python 3.12 (`backend\.venv\Scripts\python.exe`), `unittest`, Flask test client, the existing `warcraftlogs.py` GraphQL helpers. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-07-wcl-validation-harness-design.md`

## Global Constraints

- Run every Python command from `backend/` with `..\backend\.venv\Scripts\python.exe` (write it as `python` below). Tests: `python -m unittest test_checks -v`.
- Keys come from the environment: `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET`. Unit tests never reach WCL or Supabase; mock `graphql_query`, `get_fights`, `get_report_fights`, `get_guild_reports`, `get_guild_roster`.
- Mythic only: difficulty `5` everywhere a difficulty is passed.
- Rules checks recompute with fresh code in their own module. They may import constants from `raid_wide_damage`, `boss_spell_flags` and the catalog, never `analysis.rank_pull_deaths`, `analysis._in_mass_window` or anything from `defensives` except `catalog_for`, `_talented_cooldown`, `_talented_charges`, `fetch_combatants`, `SPEC_NAMES`.
- Target syntax: `<reportCode>:<raidKey>` or `<reportCode>:<raidKey>:<GuildName>/<ServerName>/<REGION>`. `raidKey` must be a key of `analysis.RAID_ENCOUNTERS`.
- Numbers pinned by the spec: reaction `1000` ms, lethal window `15000` ms, high health `0.85`, one-shot `0.80`, set-up hit `0.10`, rot `3` hits / `0.6` share / `0.35` max hit, wipe `8` real deaths in `8000` ms, health tolerance `1 %` of max HP, aura band tolerance `100` ms, Deaths table cap `200` entries, mismatches printed `10`.
- Commit messages are plain sentences in the project's style (no `feat:` prefixes) and end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Never edit `docs/atlas/build/` or `docs/atlas/agent-index.md` by hand; run `node docs/atlas/scripts/build-atlas.mjs` from the repo root.
- Work on branch `feat/wcl-checks` (exists). Never push to `main`; the owner previews before merge.

## Review Focus

1. A target whose report has no Mythic pull of that raid: every check must `skip` with "no Mythic pulls of <raid> in <code>", not crash. Test in Task 2.
2. Player names with accents (`Ñanda`) must match between the result, WCL composition and the roster: compare after `normalize_character_name` and lowercase. Test in Task 10.
3. A player who dies, is rezzed and dies again in one pull: `state` and `labels` must pick that death's own killing blow, not the first death's. Test in Task 11.
4. A counted death whose killing blow is an instant kill (`survival.deathType == "instakill"`): `labels` and the health part of `state` skip that death; `verdicts` requires every `wouldSave` false. Test in Task 8 (property 5).
5. A week with two logs of the same night (duplicate pulls): `selection` must accept whichever copy the site kept, as long as exactly one copy per cluster is kept. Test in Task 9.

---

### Task 1: Package skeleton, Outcome/Verdict, registry, runner

**Files:**
- Create: `backend/checks/__init__.py` (empty), `backend/checks/verdict.py`, `backend/checks/registry.py`, `backend/checks/__main__.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- Produces, in `verdict.py`:
  ```python
  MAX_ITEMS = 10
  @dataclass
  class Outcome:
      status: str                 # "pass" | "fail" | "skip"
      items: list = field(default_factory=list)   # first MAX_ITEMS mismatches, strings
      total: int = 0              # mismatches found in all
      reason: str = ""            # for skip, or a fail with no items
  PASS = Outcome("pass")
  def fail(items: list[str], reason: str = "") -> Outcome   # total = len(items), items truncated
  def skip(reason: str) -> Outcome
  @dataclass
  class Verdict:
      name: str; family: str; rule: str; outcome: Outcome
  def format_lines(verdicts: list[Verdict], points: float | None) -> str
  def to_json(verdicts: list[Verdict], points: float | None) -> dict
  def exit_code(verdicts: list[Verdict]) -> int        # 1 if any "fail"
  ```
- Produces, in `registry.py`:
  ```python
  CHECKS: list[tuple[str, str, Callable]]     # (name, family, check function), run order
  def rule_of(check) -> str                   # first line of check.__doc__
  def select(what: str) -> list[tuple[str, str, Callable]]   # "all", "source", "rules" or one name; unknown -> ValueError
  ```
- Produces, in `__main__.py`: `main(argv: list[str]) -> int`; `run_target(token, target, checks) -> list[Verdict]` wrapping each check in try/except so an exception becomes `fail([], reason=f"{type(e).__name__}: {e}")`.
- Printing format (exact):
  ```
  source  deaths          pass  Deaths the site reads match WCL's Deaths table
  rules   slots           FAIL  Slots and wipes follow the owner's rules  (3 mismatches)
          pull 37 Bob 10973127: site slot 4, rule slot 5
  source  state           skip  Active, ready and health at death match WCL  (no counted death in this log)
  points spent: 212
  ```
  Columns: family padded to 7, name padded to 15, status `pass` / `FAIL` / `skip` padded to 5, then the rule. Items indented 8 spaces. `points spent: unknown` when `points` is None.

- [ ] **Step 1: Write the failing tests** in `backend/test_checks.py`

```python
class VerdictTests(unittest.TestCase):
    def test_fail_keeps_ten_items_and_counts_all(self):
        o = fail([f"m{i}" for i in range(13)])
        self.assertEqual((o.status, len(o.items), o.total), ("fail", 10, 13))

    def test_format_lines_and_exit_code(self):
        vs = [Verdict("deaths", "source", "Deaths match", PASS),
              Verdict("slots", "rules", "Slots follow rules", fail(["pull 37 Bob: site 4, rule 5"])),
              Verdict("state", "source", "State matches", skip("no counted death"))]
        text = format_lines(vs, 212.0)
        self.assertIn("source  deaths          pass  Deaths match", text)
        self.assertIn("rules   slots           FAIL  Slots follow rules  (1 mismatches)", text)
        self.assertIn("        pull 37 Bob: site 4, rule 5", text)
        self.assertIn("source  state           skip  State matches  (no counted death)", text)
        self.assertTrue(text.endswith("points spent: 212\n"))
        self.assertEqual(exit_code(vs), 1)
        self.assertEqual(exit_code([vs[0], vs[2]]), 0)

class RegistryTests(unittest.TestCase):
    def test_select_families_and_unknown(self):
        self.assertEqual(select("all"), CHECKS)
        self.assertTrue(all(f == "rules" for _, f, _ in select("rules")))
        with self.assertRaises(ValueError):
            select("nope")

class RunnerTests(unittest.TestCase):
    def test_exception_in_a_check_is_a_fail_not_a_crash(self):
        def boom(run):
            """Always explodes"""
            raise RuntimeError("wcl down")
        vs = run_target("t", object(), [("boom", "source", boom)])
        self.assertEqual(vs[0].outcome.status, "fail")
        self.assertIn("RuntimeError: wcl down", vs[0].outcome.reason)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest test_checks -v`
Expected: ImportError on `checks.verdict`.

- [ ] **Step 3: Implement `verdict.py`, `registry.py` (with `CHECKS = []` for now) and `__main__.py`**

`__main__.py`: `main(argv)` parses `argv[0]` as the subcommand (`all`, `source`, `rules`, a check name, or `find-logs`), the rest as targets, plus `--json PATH`. For each target: `token = get_access_token(...)` once, `run = Run(token, parse_target(t))` (Task 2), `before = points(token)`, verdicts, `after = points(token)`, print `format_lines(verdicts, after - before if both else None)`. With `--json`, write `{"targets": [{"target": t, "verdicts": [...], "points": p}]}`. Return `exit_code` over all verdicts. `find-logs` dispatches to `checks.find_logs.main(raid_keys)` (Task 12). `if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_checks -v`
Expected: all three classes PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/checks backend/test_checks.py
git commit -m "Checks package: verdicts, registry and runner skeleton"
```

---

### Task 2: `common.py`: targets, Run, fetchers, points, the real analysis

**Files:**
- Create: `backend/checks/common.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Target:
      code: str; raid: str; guild: tuple[str, str, str] | None   # (name, server, region)
  def parse_target(s: str) -> Target        # SystemExit(f"Unknown raid key {raid}; one of: ...") on a bad key
  def raid_week(start_ms: int) -> tuple[str, str]   # ("YYYY-MM-DD", "YYYY-MM-DD"): the Tuesday (UTC) on or before start_ms, and that Tuesday + 7 days
  def points(token) -> float | None          # rateLimitData.pointsSpentThisHour; None on any exception
  class TableCapped(Exception): pass          # args: (rid, fid)
  class AnalysisError(Exception): pass        # args: (error text,)
  class Run:
      def __init__(self, token, target: Target): ...
      token, code, raid
      meta -> dict                  # get_fights(token, code), cached
      def meta_for(rid) -> dict     # get_fights per report, cached; meta == meta_for(code)
      pulls -> list[dict]           # analysis.analyze_fights(meta["fights"], None, 5, raid)
      cat                           # defensives.catalog_for(meta["report_start"])
      guild -> tuple | None         # target.guild, else report.guild from WCL (name, server.name, region.slug upper), else None
      result -> dict                # run_analysis(...) on first use; raises AnalysisError
      def actor_id(rid, name) -> int | None     # friendly whose normalized name matches, case-insensitive
      def fight(rid, fid) -> dict               # the fight dict from meta_for(rid)
      def deaths_table(rid, fid) -> list[dict]  # table(dataType: Deaths, fightIDs:[fid]).data.entries; raises TableCapped when len >= 200
      def summary(rid, fid) -> dict             # table(dataType: Summary, fightIDs:[fid]).data
      def buffs(rid, fid, pid) -> list[dict]    # table(dataType: Buffs, fightIDs:[fid], targetID: pid).data.auras
      def casts(rid, pid, start, end) -> list[dict]   # events(dataType: Casts, sourceID: pid, startTime, endTime) all pages via nextPageTimestamp
      def hits_before(rid, fid, pid, death_ts) -> list[dict]   # events(dataType: DamageTaken, fightIDs:[fid], targetID: pid, startTime: death_ts-15000, endTime: death_ts+50)
      def combatants(rid, fid) -> list[dict]    # defensives.fetch_combatants(token, rid, [fid], fight start, fight end)
      def counted_deaths() -> list[dict]        # every event in result["events"].values() with slot <= result["meta"]["maxCutoff"], not inWipe, not isCheatDeath
  def run_analysis(token_unused, target: Target, start: str, end: str) -> dict
  ```
  `run_analysis` posts to `/api/analyze` via `app.test_client()` with `{"clientId": os.environ["WCL_CLIENT_ID"], "clientSecret": os.environ["WCL_CLIENT_SECRET"], "guildName", "server", "region", "fightZone": 0, "selectedRaid": raid, "difficulty": 5, "maxCutoff": 10, "rosterOnly": True, "enableCheatDeath": False, "startDate": start, "endDate": end}`, splits the body on blank lines, returns the `result` of the line containing `"result"`, raises `AnalysisError(text)` on an `error` line or when no result line exists. `Run.result` raises `AnalysisError("no guild for this report; pass code:raid:Guild/Server/REGION")` when `guild` is None.
- All fetchers go through `warcraftlogs.graphql_query(token, query, variables)` and cache by their arguments. The three `table(...)` queries use the GraphQL alias `t` (`t: table(dataType: Deaths, fightIDs: $f)`), which the tests rely on.
- Module-level imports in `common.py`, so tests can patch them there: `import app`, `import analysis`, `import defensives`, `from warcraftlogs import get_access_token, get_fights, get_report_fights, get_guild_reports, get_guild_roster, graphql_query, normalize_character_name`.

- [ ] **Step 1: Write the failing tests**

```python
class TargetTests(unittest.TestCase):
    def test_parse_target_forms(self):
        t = parse_target("ABC123:manaforge")
        self.assertEqual((t.code, t.raid, t.guild), ("ABC123", "manaforge", None))
        t = parse_target("ABC123:nerubar:Big Guild/Area 52/US")
        self.assertEqual(t.guild, ("Big Guild", "Area 52", "US"))
        with self.assertRaises(SystemExit):
            parse_target("ABC123:not-a-raid")

    def test_raid_week_is_the_tuesday_on_or_before(self):
        # 2026-10-01T00:00Z is a Thursday -> week starts Tuesday 2026-09-29
        self.assertEqual(raid_week(1790812800000), ("2026-09-29", "2026-10-06"))
        self.assertEqual(raid_week(1790640000000), ("2026-09-29", "2026-10-06"))   # the Tuesday itself

class RunTests(unittest.TestCase):
    def test_no_mythic_pulls_gives_empty_pulls(self):
        with mock.patch("checks.common.get_fights", return_value={"report_start": 0, "fights": [
                {"id": 1, "start_time": 0, "end_time": 1, "boss": 3129, "difficulty": 4, "kill": False, "zoneID": 44}],
                "friendlies": [], "player_details": {}, "abilities": {}, "ability_schools": {}}):
            run = Run("t", parse_target("X:manaforge"))
            self.assertEqual(run.pulls, [])

    def test_deaths_table_cap_raises(self):
        with mock.patch("checks.common.graphql_query", return_value={"reportData": {"report": {"t": {"data": {"entries": [{}] * 200}}}}}):
            run = Run("t", parse_target("X:manaforge"))
            with self.assertRaises(TableCapped):
                run.deaths_table("X", 5)

    def test_points_is_none_on_error(self):
        with mock.patch("checks.common.graphql_query", side_effect=Exception("down")):
            self.assertIsNone(points("t"))

    def test_run_analysis_returns_result_or_raises(self):
        body = 'data: {"stage": "x", "message": "m"}\n\ndata: {"result": {"events": {}}}\n\n'
        fake = mock.Mock(); fake.post.return_value.get_data.return_value = body
        with mock.patch("checks.common.app.test_client", return_value=fake), \
             mock.patch.dict(os.environ, {"WCL_CLIENT_ID": "a", "WCL_CLIENT_SECRET": "b"}):
            self.assertEqual(run_analysis("t", parse_target("X:manaforge:G/S/US"), "2026-09-29", "2026-10-06"), {"events": {}})
            fake.post.return_value.get_data.return_value = 'data: {"error": "No reports found"}\n\n'
            with self.assertRaises(AnalysisError):
                run_analysis("t", parse_target("X:manaforge:G/S/US"), "2026-09-29", "2026-10-06")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest test_checks.TargetTests test_checks.RunTests -v`
Expected: ImportError on `checks.common`.

- [ ] **Step 3: Implement `common.py`** per the Interfaces block. `raid_week` works in UTC with `datetime.fromtimestamp(ms / 1000, timezone.utc)` and `weekday() == 1` for Tuesday. Guild from WCL: query `reportData.report(code) { guild { name server { name region { slug } } } }`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_checks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/checks/common.py backend/test_checks.py
git commit -m "Checks: targets, the shared Run, WCL fetchers and the in-process analysis"
```

---

### Task 3: Move `deaths` in; delete `check_deaths.py`

**Files:**
- Create: `backend/checks/source_deaths.py`
- Delete: `backend/scripts/check_deaths.py`
- Modify: `backend/checks/registry.py` (add `("deaths", "source", source_deaths.check)`)
- Test: `backend/test_checks.py`

**Interfaces:**
- `source_deaths.check(run) -> Outcome`. Docstring line: `Deaths the site reads match WCL's Deaths table`.
- Uses `analysis.get_report_deaths_bulk(run.token, run.code, run.pulls, run.meta["friendlies"], run.meta["abilities"])` for "ours" and `run.deaths_table(run.code, fid)` per pull for "theirs"; keys `(fid, targetID, timestamp)`; value the killing-blow name (`abilityName` vs `killingBlow.name`, `"Unknown"` when absent). Item strings: `missing (fid, pid, ts)`, `extra (fid, pid, ts)`, `killing blow (fid, pid, ts): site X, wcl Y`. `skip("no Mythic pulls of <raid> in <code>")` when `run.pulls` is empty; `skip(f"pull {fid} has 200+ deaths; WCL's table is capped")` on `TableCapped`.

- [ ] **Step 1: Write the failing test**

```python
class DeathsCheckTests(unittest.TestCase):
    def _run(self, theirs):
        run = mock.Mock(); run.code, run.raid = "X", "manaforge"
        run.pulls = [{"id": 1, "start_time": 0, "end_time": 9}]
        run.meta = {"friendlies": [], "abilities": {}}
        run.deaths_table.return_value = theirs
        return run

    def test_pass_fail_and_skip(self):
        ours = {1: [{"targetID": 7, "timestamp": 100, "abilityName": "Zap"}]}
        with mock.patch("checks.source_deaths.get_report_deaths_bulk", return_value=ours):
            same = [{"fight": 1, "id": 7, "timestamp": 100, "killingBlow": {"name": "Zap"}}]
            self.assertEqual(source_deaths.check(self._run(same)).status, "pass")
            other = [{"fight": 1, "id": 7, "timestamp": 100, "killingBlow": {"name": "Pow"}}, {"fight": 1, "id": 8, "timestamp": 200}]
            o = source_deaths.check(self._run(other))
            self.assertEqual((o.status, o.total), ("fail", 2))
        run = self._run([]); run.pulls = []
        self.assertEqual(source_deaths.check(run).status, "skip")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest test_checks.DeathsCheckTests -v`
Expected: ImportError.

- [ ] **Step 3: Implement `source_deaths.py`**, register it, `git rm backend/scripts/check_deaths.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_checks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A backend/checks backend/scripts backend/test_checks.py
git commit -m "Checks: deaths check moved into the package; check_deaths.py removed"
```

---

### Task 4: Move `durations`, `mitigation` and `defensives` in; delete the other three scripts

**Files:**
- Create: `backend/checks/source_durations.py`, `backend/checks/source_mitigation.py`, `backend/checks/rules_defensives.py`
- Delete: `backend/scripts/check_durations.py`, `backend/scripts/check_mitigation.py`, `backend/scripts/check_defensives.py`
- Modify: `backend/checks/registry.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- `source_durations.check(run) -> Outcome`. Docstring: `Defensive durations (catalog + talents) match real aura uses`. Body is today's `check_durations.main` loop for one report, using `run.pulls`, `run.cat`, `run.meta`; keep `TOLERANCE_MS`, `PANDEMIC`, `NOT_THE_BUTTON`, `EXTENDED_BY`, `carried_over` unchanged. `fail` items: one per flagged defensive, `"<name>: <n> of <uses> uses longer than predicted, e.g. 12.3s vs 10.0s"`; flagged when `len(longer) > n // 10`. `skip` when `run.pulls` is empty.
- `source_mitigation.check(run) -> Outcome`. Docstring: `Catalog damage reductions match real hits with and without the defensive`. Today's `check_mitigation.main` over `[p["id"] for p in run.pulls]`; `fail` items for rows with `hits >= 20` and `abs(real - predicted) > 0.03`: `"<player> <defensive>: measured 0.31, catalog 0.40 over 57 hits"`.
- `rules_defensives.check(run) -> Outcome`. Docstring: `Talent entry IDs in the log match the catalog`. Reads `run.combatants(run.code, fid)` for each pull; `pass` when any loadout's talent entry IDs intersect `{e for d in run.cat.all.values() for e in d["talent_entries"]}`; `fail(["no loadout contains a catalog talent entry: the CombatantInfo talentTree format may have changed"])` otherwise; `skip` when there are no pulls or no loadouts.
- Registry order after this task: `deaths, durations, mitigation, defensives`.

- [ ] **Step 1: Write the failing test** (the moved logic is covered by live runs; pin the registry and the defensives verdict)

```python
class MovedChecksTests(unittest.TestCase):
    def test_registry_names(self):
        self.assertEqual([n for n, _, _ in CHECKS][:4], ["deaths", "durations", "mitigation", "defensives"])

    def test_defensives_check_reads_talent_entries(self):
        run = mock.Mock(); run.code = "X"; run.pulls = [{"id": 1, "start_time": 0, "end_time": 9}]
        run.cat.all = {1: {"talent_entries": [111]}}
        run.combatants.return_value = [{"talents": {111: 1}}]
        self.assertEqual(rules_defensives.check(run).status, "pass")
        run.combatants.return_value = [{"talents": {999: 1}}]
        self.assertEqual(rules_defensives.check(run).status, "fail")
```

Check `defensives._loadout`'s output shape before writing the check (`backend/defensives.py:209`); the test's `{"talents": {...}}` must match the key it uses.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest test_checks.MovedChecksTests -v`
Expected: FAIL (registry has one entry; ImportError on `rules_defensives`).

- [ ] **Step 3: Implement the three modules**, register them, `git rm` the three scripts.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_checks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A backend/checks backend/scripts backend/test_checks.py
git commit -m "Checks: durations, mitigation and defensives moved in; old scripts removed"
```

---

### Task 5: `slots` rules check

**Files:**
- Create: `backend/checks/rules_slots.py`
- Modify: `backend/checks/registry.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- ```python
  WIPE_DEATHS, WIPE_MS = 8, 8000
  def rank(deaths: list[tuple[int, int, bool]]) -> list[tuple[int, bool]]
      # deaths: (timestamp, player id, is cheat death) in combat-log order; returns (slot, in_wipe) per death
  def check(run) -> Outcome
  ```
  Docstring: `Slots and wipes follow the owner's rules`. The rule, restated in the module docstring: real deaths take slots 1, 2, 3... in log order, same-millisecond deaths one each, a rezzed player twice; a cheat death's slot is real deaths so far + 1 and never takes a real death's slot; a death is in a wipe when some 8000 ms stretch that starts or ends at a real death holds 8 or more real deaths and contains it.
- `check`: for each counted death and each other death event in `run.result["events"]` grouped by `(reportId, fightId)`: WCL entries from `run.deaths_table(rid, fid)` sorted by `(timestamp, log order)`; `rank` over `(e["timestamp"], e["id"], False)`; map the site's events to entries by `(actor_id(rid, originalCharacter), timestamp + fight start_time)`; item on a difference: `"pull <fid> <player> <ts>: site slot S inWipe W, rule slot S' inWipe W'"`, or `"pull <fid> <player> <ts>: not in WCL's Deaths table"`. `skip` when the result has no events; `TableCapped` → item `"pull <fid>: 200+ deaths, table capped"` and continue.

- [ ] **Step 1: Write the failing tests**

```python
class SlotsRuleTests(unittest.TestCase):
    def test_rank_clauses(self):
        d = lambda ts, who, cheat=False: (ts, who, cheat)
        self.assertEqual(rank([d(10, 1), d(20, 2, True), d(30, 3)]), [(1, False), (2, False), (2, False)])
        self.assertEqual(rank([d(10, 1), d(10, 2)]), [(1, False), (2, False)])
        self.assertEqual(rank([d(10, 1), d(50, 1)]), [(1, False), (2, False)])
        wipe = [d(1000, 0)] + [d(50000 + i, i + 1) for i in range(8)]
        self.assertEqual([w for _, w in rank(wipe)], [False] + [True] * 8)
        seven = [d(49999, 9, True)] + [d(50000 + i, i + 1) for i in range(7)]
        self.assertFalse(any(w for _, w in rank(seven)))
        before = [d(49999, 9, True)] + [d(50000 + i, i + 1) for i in range(8)]
        self.assertTrue(rank(before)[0][1])      # a cheat death just before a wipe's first death is inside it
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest test_checks.SlotsRuleTests -v`
Expected: ImportError.

- [ ] **Step 3: Implement `rules_slots.py`** and register as `("slots", "rules", ...)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest test_checks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/checks/rules_slots.py backend/checks/registry.py backend/test_checks.py
git commit -m "Checks: slots and wipes recomputed from WCL's Deaths table under the owner's rules"
```

---

### Task 6: `counting` rules check

**Files:**
- Create: `backend/checks/rules_counting.py`
- Modify: `backend/checks/registry.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- ```python
  def is_counted(ev: dict, x: int) -> bool          # mirror of frontend/src/deathCounting.js: ev["slot"] <= x and not ev["inWipe"]
  def counts(result: dict, x: int) -> dict[str, tuple[int, int]]   # player -> (real counted, cheat counted)
  def check(run) -> Outcome
  ```
  Docstring: `A death counts when slot <= X and not in a wipe; defensives exist exactly on deaths that can count`. `check`: for X in 1..`result["meta"]["maxCutoff"]`, `counts` must equal a direct recount from the events (second implementation inline: `sum(1 for ev in events if ev["slot"] <= x and not ev["inWipe"] and not ev["isCheatDeath"])`); and for every event, `"defensives" in ev` iff `is_counted(ev, maxCutoff) and not ev["isCheatDeath"]`. Items: `"<player> pull <fid> <ts>: defensives present but death cannot count"` / `"...: death can count but has no defensives"`. `skip` when no events.

- [ ] **Step 1: Write the failing tests**

```python
class CountingRuleTests(unittest.TestCase):
    def test_counts_and_defensive_presence(self):
        ev = lambda slot, wipe=False, cheat=False, d=True: {"slot": slot, "inWipe": wipe, "isCheatDeath": cheat,
                                                          "reportId": "R", "fightId": 1, "timestamp": slot, **({"defensives": {}} if d else {})}
        result = {"meta": {"maxCutoff": 2}, "events": {"Bob": [ev(1), ev(3, d=False)], "Amy": [ev(2, wipe=True, d=False)]}}
        self.assertEqual(counts(result, 2), {"Bob": (1, 0), "Amy": (0, 0)})
        run = mock.Mock(); run.result = result
        self.assertEqual(rules_counting.check(run).status, "pass")
        result["events"]["Amy"][0]["defensives"] = {}
        self.assertEqual(rules_counting.check(run).status, "fail")
```

- [ ] **Step 2: Run to verify it fails** — `python -m unittest test_checks.CountingRuleTests -v`, ImportError.

- [ ] **Step 3: Implement and register** `("counting", "rules", ...)`.

- [ ] **Step 4: Run tests** — `python -m unittest test_checks -v`, PASS.

- [ ] **Step 5: Commit** — `git commit -m "Checks: first-X counting and defensive presence follow the counting rule"`

---

### Task 7: `labels` rules check

**Files:**
- Create: `backend/checks/rules_labels.py`
- Modify: `backend/checks/registry.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- ```python
  HIGH, ONE_SHOT, SETUP, REACTION_MS = 0.85, 0.80, 0.10, 1000
  ROT_MIN_HITS, ROT_SHARE, ROT_MAX_HIT = 3, 0.6, 0.35
  def full_hit(h: dict) -> int                    # amount + overkill + absorbed
  def label(hits: list[dict], kb_index: int) -> dict
      # hits: DamageTaken events for one player, time order, each with amount, overkill, absorbed, hitPoints,
      # maxHitPoints, abilityGameID; kb_index: the killing blow. Returns
      # {"deathType": "oneShot" | "burst" | "wasLow", "rot": ability id | None, "biggestHit": ability id | None}
  def check(run) -> Outcome
  ```
  Docstring: `Death labels follow the rules: one-shot, burst, rot (raid-wide only) or set up by`. Rule restated in the module docstring, as in the spec's labels row, with: "last at high health" = the latest hit before the killing blow after which `hitPoints >= HIGH * maxHitPoints`, or the health before the killing blow (`hitPoints + amount` of the killing blow) if that is high; quick = that moment is within `REACTION_MS` of the killing blow; rot uses `RAID_WIDE` from `raid_wide_damage`.
- `check`: for each counted death with `survival` and `deathType != "instakill"`: `hits = run.hits_before(rid, fid, pid, death_abs_ts)`; the killing blow is the last hit with `overkill > 0` at or before `death_abs_ts + 50`; compare `label(...)` with `survival["deathType"]`, `survival.get("rot", {}).get("abilityId")`, `survival.get("biggestHit", {}).get("abilityId")`. Item: `"<player> pull <fid>: site <deathType>/<rot>/<biggest>, rule <...>"`. Skip the death (no item) when no hit has `overkill > 0`. `skip` the check when no counted death has a survival block.

- [ ] **Step 1: Write the failing tests**

```python
class LabelRuleTests(unittest.TestCase):
    def hit(self, ts, amount, hp_after, aid=1, overkill=0):
        return {"timestamp": ts, "amount": amount, "overkill": overkill, "absorbed": 0,
                "hitPoints": hp_after, "maxHitPoints": 1000, "abilityGameID": aid}

    def test_one_shot_burst_and_was_low(self):
        kb = self.hit(1000, 900, 0, overkill=50)                       # 950 of 1000 from full
        self.assertEqual(label([self.hit(0, 10, 990), kb], 1)["deathType"], "oneShot")
        burst = [self.hit(0, 10, 990), self.hit(500, 400, 590), self.hit(990, 590, 0, overkill=10)]
        self.assertEqual(label(burst, 2)["deathType"], "burst")
        slow = [self.hit(0, 10, 990), self.hit(500, 400, 590), self.hit(2000, 590, 0, overkill=10)]
        self.assertEqual(label(slow, 2), {"deathType": "wasLow", "rot": None, "biggestHit": 1})

    def test_rot_needs_a_raid_wide_ability(self):
        aid = next(iter(RAID_WIDE))
        hits = [self.hit(0, 10, 990)] + [self.hit(1000 * i, 200, 990 - 200 * i, aid=aid) for i in range(1, 5)] \
             + [self.hit(6000, 190, 0, aid=aid, overkill=10)]
        self.assertEqual(label(hits, 5)["rot"], aid)
        not_wide = [dict(h, abilityGameID=999_999) for h in hits]
        self.assertEqual(label(not_wide, 5)["rot"], None)

    def test_threshold_edges(self):
        # "quick" is measured from the last moment at high health (t=0 here) to the killing blow.
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(600, 790, 200), self.hit(1001, 200, 0, overkill=5)], 2)["deathType"], "wasLow")
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(600, 790, 200), self.hit(999, 200, 0, overkill=5)], 2)["deathType"], "burst")
        # One-shot needs a single hit of 80 % of max HP or more (800 of 1000); 799 is burst.
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(100, 190, 800), self.hit(500, 800, 0)], 2)["deathType"], "oneShot")
        self.assertEqual(label([self.hit(0, 10, 990), self.hit(100, 191, 799), self.hit(500, 799, 0)], 2)["deathType"], "burst")
```

- [ ] **Step 2: Run to verify they fail** — ImportError.

- [ ] **Step 3: Implement and register** `("labels", "rules", ...)`.

- [ ] **Step 4: Run tests** — PASS. If an edge test disagrees with your reading of the rule, the rule in the project instructions wins; write the test to it, not to `defensives.py`.

- [ ] **Step 5: Commit** — `git commit -m "Checks: death labels recomputed from WCL hits under the owner's rules"`

---

### Task 8: `verdicts` rules check

**Files:**
- Create: `backend/checks/rules_verdicts.py`
- Modify: `backend/checks/registry.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- `def violations(defensives: dict, cat) -> list[str]` and `def check(run) -> Outcome`. Docstring: `Would-save verdicts obey the press, overkill, immunity and instant-kill rules`. Properties, each an item string when broken, for `s = defensives["survival"]`:
  1. `det["pressAgo"] >= 1.0` for every `details` entry that has one: `"<name>: pressed 0.4s before the killing blow (rule: at least 1s)"`.
  2. names in `s["wouldSave"]` ⊆ `{a["name"] for a in defensives["available"]} ∪ {defensives[k]["name"] for k in ("healthstone", "potion") if defensives.get(k, {}).get("name")} ∪ set(s.get("consumables", {}))`, and disjoint from `{a["name"] for a in defensives["cooldown"]}`: `"<name>: judged but on cooldown"`.
  3. `s["wouldSave"][name] is True` iff `det["amount"] > s["overkill"]` and `"why" not in det`, for every name with a `details` entry whose verdict is not None: `"<name>: amount 12000 vs overkill 15000 but marked saves"`.
  4. `det["amount"] <= s["maxHp"]`: `"<name>: amount above max HP"`.
  5. `s["deathType"] == "instakill"` ⇒ every `wouldSave` value is False.
  6. `s["ignoresImmunity"]` ⇒ for every name whose catalog entry has a component with `immune`, `wouldSave[name]` is not True. Catalog lookup: `cat.all[cat.name_to_id[name]].get("mitigation") or []`.
- `check`: `violations` over every counted death that has `defensives` with a `survival`; `skip` when none.

- [ ] **Step 1: Write the failing tests**

```python
class VerdictRuleTests(unittest.TestCase):
    def base(self):
        return {"available": [{"name": "Barkskin"}], "cooldown": [{"name": "Survival Instincts"}],
                "healthstone": {"usedAgo": None}, "potion": {"usedAgo": None},
                "survival": {"deathType": "wasLow", "overkill": 100, "maxHp": 1000, "ignoresImmunity": False,
                             "wouldSave": {"Barkskin": True}, "details": {"Barkskin": {"amount": 150, "pressAgo": 1.2}}}}

    def test_each_property(self):
        cat = mock.Mock(); cat.name_to_id = {"Barkskin": 1}; cat.all = {1: {"mitigation": [{"dr": 0.2}]}}
        self.assertEqual(violations(self.base(), cat), [])
        d = self.base(); d["survival"]["details"]["Barkskin"]["pressAgo"] = 0.4
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["wouldSave"]["Survival Instincts"] = False
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["details"]["Barkskin"]["amount"] = 50
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["details"]["Barkskin"]["amount"] = 5000
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["deathType"] = "instakill"
        self.assertEqual(len(violations(d, cat)), 1)
        d = self.base(); d["survival"]["ignoresImmunity"] = True; cat.all[1]["mitigation"] = [{"immune": True}]
        self.assertEqual(len(violations(d, cat)), 1)
```

- [ ] **Step 2: Run to verify they fail** — ImportError.

- [ ] **Step 3: Implement and register** `("verdicts", "rules", ...)`.

- [ ] **Step 4: Run tests** — PASS.

- [ ] **Step 5: Commit** — `git commit -m "Checks: would-save verdicts checked against the press, overkill and immunity rules"`

---

### Task 9: `selection` source check

**Files:**
- Create: `backend/checks/source_selection.py`
- Modify: `backend/checks/registry.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- ```python
  def cluster(pulls: list[dict]) -> list[list[dict]]
      # pulls: {"key": "rid_fid", "boss": int, "name": str, "start": abs ms, "end": abs ms, "kill": bool}; same boss and
      # overlapping intervals (start <= other end and other start <= end) are one cluster; transitive
  def walk(run, start: str, end: str) -> list[dict]
      # get_guild_reports for run.guild over [start, end]; get_report_fights per report; keep fights with
      # boss in RAID_ENCOUNTERS[run.raid] and difficulty == 5; abs times = report_start + fight times
  def check(run) -> Outcome
  ```
  Docstring: `The pulls and kills the site kept match the guild's reports on WCL`. `check`: `kept = {key for players in run.result["bossParticipation"].values() for keys in players.values() for key in keys}`; clusters from `walk(run, *raid_week(run.meta["report_start"]))`; items: `"cluster <boss> <start iso>: no kept pull"`, `"cluster <boss> <start iso>: 2 kept pulls <keys>"`, `"kept pull <key>: not in any cluster"`, and per boss `"<boss name>: site kills K, wcl kills K'"` where a cluster is a kill when any copy is, and the site's kills are kept keys whose copy has `kill`. `skip` when `run.guild` is None.

- [ ] **Step 1: Write the failing tests**

```python
class SelectionTests(unittest.TestCase):
    def test_cluster_overlap_and_boss(self):
        p = lambda key, boss, s, e, kill=False: {"key": key, "boss": boss, "start": s, "end": e, "kill": kill}
        cs = cluster([p("A_1", 1, 0, 100), p("B_7", 1, 50, 120), p("A_2", 1, 200, 300), p("B_8", 2, 0, 100)])
        self.assertEqual(sorted(sorted(x["key"] for x in c) for c in cs), [["A_1", "B_7"], ["A_2"], ["B_8"]])

    def test_check_accepts_either_copy_and_flags_a_missing_one(self):
        pulls = [{"key": "A_1", "boss": 1, "start": 0, "end": 100, "kill": True},
                 {"key": "B_7", "boss": 1, "start": 50, "end": 120, "kill": True},
                 {"key": "A_2", "boss": 1, "start": 200, "end": 300, "kill": False}]
        run = mock.Mock(); run.guild = ("G", "S", "US"); run.meta = {"report_start": 0}
        run.result = {"bossParticipation": {"Boss": {"Bob": ["B_7", "A_2"]}}}
        with mock.patch("checks.source_selection.walk", return_value=pulls):
            self.assertEqual(source_selection.check(run).status, "pass")
            run.result = {"bossParticipation": {"Boss": {"Bob": ["B_7"]}}}
            self.assertEqual(source_selection.check(run).status, "fail")
```

- [ ] **Step 2: Run to verify they fail** — ImportError.

- [ ] **Step 3: Implement and register** `("selection", "source", ...)`. Item messages use `p.get("name", str(p["boss"]))`, since the test's pulls carry no name.

- [ ] **Step 4: Run tests** — PASS.

- [ ] **Step 5: Commit** — `git commit -m "Checks: kept pulls and kills compared with an independent walk of the guild's week"`

---

### Task 10: `participation` source check

**Files:**
- Create: `backend/checks/source_participation.py`
- Modify: `backend/checks/registry.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- ```python
  def norm(name: str) -> str       # normalize_character_name(name).lower()
  def site_players(result: dict) -> dict[str, set[str]]    # pull key -> {norm(player)} from result["pullParticipation"]
  def wcl_players(run, rid, fid, roster: set[str]) -> set[str]   # {norm(c["name"]) for c in run.summary(rid, fid)["composition"]}, ∩ roster when roster is non-empty
  def check(run) -> Outcome
  ```
  Docstring: `Who was in each kept pull, and who counts as roster, match WCL`. `roster = get_guild_roster(run.token, *run.guild)` once (already lowercase, normalized). Items: `"pull <key>: site has <names> that WCL lacks"`, `"pull <key>: WCL has <names> that the site lacks"`. `skip` when `run.guild` is None or `pullParticipation` is empty.

- [ ] **Step 1: Write the failing tests**

```python
class ParticipationTests(unittest.TestCase):
    def test_accents_and_roster(self):
        run = mock.Mock(); run.guild = ("G", "S", "US"); run.token = "t"
        run.result = {"pullParticipation": {"Ñanda": ["R_1"], "Bob": ["R_1"]}}
        run.summary.return_value = {"composition": [{"name": "Ñanda"}, {"name": "Bob"}, {"name": "Pug"}]}
        with mock.patch("checks.source_participation.get_guild_roster", return_value={"nanda", "bob"}):
            self.assertEqual(source_participation.check(run).status, "pass")
        with mock.patch("checks.source_participation.get_guild_roster", return_value=set()):
            o = source_participation.check(run)
            self.assertEqual(o.status, "fail"); self.assertIn("pug", o.items[0])
```

Confirm what `normalize_character_name("Ñanda")` returns before fixing the expected roster spelling.

- [ ] **Step 2: Run to verify it fails** — ImportError.

- [ ] **Step 3: Implement and register** `("participation", "source", ...)`.

- [ ] **Step 4: Run tests** — PASS.

- [ ] **Step 5: Commit** — `git commit -m "Checks: pull participation and roster compared with WCL's composition and members"`

---

### Task 11: `state` source check

**Files:**
- Create: `backend/checks/source_state.py`
- Modify: `backend/checks/registry.py`
- Test: `backend/test_checks.py`

**Interfaces:**
- ```python
  BAND_TOLERANCE_MS, HP_TOLERANCE = 100, 0.01
  def active_mismatches(active_names: list[str], auras: list[dict], death_ts: int) -> list[str]
      # a name is covered when an aura with that name has a band with startTime - 100 <= death_ts <= endTime + 100
  def ready_at(cast_times: list[int], death_ts: int, cooldown_ms: int, charges: int) -> bool
      # charges regained one per cooldown_ms after each use, counted from the casts at or before death_ts
  def entry_for(entries: list[dict], pid: int, death_ts: int) -> dict | None
      # the Deaths table entry with entry["id"] == pid and abs(entry["timestamp"] - death_ts) <= 50; never "first by name"
  def health_mismatch(survival: dict, entry: dict) -> str | None
      # entry: a Deaths table entry. hp_before = the entry's last event with type "damage" and overkill > 0: its amount.
      # mismatch when abs(hp_before - survival["hpBeforePct"] * survival["maxHp"] / 100) > 0.01 * maxHp,
      # or entry["overkill"] != survival["overkill"]
  def check(run) -> Outcome
  ```
  Docstring: `Active, ready and health at death match WCL's auras, casts and Deaths table`. For each counted death (`rid, fid, pid = run.actor_id(rid, ev["originalCharacter"])`, `death_ts = ev["timestamp"] + fight start_time`):
  - active: `active_mismatches([a["name"] for a in d["active"]], run.buffs(rid, fid, pid), death_ts)`.
  - ready / cooldown: for each name in `available` and `cooldown`: `entry = run.cat.all[run.cat.name_to_id[name]]`; talents from `run.combatants(rid, fid)` for this player and `spec = ev["spec"]`; `cd = defensives._talented_cooldown(entry, talents, spec)`, `charges = defensives._talented_charges(entry, talents, spec)`; casts from `run.casts(rid, pid, fight_start - cd * charges, death_ts)` with `abilityGameID == sid`; compare `ready_at(...)` with `name in available`. Item: `"<player> pull <fid> <name>: site ready, wcl casts say on cooldown"` and the reverse. Skip the name when the entry's `cooldown_ms >= 180000` and casts before the pull exist only before `fight_start` (encounter reset).
  - health: `health_mismatch(d["survival"], entry)` where `entry` is the Deaths table entry for `(pid, death_ts)`; skipped when `deathType == "instakill"` or no survival.
  - The Deaths table entry for a death is `entry_for(run.deaths_table(rid, fid), pid, death_ts)`; `TableCapped` adds the item `"pull <fid>: 200+ deaths, table capped"` and skips that pull's health part.
  `skip` when there is no counted death.

- [ ] **Step 1: Write the failing tests**

```python
class StateTests(unittest.TestCase):
    def test_active_bands(self):
        auras = [{"name": "Barkskin", "bands": [{"startTime": 1000, "endTime": 9000}]}]
        self.assertEqual(active_mismatches(["Barkskin"], auras, 5000), [])
        self.assertEqual(len(active_mismatches(["Barkskin"], auras, 9200)), 1)
        self.assertEqual(len(active_mismatches(["Ironbark"], auras, 5000)), 1)

    def test_ready_at_with_charges(self):
        self.assertTrue(ready_at([], 10_000, 60_000, 1))
        self.assertFalse(ready_at([5_000], 10_000, 60_000, 1))
        self.assertTrue(ready_at([5_000], 70_000, 60_000, 1))
        self.assertTrue(ready_at([5_000], 10_000, 60_000, 2))
        self.assertFalse(ready_at([5_000, 6_000], 10_000, 60_000, 2))

    def test_health_mismatch_uses_the_killing_event(self):
        s = {"hpBeforePct": 40, "maxHp": 1000, "overkill": 55}
        entry = {"overkill": 55, "events": [{"type": "damage", "amount": 300, "overkill": 0}, {"type": "damage", "amount": 405, "overkill": 55}]}
        self.assertIsNone(health_mismatch(s, entry))
        self.assertIsNotNone(health_mismatch(s, dict(entry, overkill=56)))
        self.assertIsNotNone(health_mismatch(dict(s, hpBeforePct=43), entry))

    def test_second_death_of_a_rezzed_player_matches_its_own_entry(self):
        entries = [{"id": 7, "timestamp": 1000, "overkill": 1, "events": []}, {"id": 7, "timestamp": 9000, "overkill": 2, "events": []}]
        self.assertEqual(entry_for(entries, 7, 9010)["overkill"], 2)
```

- [ ] **Step 2: Run to verify they fail** — ImportError.

- [ ] **Step 3: Implement and register** `("state", "source", ...)`. Final registry order: `deaths, selection, participation, state, durations, mitigation, slots, counting, labels, verdicts, defensives`.

- [ ] **Step 4: Run tests** — `python -m unittest test_checks -v`, PASS; also `python -m unittest` (whole backend suite) still passes.

- [ ] **Step 5: Commit** — `git commit -m "Checks: active, ready and health at death compared with WCL's auras, casts and Deaths table"`

---

### Task 12: `find-logs` and the README

**Files:**
- Create: `backend/checks/find_logs.py`, `backend/checks/README.md`
- Test: `backend/test_checks.py`

**Interfaces:**
- ```python
  MIN_WIPES, FINISHED_MS, REGIONS = 3, 2 * 3600 * 1000, ("US", "EU")
  def candidates(token, raid: str) -> list[dict]
      # fightRankings(difficulty: 5, page: 1) of min(RAID_ENCOUNTERS[raid]); each ranking ->
      # {"code", "guild": (guild.name, server.name, server.region), "region"}; REGIONS first, one per guild
  def good_log(token, raid: str, cand: dict, now_ms: int) -> str | None
      # get_report_fights(token, code); Mythic wipes of the raid >= MIN_WIPES and report_start + last fight end
      # < now_ms - FINISHED_MS -> "code:raid:Guild/Server/REGION", else None
  def main(raid_keys: list[str]) -> int     # all RAID_ENCOUNTERS keys when empty; prints one line per raid, or "<raid>: no log found"
  ```
- README sections: how to run (`cd backend`, the command, the target syntax, the keys), what each check holds the site to (the registry's rule lines), what passing looks like, what to do with a fail (site bug or check bug, show the owner), the points meter, and a table **Last known-good logs** with one row per raid key (filled by Task 13).

- [ ] **Step 1: Write the failing test**

```python
class FindLogsTests(unittest.TestCase):
    def test_good_log_needs_wipes_and_a_finished_report(self):
        light = {"report_start": 0, "fights": [{"id": i, "start_time": i * 10, "end_time": i * 10 + 5, "boss": 3129,
                                                "difficulty": 5, "kill": i == 3} for i in range(4)]}
        cand = {"code": "X", "guild": ("G", "S", "US")}
        with mock.patch("checks.find_logs.get_report_fights", return_value=light):
            self.assertEqual(good_log("t", "manaforge", cand, now_ms=10**12), "X:manaforge:G/S/US")
            self.assertIsNone(good_log("t", "manaforge", cand, now_ms=1000))
            light["fights"][0]["kill"] = light["fights"][1]["kill"] = True
            self.assertIsNone(good_log("t", "manaforge", cand, now_ms=10**12))
```

- [ ] **Step 2: Run to verify it fails** — ImportError.

- [ ] **Step 3: Implement `find_logs.py`**, wire `find-logs` in `__main__.py`, write the README.

- [ ] **Step 4: Run tests** — PASS. Then live: `python -m checks find-logs` (about 2 to 5 points per raid). Expected: eight lines `code:raid:Guild/Server/REGION`, or `no log found` for a raid, which is acceptable for retired tiers whose top logs are all kills; then try `page: 2`.

- [ ] **Step 5: Commit** — `git commit -m "Checks: find-logs picks one finished Mythic log per raid key; README"`

---

### Task 13: First live run, cost, known-good logs

**Files:**
- Modify: `backend/checks/README.md` (the logs table), any check that proves wrong on real data

- [ ] **Step 1: Run one raid end to end**: `python -m checks all <line from find-logs for midnight-s2-all> --json ..\scratch-midnight.json`. Expected: eleven verdict lines and `points spent: N`. Record N.

- [ ] **Step 2: Triage every fail.** For each: read the items, decide check bug vs site bug. Fix check bugs here (with a test in `test_checks.py` when the fix is logic). Site bugs are **not** fixed in this branch: write each as a finding (check, raid, items) in the final report to the owner.

- [ ] **Step 3: Run a second raid** (`manaforge`) the same way; confirm points per run is in the 100 to 300 range the spec expects. If it is above 600, cut `state` to the first 20 counted deaths (`STATE_MAX_DEATHS = 20`) and say so in the README.

- [ ] **Step 4: Fill the README's Last known-good logs table** with the two lines used and the points each cost.

- [ ] **Step 5: Commit** — `git commit -m "Checks: first live runs; known-good logs recorded"`

---

### Task 14: Atlas and rules

**Files:**
- Modify: `docs/atlas/domains/testing.md` (the two check tables, the `check` rows, the invariant naming `check_deaths.py`, the gotcha about Mythic-only), `docs/atlas/domains/operations.md:86` and `:103`, `docs/atlas/domains/warcraftlogs/index.md:136`
- Rebuild: `node docs/atlas/scripts/build-atlas.mjs`, then `node docs/atlas/scripts/verify-atlas.mjs`

- [ ] **Step 1: Update the three Markdown pages.** `testing.md`: replace the four `check_*.py` rows with one row per registered check (name, family, rule line, source file `backend/checks/<module>.py:<line of def check>`), the arguments table with the one command and target syntax, the invariant to "keep `python -m checks all` at zero fails on a Mythic log of every raid key after any change to fetching or to a rule", and add a gotcha: "the end-to-end run needs the report's guild; pass it in the target when WCL has none attached". `operations.md`: the real-log checks step names `python -m checks all <code>:<raid>` per raid key, and the env table's "Read by" names `backend/checks/common.py`. `warcraftlogs/index.md`: same env reference.

- [ ] **Step 2: Rebuild and verify.** Run from the repo root: `node docs/atlas/scripts/build-atlas.mjs && node docs/atlas/scripts/verify-atlas.mjs`. Expected: verify prints no errors.

- [ ] **Step 3: Run the whole backend suite**: `python -m unittest` from `backend/`. Expected: all pass.

- [ ] **Step 4: Commit** — `git add docs/atlas && git commit -m "Atlas: the checks package replaces the check_*.py scripts"`

- [ ] **Step 5: Draft the owner's rules-file edit** (not committed, not in the repo): in `C:\Users\gigga\Documents\Floorpov\CLAUDE.md` replace the four script names with the one command, point New Tier steps 4 and 9 at `python -m checks all <code>:<raid>` and `python -m checks mitigation ...`, change "3600/hour" to "9000/hour (measured 2026-10-07)". Show the diff to the owner and wait for a yes before saving.

---

### Task 15: The parallel sweep

**Files:** none in the repo; verdict JSONs in the scratchpad.

- [ ] **Step 1: Get the targets**: `python -m checks find-logs`, or the README's known-good lines. One line per raid key; eight in all.

- [ ] **Step 2: Wave one, four subagents at once** (`general-purpose`, background), one per raid key, each with this prompt and nothing else:

  > From `C:\Users\gigga\Documents\Floorpov\backend`, run `.venv\Scripts\python.exe -m checks all <TARGET> --json <SCRATCH>\<RAID>.json`. The environment already has WCL_CLIENT_ID and WCL_CLIENT_SECRET. Do not edit any file. Report back the complete stdout (every verdict line, every indented item, the points line) and, if the command failed, the full traceback. Do not interpret or fix anything.

- [ ] **Step 3: Read wave one's points.** Sum the four `points spent` values. If the sum is under 1200, run the remaining four at once; otherwise two at a time.

- [ ] **Step 4: Merge**: one table, raid keys as rows, the eleven checks as columns, cells `pass` / `FAIL (n)` / `skip`. Under it, every fail's items verbatim, grouped by check, each tagged "site" or "check" with one sentence of reasoning.

- [ ] **Step 5: Report to the owner**: the table, the findings, the total points, and the branch name. No fix is applied to site code in this branch; each site finding is proposed as its own follow-up.
