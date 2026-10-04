---
id: frontend-landing-and-art
title: Landing Page and Art
domain: frontend
status: documented
summary:
  - "The landing page picks one background per page load: the current tier's art half the time (CURRENT_TIER_CHANCE = 0.5), otherwise any entry of BACKGROUNDS, uniformly."
  - "Boss art is one transparent .webp tile per boss in public/art/bosses, found by slugging the boss name; the landing strip (BOSS_STRIP) and the Analyze page (raid card final, lineup bosses) use the same slug rule."
  - "COUNCIL lists multi-boss encounters three times: a Set in LandingPage.js and AnalyzeConfig.js (fit the whole group in the tile) and a dict in the fetch script (how many models to composite)."
  - "frontend/scripts/fetch-boss-renders.py builds the tiles from wago.tools journal data and render.worldofwarcraft.com creature renders; DISPLAY_OVERRIDE and ENC_OVERRIDE pin bad lookups."
  - "The analysis loader (.fpx-load-orb in App.js) plays a hard-coded looping ulatek-loader.webm with a .jpg poster."
tagline: Background art, the boss strip, raid cards and the loader video, and the script that makes the boss tiles.
anchors:
  boss_strip: frontend/src/LandingPage.js:11
  council_landing: frontend/src/LandingPage.js:64
  current_tier_backgrounds: frontend/src/LandingPage.js:84
  current_tier_chance: frontend/src/LandingPage.js:87
  backgrounds: frontend/src/LandingPage.js:88
  updates: frontend/src/LandingPage.js:97
  background_pick: frontend/src/LandingPage.js:111
  strip_slug: frontend/src/LandingPage.js:206
  raids: frontend/src/AnalyzeConfig.js:12
  council_analyze: frontend/src/AnalyzeConfig.js:23
  boss_img: frontend/src/AnalyzeConfig.js:26
  raid_card_art: frontend/src/AnalyzeConfig.js:43
  season_two_raids: frontend/src/seasonTwoRaids.js:6
  raid_zones: frontend/src/App.js:25
  boss_order: frontend/src/App.js:68
  loader_orb: frontend/src/App.js:1519
  loader_preview: frontend/src/App.js:357
  fetch_bosses: frontend/scripts/fetch-boss-renders.py:14
  enc_override: frontend/scripts/fetch-boss-renders.py:31
  display_override: frontend/scripts/fetch-boss-renders.py:35
  council_script: frontend/scripts/fetch-boss-renders.py:36
  tile_height: frontend/scripts/fetch-boss-renders.py:146
invariants:
  - "MUST: every name in BOSS_STRIP and in a RAIDS entry's final and bosses has a matching public/art/bosses/<slug>.webp; nothing checks this at build time and a missing file renders an empty tile."
  - "MUST: a multi-boss slug is added to all three COUNCIL copies (LandingPage.js, AnalyzeConfig.js, fetch-boss-renders.py), or the tile crops members or the script fetches only one model."
  - "MUST: a raid entry's key matches a RAID_ZONES key in App.js; handleRaidChange reads reportZone and fightZone from RAID_ZONES by that key."
  - "NEVER: the background pick fall through to an empty pool; CURRENT_TIER_BACKGROUNDS is only used when it has entries, but BACKGROUNDS must never be empty."
links:
  - frontend
  - frontend-pages-and-routing
  - frontend-results-view
  - feat-analyze
  - feat-results
  - game-data
  - testing
content_hash: sha256:ebaa784603fe7be46adcf69e742a5f6db96317450e4dc47685bbe671e2ce42e1
---
## Summary

This page covers the art layer of the frontend: what the landing page shows, how boss tiles are named and found, where raid entries live, and the loading video. All of it is static data in a few JavaScript arrays plus files under `frontend/public/art/`.

- **Backgrounds** are JPEGs in `public/art/backgrounds/`, chosen once per page load (`frontend/src/LandingPage.js:111`).
- **Boss tiles** are `.webp` files in `public/art/bosses/`, named by a slug of the boss name (`frontend/src/LandingPage.js:206`, `frontend/src/AnalyzeConfig.js:25`).
- **Raid entries** for the Analyze page are the `RAIDS` array (`frontend/src/AnalyzeConfig.js:12`); the current tier's entry is imported from `seasonTwoRaids.js` (`frontend/src/seasonTwoRaids.js:6`).
- **The loader** is a `<video>` inside `.fpx-load-orb`, shown while an analysis runs (`frontend/src/App.js:1519`).
- What it deliberately does not do: none of these lists is generated or validated. The boss names, the council slugs and the raid lineups are hand-kept copies; a typo is a missing tile, not a build error.

## How it works

You can follow the art from the file on disk to the pixel on screen. Each step below is one place the code reads it.

```steps
- title: Pick a background | short: Background | sub: once per page load
  body: LandingPage memoizes one choice on mount. If CURRENT_TIER_BACKGROUNDS is non-empty and Math.random() < CURRENT_TIER_CHANCE (0.5), it picks uniformly from that list; otherwise it picks uniformly from BACKGROUNDS (LandingPage.js:111-117). With one current-tier image and 16 older ones, the current art shows on about half of loads and each older image on about 1 in 32.
  gotcha: The chosen file is set as an inline background-image with landing-keyart.svg layered behind it as a fallback (LandingPage.js:126-128). A missing JPEG shows the SVG, not an error.
- title: Run the boss strip | short: Boss strip | sub: BOSS_STRIP, doubled marquee
  body: BOSS_STRIP is a list of [name, zone label] pairs (LandingPage.js:11). The page renders it twice in a row inside .fpx-track (LandingPage.js:205) and the CSS animates the track by -50% over 52s (fp-design.css:184, fp-design.css:231), so the second copy makes the loop seamless. Hovering pauses it; prefers-reduced-motion stops it (fp-design.css:185, fp-design.css:882).
- title: Find each tile | short: Slug | sub: name to file name
  body: Each name is lowercased, every run of non-alphanumerics becomes one hyphen, and leading or trailing hyphens are trimmed (LandingPage.js:206). "Vaelgor & Ezzorak" becomes vaelgor-ezzorak.webp. The URL goes into the --img CSS variable on the tile (LandingPage.js:210), which .fpx-boss .art uses as its background (fp-design.css:196).
- title: Fit councils | short: Council | sub: whole group in frame
  body: If the slug is in COUNCIL the tile gets the council class (LandingPage.js:209), which switches the art from auto 116% (crop to the model) to contain (show every member) (fp-design.css:203). AnalyzeConfig.js applies the same rule to the lineup tiles with its own COUNCIL copy (AnalyzeConfig.js:23, AnalyzeConfig.js:123).
- title: Raid cards and lineup | short: Analyze art | sub: final and bosses
  body: Each RAIDS entry has key, name, exp, final and bosses. The raid card's art is the tile of final (AnalyzeConfig.js:43); the lineup under the cards is one tile per name in the selected entry's bosses (AnalyzeConfig.js:122). Clicking a card sends its key to handleRaidChange in App.js, which copies reportZone and fightZone from RAID_ZONES (App.js:651).
- title: Play the loader | short: Loader | sub: while loading is true
  body: When loading is true, App.js draws the .fpx-loadov overlay with a muted, looping, autoplaying video of art/ulatek-loader.webm and art/ulatek-loader.jpg as its poster (App.js:1506, App.js:1519-1524). The CSS sizes it to 212px inside a 190px pulsing orb (fp-design.css:815-821). On localhost, ?loader=1 forces the overlay on for a preview (App.js:357).
  gotcha: The file names are literal in App.js. A new tier's loader means a new file and an edit to both src and poster on lines 1521-1522.
```

## Diagram

Where each art file is read. Teal boxes are files on disk; blue boxes are the code that reads them.

```diagram
lane data Data in code
node strip lane=data color=process "BOSS_STRIP" "LandingPage.js"
node raids lane=data color=process "RAIDS" "AnalyzeConfig.js"
node s2 lane=data color=process "SEASON_TWO_RAIDS" "seasonTwoRaids.js"
node council lane=data color=caution "COUNCIL x3" "keep in sync"
node bglists lane=data color=process "Background lists" "current + older"
lane files Files in public/art
node bosses lane=files color=structural "bosses/*.webp" "300px tall"
node bgs lane=files color=structural "backgrounds/*.jpg" "one per load"
node loader lane=files color=structural "ulatek-loader" ".webm + .jpg"
lane build Build script
node script lane=build color=process "fetch-boss-renders.py" "wago + render"
node ext lane=build color=structural "Blizzard / wago" "external hosts"
edge s2 -> raids "spread in"
edge strip -> bosses "slug"
edge raids -> bosses "final, bosses"
edge council -> bosses color=caution "fit mode"
edge bglists -> bgs "random pick"
edge ext -> script color=structural "csv + jpg"
edge script -> bosses "writes"
```

## Reference

Every art-related constant and file. Filter by where it lives.

| Item {landing} | What it holds | Anchor |
|---|---|---|
| `BOSS_STRIP` {landing} | `[name, zone label]` pairs, current tier first (The Venomous Abyss, then Tidebound Grotto), then older raids | `frontend/src/LandingPage.js:11` |
| `COUNCIL` (Set) {landing} | Slugs of multi-boss tiles shown with `background-size: contain` | `frontend/src/LandingPage.js:64` |
| `CURRENT_TIER_BACKGROUNDS` {landing} | Background slugs for the current tier; currently `curse-of-ulatek` | `frontend/src/LandingPage.js:84` |
| `CURRENT_TIER_CHANCE` {landing} | Probability (0.5) a load draws from the current-tier list | `frontend/src/LandingPage.js:87` |
| `BACKGROUNDS` {landing} | Every older background slug, drawn uniformly the rest of the time | `frontend/src/LandingPage.js:88` |
| `UPDATES` {landing} | `[title, copy, date label]` rows for "Recent updates", newest first; the date is free text | `frontend/src/LandingPage.js:97` |
| `FEATURES` {landing} | The three "What it finds" cards | `frontend/src/LandingPage.js:71` |
| `RAIDS` {analyze} | Raid cards: `key`, `name`, `exp`, `final` (card art), `bosses` (lineup); 4 inline entries plus `SEASON_TWO_RAIDS` | `frontend/src/AnalyzeConfig.js:12` |
| `COUNCIL` (Set) {analyze} | Same slugs as the landing copy, used for lineup tiles | `frontend/src/AnalyzeConfig.js:23` |
| `slug` / `bossImg` {analyze} | Name-to-slug rule and the `PUBLIC_URL/art/bosses/<slug>.webp` path | `frontend/src/AnalyzeConfig.js:25` |
| `SEASON_TWO_RAIDS` {shared} | The `midnight-s2-all` entry: `reportZone: null`, `fightZone: '0'`, `final: "Ula'tek"`, 9 bosses | `frontend/src/seasonTwoRaids.js:6` |
| `RAID_ZONES` {shared} | Per raid key: display name, `reportZone`, `fightZone`; spreads in `SEASON_TWO_RAIDS` | `frontend/src/App.js:25` |
| `BOSS_ORDER` {shared} | Per raid key: Adventure-Guide boss order used to sort results; spreads in `SEASON_TWO_RAIDS` | `frontend/src/App.js:68` |
| Loader `<video>` {loader} | `art/ulatek-loader.webm`, poster `art/ulatek-loader.jpg`; `autoPlay loop muted playsInline` | `frontend/src/App.js:1520` |
| `.fpx-load-orb` CSS {loader} | 190px orb, pulsing glow, video sized 212px with a blue drop shadow | `frontend/src/fp-design.css:815` |
| `BOSSES` {script} | Names the script fetches; a command-line list narrows it to those names | `frontend/scripts/fetch-boss-renders.py:14` |
| `ENC_OVERRIDE` {script} | Lowercased boss name to a fixed JournalEncounter ID (`l'ura` → `2740`) | `frontend/scripts/fetch-boss-renders.py:31` |
| `DISPLAY_OVERRIDE` {script} | Slug to a hand-picked list of display IDs, replacing the journal's (`the-lost-explorers` → `143082`) | `frontend/scripts/fetch-boss-renders.py:35` |
| `COUNCIL` (dict) {script} | Slug to how many distinct display IDs to composite side by side | `frontend/scripts/fetch-boss-renders.py:36` |
| `_boss_results.json` {script} | Per-boss status report the script writes next to itself; gitignored | `frontend/scripts/fetch-boss-renders.py:155`, `frontend/.gitignore:24` |

### How the fetch script builds a tile

Run it with Python and Pillow; it writes straight into `frontend/public/art/bosses/` (`frontend/scripts/fetch-boss-renders.py:11`).

1. **Encounter ID.** `ENC_OVERRIDE` first; otherwise it searches the wago.tools `JournalEncounter` CSV for the longest word of the name, keeps rows whose normalized name equals or contains the boss name, and takes the highest ID (`frontend/scripts/fetch-boss-renders.py:95-104`). The highest ID wins so a recent encounter beats an older one with the same name.
2. **Display IDs.** From the `JournalEncounterCreature` CSV it keeps rows for that encounter, sorted by `OrderIndex`, and collects distinct `CreatureDisplayInfoID`s until it has `COUNCIL[slug]` of them, or 1 (`frontend/scripts/fetch-boss-renders.py:105-115`). `DISPLAY_OVERRIDE` then replaces the list wholesale (`frontend/scripts/fetch-boss-renders.py:116`).
3. **Cut out.** Each `https://render.worldofwarcraft.com/us/npcs/zoom/creature-display-<id>.jpg` is flood-filled from eight border seeds to remove the flat background, feathered, and cropped to the model (`frontend/scripts/fetch-boss-renders.py:54-82`, `frontend/scripts/fetch-boss-renders.py:123`).
4. **Composite.** Models are scaled to 560px tall and laid left to right with a 10% overlap and a soft shadow, cropped, then resized to `TILE_H = 300` and saved as WebP quality 82 (`frontend/scripts/fetch-boss-renders.py:128-148`).

## Context map

Where this sub-page sits in the larger system.

```context
depends-on: [[frontend]] — App.js owns loading state, RAID_ZONES and BOSS_ORDER
depends-on: [[game-data]] — encounter and creature display IDs come from wago.tools game tables
depends-on: render.worldofwarcraft.com — official creature renders the script cuts out
provides: background image choice and the boss marquee on /
provides: raid cards and boss lineup art on /analyze
provides: the looping boss video on the analysis loader
relied-on-by: [[feat-analyze]] — the raid picker and the loader during a run
relied-on-by: [[frontend-pages-and-routing]] — mounts LandingPage at / and AnalyzeConfig at /analyze
relied-on-by: [[frontend-results-view]] — BOSS_ORDER sorts boss chips and per-boss sections
```

## Standing it up

| Concern | This area | Source |
|---|---|---|
| Asset prefix | Background, boss tile and loader URLs are built from `process.env.PUBLIC_URL` (CRA built-in) | `frontend/src/LandingPage.js:127`, `frontend/src/AnalyzeConfig.js:26`, `frontend/src/App.js:1521` |
| Boss tile script | `python frontend/scripts/fetch-boss-renders.py ["Boss Name" ...]`; needs Pillow and outbound access to `wago.tools` and `render.worldofwarcraft.com` | `frontend/scripts/fetch-boss-renders.py:3`, `frontend/scripts/fetch-boss-renders.py:8` |
| Tile format | Transparent WebP, 300px tall, width follows the model | `frontend/scripts/fetch-boss-renders.py:146-148` |
| Loader file | `frontend/public/art/ulatek-loader.webm` is 512x512 VP9 with an alpha channel at 30 fps (read from the file's stream headers); its poster is `ulatek-loader.jpg` | `frontend/src/App.js:1521-1522` |
| Background files | `frontend/public/art/backgrounds/<slug>.jpg`, 2200px wide, JPEG quality 72, progressive (read from the files themselves); the slug is what goes in `CURRENT_TIER_BACKGROUNDS` or `BACKGROUNDS` | `frontend/src/LandingPage.js:84-95`, `frontend/src/LandingPage.js:127` |
| Hosting | All art is committed under `frontend/public/art/` and served from the site itself, never hotlinked, so a source page moving or disappearing can't break the landing page and no third party sees visitors' requests | `frontend/src/LandingPage.js:127` |
| Fallback | `landing-keyart.svg` sits behind the chosen photo and shows only if that image fails to load | `frontend/src/LandingPage.js:128` |
| Attribution | The footer carries the Blizzard non-affiliation, trademark and key-art notice that fan use of the art relies on; revisit the art's use if the site ever becomes commercial | `frontend/src/LandingPage.js:274-276` |
| Secrets | None. The script sends a browser User-Agent and Referer and no credentials | `frontend/scripts/fetch-boss-renders.py:10`, `frontend/scripts/fetch-boss-renders.py:47` |

## Invariants

- **MUST** every name in `BOSS_STRIP` and in a `RAIDS` entry's `final` and `bosses` have a matching `frontend/public/art/bosses/<slug>.webp`. Nothing checks it: the tile's `--img` points at a file that does not exist and the tile renders empty (`frontend/src/LandingPage.js:210`, `frontend/src/AnalyzeConfig.js:26`).
- **MUST** add a multi-boss slug to all three `COUNCIL` copies (`frontend/src/LandingPage.js:64`, `frontend/src/AnalyzeConfig.js:23`, `frontend/scripts/fetch-boss-renders.py:36`). Missing from a Set, the tile crops members off; missing from the dict, the script fetches only one model.
- **MUST** give a raid entry a `key` that exists in `RAID_ZONES`; `handleRaidChange` reads `reportZone` and `fightZone` from it with no fallback (`frontend/src/App.js:653-658`).
- **NEVER** let `BACKGROUNDS` be empty. The current-tier pool is guarded by its length, but the fallback pool is not, and an empty pool yields `undefined.jpg` (`frontend/src/LandingPage.js:113-116`).

## Gotchas

- **Raid lineups exist twice**: `RAIDS[].bosses` in `AnalyzeConfig.js` and `BOSS_ORDER` in `App.js` are separate copies for the four older entries; only `SEASON_TWO_RAIDS` feeds both (`frontend/src/AnalyzeConfig.js:12`, `frontend/src/App.js:68`). The comment at `frontend/src/AnalyzeConfig.js:10` says RAIDS mirrors them; nothing enforces it.
- **Season 1 is one combined card**: `voidspire`, `dreamrift` and `queldanas` are in `RAID_ZONES` and `BOSS_ORDER` (`frontend/src/App.js:29-43`) but have no card of their own in `RAIDS`. The Analyze page offers them together as `midnight-all`, whose encounter set is the union of all three (`backend/analysis.py:208`). The per-raid keys remain valid backend selections. The test pins five cards (`frontend/src/AnalyzeConfig.test.js:28`).
- **The script's council dict is a count, not a flag**: `COUNCIL` in the script maps slug to a number of models (`frontend/scripts/fetch-boss-renders.py:36`). A council whose journal lists the same display ID twice still gets fewer distinct models than asked.
- **DISPLAY_OVERRIDE replaces, it does not merge**: when a slug is in `DISPLAY_OVERRIDE`, the council count is ignored and exactly the listed IDs are used (`frontend/scripts/fetch-boss-renders.py:116`). The Lost Explorers tile is one model for that reason.
- **Journal search is fuzzy**: the encounter match accepts substring matches either way for names longer than five letters (`frontend/scripts/fetch-boss-renders.py:98-101`), then takes the highest ID. A short or common name can pick the wrong encounter; `ENC_OVERRIDE` exists for that (`l'ura`).
- **The loader is not gated by reduced motion**: the reduced-motion rule stops the orb's glow pulse but not the video, which still autoplays (`frontend/src/fp-design.css:888`, `frontend/src/App.js:1523`).
- **UPDATES dates have no year**: the third field is a display label like `'OCT 1'`; ordering is just array order (`frontend/src/LandingPage.js:97-103`).

## Glossary

- **Slug**: the file-name form of a boss name: lowercase, runs of other characters turned into single hyphens, ends trimmed. The same rule lives in `LandingPage.js`, `AnalyzeConfig.js` and the script.
- **Council**: an encounter with several bosses on one tile. The JavaScript copies only change how the tile fits; the script copy says how many models to draw.
- **Final**: the boss whose tile is the raid card's art on the Analyze page.
- **Display ID**: a `CreatureDisplayInfoID` from the game tables; the render server serves one image per display ID.

## Related

- [[frontend]] — the parent domain and the App.js shell that owns RAID_ZONES and loading state
- [[frontend-pages-and-routing]] — the routes that mount LandingPage and AnalyzeConfig, and the analysis stream that drives the loader
- [[frontend-results-view]] — where BOSS_ORDER sorts the boss chips and per-boss sections
- [[feat-analyze]] — the end-to-end Analyze slice the raid cards and loader belong to
- [[feat-results]] — the slice the analysis hands off to after the loader
- [[game-data]] — the wago.tools tables the fetch script reads
- [[testing]] — `AnalyzeConfig.test.js` pins the raid cards and the Season 2 lineup
