---
id: frontend-pages-and-routing
title: Pages & Routing
domain: frontend
status: documented
summary:
  - "Two nested route tables in App.js: /terms and /privacy at the top level, then /, /analyze, /results and /saved inside a catch-all."
  - "Pages share state by living inside one component; navigating never refetches, it only changes which view of the same state renders."
  - "A share link is /results?share=<id>; the app fetches it once per id and merges its config without the viewer's credentials."
  - "The analysis arrives as a server-sent-event stream over a POST; the browser splits on blank lines and handles error, message and result payloads."
  - "Cancel aborts the fetch with an AbortController; the loader overlay sits above whatever route is showing."
tagline: Which URL shows what, how state moves between pages, and how the analysis stream is read.
anchors:
  outer_routes: frontend/src/App.js:1386
  inner_routes: frontend/src/App.js:1537
  full_bleed: frontend/src/App.js:186
  share_effect: frontend/src/App.js:333
  load_shared: frontend/src/App.js:297
  load_saved: frontend/src/App.js:322
  open_recent: frontend/src/App.js:488
  handle_submit: frontend/src/App.js:663
  stream_loop: frontend/src/App.js:718
  result_branch: frontend/src/App.js:742
  cancel: frontend/src/App.js:639
  raid_change: frontend/src/App.js:652
  loader_overlay: frontend/src/App.js:1507
  scroll_top: frontend/src/App.js:173
  backend_analyze: backend/app.py:82
  backend_result: backend/app.py:610
invariants:
  - "MUST: a given ?share= id is requested at most once per page life (attemptedShareRef), so a failing share cannot loop."
  - "MUST: an incoming ?share= link wins over the IndexedDB restore of the last analysis."
  - "NEVER: a shared, saved or recent config replaces the viewer's clientId or clientSecret."
  - "MUST: the stream reader flushes the decoder and processes the remaining buffer before it stops on stream end."
links:
  - frontend
  - frontend-results-view
  - frontend-landing-and-art
  - backend
  - auth
  - feat-analyze
  - feat-share
  - feat-saved
content_hash: sha256:50c65dc1f90f03749a6b8550d9f804ff8e9bd2d9230e92c84c0ff17fec2b824a
---
## Summary

- Routing is React Router 7 inside `BrowserRouter` (`frontend/src/index.js:10`). `App.js` declares an outer `<Routes>` for the legal pages and a catch-all `/*` that holds a second `<Routes>` for the app surfaces (`frontend/src/App.js:1386`, `frontend/src/App.js:1537`).
- Every page reads from the same `WarcraftLogsApp` state, so moving from Analyze to Results is a navigation, not a data handoff.
- Results can come from four places: a fresh analysis, a share link, a saved report or a recent run. Each path ends by calling `setData` and navigating to `/results`.

## How it works

#### The routes

| Path | Renders | Notes |
|---|---|---|
| `/terms` | `TermsOfService` | Outer table, own layout (`frontend/src/App.js:1387`) |
| `/privacy` | `PrivacyPolicy` | Outer table (`frontend/src/App.js:1396`) |
| `/` | `LandingPage` | Inner table (`frontend/src/App.js:1538`) |
| `/analyze` | `AnalyzeConfig` | Inner table; gets `config`, `handleSubmit`, `handleRaidChange` (`frontend/src/App.js:1549`) |
| `/results` | Results markup inline in `App.js` | Filters, matrix, player list (`frontend/src/App.js:1567`) |
| `/results?share=<id>` | Same, after loading the share | Effect at `frontend/src/App.js:333` |
| `/saved` | `SavedReports` inside the rail layout | `frontend/src/App.js:2206` |
| any other path | The `/*` wrapper with no inner match | The share modal and loader overlay can still render |

These four paths render full-bleed (`fpx-landing-wrap`); anything else gets the older 1400px `analysis-content` container (`frontend/src/App.js:186`, `frontend/src/App.js:1504`). `ScrollToTop` resets the window on every path change (`frontend/src/App.js:173`).

#### How results reach /results

```steps
- title: Fresh analysis | short: Analyze | sub: POST /api/analyze
  body: handleSubmit checks the four required fields, saves credentials to the user's account if signed in (not awaited), clears old data and opens the stream (App.js:663). On the result payload it stores data, writes a recent run and navigates to /results (App.js:917, App.js:920).
- title: Share link | short: Share | sub: GET /api/shared/:id
  body: When location.search carries share=, the effect calls loadSharedResults once per id. It sets data, merges the shared config through stripSecrets, and replaces the URL with /results plus the same query (App.js:297, App.js:312).
  gotcha: The attempted id is kept in a ref (App.js:333), so an error is shown once instead of retrying forever.
- title: Saved report | short: Saved | sub: GET /api/saved/:id
  body: SavedReports fetches the full analysis with the session token, then hands it to handleLoadSavedReport, which resets expansion and sort, merges config without secrets and navigates to /results (SavedReports.js:35, App.js:322).
- title: Recent run | short: Recent | sub: IndexedDB, no account
  body: The Results header and the empty state list the last 5 runs. openRecentRun merges that run's stripped config and data (App.js:488).
- title: Refresh | short: Refresh | sub: restore last analysis
  body: On mount, unless a share id is present, the last analysis is read back from IndexedDB and shown (App.js:516). Saving back happens only when data changes, not on each form keystroke (App.js:535).
```

#### Reading the analysis stream

The backend answers `POST /api/analyze` with a stream of `data: {json}\n\n` frames (`backend/app.py:82`, final frame at `backend/app.py:610`). The browser does not use `EventSource`, because the request is a POST with a JSON body. Instead it reads `response.body` directly:

- Before the stream, a non-OK HTTP status is turned into an error from the JSON `error` field if there is one (`frontend/src/App.js:712`).
- Each chunk is decoded and appended to a buffer, the buffer is split on blank lines, and the last partial piece is kept for the next read (`frontend/src/App.js:722`).
- For each `data: ` frame: `error` throws, `message` updates the loader text, `result` finishes the run (`frontend/src/App.js:738`).
- On the result, `meta.cheatDeathEnabled` overwrites the form's checkbox, so the UI reflects what the server actually ran (`frontend/src/App.js:743`).
- The session token is attached when present, so the server can allow cheat-death detection for signed-in users (`frontend/src/App.js:701`).

## Diagram

```diagram
lane in Ways in
node submit lane=in color=process "Analyze submit" "POST /api/analyze"
node share lane=in color=process "Share link" "?share=id"
node saved lane=in color=process "Saved report" "GET /api/saved/id"
node recent lane=in color=process "Recent run" "IndexedDB"
lane state Shell state
node strip lane=state color=safe "stripSecrets" "config merge"
node data lane=state color=safe "setData" "results in state"
lane out Out
node results lane=out color=process "/results" "rendered view"
node idb lane=out color=structural "IndexedDB" "last + recent"
edge submit -> data "stream result"
edge share -> strip "config"
edge saved -> strip "config"
edge recent -> strip "config"
edge strip -> data "merge"
edge data -> results "navigate"
edge data -> idb color=structural "persist"
```

## Context map

```context
depends-on: [[backend]] — /api/analyze stream, /api/shared, /api/saved, /api/share
depends-on: [[auth]] — the Supabase session token attached to analyze and saved calls
depends-on: [[frontend]] — the shell state these routes read from
provides: URL routes for every surface, including share links
provides: the client-side reader of the analysis event stream
relied-on-by: [[frontend-results-view]] — renders whatever data this flow stored
relied-on-by: [[feat-analyze]] — the submit-to-results path
relied-on-by: [[feat-share]] — loading /results?share=
relied-on-by: [[feat-saved]] — opening a saved analysis
```

## Invariants

- **MUST** request a given `?share=` id at most once per page life; `attemptedShareRef` (`frontend/src/App.js:333`) blocks repeats so a failing share cannot loop.
- **MUST** let an incoming `?share=` link win over the IndexedDB restore; the restore effect returns early when a share id is present and skips if data already loaded (`frontend/src/App.js:517`, `frontend/src/App.js:521`).
- **NEVER** let a shared, saved or recent config replace the viewer's `clientId` or `clientSecret`; each merge goes through `stripSecrets` (`frontend/src/App.js:310`, `frontend/src/App.js:326`, `frontend/src/App.js:493`).
- **MUST** flush the decoder and process the remaining buffer before stopping on stream end, or the final `result` frame can be lost (`frontend/src/App.js:726`).

## Gotchas

- **Cancel only aborts the browser side**: `handleCancel` aborts the fetch and hides the loader (`frontend/src/App.js:639`). The rail buttons in the loader also cancel before navigating (`frontend/src/App.js:1514`).
- **Home and New Analysis clear results**: leaving Results through the rail's Home or Analyze buttons, or the New Analysis button, calls `setData(null)` (`frontend/src/App.js:1578`, `frontend/src/App.js:1611`). The run is still in Recent.
- **Logout clears loaded data**: `handleLogout` signs out, resets stored credentials, clears `data` and turns cheat-death off (`frontend/src/App.js:600`).
- **Raid choice writes three fields**: `handleRaidChange` copies `reportZone` and `fightZone` from `RAID_ZONES` into config alongside `selectedRaid` (`frontend/src/App.js:652`). A raid key missing from `RAID_ZONES` would throw here.
- **The header date is "now"**: the Results heading prints today's date, not when the analysis ran (`frontend/src/App.js:1644`). The run time lives in `meta.generatedAt`.

## Related

- [[frontend]] — the shell and module map
- [[frontend-results-view]] — what /results draws from the stored data
- [[frontend-landing-and-art]] — what / and /analyze show
- [[backend]] — the endpoints these routes call
- [[auth]] — the session that unlocks saved reports and cheat-death detection
- [[feat-analyze]] — the analyze slice end to end
- [[feat-share]] — share links end to end
- [[feat-saved]] — saved analyses end to end
