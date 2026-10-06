---
id: frontend
title: Frontend
domain: frontend
status: documented
summary:
  - "A Create React App site: one large shell component (App.js) owns all state, routing and the analysis stream; smaller files render each surface."
  - "The browser talks to two back ends: the Flask API (analysis, shares, saved reports, account delete) and Supabase directly (auth and stored WarcraftLogs credentials)."
  - "The API base URL is chosen at runtime: REACT_APP_API_URL if set at build time, else localhost:5000 on a local host, else /api on the page's own host."
  - "WarcraftLogs credentials never leave the browser except in the /api/analyze call; stripSecrets removes them from shares, saves and local history."
  - "The latest analysis and the last 5 runs persist in IndexedDB, so a refresh or a closed tab does not lose results."
tagline: The React site raid officers use, from landing page to the per-death breakdown.
anchors:
  entry: frontend/src/index.js:9
  app_shell: frontend/src/App.js:187
  api_url: frontend/src/api.js:8
  api_fetch: frontend/src/api.js:55
  strip_secrets: frontend/src/api.js:43
  local_creds: frontend/src/api.js:21
  supabase_client: frontend/src/supabaseClient.js:6
  session_only: frontend/src/supabaseClient.js:12
  warmup: frontend/src/App.js:262
  indexeddb: frontend/src/App.js:380
  design_tokens: frontend/src/fp-design.css:6
  rail: frontend/src/FpxRail.js:8
invariants:
  - "MUST: every request to the Flask API resolves its base URL through API_URL in api.js; there is no second hard-coded backend host."
  - "NEVER: clientId or clientSecret are written to a share, a saved report, the recent-runs list or the persisted last analysis; stripSecrets runs on each of those paths."
  - "MUST: a config loaded from a share, a saved report or a recent run is merged through stripSecrets so it cannot overwrite the viewer's own credentials."
  - "MUST: storage access (localStorage, cookies) is wrapped in try/catch so a private window or blocked storage degrades to an empty form, not a crash."
links:
  - frontend-pages-and-routing
  - frontend-landing-and-art
  - frontend-results-view
  - backend
  - auth
  - data-model
  - deployment
  - security
  - testing
  - feat-analyze
  - feat-results
  - feat-saved
  - feat-share
  - feat-account
content_hash: sha256:9228a618b4a338db451fa6028fcdb03dedda38e1553498d35457c32f15dd86b1
---
## Summary

The **frontend** is the React (Create React App) site at the top of Floor Pov. It renders the landing page, the Analyze form, the Results breakdown and the Saved list, and it consumes the backend's streamed analysis directly in the browser.

- The app mounts in `frontend/src/index.js:9` inside a `BrowserRouter`, and loads two style sheets: the older `index.css` and the `fpx-` design system in `fp-design.css` (`frontend/src/index.js:4`).
- Almost all state lives in one component, `WarcraftLogsApp` in `frontend/src/App.js:187`. Child surfaces receive props and callbacks; there is no global store.
- Two network partners: the Flask API through `apiFetch` (`frontend/src/api.js:55`) and Supabase through the shared client (`frontend/src/supabaseClient.js:6`).
- What it deliberately does not do: it never computes deaths, slots or defensive verdicts itself. Those arrive pre-computed from the backend; the browser only counts, filters and displays them.

## How it works

You can think of `App.js` as the switchboard. It owns the analysis config, the loaded results, the signed-in user and every modal flag. Each page is a thin renderer that reads from it and calls back into it.

```steps
- title: Boot and warm the API | short: Boot | sub: warm the API, restore session
  body: On mount the app fires a fire-and-forget GET /api/health so a cold Lambda copy starts while the user reads (App.js:262). In parallel it restores the Supabase session, or signs out locally if a "stay logged in = off" session outlived its browser (App.js:277).
  gotcha: The health ping swallows every error on purpose. A slow or down backend never blocks the page from rendering.
- title: Restore last results | short: Restore | sub: IndexedDB, unless a share link
  body: Unless the URL carries ?share=, the app reads the last analysis from IndexedDB (database FloorPovDB, store analysisData, key sharedAnalysisData) and puts it back on screen (App.js:531). The recent-runs list is loaded the same way and re-saved to scrub credentials older versions stored (App.js:515).
- title: Fill credentials | short: Credentials | sub: browser first, then account
  body: The config starts with credentials remembered in localStorage under fpx.wclCredentials (api.js:21, App.js:199). When a user signs in, their stored row in the Supabase api_credentials table overrides those (App.js:561).
- title: Run the analysis | short: Analyze | sub: POST and read the stream
  body: handleSubmit POSTs the config to /api/analyze and reads the response body as a server-sent-event stream, updating the loader text on each message and storing the final result (App.js:681). See frontend-pages-and-routing for the stream format.
- title: Render and persist | short: Results | sub: count, filter, display
  body: The result is stored in state, saved to IndexedDB and to the recent-runs list, and the app navigates to /results (App.js:937). Every table on that page is derived from the stored result plus the current filters.
```

## Diagram

The component map. Blue edges are props and callbacks from the shell; teal boxes are external services.

```diagram
lane shell App shell
node index lane=shell color=structural "index.js" "BrowserRouter"
node app lane=shell color=process "App.js" "state + routes"
node rail lane=shell color=structural "FpxRail" "left nav"
lane pages Pages and modals
node landing lane=pages color=process "LandingPage" "/"
node analyze lane=pages color=process "AnalyzeConfig" "/analyze"
node results lane=pages color=process "Results view" "/results (in App.js)"
node saved lane=pages color=process "SavedReports" "/saved"
node modals lane=pages color=process "Auth / Settings" "modals"
lane leaf Results leaves
node deathrow lane=leaf color=safe "DeathRow" "one death"
node defpanel lane=leaf color=safe "DefensivePanel" "per-player chips"
node counting lane=leaf color=safe "deathCounting" "slot / inWipe"
lane ext Services
node api lane=ext color=structural "Flask API" "api.js API_URL"
node supa lane=ext color=structural "Supabase" "auth + credentials"
node idb lane=ext color=structural "IndexedDB" "last run, recent 5"
edge index -> app "mounts"
edge app -> rail "renders"
edge app -> landing "route"
edge app -> analyze "route"
edge app -> results "route"
edge app -> saved "route"
edge app -> modals "flags"
edge results -> deathrow "per death"
edge results -> defpanel "per player"
edge results -> counting "isCounted"
edge app -> api color=process "fetch"
edge saved -> api color=process "apiFetch"
edge modals -> supa color=process "supabase-js"
edge app -> idb color=structural "persist"
```

## Reference

The main modules. Filter by role.

| Module {shell} | What it does | Anchor |
|---|---|---|
| `App.js` {shell} | The shell: config, results, user, modals, both route tables, the analysis stream reader, and the Results page markup | `frontend/src/App.js:187` |
| `index.js` {shell} | Mounts `<App />` in `React.StrictMode` and `BrowserRouter`; imports both style sheets | `frontend/src/index.js:9` |
| `FpxRail.js` {shell} | The shared collapsible left nav (Home, Run Analysis, Results, Saved) | `frontend/src/FpxRail.js:8` |
| `AppHeader.js` {shell} | A small top header with brand and auth buttons | `frontend/src/AppHeader.js:5` |
| `LandingPage.js` {page} | Home: random background art, boss strip marquee, feature cards, recent updates | `frontend/src/LandingPage.js:105` |
| `AnalyzeConfig.js` {page} | The Analyze form: raid cards, boss lineup, credentials and scope fields | `frontend/src/AnalyzeConfig.js:28` |
| `seasonTwoRaids.js` {page} | The Midnight Season 2 raid entry, shared by `AnalyzeConfig.js` and `App.js` | `frontend/src/seasonTwoRaids.js:6` |
| `SavedReports.js` {page} | Lists, opens and deletes the signed-in user's saved analyses | `frontend/src/SavedReports.js:10` |
| `TermsOfService.js` / `PrivacyPolicy.js` {page} | Static legal pages at `/terms` and `/privacy` | `frontend/src/TermsOfService.js:6` |
| `DeathRow.js` {results} | One death: killing blow, health bar, defensive icon strip, tooltips | `frontend/src/DeathRow.js:235` |
| `DefensivePanel.js` {results} | Per-player defensive rollup chips | `frontend/src/DefensivePanel.js:20` |
| `deathCounting.js` {results} | Decides which deaths count toward "first X deaths per pull" | `frontend/src/deathCounting.js:22` |
| `Auth.js` {account} | Sign-in / sign-up / reset modal with a Cloudflare Turnstile CAPTCHA | `frontend/src/Auth.js:8` |
| `Settings.js` {account} | Edit stored WarcraftLogs credentials, email, password; delete the account | `frontend/src/Settings.js:6` |
| `SaveReportDialog.js` {account} | Names and saves the current analysis (7, 14 or 30 days) | `frontend/src/SaveReportDialog.js:7` |
| `InfoModal.js` {account} | The "How it works" modal on the Analyze page | `frontend/src/InfoModal.js:66` |
| `api.js` {plumbing} | `API_URL`, `apiFetch`, `stripSecrets`, browser credential memory | `frontend/src/api.js:9` |
| `supabaseClient.js` {plumbing} | The Supabase client and the "stay logged in" session-only logic | `frontend/src/supabaseClient.js:6` |
| `mockResults.js` {plumbing} | A seeded fixture for `?mock=1` on localhost | `frontend/src/mockResults.js:237` |
| `fp-design.css` {style} | The `fpx-` design system: color tokens on `:root`, layout, loader, boss tiles | `frontend/src/fp-design.css:6` |
| `index.css` {style} | Older global styles, still used by the share modal and `.analysis-shell` | `frontend/src/index.css:112` |

## Standing it up

| Concern | This domain | Source |
|---|---|---|
| Runs on | Static CRA build (`react-scripts build`) served as a single-page app; React 19, React Router 7 | `frontend/package.json` scripts and dependencies |
| Local dev | `npm start` (CRA dev server); talks to a local Flask API on port 5000 | `frontend/src/api.js:9` |
| API base URL | `REACT_APP_API_URL` if set at build time; else `http://localhost:5000` when the host is `localhost` or `127.0.0.1`; else `''`, the page's own host, where CloudFront serves the API under `/api` | `frontend/src/api.js:8` |
| Asset prefix | `PUBLIC_URL` (CRA built-in) prefixes art paths: backgrounds, boss tiles, loader video | `frontend/src/LandingPage.js:127`, `frontend/src/App.js:1550` |
| Supabase | Project URL and the public anon key are constants in code, not env vars | `frontend/src/supabaseClient.js:3` |
| CAPTCHA | Turnstile site key is a constant; tokens are checked by an external Cloudflare Worker before calling Supabase auth | `frontend/src/Auth.js:6`, `frontend/src/Auth.js:72` |
| Secrets | None in the bundle. WarcraftLogs credentials are typed by the user and kept in their own browser or their Supabase row | `frontend/src/api.js:21` |
| SPA fallback | `public/_redirects.txt` holds a `/* /index.html 200` rewrite | `frontend/public/_redirects.txt:1` |

## Environments

| Aspect | Local | Production |
|---|---|---|
| API base | `http://localhost:5000` (unless `REACT_APP_API_URL` is set) | `/api` on floorpov.gg itself (unless `REACT_APP_API_URL` is set) |
| Supabase | Same hard-coded project as production | Same |
| `?mock=1` fixture results | Works: seeds Results with `MOCK_RESULTS` (`frontend/src/App.js:362`) | Ignored: gated to localhost |
| `?loader=1` loader preview | Works: shows the analysis loader overlay (`frontend/src/App.js:373`) | Ignored |
| Backend warm-up ping | Fires against the local API | Fires against the Lambda API on every page load (`frontend/src/App.js:262`) |

## Invariants

- **MUST** every request to the Flask API resolve its base URL through `API_URL` in `frontend/src/api.js:9`; the analyze call, the health ping and `apiFetch` all use it.
- **NEVER** write `clientId` or `clientSecret` into a share, a saved report, the recent-runs list or the persisted last analysis. `stripSecrets` (`frontend/src/api.js:43`) runs on each path: `frontend/src/App.js:635`, `frontend/src/SaveReportDialog.js:31`, `frontend/src/App.js:481`, `frontend/src/App.js:552`.
- **MUST** merge a config loaded from a share, a saved report or a recent run through `stripSecrets`, so it cannot overwrite the viewer's own credentials (`frontend/src/App.js:325`, `frontend/src/App.js:341`, `frontend/src/App.js:508`).
- **MUST** wrap storage access in try/catch so blocked storage leaves an empty form instead of a crash (`frontend/src/api.js:24`, `frontend/src/supabaseClient.js:15`).

## Gotchas

- **App.js is one 2,300-line component**: the Results page and the share modal are inline JSX in `frontend/src/App.js`. A change to results layout is a change to the shell.
- **Supabase settings are not env-driven**: switching Supabase projects means editing `frontend/src/supabaseClient.js:3`, not setting a variable. The anon key there is the public key Supabase expects in browsers.
- **The CAPTCHA check is client-side**: `Auth.js` verifies the Turnstile token with an external Worker and then calls Supabase directly (`frontend/src/Auth.js:72`, `frontend/src/Auth.js:139`). Anything enforcing CAPTCHA server-side has to live in Supabase or the Worker, not this code.
- **Debug globals on window**: each completed analysis sets `window.deathTrackerData`, `window.exportDeathData` and `window.exportAndCopy` (`frontend/src/App.js:769`). `exportDeathData` hard-codes a cutoff of 2 (`frontend/src/App.js:773`), so its "included" flags can differ from what the page shows.
- **SPA rewrite file name**: the rewrite rule lives in `_redirects.txt`. Hosts that read Netlify-style rules look for a file named exactly `_redirects`; check the host's behavior before relying on it for deep links like `/results?share=`.

## Glossary

- **Shell**: `WarcraftLogsApp` in `App.js`, the one component that owns state and both route tables.
- **fpx-**: the class-name prefix of the current design system in `fp-design.css`.
- **Recent runs**: the last 5 completed analyses, kept per browser in IndexedDB with credentials stripped.
- **Warm-up ping**: the unawaited `GET /api/health` on page load that starts a cold Lambda copy.

## Related

- [[frontend-pages-and-routing]] — routes, state handoff between pages and the analysis stream reader
- [[frontend-landing-and-art]] — landing art, boss strip, raid entries and the loader video
- [[frontend-results-view]] — death counting, the matrix, DeathRow and DefensivePanel
- [[backend]] — the Flask API every fetch goes to
- [[auth]] — Supabase sessions, the session-only cookie and CAPTCHA
- [[data-model]] — the api_credentials table and saved/shared analysis storage
- [[deployment]] — how the site and API are hosted on AWS
- [[security]] — credential handling and the client-side CAPTCHA
- [[testing]] — `api.test.js` and `AnalyzeConfig.test.js`
- [[feat-analyze]] — the end-to-end Analyze slice
- [[feat-results]] — the end-to-end Results slice
- [[feat-saved]] — saved analyses
- [[feat-share]] — share links
- [[feat-account]] — account and settings
