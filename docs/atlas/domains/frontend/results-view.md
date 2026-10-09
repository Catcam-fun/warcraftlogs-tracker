---
id: frontend-results-view
title: Results View
domain: frontend
status: documented
summary:
  - "The /results page is inline JSX in App.js: a filter bar, a player-by-boss death-rate matrix, and an expandable player list whose rows are DeathRow components."
  - "Which deaths count is one rule in deathCounting.js: a death counts when its slot is at most the chosen X and it is not inWipe; old saved results fall back to per-pull cutoff timestamps."
  - "Every number is recomputed in the browser from the stored result plus the filters (deaths to count, boss chips, minimum pulls, search, hidden players, alt groups); the backend is not called again."
  - "DeathRow shows one death: killing blow and how it happened, health before it, and a strip of defensives (active, ready, on cooldown) with tooltips carrying the backend's verdicts."
  - "DefensivePanel rolls a player's counted real deaths into a preventable / one-shot chip and the abilities that would have saved them most often."
tagline: How the stored analysis becomes the matrix, the player list and each death's row.
anchors:
  is_counted: frontend/src/deathCounting.js:22
  counted_deaths: frontend/src/deathCounting.js:31
  legacy_cutoff: frontend/src/deathCounting.js:14
  cutoff_state: frontend/src/App.js:225
  filtered_stats: frontend/src/App.js:993
  overview_data: frontend/src/App.js:1143
  memos: frontend/src/App.js:1266
  kill_counts: frontend/src/App.js:1276
  sort_overview: frontend/src/App.js:1288
  percentage_color: frontend/src/App.js:1341
  results_route: frontend/src/App.js:1595
  cutoff_select: frontend/src/App.js:1696
  player_list: frontend/src/App.js:2102
  death_row: frontend/src/DeathRow.js:243
  death_context: frontend/src/DeathRow.js:259
  ready_tip: frontend/src/DeathRow.js:326
  tip: frontend/src/DeathRow.js:206
  summarize_defensives: frontend/src/DefensivePanel.js:20
  summary_chip: frontend/src/DefensivePanel.js:43
invariants:
  - "MUST: every count, rate and kill count on the page goes through isCounted / countedDeaths, so the matrix, the player list and the killing-blow tooltips agree."
  - "NEVER: a death with inWipe counts, whatever the chosen X."
  - "NEVER: the frontend recompute slot, inWipe or a defensive verdict; it only filters and displays what the backend sent."
  - "MUST: DeathRow and DefensivePanel skip defensive data that lacks the current shape (active and available arrays), so older saves and shares still render."
links:
  - frontend
  - frontend-pages-and-routing
  - frontend-landing-and-art
  - backend-death-counting
  - backend-defensive-analysis
  - backend-death-descriptions
  - feat-results
  - feat-analyze
  - feat-share
  - feat-saved
content_hash: sha256:32a7b77e288791396235dafaeaa9f28343dee6c4868dd2a8b18e147d98296048
---
## Summary

The **Results view** is what a raid officer reads after an analysis. It lives inside the `/results` route in `frontend/src/App.js:1595`, with two leaf components for the detail: `DeathRow.js` and `DefensivePanel.js`.

- The page reads one stored object, `data`, and a handful of filter states. All tables are derived with `useMemo` from those (`frontend/src/App.js:1266-1273`).
- "First X deaths per pull" is decided by `isCounted` (`frontend/src/deathCounting.js:22`), using the `slot` and `inWipe` fields the backend put on each death.
- Each death row is a `DeathRow` (`frontend/src/DeathRow.js:243`); a player's defensive rollup is `summarizeDefensives` plus two small chips (`frontend/src/DefensivePanel.js:20`).
- What it deliberately does not do: it never decides a slot, a wipe, a death type or whether a defensive would have saved someone. Those come from the backend; this page counts, filters, sorts and explains.

## How it works

Changing any filter re-runs the same pipeline. You can think of it as a sieve: every death in `data.events` falls through the same holes, and the page only draws what is left.

```steps
- title: Choose X | short: Deaths to count | sub: 1 to meta.maxCutoff
  body: The "Deaths to count" select sets cutoff (default 2, App.js:225). Its options run from 1 to data.meta.maxCutoff (App.js:1696-1701), which the backend clamps to 1-10 from the Analyze form (backend/app.py:134).
  gotcha: When a different result loads, fitFiltersToResult lowers cutoff to that result's maxCutoff if it was higher (frontend/src/App.js:252, frontend/src/resultFilters.js), so the select always has a matching option.
- title: Decide what counts | short: isCounted | sub: slot <= X and not inWipe
  body: For each death, isCounted returns slot <= cutoff && !inWipe (deathCounting.js:22-25). Results saved before slot existed fall back to data.pullCutoffTimestamps[reportId_fightId][X], or the largest X stored, and count deaths at or before that time (deathCounting.js:14-27). countedDeaths then splits the survivors into real and cheat lists (deathCounting.js:31-38).
- title: Apply filters | short: Filters | sub: bosses, pulls, search, hidden, alts
  body: Boss chips limit events and pulls to the selected bosses (App.js:1024, App.js:1037). Alt groups merge each main's characters' events and pulls (App.js:1018-1022). Search drops non-matching names; Minimum pulls and Hide drop players afterwards (App.js:1057, App.js:1136).
- title: Build the matrix | short: Matrix | sub: player x boss rates
  body: computeOverviewData builds grid[player][boss] with counted real deaths over that player's pulls of the boss, plus an overall column (App.js:1143-1259). Cheat deaths enter totalRate only when cheat detection was on (App.js:1198, App.js:1230). The matrix is collapsed by default (App.js:230).
- title: Build the player list | short: Players | sub: sorted by real rate
  body: computeFilteredStats builds one row per player with real deaths, pulls, rate, deaths grouped by boss, the top 5 killing abilities per boss (Unknown excluded) and a defensive summary of the counted real deaths (App.js:993-1132). The list is sorted by real rate, then real deaths, both descending (App.js:1140).
- title: Expand a player | short: Death rows | sub: per boss, DeathRow each
  body: Expanding a player shows DefensiveTopUnused, then one section per boss in Adventure-Guide order with counts, top abilities and a DeathRow per counted death (App.js:2142-2187). With cheat deaths shown, real and cheat deaths are merged and sorted by absTs (App.js:2181).
```

### What a death row shows

`DeathRow` has four columns (`frontend/src/fp-design.css:725`): the killing blow, a health bar, the defensive strip, and a "View log" link with the time.

- **Killing blow line**: `#pullNo · ability name`, a CHEAT badge for a cheat death, then one context line chosen in this order (`frontend/src/DeathRow.js:259-271`): cheat death, no hit in the log, no killing blow recorded, instant kill, one-shot ("one-shot from N%", or "one-shot by X (P%) from N%" when a smaller hit finished them), burst ("burst from N%: K hits in Ts"), rot ("worn down by X (rot, K hits)"), set up by the biggest hit, and finally plain "at N%, hit for M%". The label itself comes from `survival.deathType`, `burst`, `rot`, `oneShotHit` and `biggestHit`, set by the backend.
- **Killing-blow tooltip**: the spell's in-game description from `data.abilityText` (by spell ID), the killing blow size, rot / burst / one-shot by / set-up rows ("One-shot by" names a one-shot's big hit when a smaller hit finished them; "Set up by" only on deaths that were neither one-shot nor burst), health before it and overkill, warnings for "ignores immunity" and "ignores reduction", and how many counted raiders that ability killed in these results (`frontend/src/DeathRow.js:273-323`). The kill count is `killCounts`, built with the same `isCounted` rule (`frontend/src/App.js:1276-1284`).
- **Health bar**: width is `hpBeforePct`, capped at 100; hidden for instant kills (`frontend/src/DeathRow.js:438-441`).
- **Defensive strip**, left to right (`frontend/src/DeathRow.js:381-425`):
  - **Active** (gold ring, "ON" tag): auras up when they died, including externals with who cast them.
  - **Ready** (green ring and check if it would have saved them, dimmed if not): every entry of `available` plus each consumable in `survival.consumables`. The verdict comes from `survival.wouldSave[name]`.
  - **On cooldown** (greyed, with seconds until ready): `cooldown` entries plus a used Healthstone or potion.
  - **"all together ✓"** when no single ability saves them but `allTogetherWouldSave` is true, and **"?"** when the pull had no talent data (`frontend/src/DeathRow.js:444-453`).
- **Ready-icon tooltip** verdicts, from `survival.details[name]` (`frontend/src/DeathRow.js:337-343`): "Saves them · N to spare", "Can't tell" (timeline unreadable), "Doesn't help" with a reason from `whyText` (`frontend/src/DeathRow.js:116-139`), or "Not enough · N short". Below that: amount prevented or healed, heal-over-time ticks that land in time, the press time, talents that changed it, and where a potion or Healthstone value came from (`frontend/src/DeathRow.js:173-187`).

## Diagram

The data path from the stored result to a row. Blue is the counting pipeline, green is what renders.

```diagram
lane in Stored result
node data lane=in color=structural "data" "events, participation"
node filters lane=in color=process "Filter state" "X, bosses, search"
lane count Counting
node counted lane=count color=process "isCounted" "slot <= X, !inWipe"
node stats lane=count color=process "computeFilteredStats" "player rows"
node overview lane=count color=process "computeOverviewData" "player x boss"
node kills lane=count color=process "killCounts" "boss|ability"
lane view Rendered
node matrix lane=view color=safe "Death-rate matrix" "sortable"
node plist lane=view color=safe "Player list" "by real rate"
node drow lane=view color=safe "DeathRow" "one death"
node dpanel lane=view color=safe "DefensivePanel" "chips"
edge data -> counted "each death"
edge filters -> counted "cutoff"
edge counted -> stats
edge counted -> overview
edge counted -> kills
edge overview -> matrix "grid"
edge stats -> plist "rows"
edge stats -> dpanel "summary"
edge plist -> drow "expand"
edge kills -> drow "tooltip"
```

## Reference

The pieces of the Results view. Filter by kind.

| Piece {counting} | What it does | Anchor |
|---|---|---|
| `isCounted` {counting} | `slot <= cutoff && !inWipe`; legacy fallback to `pullCutoffTimestamps` | `frontend/src/deathCounting.js:22` |
| `countedDeaths` {counting} | Splits counted events into `{ real, cheat }` by `isCheatDeath` | `frontend/src/deathCounting.js:31` |
| `killCounts` {counting} | Counted real deaths per `"boss|ability"`, for the killing-blow tooltip | `frontend/src/App.js:1276` |
| `computeFilteredStats` {table} | Player list rows: deaths, pulls, rate, per-boss deaths, top abilities, defensive summary | `frontend/src/App.js:993` |
| `computeOverviewData` {table} | Matrix grid and overall column; bosses in `BOSS_ORDER` order | `frontend/src/App.js:1143` |
| `sortOverviewData` / `handleSort` {table} | Matrix sort by Player, a boss column or Overall; a second click flips to descending; no-rate cells sort as -1 | `frontend/src/App.js:1288`, `frontend/src/App.js:1314` |
| `getPercentageColor` {table} | Colors a rate against its column: IQR outliers get the end colors, the rest a green-yellow-red scale around the median | `frontend/src/App.js:1341` |
| `getWCLLink` {table} | `warcraftlogs.com/reports/<id>#fight=<fightId>&type=deaths` | `frontend/src/App.js:1336` |
| Deaths to count {filter} | `cutoff`, default 2, options 1 to `meta.maxCutoff` | `frontend/src/App.js:1696` |
| Boss filters {filter} | Chips in `BOSS_ORDER` order; none selected means all | `frontend/src/App.js:1729` |
| Minimum pulls {filter} | Hides players with fewer pulls (digits only) | `frontend/src/App.js:1741` |
| Search {filter} | Case-insensitive substring on player name | `frontend/src/App.js:1758` |
| Hidden players {filter} | "Hide" on a row; a pill list restores them | `frontend/src/App.js:1768` |
| Group characters {filter} | Merge alts into a main for both tables, this session only | `frontend/src/App.js:1805` |
| `DeathRow` {row} | One death: killing blow, context line, health bar, defensive strip, log link | `frontend/src/DeathRow.js:243` |
| `Tip` / `TipBox` {row} | Hover or focus tooltip, portaled to `document.body` and kept inside the viewport | `frontend/src/DeathRow.js:206`, `frontend/src/DeathRow.js:191` |
| `Icon` {row} | Blizzard icon, then WarcraftLogs' copy, then the name's first letter | `frontend/src/DeathRow.js:223` |
| `effectText` {row} | Describes an ability from its catalog components, or its game text for externals | `frontend/src/DeathRow.js:82` |
| `summarizeDefensives` {panel} | Per player: deaths with data, assessed, preventable, one-shots, top 3 savers and top 3 unused majors | `frontend/src/DefensivePanel.js:20` |
| `DefensiveSummaryChip` {panel} | "N/M preventable" (green at 0, red at half or more, amber between) and "K one-shots" | `frontend/src/DefensivePanel.js:43` |
| `DefensiveTopUnused` {panel} | "Would have saved them most often", else "Most often unused at death" | `frontend/src/DefensivePanel.js:71` |

### Data fields the view reads

From the backend's result (`backend/app.py:663-676`): `events` (deaths per player, each with `boss`, `pullNo`, `reportId`, `fightId`, `absTs`, `abilityName`, `abilityId`, `isCheatDeath`, `slot`, `inWipe`, `class`, `spec`, `defensives`), `pullParticipation`, `bossParticipation`, `pullCutoffTimestamps`, `icons`, `abilityIcons`, `abilityInfo`, `abilityText`, and `meta.maxCutoff`. The defensive shape is documented in the comment at `frontend/src/DefensivePanel.js:3-14`.

## Context map

Where this sub-page sits in the larger system.

```context
depends-on: [[backend-death-counting]] — slot and inWipe on every death
depends-on: [[backend-defensive-analysis]] — active, available, cooldown and survival verdicts per death
depends-on: [[backend-death-descriptions]] — deathType, burst, rot and biggestHit for the context line
depends-on: [[frontend-pages-and-routing]] — the /results route and the data / config state in App.js
depends-on: [[frontend-landing-and-art]] — BOSS_ORDER for boss order in chips and sections
provides: per-player and per-boss death rates for the chosen "first X deaths"
provides: an explained row per counted death, with defensive verdicts
relied-on-by: [[feat-results]] — the end-to-end Results slice
relied-on-by: [[feat-share]] — a shared link renders through this same view
relied-on-by: [[feat-saved]] — an opened saved report renders through this same view
```

## Invariants

- **MUST** count through `isCounted` / `countedDeaths` everywhere: the matrix (`frontend/src/App.js:1195`, `frontend/src/App.js:1228`), the player list (`frontend/src/App.js:1048`) and `killCounts` (`frontend/src/App.js:1279`). A second rule anywhere would make the tables disagree.
- **NEVER** count a death with `inWipe`, whatever X is (`frontend/src/deathCounting.js:24`). Mass deaths at a wipe say nothing about who failed first.
- **NEVER** recompute `slot`, `inWipe`, `deathType` or `wouldSave` in the browser. They come from the backend (`backend/analysis.py:188`, `backend/app.py:574-575`, `backend/defensives.py:2396`, `backend/defensives.py:2432`, `backend/defensives.py:2442`); the view only reads them.
- **MUST** skip defensive data without the current shape (`active` and `available` arrays) so saves and shares from older versions still render (`frontend/src/DeathRow.js:23`, `frontend/src/DefensivePanel.js:17`).

## Gotchas

- **Merged alts count every character's pulls, everywhere**: the overall row, the matrix and the expanded player card's per-boss line all add up the pulls of the main and its merged alts; the card uses `groupPulls` (`frontend/src/App.js:2147`, `frontend/src/groupPulls.js`), so its per-boss rate matches the matrix.
- **Filters survive a new result, fitted to it**: `hiddenPlayers`, `minPulls`, `searchQuery` and `characterGroups` carry over when another result loads, and only `expandedPlayers` and `sortConfig` are reset (`frontend/src/App.js:339-340`, `frontend/src/App.js:506-507`). `cutoff` is capped at the new result's maximum and boss chips the new result doesn't have are dropped (`frontend/src/App.js:252`, `frontend/src/resultFilters.js`), so a previous raid's chips can no longer empty the tables.
- **"Analyzed" is when the analysis ran**: the header shows the result's `meta.generatedAt` (`frontend/src/App.js:1672`, `frontend/src/analyzedAt.js`), which the backend stamps in UTC (`backend/app.py:656`), so a saved or shared report keeps its original date. Older results stamped without a zone are read as UTC; a result with no stamp shows no date rather than today's.
- **Matrix sort only affects the matrix**: the player list is always ordered by real rate (`frontend/src/App.js:1140`). With no sort chosen, matrix rows are alphabetical (`frontend/src/App.js:1153`).
- **Color scale ignores the search box**: matrix colors are computed over all visible players, not just the searched ones, so a cell keeps its color while you search (`frontend/src/App.js:1971-1982`).
- **Cheat deaths in the player list are not gated by the toggle**: `computeFilteredStats` counts cheat deaths whatever `enableCheatDeath` says, and only hides them in the display (`frontend/src/App.js:1047-1052`, `frontend/src/App.js:2111`); the matrix gates them (`frontend/src/App.js:1198`). In practice the backend only sends cheat deaths when detection ran.
- **One-shots include instant kills**: the "one-shots" chip counts `deathType` `oneShot` and `instakill` together (`frontend/src/DefensivePanel.js:33`).
- **Potion quality art follows PUBLIC_URL**: `qualityArt` builds `${PUBLIC_URL}/art/quality/<name>.png` like every other art path (`frontend/src/DeathRow.js:170`), so it also loads when the site is served under a sub-path (`frontend/src/qualityArt.test.js`).
- **Death rows are keyed by index**: `DeathRow` gets `key={idx}` (`frontend/src/App.js:2183`), so open tooltips can attach to a different row when the list changes under them.

## Glossary

- **Cutoff (X)**: the "Deaths to count" value. A death counts when its slot is at most X.
- **Slot**: which death of the pull this was, set by the backend. A cheat death gets the real deaths so far plus one, so it never takes a real death's place.
- **inWipe**: set by the backend when the death is part of a mass death; such deaths never count.
- **Real rate**: counted real deaths divided by pulls, as a percentage.
- **Preventable**: a counted real death where at least one ready ability, or all of them together, would have kept the player alive by the backend's replay.

## Related

- [[frontend]] — the parent domain and the App.js shell
- [[frontend-pages-and-routing]] — how data reaches /results (stream, share, saved, recent runs)
- [[frontend-landing-and-art]] — BOSS_ORDER and the raid entries that order bosses here
- [[backend-death-counting]] — where slot and inWipe are decided
- [[backend-defensive-analysis]] — where the defensive strip and verdicts come from
- [[backend-death-descriptions]] — where one-shot, burst, rot and "set up by" come from
- [[feat-results]] — the end-to-end Results slice
- [[feat-analyze]] — the run that produces the result
- [[feat-share]] — share links render this view
- [[feat-saved]] — saved reports render this view
