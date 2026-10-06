---
id: backend-death-counting
title: Death Counting
domain: backend
status: documented
summary:
  - "Every death in a pull gets a slot (which death of the pull it was) and an inWipe flag from rank_pull_deaths in backend/analysis.py."
  - "A death counts for \"first X deaths\" when slot <= X and it is not in a wipe; the frontend applies that rule with the user's X."
  - "A wipe is any 8-second stretch holding 8 real deaths; windows start or end at a real death, and cheat deaths never help make one."
  - "Cheat deaths never take a slot from a real death: a cheat death's slot is the real deaths so far plus one."
  - "A save the player died from within 5 seconds is dropped before ranking (drop_saves_that_died)."
tagline: How the backend decides which deaths of a pull count toward "first X deaths".
anchors:
  mass_threshold: "backend/analysis.py:19"
  mass_window: "backend/analysis.py:20"
  in_mass_window: "backend/analysis.py:111"
  survive_ms: "backend/analysis.py:129"
  drop_saves: "backend/analysis.py:132"
  rank_pull_deaths: "backend/analysis.py:142"
  is_in_mass_death: "backend/analysis.py:75"
  find_mass_death_start: "backend/analysis.py:167"
  app_rank: "backend/app.py:498"
  app_defensive_gate: "backend/app.py:539"
  app_cutoffs: "backend/app.py:572"
  frontend_is_counted: "frontend/src/deathCounting.js:22"
  tests: "backend/test_death_slots.py:14"
links:
  - backend
  - backend-analysis-pipeline
  - backend-api-endpoints
  - backend-defensive-analysis
  - warcraftlogs
  - data-model
  - frontend-results-view
  - feat-analyze
invariants:
  - "MUST: a death counts only when slot <= X and inWipe is false."
  - "MUST: deaths on the same millisecond take one slot each, in combat-log order."
  - "MUST: a player who dies, is battle-rezzed and dies again takes two slots."
  - "NEVER: let a cheat death take a slot from a real death, or count toward a wipe."
  - "NEVER: count anything inside a wipe, real or cheat."
content_hash: sha256:5450dc89a81b27a549fbe640565c82a51927b49e9ce8b470bf97e97e4a60852c
---
## Summary

- The site's headline number is "first X deaths per pull": who tends to die early. The backend does not apply X itself for the stored events. It tags every death with `slot` and `inWipe` (`backend/app.py:531`), and the frontend's `isCounted` keeps a death when `slot <= X` and it is not in a wipe (`frontend/src/deathCounting.js:22`). See [[frontend-results-view]].
- The ranking lives in one function, `rank_pull_deaths` (`backend/analysis.py:142`), applied per pull to every death in that pull: all players, guild members or not, cheat deaths included (`backend/app.py:498`). Non-members are filtered out only after ranking (`backend/app.py:503`), so a pug's death still takes its slot.
- The backend does apply X in one place: only a counting death (real, `slot <= maxCutoff`, not in a wipe) gets defensive analysis and has its pre-death hits fetched (`backend/app.py:310`, `backend/app.py:539`).

## How it works

Each pull's deaths go through three steps, in `backend/app.py:498` and `backend/app.py:499`.

```steps
- title: Drop saves that died | short: Drop failed saves | sub: drop_saves_that_died
  body: A cheat death is removed when the same player (by `targetID`) has a real death more than 0 and at most `CHEAT_DEATH_SURVIVE_MS` (5000 ms) after it (`backend/analysis.py:129`, `backend/analysis.py:132`). The comment at `backend/analysis.py:125` records why 5 seconds: on live Mythic logs, Purgatory that is not healed off kills 3-5 seconds after it triggers.
  gotcha: The check uses `targetID`, which is per report. That is fine because ranking always runs on one pull of one report.
- title: Sort by time | short: Sort | sub: stable, log order kept
  body: The remaining deaths are sorted by timestamp (`backend/app.py:498`). Python's sort is stable, so deaths on the same millisecond keep the order they arrived in. Real deaths are added to each fight's list in combat-log order, and cheat deaths are appended after them (`backend/analysis.py:580`, `backend/analysis.py:619`), so on a tie a real death ranks before a cheat death.
- title: Rank | short: Rank | sub: rank_pull_deaths
  body: Walking the sorted list, each real death increments a counter and takes it as its slot; each cheat death takes the counter plus one without incrementing it (`backend/analysis.py:157`). Every death, real or cheat, is then checked against the wipe windows built from real deaths only (`backend/analysis.py:155`, `backend/analysis.py:163`). The function returns one `(slot, in_wipe)` pair per death, in the same order.
```

#### Slots

- A real death's slot is its position among real deaths: 1 is the first death of the pull. Deaths on the same millisecond each take their own slot, so "first 2" is exactly two real deaths (`backend/test_death_slots.py:24`).
- A player who dies, is battle-rezzed and dies again appears twice and takes two slots (`backend/test_death_slots.py:29`).
- A cheat death's slot is "real deaths so far + 1". It therefore counts for "first X" exactly when fewer than X real deaths came before it, and it never pushes a real death past X (`backend/test_death_slots.py:15`, `backend/test_death_slots.py:20`).

#### Wipes

`_in_mass_window(ts, real_ts)` (`backend/analysis.py:111`) answers "is this moment inside a wipe". A wipe is any stretch of `MASS_DEATH_WINDOW` (8000 ms) holding at least `MASS_DEATH_THRESHOLD` (8) real deaths (`backend/analysis.py:19`, `backend/analysis.py:20`). The candidate windows are anchored on real deaths in both directions: for each real death at `t0`, both `[t0, t0 + 8s]` and `[t0 - 8s, t0]` are tried (`backend/analysis.py:119`). Bounds are inclusive.

Because a window can end at the wipe's last death, a cheat death a few milliseconds before the first wipe death still falls inside it. The test at `backend/test_death_slots.py:45` uses a real log where a Cheat Death proc landed 8 ms before the wipe began. Cheat deaths are never in `real_ts`, so seven real deaths plus a cheat death is not a wipe (`backend/test_death_slots.py:33`). Fewer than 8 real deaths in the whole pull means no wipe at all (`backend/analysis.py:116`).

#### The legacy cutoff timestamps

The result also carries `pullCutoffTimestamps`: for each pull and each X from 1 to the number of real deaths, a time in ms from pull start (`backend/app.py:572`). It is the X-th real death's time, or, when that death is in a mass death, one millisecond before the mass death began (`find_mass_death_start`, `backend/analysis.py:167`). The frontend uses it only for results saved before `slot` existed (`frontend/src/deathCounting.js:11`, `frontend/src/deathCounting.js:26`).

`find_mass_death_start` uses the older detector `is_in_mass_death` (`backend/analysis.py:75`), which tries only windows that start at a death and look forward. It is kept for the old format; new counting does not depend on it.

## Diagram

From one pull's raw deaths to the pairs the frontend reads.

```diagram
lane in Inputs
node raw lane=in color=structural "Pull deaths" "real + cheat"
lane rank Ranking
node drop lane=rank color=process "Drop failed saves" "5 s window"
node sort lane=rank color=process "Sort by time" "stable"
node slot lane=rank color=process "Assign slots" "real counter"
node wipe lane=rank color=process "Wipe check" "8 in 8 s"
lane out Outputs
node ev lane=out color=safe "Death event" "slot + inWipe"
node def lane=out color=safe "Defensives" "counting deaths only"
node fe lane=out color=safe "isCounted" "frontend, user X"
edge raw -> drop
edge drop -> sort
edge sort -> slot
edge slot -> wipe
edge wipe -> ev color=safe "tag"
edge ev -> def color=safe "slot <= max"
edge ev -> fe color=safe "slot <= X"
```

## Reference

| Name {code} | What it does | Where |
|---|---|---|
| `rank_pull_deaths` {code} | `[(slot, in_wipe)]` for one pull's sorted deaths | `backend/analysis.py:142` |
| `_in_mass_window` {code} | Is a timestamp inside any wipe window of real deaths | `backend/analysis.py:111` |
| `drop_saves_that_died` {code} | Removes cheat deaths followed by that player's real death within 5 s | `backend/analysis.py:132` |
| `find_mass_death_start` {legacy} | Legacy cutoff: 1 ms before the mass death containing a death | `backend/analysis.py:167` |
| `is_in_mass_death` {legacy} | Older forward-only window detector | `backend/analysis.py:75` |
| `MASS_DEATH_THRESHOLD` {const} | 8 real deaths | `backend/analysis.py:19` |
| `MASS_DEATH_WINDOW` {const} | 8000 ms | `backend/analysis.py:20` |
| `CHEAT_DEATH_SURVIVE_MS` {const} | 5000 ms | `backend/analysis.py:129` |
| `maxCutoff` {const} | 1-10, default 5; gates defensive analysis only | `backend/app.py:128` |

## Context map

```context
depends-on: [[backend-analysis-pipeline]] — supplies each pull's deaths and cheat deaths
depends-on: [[warcraftlogs]] — combat-log order of deaths on the same millisecond
provides: slot and inWipe on every death event
provides: the legacy pullCutoffTimestamps map
relied-on-by: [[frontend-results-view]] — isCounted applies slot <= X and not inWipe
relied-on-by: [[backend-defensive-analysis]] — only counting deaths are analyzed
relied-on-by: [[backend-api-endpoints]] — the fields are part of the result contract
relied-on-by: [[data-model]] — saved and shared results store these fields
```

## Invariants

- **MUST** count a death only when `slot <= X` and `inWipe` is false (`frontend/src/deathCounting.js:24`, `backend/app.py:539`).
- **MUST** give deaths on the same millisecond one slot each, in combat-log order (`backend/test_death_slots.py:24`).
- **MUST** give a player who dies, is battle-rezzed and dies again two slots (`backend/test_death_slots.py:29`).
- **NEVER** let a cheat death take a slot from a real death, or count toward a wipe (`backend/analysis.py:155`, `backend/analysis.py:158`).
- **NEVER** count anything inside a wipe, real or cheat (`backend/test_death_slots.py:40`).

## Gotchas

- **Non-guild deaths still take slots**: ranking runs before the roster filter (`backend/app.py:499`, `backend/app.py:503`). A pug who dies first holds slot 1, and the guild's first death is slot 2. The docstring states the input is every death in the pull, all players (`backend/analysis.py:145`): "first X deaths" is about the pull, not the guild's share of it.
- **X is applied twice, with different values**: the backend uses `maxCutoff` from the request to decide which deaths get defensives; the frontend uses whatever X the viewer picks. A death past `maxCutoff` can count in the UI but will have no `defensives` block.

## Glossary

- **Slot**: which death of the pull this was, counting real deaths only; for a cheat death, real deaths so far plus one.
- **Wipe**: an 8-second stretch holding 8 or more real deaths; nothing inside it counts.
- **Real death**: a `death` event from WarcraftLogs, as opposed to a cheat death.
- **Counting death**: a real death with `slot <= maxCutoff` outside a wipe; the only kind that gets defensive analysis.

## Related

- [[backend]] — the service landing page
- [[backend-analysis-pipeline]] — where ranking happens in the analysis
- [[backend-api-endpoints]] — `slot`, `inWipe` and `pullCutoffTimestamps` in the result
- [[backend-defensive-analysis]] — analysis limited to counting deaths
- [[warcraftlogs]] — the death and cheat-death events being ranked
- [[data-model]] — stored results keep these fields
- [[frontend-results-view]] — applies the count with the viewer's X
- [[feat-analyze]] — the "first X deaths" setting from the user's side
