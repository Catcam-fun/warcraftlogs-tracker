---
id: feat-analyze
title: Analyze a Guild
domain: feat-analyze
status: documented
summary:
  - "The Analyze page (/analyze) collects WarcraftLogs credentials, guild, server, region, raid, difficulty, an optional date range, deaths tracked per pull, the Guild Roster toggle and cheat-death detection."
  - "Submitting POSTs the whole form to /api/analyze, which answers with a server-sent event stream of progress lines and, at the end, one result object."
  - "While the stream runs, a full-screen loader shows the latest progress line and a Cancel button that aborts the request."
  - "The server clamps what the form sends: deaths tracked to 1-10, the date range to the raid's tier window, and cheat-death detection to signed-in callers."
  - "On success the result is kept in the browser (IndexedDB, plus a five-run Recent list) and the app moves to /results."
tagline: The form that starts a death review, and the streamed request it sends.
anchors:
  route: "frontend/src/App.js:1577"
  form_component: "frontend/src/AnalyzeConfig.js:28"
  raid_cards: "frontend/src/AnalyzeConfig.js:12"
  default_config: "frontend/src/App.js:198"
  raid_change: "frontend/src/App.js:670"
  submit: "frontend/src/App.js:681"
  stream_reader: "frontend/src/App.js:736"
  loader: "frontend/src/App.js:1535"
  cancel: "frontend/src/App.js:657"
  local_credentials: "frontend/src/api.js:21"
  analyze_endpoint: "backend/app.py:109"
  max_cutoff_clamp: "backend/app.py:134"
  cheat_death_gate: "backend/app.py:143"
  roster_toggle: "backend/app.py:145"
  date_window: "backend/analysis.py:280"
  encounter_allowlist: "backend/analysis.py:234"
  analyze_rate_limit: "backend/app.py:53"
links:
  - frontend
  - frontend-pages-and-routing
  - frontend-landing-and-art
  - backend
  - backend-api-endpoints
  - backend-analysis-pipeline
  - backend-death-counting
  - backend-caching-and-limits
  - warcraftlogs
  - data-model
  - auth
  - security
  - feat-results
  - feat-account
flows:
  - request-path
invariants:
  - "MUST: the server clamp maxCutoff to 1-10 (backend/app.py:134); the form's min/max are only a hint."
  - "MUST: user dates only narrow the raid's tier window, never widen it (backend/analysis.py:280)."
  - "NEVER: run cheat-death detection for a caller without a valid Supabase session, whatever the request body says (backend/app.py:143)."
  - "MUST: fights be kept only when their encounter ID is in the selected raid's RAID_ENCOUNTERS set (backend/analysis.py:315)."
  - "NEVER: store the Client ID or Secret in the browser's analysis history; stripSecrets removes them before IndexedDB writes (frontend/src/App.js:552)."
content_hash: sha256:5a7a55a781e31d0cb44e7828b2cff90d6b8779f7bf13fecfafe8563944872171
---
## Summary

- **What it is.** The `/analyze` route renders `AnalyzeConfig` (`frontend/src/App.js:1577`, `frontend/src/AnalyzeConfig.js:28`). You pick a raid card, fill in your WarcraftLogs API client and guild, and press **Analyze Reports**.
- **What it sends.** `handleSubmit` (`frontend/src/App.js:681`) posts the whole config to `POST /api/analyze` and reads the response as a stream of `data:` lines (`frontend/src/App.js:736`).
- **What the server does.** `analyze()` (`backend/app.py:109`) authenticates with WarcraftLogs, fetches the roster and reports, reads each report's short fight list, drops duplicate pulls, reads in full only the reports it keeps pulls from, ranks deaths and builds the result. See [[backend-analysis-pipeline]] for the internals.
- **What it trusts.** Very little. The server clamps deaths tracked, narrows dates to the tier, and decides cheat-death detection from the bearer token, not from the checkbox.
- **What it leaves alone.** Nothing is written to Supabase by an analysis except the shared report cache. Results live in your browser until you save or share them ([[feat-saved]], [[feat-share]]).

## How it works

You reach the page from the landing page's run button (`frontend/src/App.js:1568`) or the left rail. The form state lives in `App.js`, not in the form component, so it survives moving between pages.

```steps
- title: Pick a raid | short: Pick a raid | sub: raid card sets the key
  body: The raid grid comes from the RAIDS list in frontend/src/AnalyzeConfig.js:12 (Manaforge Omega, Liberation of Undermine, Nerub'ar Palace, Midnight Season 1, and the Season 2 entries from frontend/src/seasonTwoRaids.js:6). Clicking a card calls handleRaidChange (frontend/src/App.js:670), which writes selectedRaid plus that raid's reportZone and fightZone from RAID_ZONES (frontend/src/App.js:30). The lineup under the grid shows the selected raid's bosses.
  gotcha: The initial config selects 'manaforge' (frontend/src/App.js:203), not the newest tier. If selectedRaid is not in RAIDS, the lineup falls back to RAIDS[0] (frontend/src/AnalyzeConfig.js:34).
- title: Fill credentials and scope | short: Credentials & scope | sub: client, guild, server, region
  body: Client ID and Secret are required. Signed out, they are remembered in this browser under localStorage key fpx.wclCredentials (frontend/src/api.js:21, saved on every change at frontend/src/App.js:217). Signed in, they also load from and save to the api_credentials table (frontend/src/App.js:561, frontend/src/App.js:587). Guild name, server and region (us, eu, kr, tw, cn) identify the guild; difficulty is Normal (3), Heroic (4) or Mythic (5) (frontend/src/AnalyzeConfig.js:160).
  gotcha: handleSubmit only checks that Client ID, Secret, guild and server are filled (frontend/src/App.js:682). A wrong guild name is discovered only when WarcraftLogs returns no reports.
- title: Set dates and deaths tracked | short: Dates & first X | sub: optional window, 1-10
  body: Start and end dates are optional; blank means the start of the tier and today (frontend/src/AnalyzeConfig.js:171). Max Deaths to Track is the "first X deaths per pull" ceiling, 1 to 10 (frontend/src/AnalyzeConfig.js:191). On the server the date range is intersected with RAID_DATE_WINDOWS (backend/analysis.py:262) by resolve_report_window (backend/analysis.py:280), and maxCutoff is clamped to 1-10 (backend/app.py:134).
  gotcha: maxCutoff also decides which deaths get defensive analysis at all (backend/app.py:574), and a report with no death inside it reads no defensive data from WarcraftLogs (backend/app.py:386). Raising the Results page's slider above it later shows deaths without a defensive panel.
- title: Roster and cheat deaths | short: Toggles | sub: who counts, cheat deaths
  body: Guild Roster (on by default, frontend/src/App.js:213) means only players on the guild's WarcraftLogs roster count; off, everyone in the reports counts and the roster is not fetched (backend/app.py:145, backend/app.py:165). Cheat Death Detection is disabled for signed-out users (frontend/src/AnalyzeConfig.js:195) and enforced on the server from the bearer token (backend/app.py:120, backend/app.py:143).
  gotcha: If the roster fetch fails or returns nobody, is_guild_member lets everyone through (backend/app.py:181) and the stream says so.
- title: Submit and stream | short: Submit | sub: POST /api/analyze
  body: handleSubmit builds the payload, splitting authorFilters on commas and parsing characterGroups JSON (frontend/src/App.js:703), attaches the Supabase access token when signed in (frontend/src/App.js:719) and fetches /api/analyze. Each SSE line carries either message (shown in the loader), error (thrown) or result (frontend/src/App.js:753).
  gotcha: The analyze route is limited to 60 calls per client IP per hour (backend/app.py:53); the 429 JSON body becomes the form's error (frontend/src/App.js:730).
- title: Watch the loader | short: Loader | sub: progress, Cancel
  body: While loading is true, an overlay with the current tier's boss video, the latest stage message and a Cancel button covers the page (frontend/src/App.js:1535). Cancel aborts the fetch through its AbortController (frontend/src/App.js:657) and the form shows "Analysis cancelled" (frontend/src/App.js:952).
- title: Land on results | short: Results | sub: store, navigate
  body: On the result line the app copies meta.cheatDeathEnabled back into the form (frontend/src/App.js:763), sets the data, writes it to IndexedDB (frontend/src/App.js:550) and to the Recent runs list (frontend/src/App.js:937), then navigates to /results (frontend/src/App.js:940).
```

## Diagram

```diagram
lane ui Browser
lane api Flask API
lane ext External
node form lane=ui color=process "Analyze form" "AnalyzeConfig.js"
node submit lane=ui color=process "handleSubmit" "fetch + stream"
node loader lane=ui color=process "Loader overlay" "stage text"
node results lane=ui color=safe "/results" "data in state"
node analyze lane=api color=process "POST /api/analyze" "SSE generator"
node clamp lane=api color=caution "Clamp inputs" "cutoff, dates, auth"
node wcl lane=ext color=structural "WarcraftLogs" "via proxy"
node supa lane=ext color=structural "Supabase" "token check, cache"
edge form -> submit "Analyze"
edge submit -> analyze "POST JSON"
edge analyze -> clamp "validate"
edge clamp -> wcl "reports"
edge clamp -> supa color=structural "verify token"
edge analyze -> loader "data lines"
edge loader -> results color=safe "result"
```

## Context map

```context
depends-on: [[frontend-pages-and-routing]] — the /analyze route and the shared config state in App.js
depends-on: [[frontend-landing-and-art]] — raid-card and lineup boss art, and the loader video
depends-on: [[backend-api-endpoints]] — POST /api/analyze and its rate limiter
depends-on: [[backend-analysis-pipeline]] — report fetch, fight filtering, dedup, death ranking
depends-on: [[backend-death-counting]] — slot and inWipe on every death
depends-on: [[backend-caching-and-limits]] — finished-report caches and the 60/hour limit
depends-on: [[warcraftlogs]] — OAuth token, guild reports, roster, fights and events
depends-on: [[auth]] — the optional bearer token that unlocks cheat-death detection
depends-on: [[data-model]] — api_credentials for signed-in users, report_cache on the server
provides: the analysis result object (meta, events, participation, icons, ability text)
provides: browser-local persistence of the last result and five recent runs
relied-on-by: [[feat-results]] — renders the result this page produces
relied-on-by: [[feat-saved]] — saves the result and its config
relied-on-by: [[feat-share]] — shares the result and its config
```

## Reference

| Item {kind} | Where | Notes |
|---|---|---|
| `/analyze` {route} | `frontend/src/App.js:1577` | renders `AnalyzeConfig` with config, handlers, user |
| `AnalyzeConfig` {component} | `frontend/src/AnalyzeConfig.js:28` | raid grid, lineup, form, run button |
| `RAIDS` {component} | `frontend/src/AnalyzeConfig.js:12` | raid cards; `final` is card art, `bosses` the lineup |
| `RAID_ZONES` {component} | `frontend/src/App.js:30` | raid key to reportZone and fightZone |
| `handleSubmit` {component} | `frontend/src/App.js:681` | validation, payload, stream reader |
| `POST /api/analyze` {api} | `backend/app.py:109` | SSE stream; limited 60/hour per IP |
| `clientId`, `clientSecret` {field} | `backend/app.py:125` | WarcraftLogs V2 client; required |
| `guildName`, `server`, `region` {field} | `backend/app.py:127` | required |
| `selectedRaid`, `fightZone` {field} | `backend/app.py:130` | raid key drives the encounter allowlist |
| `difficulty` {field} | `backend/app.py:132` | 3 Normal, 4 Heroic, 5 Mythic |
| `maxCutoff` {field} | `backend/app.py:134` | clamped to 1-10, default 5 |
| `startDate`, `endDate` {field} | `backend/app.py:135` | narrowed to the tier window |
| `authorFilters`, `characterGroups` {field} | `backend/app.py:141` | no form inputs today; sent as empty |
| `enableCheatDeath` {field} | `backend/app.py:143` | honored only with a valid session |
| `rosterOnly` {field} | `backend/app.py:145` | default on; off skips the roster fetch |
| `RAID_ENCOUNTERS` {server} | `backend/analysis.py:234` | per-raid encounter ID allowlist |
| `RAID_DATE_WINDOWS` {server} | `backend/analysis.py:262` | per-raid outer date bounds |
| `fpx.wclCredentials` {storage} | `frontend/src/api.js:21` | localStorage, this browser only |
| `sharedAnalysisData` {storage} | `frontend/src/App.js:552` | IndexedDB `FloorPovDB`, last result |
| `recentRuns` {storage} | `frontend/src/App.js:453` | IndexedDB, last 5 runs |

## Invariants

- **MUST** the server clamp `maxCutoff` to 1-10 (`backend/app.py:134`); the form's `min`/`max` are only a hint.
- **MUST** user dates only narrow the raid's tier window, never widen it (`backend/analysis.py:280`), so a run never pages through a guild's whole history.
- **NEVER** run cheat-death detection for a caller without a valid Supabase session, whatever the request body says (`backend/app.py:143`). The stream tells the caller it was skipped (`backend/app.py:152`).
- **MUST** fights be kept only when their encounter ID is in the selected raid's `RAID_ENCOUNTERS` set (`backend/analysis.py:315`); dungeon bosses never enter a raid's numbers.
- **NEVER** store the Client ID or Secret in the browser's analysis history: `stripSecrets` removes them before the IndexedDB writes (`frontend/src/App.js:481`, `frontend/src/App.js:552`).

## Gotchas

- **A stream that ends without a result is an error**: if the server stops mid-analysis without sending one (out of memory, the 15-minute limit), the page shows "The analysis stopped before it finished" instead of leaving the loader spinning (`frontend/src/App.js`).
- **The request body carries the WarcraftLogs secret**: `/api/analyze` receives `clientId` and `clientSecret` in the JSON body (`backend/app.py:125`) and uses them to get a token (`backend/app.py:158`). They are not stored by this route.
- **Old configs still work**: `rosterOnly` treats a missing value as on (`backend/app.py:145`), so saved or shared configs from before the toggle keep their behavior.
- **A partial result is still a result**: reports that fail to load are listed in `meta.failedReports` and announced in the stream (`backend/app.py:461`); reports missing defensive data are announced separately (`backend/app.py:465`). A report whose full read fails is dropped before deaths are read: its pulls come from another log of the same pull if there is one (`backend/app.py:266-278`), and it is not listed in `failedReports`.
- **No zone filter on report fetch**: reports are fetched by date only, because a mixed raid and dungeon night can carry a dungeon zone (`backend/warcraftlogs.py:176`). The encounter allowlist does the separation.

## Related

- [[feat-results]] — what you see once the stream finishes
- [[backend-analysis-pipeline]] — the server side of the stream, step by step
- [[backend-death-counting]] — how "first X deaths" slots and wipes are decided
- [[warcraftlogs]] — the API this page spends points on
- [[auth]] — the session that unlocks cheat-death detection
- [[feat-account]] — where signed-in users keep their API credentials
- [[frontend-pages-and-routing]] — the route and shared state
- [[frontend-landing-and-art]] — the boss art on the raid cards and loader
- [[backend-api-endpoints]] — the endpoint inventory
- [[backend-caching-and-limits]] — caches and rate limits behind the stream
- [[data-model]] — the tables touched along the way
- [[security]] — credential handling and rate limiting
- [[frontend]] — the React app this page lives in
- [[backend]] — the Flask service behind it
