---
id: game-data-defensive-catalog
title: Defensive Catalog Build
domain: game-data
status: documented
summary:
  - "build_defensive_catalog.py writes backend/defensive_catalog.py: one catalog of defensives, externals and consumables per retail patch from 11.0.2 on."
  - "A curated list in the script decides which abilities count and for whom; the game data on wago.tools supplies cooldowns, charges, durations, damage reductions and the talents that grant or change each one."
  - "Each patch is built from its last build on wago.tools, and the analysis picks the patch that was live when a report was logged."
  - "The build stops if the current patch renamed a curated spell or has a talent naming a defensive that nobody has reviewed; older patches only print notes."
  - "Potions use POTION_TYPICAL, a median heal measured from real logs, because their heal depends on quality rank and talents."
tagline: How the per-patch defensive catalog is built from game data and a curated list.
anchors:
  curated: backend/scripts/build_defensive_catalog.py:18
  baseline: backend/scripts/build_defensive_catalog.py:122
  mitigation: backend/scripts/build_defensive_catalog.py:141
  effects: backend/scripts/build_defensive_catalog.py:199
  talent_effects: backend/scripts/build_defensive_catalog.py:264
  talents_reviewed: backend/scripts/build_defensive_catalog.py:291
  potion_typical: backend/scripts/build_defensive_catalog.py:343
  first_patch: backend/scripts/build_defensive_catalog.py:403
  wago_cache: backend/scripts/build_defensive_catalog.py:406
  table: backend/scripts/build_defensive_catalog.py:414
  patches: backend/scripts/build_defensive_catalog.py:429
  potion_ranks: backend/scripts/build_defensive_catalog.py:696
  unreviewed: backend/scripts/build_defensive_catalog.py:873
  build_catalog: backend/scripts/build_defensive_catalog.py:893
  rename_check: backend/scripts/build_defensive_catalog.py:932
  main: backend/scripts/build_defensive_catalog.py:1027
  fail_latest: backend/scripts/build_defensive_catalog.py:1038
  output_patches: backend/defensive_catalog.py:7
  output_catalogs: backend/defensive_catalog.py:22
  catalog_for: backend/defensives.py:122
  standard_potion: backend/defensives.py:58
links:
  - game-data
  - game-data-boss-and-raid-data
  - backend-defensive-analysis
  - backend
  - operations
  - testing
invariants:
  - "MUST: the build fails when the current patch's game data names a curated spell ID differently than the curated list."
  - "MUST: the build fails when a current-patch talent names a tracked defensive with a survival word and no modifier, TALENT_EFFECTS entry or TALENTS_REVIEWED line covers it."
  - "MUST: the catalog file is written only from a run over every patch; a run limited to some patches is a dry run."
  - "NEVER: hand-edit defensive_catalog.py; the curated lists live in the build script."
flows:
  - data-build-path
content_hash: sha256:8791e88978197b3434c092a247edc270993e8428b7078e81f0789ab4771ca3a0
---
## Summary

- `backend/scripts/build_defensive_catalog.py` is the largest build script. It writes `backend/defensive_catalog.py`, which `backend/defensives.py` reads to know every defensive's cooldown, charges, effect and the talents that change them (`backend/defensives.py:28`).
- The split of work is stated at the top of the script: **the curated list decides which abilities count and for whom; the game data supplies the numbers** (`backend/scripts/build_defensive_catalog.py:3-5`).
- There is **one catalog per patch**, because cooldowns and talents change between patches. `catalog_for` picks the patch that was live on the report's start day (`backend/defensives.py:122-128`).

## How it works

```steps
- title: List the patches | short: Patches | sub: from wago.tools builds
  body: patches() reads https://wago.tools/api/builds, skips background-download builds, keeps retail versions from FIRST_PATCH (11.0.2) on, and for each patch records the earliest build date and the last build version (backend/scripts/build_defensive_catalog.py:403, 427-441).
- title: Load the tables | short: Tables | sub: one build at a time
  body: GameData loads the DB2 tables one catalog needs for that build: SpellName, SpellEffect, SpellCooldowns, SpellCategories, SpellCategory, SpellClassOptions, SpellMisc, SpellDuration, SpellLabel, SpellShapeshift, TraitDefinition, TraitNodeEntry, ChrSpecialization and SpecializationSpells (backend/scripts/build_defensive_catalog.py:446-493). Each comes from table(), which downloads https://wago.tools/db2/{name}/csv?build=... (backend/scripts/build_defensive_catalog.py:414-426).
  gotcha: Set WAGO_CACHE to a folder and every table is kept there gzipped as {name}_{build}.csv.gz, so a rerun reads from disk (backend/scripts/build_defensive_catalog.py:406, 415-423).
- title: Check each curated spell | short: Rename check | sub: name must match
  body: For every CURATED entry, a spell ID missing from the build is noted as not in this patch; a spell ID whose game name differs from the curated name is recorded as a problem (backend/scripts/build_defensive_catalog.py:928-934).
- title: Fill in the numbers | short: Numbers | sub: cooldown, charges, effect
  body: The cooldown is the longer of RecoveryTime and CategoryRecoveryTime, replaced by the charge recharge for charged spells, with COOLDOWN_FALLBACK for the few stored elsewhere (backend/scripts/build_defensive_catalog.py:935-940, 395). components() reads each effect from the game data at the places EFFECTS names, with talent modifiers attached (backend/scripts/build_defensive_catalog.py:759). The entry also gets known (baseline, talent or evidence), major (cooldown of 60s or more), talent_entries and aura_ms (backend/scripts/build_defensive_catalog.py:944-955).
- title: Attach talents | short: Talents | sub: cooldown, charges, duration
  body: Modifiers collects the talents and spec passives that change a spell's cooldown, charges or duration, each tagged with who gets it (talent entries or specs) (backend/scripts/build_defensive_catalog.py:545-551, 954-962). TALENT_EFFECTS adds effects the data doesn't attach to the button's own spell (backend/scripts/build_defensive_catalog.py:256-264).
- title: Potions and Healthstones | short: Consumables | sub: measured heals
  body: A potion with a POTION_TYPICAL value gets that heal as an observed amount, and potion_ranks adds each quality rank's item level and tooltip heal (backend/scripts/build_defensive_catalog.py:965-968, 694-727). Iron Stomach, Soulburn and Gorebound Fortitude are added to consumables by hand-written rules (backend/scripts/build_defensive_catalog.py:992-1020).
- title: Review new talents | short: Review | sub: survival words
  body: unreviewed_talents finds talents whose tooltip names a tracked defensive together with a survival word (damage taken, absorb, heal, armor, immun, reduc) and that nothing yet handles; each becomes a problem (backend/scripts/build_defensive_catalog.py:870-890, 1020-1021).
- title: Fail or write | short: Write | sub: latest patch must be clean
  body: main() builds every patch in order. Problems on the latest patch stop the run with "spell data changed; update CURATED / EFFECTS"; on older patches they are printed as notes (backend/scripts/build_defensive_catalog.py:1037-1041). The file is written only when no patch filter was given (backend/scripts/build_defensive_catalog.py:1047-1059).
```

#### The curated lists

These live at the top of the script and are what a person edits:

| List {curated} | What it decides | Where |
|---|---|---|
| `CURATED` {curated} | spell ID, name, class, specs and kind (personal, external, healthstone, potion) of every tracked ability | `backend/scripts/build_defensive_catalog.py:18` |
| `BASELINE` {curated} | abilities every player of the class or spec has, talent or not | `backend/scripts/build_defensive_catalog.py:122` |
| `NAME_ALIAS_OK` {curated} | talents allowed to grant a button through a same-named spell | `backend/scripts/build_defensive_catalog.py:130` |
| `MITIGATION` {curated} | what each ability does: dr, immune, absorb, heal, hp, armor, school, duration | `backend/scripts/build_defensive_catalog.py:141` |
| `EFFECTS` {data} | where each value lives in the game data (spell, effect index) | `backend/scripts/build_defensive_catalog.py:199` |
| `TALENT_EFFECTS` {data} | talent effects the data doesn't link to the button | `backend/scripts/build_defensive_catalog.py:264` |
| `TALENTS_REVIEWED` {curated} | talents checked and left out, with the reason | `backend/scripts/build_defensive_catalog.py:291` |
| `POTION_TYPICAL` {measured} | median heal per potion from real logs of its tier | `backend/scripts/build_defensive_catalog.py:343` |
| `COOLDOWN_FALLBACK` {data} | cooldowns the data stores elsewhere, in seconds | `backend/scripts/build_defensive_catalog.py:395` |

Two related tables live in `backend/defensives.py`, not the build script: `DEMONIC_HEALTHSTONE_MEASURED` (measured share of max health per tier) and `STANDARD_POTION` (the potion most raiders drank on bosses in each tier, used when a player's own potion heal isn't in the pulls) (`backend/defensives.py:53`, `backend/defensives.py:58-59`).

#### Output shape

`backend/defensive_catalog.py` holds five top-level names, written by `main()` (`backend/scripts/build_defensive_catalog.py:1049-1058`):

- `PATCHES`: `[(first day live, patch)]`, oldest first (`backend/defensive_catalog.py:7`).
- `CATALOGS`: `{patch: {spell ID: entry}}` (`backend/defensive_catalog.py:22`). An entry carries `name`, `class`, `specs`, `kind`, `known`, `cooldown_ms`, `charges`, `major`, `talent_entries`, `replaced_by_entries`, `mitigation` and `aura_ms`, plus `cooldown_mods`, `charge_mods`, `duration_mods`, `ranks`, `needs_form` or `form_armor` where they apply (`backend/scripts/build_defensive_catalog.py:948-989`).
- `HEALING_TAKEN`: per patch, talents and auras that change healing taken (`backend/defensive_catalog.py:15865`).
- `LATEST` and `CATALOG`: the newest patch and its catalog (`backend/defensive_catalog.py:22354-22355`).

`defensives.py` wraps each patch in a `Catalog` object (`backend/defensives.py:70-119`) and hashes the patches' cast IDs, buff names and talent entries into `CATALOG_FINGERPRINT`, which is part of the defensive cache key (`backend/defensives.py:163-168`).

## Invariants

- **MUST** fail the build when the current patch's game data names a curated spell ID differently than `CURATED` (`backend/scripts/build_defensive_catalog.py:932-934`, `backend/scripts/build_defensive_catalog.py:1038-1039`).
- **MUST** fail the build when a current-patch talent names a tracked defensive with a survival word and nothing covers it (`backend/scripts/build_defensive_catalog.py:287-290`, `backend/scripts/build_defensive_catalog.py:1022-1023`).
- **MUST** write the catalog file only from a run over every patch; a run with patch arguments ends with "dry run" (`backend/scripts/build_defensive_catalog.py:1047-1048`).
- **NEVER** hand-edit `defensive_catalog.py`; its header says to edit the curated lists in the script (`backend/defensive_catalog.py:1-2`).

## Gotchas

- **A patch's "first day" is its earliest build on wago.tools**: `patches()` takes the minimum `created_at` of the patch's builds (`backend/scripts/build_defensive_catalog.py:440-442`), and `catalog_for` compares that against the report's UTC start day (`backend/defensives.py:126-128`). A build created before the patch went live moves the switch-over earlier.
- **`WAGO_CACHE` holds pinned builds only**: a table fetched for a specific build is cached and reused as long as its file exists, which is safe because a build never changes. A table fetched without a build (the live data) is never cached, since it changes with every game build (`backend/scripts/build_defensive_catalog.py:414-418`, `backend/test_wago_cache.py`).
- **Potions are scored from logs first**: the script's comment says each player's own potion heals in the same report are used when they drank one there; `POTION_TYPICAL` stands in otherwise (`backend/scripts/build_defensive_catalog.py:339-342`). A potion with no `POTION_TYPICAL` value keeps no typical heal.
- **Only the newest expansion's potion items get ranks**: `potion_ranks` keeps items whose `ExpansionID` is the build's expansion, since older potions scale differently after an item squish (`backend/scripts/build_defensive_catalog.py:706-713`).
- **Spec names must match**: a spec listed in `CURATED` has to exist in `defensives.SPEC_NAMES`, which `backend/test_defensives.py:617-620` checks.

## Context map

```context
depends-on: wago.tools DB2 tables and build list (https://wago.tools/db2, /api/builds)
depends-on: real boss-pull logs, for POTION_TYPICAL
provides: backend/defensive_catalog.py (PATCHES, CATALOGS, HEALING_TAKEN, LATEST, CATALOG)
provides: table() and patches(), reused by the other wago build scripts
relied-on-by: [[backend-defensive-analysis]] — every verdict reads the report's patch catalog
relied-on-by: [[game-data-boss-and-raid-data]] — build_spell_icons reads CATALOGS; three scripts reuse table()
relied-on-by: [[testing]] — catalog-driven tests in backend/test_defensives.py
```

## Glossary

- **Catalog**: the per-patch table of tracked defensives, externals and consumables, keyed by spell ID.
- **Curated list**: the hand-maintained `CURATED` entries that decide which abilities are tracked, for which class and spec.
- **Talent entry**: a talent-tree node entry ID; a player has a talent when their pull's loadout includes one of its entries.
- **Dry run**: running the script with patch arguments, which builds those patches but writes nothing.

## Related

- [[game-data]] — all the generated modules and how they connect
- [[game-data-boss-and-raid-data]] — the icon build that reads this catalog
- [[backend-defensive-analysis]] — how the catalog is applied to each death
- [[backend]] — where defensive results join the Analyze response
- [[operations]] — when to rebuild after a patch
- [[testing]] — tests that pin catalog behavior
