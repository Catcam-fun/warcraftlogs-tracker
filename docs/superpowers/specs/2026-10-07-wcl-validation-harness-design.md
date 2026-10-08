# WCL validation harness: design

Date: 2026-10-07. Status: approved in conversation, awaiting written review.

## Goal

A maintenance tool that proves two things about what floorpov.gg shows:

1. **Source:** what the site reads from WarcraftLogs (WCL) is what WCL has.
2. **Rules:** what the site shows follows the owner's rules (death slots,
   wipes, "first X" counting, death labels, would-save verdicts).

It replaces the four `backend/scripts/check_*.py` scripts with one package
and one command, runs the real analysis end to end, and is built so that
adding a check is cheap, because checks will keep being added as rules
change. It is run after a change to fetching or to a rule, after a new tier
or patch, and as a parallel sweep over every raid key. Nothing on the live
site calls it.

## Non-goals

- Validating data that does not come from WCL (boss spell text, icons,
  armor constants, the defensive catalog's numbers). Those have build-time
  checks of their own.
- Golden snapshots of result objects. Possible later complement; not here.
- Running in CI. It spends the owner's WCL points and needs the key.

## Shape

```
backend/checks/
  __init__.py
  __main__.py        # python -m checks <subcommand> ...
  common.py          # token, Run, points meter, in-process analysis
  registry.py        # ordered list of (name, family, function)
  verdict.py         # Verdict dataclass, printing, JSON
  source_deaths.py   # one module per check (names below)
  source_selection.py
  source_participation.py
  source_state.py
  source_durations.py
  source_mitigation.py
  rules_slots.py
  rules_counting.py
  rules_labels.py
  rules_verdicts.py
  rules_defensives.py
  find_logs.py
  README.md          # how to run, the last known-good log per raid key
backend/test_checks.py   # offline tests of the checks' own logic
```

`backend/scripts/check_deaths.py`, `check_durations.py`,
`check_mitigation.py` and `check_defensives.py` are deleted. `scripts/`
then holds only the `build_*.py` scripts.

### Command

Run from `backend/` with the venv's Python:

```
python -m checks all <reportCode>:<raidKey> [more ...] [--json PATH]
python -m checks source <reportCode>:<raidKey>      # one family
python -m checks rules  <reportCode>:<raidKey>
python -m checks deaths <reportCode>:<raidKey>      # one check
python -m checks find-logs [raidKey ...]            # one log per raid key
```

`WCL_CLIENT_ID` and `WCL_CLIENT_SECRET` come from the environment, as the
build scripts do today. `<raidKey>` is a `RAID_ENCOUNTERS` key; an unknown
key is a clear error, not a type error.

### A check is one function

```python
def check(run: Run) -> Verdict:
    """<one line: the rule or source this holds the site to>"""
```

`registry.py` lists every check in run order with its family (`source` or
`rules`). The docstring's first line is printed beside the verdict, so the
output of `all` reads as the list of expectations the site currently meets.
Adding a check is one module plus one registry line.

### Run

Built once per report and shared by every check:

- `token`, `code`, `raid`.
- `meta`: `get_fights` output (fights, friendlies, player_details,
  abilities, ability_schools) fetched once.
- `pulls`: the raid's Mythic pulls, `analyze_fights(meta["fights"], None, 5, raid)`.
- `cat`: `defensives.catalog_for(meta["report_start"])`.
- `result`: the real analysis result, built on first use (see below).
- `guild`: name, server slug, region, read from the report
  (`reportData.report.guild`).
- `points()`: `rateLimitData.pointsSpentThisHour`, read before and after the
  run; the difference is printed at the end.
- Lazy, cached fetchers the checks share: the Deaths table per pull (15 pulls
  per request, as `check_deaths.py` does today), the Summary table per pull,
  the Buffs table per (pull, player), Casts events per (pull, player) with
  the `sourceID` argument, the player's DamageTaken in the 15 s before each
  counted death with the `targetID` argument.

### The real analysis result

`common.run_analysis(run)` posts to `/api/analyze` through
`app.test_client()`, as `test_api.py` does, with: the owner's key, the
report's guild, `selectedRaid` = the raid key, `difficulty` 5, `rosterOnly`
true, `enableCheatDeath` false, `maxCutoff` 10, and `startDate`/`endDate`
set to the raid week holding the report (the Tuesday reset before the
report's start, to the next reset). It parses the SSE stream and keeps the
single `result` event. An `error` event fails every check that needs the
result, with the error text as the reason.

Mythic only, as the existing checks are. The result's `events`,
`pullParticipation` and `bossParticipation` are what the browser renders;
the frontend only filters them.

### Verdicts

`Verdict(name, family, rule, status, items, reason, points)` with status
`pass`, `fail` or `skip`. `items` is up to ten named mismatches (the check
counts the rest). Printing:

```
source  deaths         pass   Deaths the site reads match WCL's Deaths table
rules   slots          FAIL   Slots and wipes follow the owner's rules  (3 mismatches)
          pull 37 Bob 10973127: site slot 4, rule slot 5
source  state          skip   ... (no counted death in this log)
points spent: 212
```

`--json PATH` writes `[{name, family, rule, status, items, reason}]` plus
`points`. Exit code 1 if any check failed, else 0 (skips do not fail).

## The checks

### Source family

| name | compares | with | pass |
|---|---|---|---|
| `deaths` | every non-cheat death the site reads (player, pull, timestamp, killing-blow name) | WCL Deaths table per pull | 0 missing, 0 extra, 0 different killing blows |
| `selection` | the kept pull keys per boss in `result` (`bossParticipation` values, `reportId_fightId`) | an independent walk: `get_guild_reports` for the guild over the same week, light fights of each, the raid's Mythic pulls, clustered by absolute start time with a 5 s overlap rule written in the check | every kept pull key falls in exactly one cluster, every cluster holds exactly one kept key, and per boss the number of clusters with a kill equals the number of kept keys whose fight is a kill |
| `participation` | the players in each kept pull (`pullParticipation` inverted) | WCL Summary table `composition` per pull, intersected with WCL guild members (`guildData.guild.members`) | same set per pull; names compared after `normalize_character_name` |
| `state` | per counted death: `defensives.active` names; `available` vs `cooldown`; `survival.hpBeforePct * maxHp` and `survival.overkill` | Buffs table bands covering the death timestamp (names mapped through the catalog); a cooldown recompute from `sourceID` Casts using the catalog's cooldown and charges with the pull's talents (`_talented_cooldown`, `_talented_charges`); the Deaths table entry's killing-blow `amount - overkill` and `overkill` | every active name has a covering band; ready/cooldown agree; health before within 1% of max HP; overkill equal |
| `durations` | predicted aura length (catalog + talents) | real aura uses | no defensive with more than a tenth of uses LONGER (today's rule) |
| `mitigation` | catalog damage reduction | hits with and without the defensive up | no defensive with 20+ hits off by more than 0.03 (today's rule) |

`state` reads one Buffs table per (pull, player) with a counted death and
one Casts page per such pair, bounded by the counted deaths, so its cost
scales with deaths, not with the report.

### Rules family

Each module's docstring quotes the rule from the owner's instructions it
encodes. The recomputations are written fresh in the check, not imported
from `analysis.py` or `defensives.py`, so they can disagree with the site.

| name | rule | recomputed from | pass |
|---|---|---|---|
| `slots` | slot = which death of the pull; same-millisecond deaths take one slot each in log order; a rezzed player takes two; cheat deaths take no slot; any 8 s stretch with 8 real deaths is a wipe (windows start or end at a real death); nothing inside a wipe counts | WCL Deaths table per pull | every `events[]` entry's `slot` and `inWipe` equal the recompute |
| `counting` | a death counts when `slot <= X` and not `inWipe`; defensives exist on exactly the deaths that can count (slot within `maxCutoff`, not in a wipe, not a cheat death) | `result` only | for X in 1..10, a Python mirror of `frontend/src/deathCounting.js` gives the per-player counts the result implies; `defensives` present iff the death can count |
| `labels` | from the hits since the player was last at 85 %+: one-shot = under 1 s and one hit 80 %+ of max HP; burst = under 1 s, no such hit; rot = only a `RAID_WIDE` ability, 3+ small hits, most of the damage; else set up by the biggest hit of 10 %+ | DamageTaken events for the player in the 15 s before death, `targetID` argument | `survival.deathType`, `rot.name`, `biggestHit.name` agree |
| `verdicts` | a press is at least 1 s before the killing blow and never before the ability was ready; extra health counts only up to what was missing; "saves them" iff amount exceeds overkill; instant kills are never saveable; no immunity credited against an `IGNORES_IMMUNITY` spell | `result` plus the catalog | every `survival.details[*]` and `wouldSave` entry satisfies the properties |
| `defensives` | talent entry IDs in the log match the catalog | CombatantInfo in the report | `pass` when any loadout contains a catalog entry; `fail` with the "format changed" message otherwise |

### find-logs

For each raid key (all of them by default): take the raid's first encounter
ID, read `fightRankings(difficulty: 5, page: 1)`, and for the top guilds in
turn read the report's light fight list until one has at least three Mythic
wipes of that raid and ended more than two hours ago. Print
`<code>:<raidKey>` per raid, one per line, ready to paste into `all`. About
2 to 5 points per raid.

## The parallel sweep

- One subagent per raid key. Each receives a raid key and a log code, runs
  `python -m checks all <code>:<raid> --json <scratch>/<raid>.json` from
  `backend/`, and reports the verdict lines plus the mismatches verbatim.
  Subagents run the tool and read output; they do not edit code.
- Four at a time, two waves. The first wave's measured spend decides the
  second wave's width. The key's limit is 9000 points an hour (measured
  2026-10-07); one `all` is expected at 100 to 300.
- The coordinator merges the JSON files into one raid-by-check table and
  lists every fail. Each fail is shown to the owner as a finding (site bug
  or check bug) before anything is changed.
- `backend/checks/README.md` records the log code last used per raid key,
  so the next sweep starts from known-good logs and the same eight commands
  are the regression sweep.

## Failure handling

- A WCL error inside a check fails that check with the error text; `all`
  continues.
- A pull with 200 Deaths table entries (the table's cap): the checks that
  need the table `skip` and name the pull.
- No counted death in the log: `state`, `labels`, `verdicts` and the
  per-death parts of `participation` skip with that reason.
- An analysis `error` event: every result-based check fails with the text.
- The points meter is best-effort: if `rateLimitData` fails, "points: unknown".

## Testing the tool itself

`backend/test_checks.py`, offline, no keys:

- `slots`: hand-built death lists for each clause of the rule.
- `counting`: a small result with known slots and wipes, X from 1 to 10.
- `labels`: hit lists at each threshold edge (0.99 s vs 1.01 s, 79 % vs 81 %,
  a raid-wide vs a non-raid-wide ability).
- `verdicts`: a result with one violating entry per property.
- The points meter with `graphql_query` mocked.
- The verdict printer and the exit code.

## Docs and rules

- Atlas pages that name the old scripts: `testing.md`, `operations.md`,
  `warcraftlogs/index.md`. Update in the same branch, run
  `node docs/atlas/scripts/build-atlas.mjs` and `verify-atlas.mjs`, commit
  the rebuilt files.
- The owner's local rules file (not in the repo): the four script names
  become the one command, New Tier checklist steps 4 and 9 point at it, and
  the point limit becomes 9000. Shown to the owner before saving.
- Preview to the owner before merge; merging `main` deploys.

## Decisions already made

- Mythic only, like today's checks.
- Cheat deaths off in the end-to-end run (needs a signed-in session).
- Rules recomputations live in the check modules, duplicated on purpose.
- The week window is the raid reset week containing the report.
