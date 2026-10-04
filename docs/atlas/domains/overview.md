---
id: overview
title: Overview
domain: overview
status: documented
summary:
  - "Floor Pov is a raid-death review site for World of Warcraft guilds: it reads a guild's WarcraftLogs reports and counts who died first on each boss pull."
  - "Three parts: a React site (frontend/), a Flask API (backend/) that does every WarcraftLogs call, and Supabase for accounts, saves, shares and a shared report cache."
  - "A death counts when it is within the first X deaths of its pull (its slot) and is not part of a wipe; cheat deaths are tracked beside real ones for signed-in users."
  - "Each counted death gets a defensive analysis: what killed the player and which defensive they had ready would have saved them."
  - "Eight raid keys are supported in the backend (The War Within and Midnight); the Analyze page offers five of them as raid cards."
tagline: What Floor Pov is, the words it uses, and which raids it covers.
anchors:
  landing_copy: frontend/src/LandingPage.js:186
  footer_blurb: frontend/src/LandingPage.js:258
  api_module: backend/app.py:3
  analyze_route: backend/app.py:82
  raid_encounters: backend/analysis.py:196
  raid_date_windows: backend/analysis.py:224
  analyze_fights: backend/analysis.py:264
  rank_pull_deaths: backend/analysis.py:150
  wipe_window: backend/analysis.py:119
  wipe_threshold: backend/analysis.py:19
  duplicate_pull: backend/analysis.py:56
  cheat_death_ids: backend/features.py:14
  cheat_death_survive: backend/analysis.py:137
  roster_toggle: backend/app.py:118
  max_cutoff_clamp: backend/app.py:107
  frontend_counting: frontend/src/deathCounting.js:22
  raid_cards: frontend/src/AnalyzeConfig.js:12
  raid_zones: frontend/src/App.js:30
  season_two_entry: frontend/src/seasonTwoRaids.js:6
links:
  - hub
  - frontend
  - backend
  - warcraftlogs
  - data-model
  - auth
  - game-data
  - deployment
  - security
  - testing
  - operations
  - feat-analyze
  - feat-results
content_hash: sha256:c5b388805547c2f1c5dda43a8c4af596d32c6434df37d98e6e08089a759d1a77
---
## Summary

- **Floor Pov** is a death-analysis site for World of Warcraft raid guilds. The landing page puts it as: it "reads a WarcraftLogs report and rebuilds the raid night around death — who fell each pull, where the wipes cascaded, and which bosses kept ending you" (`frontend/src/LandingPage.js:186`).
- You give it a guild, server, region, raid, difficulty and your own WarcraftLogs API client. The Flask API (`backend/app.py:82`) reads that guild's reports for the raid, keeps only that raid's boss pulls, and counts the first deaths of each pull per player.
- Every counted death is analyzed: the hits before it, the killing blow, and which defensives the player had ready that would have kept them alive.
- The site never keeps a WarcraftLogs key of its own. Each analysis brings the caller's `clientId` and `clientSecret`.
- What it deliberately leaves alone: deaths inside a **wipe** never count, and players outside the guild roster are left out unless you turn the roster filter off.

## Diagram

The top-level shape. Everything a user sees is the React site; everything that talks to WarcraftLogs is the Flask API; game data is built ahead of time by scripts and committed as Python modules.

```diagram
lane client Browser
node site lane=client color=process "React site" "frontend/src"
lane api Server
node flask lane=api color=process "Flask API" "backend/app.py"
node analysis lane=api color=safe "Death counting" "analysis.py"
node defs lane=api color=safe "Defensive analysis" "defensives.py"
lane data Data
node wcl lane=data color=structural "WarcraftLogs" "GraphQL v2"
node supa lane=data color=structural "Supabase" "auth · saves · cache"
node gen lane=data color=structural "Game data modules" "built by scripts"
edge site -> flask "analyze, save"
edge flask -> wcl "reports, deaths"
edge flask -> analysis "pulls"
edge analysis -> defs color=safe "counted deaths"
edge defs -> gen color=structural "spell data"
edge flask -> supa color=structural "cache, storage"
edge site -> supa color=caution "sign in"
band structural "Substrate · static site + Render + Supabase"
```

## Reference

Supported raids. A raid key is what the Analyze page writes to `selectedRaid`. The backend keeps a fight only if its encounter ID is in that key's set and its difficulty matches (`backend/analysis.py:275`), and it fetches reports only inside the key's date window (`backend/analysis.py:242`). User dates can narrow the window but never widen it.

| Raid key {midnight} | Name on the site | Encounters | Report window | On the Analyze page |
|---|---|---|---|---|
| `midnight-s2-all` {midnight} | Midnight Season 2 (The Venomous Abyss + Nymrissa Wavecaller in the Tidebound Grotto) | 9 (`backend/analysis.py:199`) | 2026-08-13, open-ended (`backend/analysis.py:227`) | yes, via `frontend/src/seasonTwoRaids.js:6` |
| `midnight-all` {midnight} | Midnight Season 1 (Voidspire, Dreamrift, March on Quel'Danas) | 9 (`backend/analysis.py:208`) | 2026-03-12 to 2026-08-23 (`backend/analysis.py:234`) | yes (`frontend/src/AnalyzeConfig.js:19`) |
| `voidspire` {midnight} | The Voidspire | 6 (`backend/analysis.py:205`) | 2026-03-12 to 2026-08-23 | no; only in `RAID_ZONES` (`frontend/src/App.js:34`) |
| `dreamrift` {midnight} | The Dreamrift | 1 (`backend/analysis.py:206`) | 2026-03-12 to 2026-08-23 | no; only in `RAID_ZONES` |
| `queldanas` {midnight} | March on Quel'Danas | 2 (`backend/analysis.py:207`) | 2026-03-12 to 2026-08-23 | no; only in `RAID_ZONES` |
| `manaforge` {tww} | Manaforge Omega | 8 (`backend/analysis.py:201`) | 2025-08-07 to 2026-03-22 (`backend/analysis.py:230`) | yes, and the form's default (`frontend/src/App.js:203`) |
| `undermine` {tww} | Liberation of Undermine | 8 (`backend/analysis.py:202`) | 2025-02-27 to 2025-08-17 (`backend/analysis.py:229`) | yes |
| `nerubar` {tww} | Nerub'ar Palace | 8 (`backend/analysis.py:203`) | 2024-09-05 to 2025-03-09 (`backend/analysis.py:228`) | yes |

The Analyze page's raid cards come from `RAIDS` (`frontend/src/AnalyzeConfig.js:12`), which spreads in `SEASON_TWO_RAIDS`. The names and boss order the Results page uses come from `RAID_ZONES` and `BOSS_ORDER` in `frontend/src/App.js:30` and `frontend/src/App.js:73`, which spread in the same entry. A raid key the backend does not know falls back to the older zone-and-difficulty filter (`backend/analysis.py:280`).

The parts of the system, and where each is documented:

| Part {layer} | What it is | Page |
|---|---|---|
| React site {layer} | Landing, Analyze, Results, Saved and Share pages | [[frontend]] |
| Flask API {layer} | `/api/analyze` stream plus storage routes | [[backend]] |
| WarcraftLogs client {layer} | OAuth token and GraphQL queries | [[warcraftlogs]] |
| Supabase tables {layer} | saves, shares, credentials, report cache | [[data-model]] |
| Sign-in {layer} | Supabase Auth bearer tokens | [[auth]] |
| Generated game data {layer} | defensive catalog, boss spells, armor, raid-wide damage | [[game-data]] |
| Hosting {layer} | static site, Render, Supabase | [[deployment]] |
| Trust boundaries {layer} | secrets, RLS, rate limits | [[security]] |
| Tests and real-log checks {layer} | unittest, jest, `check_*.py` | [[testing]] |
| Running it, new raid tiers {layer} | env vars, health, failure modes | [[operations]] |

## Glossary

- **Report**: one WarcraftLogs log upload. The API lists a guild's reports inside the raid's date window, then reads each report's fights.
- **Pull**: one boss attempt inside a report, kill or wipe. Only fights whose encounter ID belongs to the chosen raid key and whose difficulty matches are kept (`backend/analysis.py:264`).
- **Duplicate pull**: the same attempt logged by two raiders. A pull of the same boss that overlaps an earlier one by 15 seconds or more, or by half its length, is dropped (`backend/analysis.py:56`).
- **Raid tier**: the raid key chosen on the Analyze page, such as `midnight-s2-all`. It fixes which encounter IDs count and which dates are searched (`backend/analysis.py:196`, `backend/analysis.py:224`).
- **Difficulty**: WarcraftLogs' difficulty number: 3 Normal, 4 Heroic, 5 Mythic (`frontend/src/AnalyzeConfig.js:167`, `backend/app.py:233`).
- **Deaths tracked**: the "first X deaths per pull" setting, `maxCutoff`. The server clamps it to 1-10 (`backend/app.py:107`).
- **Slot**: which death of the pull a death was, 1 for the first. A player who dies, is battle-rezzed and dies again takes two slots; a cheat death gets real deaths so far plus one, so it never pushes a real death out (`backend/analysis.py:150`).
- **Wipe**: any 8-second stretch holding 8 real deaths (`backend/analysis.py:19`, `backend/analysis.py:119`). Deaths inside it never count; cheat deaths never make one.
- **Counted death**: a death with `slot <= X` that is not in a wipe. The frontend applies the same rule when you change X on the Results page (`frontend/src/deathCounting.js:22`).
- **Cheat death**: a lethal hit the player survived through an effect such as Cheat Death, Cauterize, Purgatory or Guardian Spirit, recognised by the debuff or heal it leaves (`backend/features.py:14`). It only counts if the player did not die within 5 seconds (`backend/analysis.py:137`), and detection is for signed-in callers only (`backend/app.py:116`).
- **Killing blow**: the ability WarcraftLogs records as having killed the player (`killingAbilityGameID`, `backend/analysis.py:613`). The results page shows its name, icon and in-game description.
- **Defensive**: a player's own damage-reduction or healing button, an external or raid cooldown from someone else, or a consumable (healthstone, potion). The catalog of them is built per game patch from game data; see [[game-data]].
- **Roster filter**: the "Only count guild members" toggle, on by default. On, only players on the guild's WarcraftLogs roster count; off, everyone in the reports counts and the roster is not fetched (`backend/app.py:118`, `backend/app.py:154`).
- **Character groups**: alts folded into a main character, so their deaths and pulls add up under one name (`backend/analysis.py:34`).

## Gotchas

- **Three raid keys exist only on the server side**: `voidspire`, `dreamrift` and `queldanas` are in `RAID_ENCOUNTERS` and in `RAID_ZONES` but not in the Analyze page's `RAIDS`, so the page never offers them. `midnight-all` covers all three.
- **The form defaults to an old tier**: the initial config selects `manaforge` (`frontend/src/App.js:203`), not the current season.
- **Only the newest tier is open-ended**: when a tier's successor opens, its window must get an end date (successor's raid opening plus 5 days), or analyses of the old tier keep listing every report up to today. Midnight Season 1 ends 2026-08-23 (`backend/analysis.py:231`); `test_only_the_newest_tier_is_open_ended` fails if a tier is left open (`backend/test_raid_selection.py`).

## Related

- [[hub]] — the request path end to end
- [[frontend]] — the React site and its pages
- [[backend]] — the Flask API that runs every analysis
- [[warcraftlogs]] — the external API all data comes from
- [[data-model]] — what Supabase stores
- [[auth]] — sign-in and what it unlocks
- [[game-data]] — the pre-built spell, boss and armor data
- [[deployment]] — where each part is hosted
- [[security]] — secrets, row-level security and rate limits
- [[testing]] — unit tests and real-log checks
- [[operations]] — environment, failure modes and adding a raid tier
- [[feat-analyze]] — the Analyze form as a user sees it
- [[feat-results]] — how counted deaths are shown
