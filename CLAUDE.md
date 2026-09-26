# Floor Pov (floorpov.gg)

WarcraftLogs death-analysis site for WoW raid guilds.
- `frontend/`: React (CRA) site.
- `backend/`: Flask API on Render, at `deathwarcraftlogs-api.onrender.com`.
- Storage: Supabase.

## Working with the owner

- **Preview before anything goes live.** Show screenshots or a preview page and wait for approval before merging. Merging to `main` auto-deploys.
- The owner isn't deep into git. Explain branches and PRs in plain terms, and don't assume they'll run commands.
- When work is blocked by a network host, name the exact host to allow (Network access in the environment settings). Don't ask for broad access.

## Art rules

Apply these to any art update without being asked.

### Backgrounds (landing page only)

- **Only official Blizzard artwork:** key art and cinematic stills from Blizzard's press kits (`blizzard.gamespress.com`), matching the existing set in `frontend/public/art/backgrounds/`.
- **Never** in-game screenshots, fan art, wallpapers from third-party sites, or logos.
- Each tier's patch press kit usually has one key art image, named like `*_Key_Art.jpg`. Everything else in those kits is usually screenshots, so leave it out.
- Process the same way as the existing images:
  - Downscale to 2200px wide.
  - JPEG quality 72, progressive.
  - Kebab-case filename named after the art, e.g. `curse-of-ulatek.jpg`.
- Add the slug to `BACKGROUNDS` in `frontend/src/LandingPage.js`, current tier first. One is picked at random per page load.
- Backgrounds stay on the landing page. Don't add them to the Analyze, Results or Saved pages.

### Boss strip (landing page)

- **Only official Blizzard creature renders** (3D model renders), fetched with `frontend/scripts/fetch-boss-renders.py`.
  - Model IDs come from `wago.tools`; images come from `render.worldofwarcraft.com`.
  - Output is 300px-tall transparent `.webp` tiles in `frontend/public/art/bosses/`.
- Every boss in the current tier gets a tile, including world bosses and lair bosses such as Nymrissa Wavecaller.
- The current tier goes first in `BOSS_STRIP`, with the correct zone label.
- Multi-boss fights show every member on one tile: add the slug to `COUNCIL` in both `LandingPage.js` and the script.
- **Look at every render before shipping.** If one is broken (a spell effect, duplicate models, a placeholder), pin a good display ID in `DISPLAY_OVERRIDE`.
- Never ship a boss without art; a missing image shows as an empty tile.

### Hosts needed for art work

`blizzard.gamespress.com`, `fservus20221227.blob.core.windows.net` (full-size press kit files), `wago.tools`, `render.worldofwarcraft.com`.

## New tier checklist

1. Follow the Season 2 example: commit `0e825bb` (PR #1).
   - Backend: encounter IDs and date window in `backend/analysis.py` (`RAID_ENCOUNTERS`, `RAID_DATE_WINDOWS`), plus a test in `backend/test_raid_selection.py`.
   - Frontend: a raid entry like `frontend/src/seasonTwoRaids.js`, wired into `AnalyzeConfig.js` and `App.js`.
   - Encounter IDs come from BigWigs' raid folders.
2. Update the boss strip and backgrounds per the art rules above.
3. Add a line to `UPDATES` in `LandingPage.js`.

## Code rules

- **Never** send, store, share or log the WarcraftLogs Client ID/Secret beyond the `/api/analyze` call. Strip them with `stripSecrets` (frontend) and `strip_secrets` (backend).
- Account and saved-report endpoints must verify the Supabase session with `@require_user`. Never trust a `user_id` sent in the request.
- Signed-in-only features (such as cheat-death detection) are enforced on the server, not just in the UI.
- All backend calls go through `frontend/src/api.js`. Don't hard-code the backend URL.
- Saved reports: 5 per user. Shares: 72 hours, compressed, stored in Supabase `shared_results`.

## Checks before pushing

- Backend: `cd backend && python -m pytest -q`
- Frontend: `cd frontend && CI=true npx react-scripts build && CI=true npx react-scripts test --watchAll=false`. `CI=true` turns lint warnings into errors.
- To view results without WarcraftLogs, open `http://localhost:3000/results?mock=1` (localhost only).
