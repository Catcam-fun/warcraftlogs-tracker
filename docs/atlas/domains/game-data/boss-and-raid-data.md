---
id: game-data-boss-and-raid-data
title: Boss & Raid Data Builds
domain: game-data
status: documented
summary:
  - "Five smaller build scripts fill in what the defensive catalog can't: boss spells that pierce immunities, boss spell descriptions, armor constants, raid-wide abilities, and ability icons."
  - "build_boss_spell_flags, build_boss_spell_text and build_spell_icons read game tables from wago.tools; build_armor_constants and build_raid_wide measure top-ranked kills on WarcraftLogs."
  - "Four of them walk the raids in RAID_ENCOUNTERS; build_spell_icons walks the defensive catalog instead."
  - "The two WCL scripts need WCL_CLIENT_ID and WCL_CLIENT_SECRET and spend points on that key."
tagline: How the boss-side and icon tables are built, and what each script needs.
anchors:
  flags_script: backend/scripts/build_boss_spell_flags.py:31
  flags_attribute: backend/scripts/build_boss_spell_flags.py:25
  text_render: backend/scripts/build_boss_spell_text.py:67
  text_main: backend/scripts/build_boss_spell_text.py:119
  armor_measure: backend/scripts/build_armor_constants.py:70
  armor_main: backend/scripts/build_armor_constants.py:109
  raid_wide_kills: backend/scripts/build_raid_wide.py:33
  raid_wide_shares: backend/scripts/build_raid_wide.py:49
  raid_wide_main: backend/scripts/build_raid_wide.py:78
  icons_main: backend/scripts/build_spell_icons.py:58
  use_immunity: backend/defensives.py:1231
  use_armor: backend/defensives.py:954
  use_rot: backend/defensives.py:1731
  use_icons: backend/defensives.py:131
  use_text: backend/app.py:659
  icon_url: frontend/src/DeathRow.js:22
links:
  - game-data
  - game-data-defensive-catalog
  - backend-defensive-analysis
  - backend-death-descriptions
  - backend
  - warcraftlogs-api-client
  - warcraftlogs-point-budget
  - operations
  - testing
invariants:
  - "MUST: an immunity is never credited against a spell in IGNORES_IMMUNITY."
  - "MUST: only abilities in RAID_WIDE can make a death read as worn down (rot)."
  - "NEVER: store boss damage amounts in boss spell text; the game scales them at run time, so the tooltip shows the real hit from the log."
flows:
  - data-build-path
content_hash: sha256:5e24640f8d3a4a18b52bdc3439462034953b8ec3337ce6209cd96a9e82267a42
---
## Summary

- These five scripts produce the boss-side facts the analysis looks up, plus the icons and descriptions of the defensives. Each overwrites one module in `backend/` (see the inventory on [[game-data]]).
- **wago.tools scripts** reuse `table()` and `patches()` from `build_defensive_catalog.py` (`backend/scripts/build_boss_spell_flags.py:23`, `backend/scripts/build_boss_spell_text.py:31`, `backend/scripts/build_spell_icons.py:24`), so `WAGO_CACHE` applies to them too.
- **WCL scripts** read the top of `fightRankings` for each boss and download those kills' damage taken, using the site's own client (`backend/scripts/build_armor_constants.py:33`, `backend/scripts/build_raid_wide.py:24`).

## How it works

#### build_boss_spell_flags.py: hits through immunities

Run as `python backend/scripts/build_boss_spell_flags.py`; needs wago.tools (`backend/scripts/build_boss_spell_flags.py:12-14`).

1. Finds damaging spells: base-difficulty `SpellEffect` rows with a school-damage or health-leech effect, or a periodic-damage aura (`backend/scripts/build_boss_spell_flags.py:27-37`).
2. Walks the Dungeon Journal: every `JournalEncounterSection` spell of an encounter in `RAID_ENCOUNTERS`, then every spell those trigger (`backend/scripts/build_boss_spell_flags.py:39-49`). Encounters missing from the journal print a warning (`backend/scripts/build_boss_spell_flags.py:50-52`).
3. Keeps damaging spells whose `SpellMisc.Attributes_0` has the "no immunities" bit `0x20000000`, if their ID is 400,000 or higher (The War Within onward) or they were found in the journal walk (`backend/scripts/build_boss_spell_flags.py:25-26`, `backend/scripts/build_boss_spell_flags.py:54-58`).
4. Writes the sorted IDs as the frozenset `IGNORES_IMMUNITY` (`backend/scripts/build_boss_spell_flags.py:60-68`).

`defensives.py` uses it so an immunity never zeroes such a hit, and labels the verdict `pierces` (`backend/defensives.py:1230-1232`, `backend/defensives.py:1503-1504`, `backend/defensives.py:1757`).

#### build_boss_spell_text.py: killing-blow descriptions

Run as `python backend/scripts/build_boss_spell_text.py` after the raid is in `RAID_ENCOUNTERS`; needs wago.tools (`backend/scripts/build_boss_spell_text.py:15-20`).

1. Loads names, descriptions, durations, radii and effects from the latest build (`backend/scripts/build_boss_spell_text.py:37-55`, `backend/scripts/build_boss_spell_text.py:120`).
2. Collects spells: the journal's spells for the raids' encounters, the spells they trigger, spells linked to them by a bare `$@spelldesc` pointer in either direction, and same-named spells from ID 400,000 up (`backend/scripts/build_boss_spell_text.py:122-149`).
3. `render()` fills Blizzard's description template where the data is exact (durations, tick periods, radii, spell names, percentages), drops difficulty and class conditions, and removes damage amounts, which scale at run time (`backend/scripts/build_boss_spell_text.py:67-116`).
4. Drops text written to "you" (player spells), dedupes identical texts into `TEXTS`, maps spell IDs to them in `SPELLS`, and writes a `text_for()` helper (`backend/scripts/build_boss_spell_text.py:151-167`).

`app.py` sends `text_for(abilityId)` for each counted killing blow as `abilityText` (`backend/app.py:657-660`).

#### build_armor_constants.py: armor per boss

Run as `WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/build_armor_constants.py` (`backend/scripts/build_armor_constants.py:21`).

1. For each difficulty (Mythic, Heroic, Normal) and each encounter in `RAID_ENCOUNTERS`, reads `fightRankings` and measures the first 5 ranked kills; private or deleted reports are skipped (`backend/scripts/build_armor_constants.py:35-36`, `backend/scripts/build_armor_constants.py:112-126`).
2. `measure()` groups a pull's hits by player and active buffs. Two or more agreeing magic hits set the baseline; a melee swing's share of it is armor's share alone, which solves for K given the player's armor on that hit (`backend/scripts/build_armor_constants.py:70-106`, method in the docstring at `backend/scripts/build_armor_constants.py:3-13`).
3. Stores the median K per boss, falling back to the raid's pooled median when a boss has fewer than 10 samples (`backend/scripts/build_armor_constants.py:37`, `backend/scripts/build_armor_constants.py:130-137`).
4. Physical boss spells with at least 5 samples are sorted into `IGNORES_ARMOR` (median share at least 0.97) or `REDUCED_BY_ARMOR` (at most 0.9) (`backend/scripts/build_armor_constants.py:41-43`, `backend/scripts/build_armor_constants.py:141-149`).

`armor_constant()` reads K with a Mythic, then Heroic, then Normal fallback, and `_armor_reduction()` uses the two spell lists (`backend/defensives.py:954-959`, `backend/defensives.py:963-976`). The docstring names the use: how much more a druid's Bear Form armor would have reduced a physical killing blow (`backend/scripts/build_armor_constants.py:18-19`).

#### build_raid_wide.py: raid-wide abilities

Run as `WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/build_raid_wide.py`; its docstring puts the cost at about 10 WCL points per encounter (`backend/scripts/build_raid_wide.py:3`, `backend/scripts/build_raid_wide.py:12-13`).

1. `kills()` takes Mythic `fightRankings` page 1 and keeps the first 3 kills from different guilds (`backend/scripts/build_raid_wide.py:26`, `backend/scripts/build_raid_wide.py:33-46`).
2. `shares()` downloads each kill's DamageTaken through `defensives._fetch_blocks` with an `endTime`, keeps hits on players from non-friendly sources, groups each ability's hits into occurrences no more than 1 second apart, and records the share of the raid each occurrence hit (`backend/scripts/build_raid_wide.py:49-75`).
3. An ability needs at least 3 occurrences in a kill; its per-kill median shares are medianed again, and it is raid-wide at 0.5 or more (`backend/scripts/build_raid_wide.py:27-29`, `backend/scripts/build_raid_wide.py:85-90`).
4. Writes `RAID_WIDE = {abilityID: share}` with the ability and boss name as a comment (`backend/scripts/build_raid_wide.py:95-102`).

The death description only calls a death "rot" when the dominant ability is in `RAID_WIDE`, hit at least 3 times, and no hit was a big chunk (`backend/defensives.py:752-757`, `backend/defensives.py:1731-1733`).

#### build_spell_icons.py: defensive icons and descriptions

Run as `python backend/scripts/build_spell_icons.py` after rebuilding the catalog; needs wago.tools (`backend/scripts/build_spell_icons.py:10-14`).

1. Gathers every ability name across all patches in `CATALOGS`, with its spell IDs newest patch first (`backend/scripts/build_spell_icons.py:58-64`).
2. From the latest build, maps `SpellMisc.SpellIconFileDataID` to an icon file under `interface\icons` via `ManifestInterfaceData` (`backend/scripts/build_spell_icons.py:28-35`, `backend/scripts/build_spell_icons.py:65`). Potions use their item's icon instead of the spell's (`backend/scripts/build_spell_icons.py:38-55`).
3. Fills each description with `render()` from the boss text script (`backend/scripts/build_spell_icons.py:23`, `backend/scripts/build_spell_icons.py:76`), prints names with no icon or no text, and writes `ICONS` and `DESCRIPTIONS` (`backend/scripts/build_spell_icons.py:81-93`).

`icon_name()` prefers `ICONS` and falls back to the report's own icon for boss abilities (`backend/defensives.py:131-139`). The browser loads `render.worldofwarcraft.com/us/icons/56/<icon>.jpg`, falling back to `assets.rpglogs.com` (`frontend/src/DeathRow.js:22`, `frontend/src/DeathRow.js:215`).

## Reference

| Script {wago} | Needs | Reads | Writes |
|---|---|---|---|
| `build_boss_spell_flags.py` {wago} | wago.tools | `RAID_ENCOUNTERS`, live `SpellEffect`, `SpellMisc`, journal tables | `IGNORES_IMMUNITY` |
| `build_boss_spell_text.py` {wago} | wago.tools | `RAID_ENCOUNTERS`, latest build's spell and journal tables | `TEXTS`, `SPELLS`, `text_for` |
| `build_spell_icons.py` {wago} | wago.tools; a fresh `defensive_catalog.py` | `CATALOGS`, `SpellMisc`, `ManifestInterfaceData`, item tables | `ICONS`, `DESCRIPTIONS` |
| `build_armor_constants.py` {wcl} | `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` | `RAID_ENCOUNTERS`, top 5 kills per boss and difficulty | `ARMOR_K`, `IGNORES_ARMOR`, `REDUCED_BY_ARMOR` |
| `build_raid_wide.py` {wcl} | `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` | `RAID_ENCOUNTERS`, 3 Mythic kills per boss | `RAID_WIDE` |

## Invariants

- **MUST** never credit an immunity against a spell in `IGNORES_IMMUNITY` (`backend/defensives.py:1230-1232`).
- **MUST** only let abilities in `RAID_WIDE` make a death read as worn down (`backend/defensives.py:1731`).
- **NEVER** store boss damage amounts in spell text; they scale by difficulty and item level, so the tooltip shows the log's real hit (`backend/scripts/build_boss_spell_text.py:11-14`).

## Gotchas

- **The flags script reads live tables, the others a pinned build**: `build_boss_spell_flags.py` calls `table(name)` with no build (`backend/scripts/build_boss_spell_flags.py:33`, `backend/scripts/build_boss_spell_flags.py:55`), while the text and icon scripts pass `patches()[-1][2]` (`backend/scripts/build_boss_spell_text.py:120`, `backend/scripts/build_spell_icons.py:65`). Live tables are never cached, so the flags script always reads current data (`backend/scripts/build_defensive_catalog.py:419-423`).
- **Armor events need the fight's endTime**: WCL answers a `fightIDs`-scoped events query without an `endTime` with an empty second page (`backend/defensives.py:787-788`). `_events` therefore looks up the fight's `endTime` first and sends it with every page (`backend/scripts/build_armor_constants.py:47-55`); before that fix, a pull with more than 10,000 DamageTaken events was measured from its first page only. `backend/test_armor_build.py` checks that every page is read. `build_raid_wide.py` goes through `_fetch_blocks`, which also sends one.
- **Measured tables depend on public kills**: both WCL scripts read whatever `fightRankings` returns today. A boss with too few samples falls back to its raid's pooled K, or gets no entry at all (`backend/scripts/build_armor_constants.py:133-137`).
- **The boss text is tested on a real spell**: `backend/test_boss_spell_text.py:34-36` checks that Sever's text mentions a frontal cone, so a regenerated file that loses it fails the suite.

## Context map

```context
depends-on: [[game-data-defensive-catalog]] — table(), patches(), and CATALOGS for the icon build
depends-on: [[warcraftlogs-api-client]] — get_access_token, get_fights and graphql_query in the WCL scripts
depends-on: RAID_ENCOUNTERS in backend/analysis.py — the bosses to cover
provides: IGNORES_IMMUNITY, TEXTS and text_for, ARMOR_K and the armor spell lists, RAID_WIDE, ICONS and DESCRIPTIONS
relied-on-by: [[backend-defensive-analysis]] — immunity, armor and icon lookups
relied-on-by: [[backend-death-descriptions]] — RAID_WIDE decides rot
relied-on-by: [[backend]] — app.py adds killing-blow text to the response
```

## Glossary

- **Armor constant (K)**: the boss-specific number in armor / (armor + K), the share of physical damage armor removes.
- **Occurrence**: one cast of a boss ability, taken as its hits no more than 1 second apart.
- **Dungeon Journal**: the in-game encounter guide; its tables list each boss's abilities by spell ID.

## Related

- [[game-data]] — the inventory of all generated modules
- [[game-data-defensive-catalog]] — the catalog these scripts build on
- [[backend-defensive-analysis]] — reads immunity, armor and icon data
- [[backend-death-descriptions]] — reads `RAID_WIDE`
- [[backend]] — serves the spell text in each result
- [[warcraftlogs-api-client]] — the client the WCL scripts use
- [[warcraftlogs-point-budget]] — the WCL scripts spend points too
- [[operations]] — when each script is rerun
- [[testing]] — tests over the generated output
