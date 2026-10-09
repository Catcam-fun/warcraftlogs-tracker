---
id: feat-results
title: Results & Death Breakdown
domain: feat-results
status: documented
summary:
  - "The Results page (/results) turns one analysis result into per-player death rates, a player-by-boss matrix, and an expandable death log per player."
  - "Every number is computed in the browser from the result: a death counts when its slot is within the chosen 'Deaths to count' and it is not part of a wipe."
  - "Each death row shows the killing blow, health before it, and a strip of defensives (active, ready, on cooldown) with verdict tooltips from the server's defensive analysis."
  - "The killing-blow tooltip carries the in-game spell text and how many counted deaths that ability caused; each row links to the pull's Deaths view on WarcraftLogs."
  - "Filters (boss chips, minimum pulls, search, hide, alt grouping) never call the server."
tagline: How one analysis result becomes death rates, a matrix and per-death verdicts.
anchors:
  route: "frontend/src/App.js:1595"
  cutoff_state: "frontend/src/App.js:225"
  cutoff_select: "frontend/src/App.js:1696"
  is_counted: "frontend/src/deathCounting.js:22"
  counted_deaths: "frontend/src/deathCounting.js:31"
  player_stats: "frontend/src/App.js:993"
  matrix_data: "frontend/src/App.js:1143"
  kill_counts: "frontend/src/App.js:1276"
  wcl_link: "frontend/src/App.js:1336"
  player_list: "frontend/src/App.js:2101"
  death_row: "frontend/src/DeathRow.js:238"
  defensive_summary: "frontend/src/DefensivePanel.js:20"
  result_shape: "backend/app.py:647"
  death_event: "backend/app.py:559"
  defensives_gate: "backend/app.py:583"
links:
  - frontend
  - frontend-results-view
  - frontend-pages-and-routing
  - backend-analysis-pipeline
  - backend-death-counting
  - backend-defensive-analysis
  - backend-death-descriptions
  - warcraftlogs
  - game-data
  - feat-analyze
  - feat-saved
  - feat-share
flows:
  - request-path
invariants:
  - "MUST: a death count only when slot <= the chosen cutoff and inWipe is false (frontend/src/deathCounting.js:22)."
  - "NEVER: let a cheat death take a real death's slot; it is counted separately as +N cheat (frontend/src/deathCounting.js:31)."
  - "MUST: defensive analysis exist only for deaths that could count (slot <= maxCutoff, not in a wipe, not a cheat death) (backend/app.py:583)."
  - "NEVER: call the server when a filter changes; every table is recomputed from the loaded result (frontend/src/App.js:1266)."
content_hash: sha256:dbb78aacb81c6655d715efe61ebc4c4af6ab4fd2fac3c79d858366a5655f1453
---
## Summary

- **What it is.** The `/results` route (`frontend/src/App.js:1595`) shows the analysis held in app state: a filter bar, a collapsible death-rate matrix, and a player list whose rows expand into a per-boss death log.
- **Where the numbers come from.** The server sends every guild-member death with a `slot` and `inWipe` (`backend/app.py:559`). The browser decides what counts with `isCounted` (`frontend/src/deathCounting.js:22`), so changing "Deaths to count" re-scores instantly.
- **What a death row shows.** `DeathRow` (`frontend/src/DeathRow.js:238`) draws the killing blow, health before it, the defensive strip and a "View log" link.
- **What it leaves alone.** Results never refetch. Saved, shared and recent runs all render through the same page from stored data.

## How it works

You arrive here after an analysis, a saved report, a share link, or a Recent run. All four set the same `data` state and navigate to `/results`.

```steps
- title: Choose deaths to count | short: Deaths to count | sub: first X per pull
  body: The select offers 1 to data.meta.maxCutoff (frontend/src/App.js:1696). The chosen value is the cutoff state, which starts at 2 (frontend/src/App.js:225). countedDeaths splits each player's events into real and cheat deaths that count (frontend/src/deathCounting.js:31). Results saved before slot existed fall back to per-pull cutoff timestamps (frontend/src/deathCounting.js:14).
  gotcha: The cutoff starts at 2 even when the analysis tracked only 1 death per pull, so the select can show a value it does not list.
- title: Narrow the view | short: Filters | sub: bosses, pulls, search
  body: Boss chips (frontend/src/App.js:1729), a minimum-pulls box (frontend/src/App.js:1743), a player search (frontend/src/App.js:1758), per-player Hide (frontend/src/App.js:2130) and "Group characters" to merge alts into a main (frontend/src/App.js:1805). Both tables are memoized on these inputs (frontend/src/App.js:1266).
  gotcha: Alt groups made here live only in page state; they are not part of the result that gets saved or shared.
- title: Read the matrix | short: Matrix | sub: player x boss
  body: computeOverviewData builds a death rate per player per boss and overall (frontend/src/App.js:1143). Rates are counted deaths over pulls the player was in (pullParticipation and bossParticipation from backend/app.py:641). Colors scale around the median with outliers clamped (frontend/src/App.js:1341).
- title: Read the player list | short: Players | sub: rate, preventable
  body: computeFilteredStats sorts players by real death rate (frontend/src/App.js:1140). Each row shows deaths over pulls, the rate, +N cheat when cheat deaths count (frontend/src/App.js:2127), and a defensive chip such as "3/5 preventable" from summarizeDefensives (frontend/src/DefensivePanel.js:20).
- title: Expand a player | short: Death log | sub: per boss, per death
  body: Expanding lists bosses in Adventure Guide order (frontend/src/App.js:153), each with top killing abilities and one DeathRow per counted death (frontend/src/App.js:2180). The row text describes the death as one-shot, burst, worn down by a raid-wide ability (rot), or the biggest hit before it (frontend/src/DeathRow.js:254).
- title: Hover the killing blow | short: Killing blow | sub: spell text, kill count
  body: The tooltip shows the ability's icon (abilityIcons by spell ID), its in-game description (abilityText, backend/app.py:674), the hit size, and "Killed N raiders in these pulls" from killCounts (frontend/src/App.js:1276).
- title: Hover a defensive | short: Defensive verdict | sub: saves, not enough, can't tell
  body: Ready abilities and consumables are green when the server's replay says they would have saved the player, red otherwise, with the amount and press time (frontend/src/DeathRow.js:323). Active and on-cooldown abilities have their own tooltips (frontend/src/DeathRow.js:379).
- title: Open the log | short: View log | sub: WarcraftLogs deaths view
  body: Each row links to https://www.warcraftlogs.com/reports/<report>#fight=<fight>&type=deaths (frontend/src/App.js:1336), opened in a new tab (frontend/src/DeathRow.js:448).
```

## Diagram

```diagram
lane srv Flask API
lane st Browser state
lane view Results page
node build lane=srv color=process "Result object" "app.py:635"
node defs lane=srv color=process "analyze_death" "per counted death"
node data lane=st color=structural "data" "events, meta"
node cutoff lane=st color=process "cutoff" "Deaths to count"
node count lane=st color=safe "isCounted" "slot, inWipe"
node matrix lane=view color=process "Matrix" "player x boss"
node players lane=view color=process "Player list" "rate, chip"
node row lane=view color=safe "DeathRow" "verdict tooltips"
edge defs -> build "defensives"
edge build -> data "result line"
edge data -> count "events"
edge cutoff -> count "X"
edge count -> matrix "rates"
edge count -> players "rates"
edge players -> row "expand"
```

## Context map

```context
depends-on: [[feat-analyze]] — produces the result this page renders
depends-on: [[frontend-results-view]] — the components behind the page
depends-on: [[frontend-pages-and-routing]] — the /results route and shared state
depends-on: [[backend-death-counting]] — slot and inWipe on every death
depends-on: [[backend-defensive-analysis]] — death.defensives and its survival replay
depends-on: [[backend-death-descriptions]] — one-shot, burst, rot and biggest-hit wording inputs
depends-on: [[game-data]] — icons, ability info and boss spell text in the result
depends-on: [[warcraftlogs]] — the report and fight IDs behind each log link
provides: per-player death rates at any cutoff up to maxCutoff
provides: per-death killing blow, defensive strip and verdicts
provides: Save and Share buttons for the loaded result
relied-on-by: [[feat-saved]] — reopened saves render here
relied-on-by: [[feat-share]] — share links open here
```

## Reference

| Field or piece {kind} | Where | Meaning |
|---|---|---|
| `meta` {result} | `backend/app.py:648` | guild, maxCutoff, dates, difficulty, cheatDeathEnabled, rosterOnly, failedReports |
| `events` {result} | `backend/app.py:663` | player to list of death events |
| `pullParticipation` {result} | `backend/app.py:664` | player to pulls they were in |
| `bossParticipation` {result} | `backend/app.py:665` | boss to player to pulls |
| `pullCutoffTimestamps` {result} | `backend/app.py:666` | legacy per-pull cutoffs |
| `icons`, `abilityIcons` {result} | `backend/app.py:668` | defensive icons by name; killing-blow icons by spell ID |
| `abilityInfo`, `abilityText` {result} | `backend/app.py:672` | defensive effects; killing-blow spell descriptions |
| `slot`, `inWipe` {event} | `backend/app.py:575` | where the death falls in the pull |
| `isCheatDeath` {event} | `backend/app.py:574` | a save from a lethal hit, not a death |
| `defensives` {event} | `backend/app.py:608` | only for deaths that could count |
| `pullNo`, `absTs` {event} | `backend/app.py:568` | pull number per boss; absolute time |
| `isCounted` {code} | `frontend/src/deathCounting.js:22` | the counting rule |
| `computeFilteredStats` {code} | `frontend/src/App.js:993` | player list |
| `computeOverviewData` {code} | `frontend/src/App.js:1143` | matrix |
| `DeathRow` {code} | `frontend/src/DeathRow.js:238` | one death |
| `DefensiveSummaryChip` {code} | `frontend/src/DefensivePanel.js:43` | preventable and one-shot chips |

## Invariants

- **MUST** a death count only when `slot <= cutoff` and `inWipe` is false (`frontend/src/deathCounting.js:22`). The server computes both with `rank_pull_deaths` (`backend/app.py:543`).
- **NEVER** let a cheat death take a real death's slot; it is counted separately as "+N cheat" (`frontend/src/deathCounting.js:31`, `frontend/src/App.js:2127`).
- **MUST** defensive analysis exist only for deaths that could count: slot within `maxCutoff`, not in a wipe, not a cheat death (`backend/app.py:583`).
- **NEVER** call the server when a filter changes; every table is recomputed from the loaded result (`frontend/src/App.js:1266`).

## Gotchas

- **"Analyzed" is when the analysis ran**: the header shows the result's `meta.generatedAt` (`frontend/src/App.js:1672`, `frontend/src/analyzedAt.js`), which the backend stamps in UTC (`backend/app.py:656`), so a saved or shared report keeps its original date. Older results stamped without a zone are read as UTC; a result with no stamp shows no date rather than today's.
- **Older results have older shapes**: `isCurrentShape` skips defensive data saved before the current format (`frontend/src/DefensivePanel.js:17`), and rows fall back to "Off cooldown when they died".
- **Cheat deaths need the flag**: the matrix only adds cheat deaths when `config.enableCheatDeath` is true (`frontend/src/App.js:1198`), which is synced from `meta.cheatDeathEnabled` after a run (`frontend/src/App.js:763`).
- **Debug globals**: a finished run sets `window.deathTrackerData` and export helpers on `window` (`frontend/src/App.js:769`).

## Related

- [[feat-analyze]] — where the result comes from
- [[frontend-results-view]] — component-level detail
- [[backend-death-counting]] — slots, wipes and cheat deaths
- [[backend-defensive-analysis]] — the replay behind each verdict
- [[backend-death-descriptions]] — how deaths are described
- [[backend-analysis-pipeline]] — how the result object is assembled
- [[game-data]] — icons and spell text
- [[feat-saved]] — keep a result on your account
- [[feat-share]] — send a result to someone else
- [[warcraftlogs]] — where each log link points
- [[frontend-pages-and-routing]] — the route
- [[frontend]] — the React app
