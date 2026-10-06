---
id: backend-death-descriptions
title: Death Descriptions
domain: backend
status: documented
summary:
  - "Each analyzed death is labeled from the hits since the player was last at 85% health or more."
  - "One-shot: high health under a second before death and one hit of 80% of max health or more. Burst: same timing, no hit that big."
  - "Worn down (rot): only when one raid-wide ability from raid_wide_damage.py did most of the damage in 3 or more small hits."
  - "Set up by: otherwise, the biggest hit of at least 10% max health since they were last high, and how often that ability hit them."
  - "The killing-blow tooltip text is the boss spell's in-game description from boss_spell_text.py, keyed by spell ID."
tagline: How the backend decides whether a death was a one-shot, a burst, rot, or set up by one big hit.
invariants:
  - "MUST: classify from the hits since the player was last at FULL_HEALTH (85%) or more, within the 15-second window."
  - "MUST: a one-shot or burst needs high health no more than REACTION_MS (1s) before the killing blow."
  - "NEVER: call a death rot unless the dominant ability is in RAID_WIDE."
  - "NEVER: call a one-shot or burst death rot."
anchors:
  full_health: "backend/defensives.py:729"
  one_shot_share: "backend/defensives.py:740"
  setup_hit_share: "backend/defensives.py:743"
  rot_thresholds: "backend/defensives.py:747"
  classify: "backend/defensives.py:1689"
  biggest_hit: "backend/defensives.py:1700"
  rot: "backend/defensives.py:1709"
  burst: "backend/defensives.py:1749"
  raid_wide: "backend/raid_wide_damage.py:5"
  raid_wide_share: "backend/scripts/build_raid_wide.py:29"
  text_for: "backend/boss_spell_text.py:7853"
  ability_text: "backend/app.py:658"
  death_row_ctx: "frontend/src/DeathRow.js:249"
links:
  - backend-defensive-analysis
  - backend-death-counting
  - game-data
  - warcraftlogs
  - frontend-results-view
  - feat-results
content_hash: sha256:e50e4fd50c7235ff449c7db91e1e0b989136b98309c5c33d6911e45a15ecf23f
---
## Summary

- The description is computed at the end of `assess_survival` in `backend/defensives.py`, on the same replayed hits used for the "would it have saved them" verdict (`backend/defensives.py:1683`). See [[backend-defensive-analysis]] for that replay.
- The key reference point is **the last moment the player was at high health**: 85% of max health or more (`FULL_HEALTH`, `backend/defensives.py:729`). Damage before that had already been healed back.
- Four outcomes reach the page: **one-shot**, **burst**, **worn down by** (rot) and **set up by**. Instant kills are a fifth type that skips all of this (`backend/defensives.py:1587`).
- Only abilities in the generated `RAID_WIDE` list can make a death rot (`backend/raid_wide_damage.py:5`). Soaks and mechanics a player walks into are not on it.

## How it works

The classification reads the health line built from the hits in the lethal window (`_health_points`, `backend/defensives.py:1239`). Click each step.

```steps
- title: Find the last high-health moment | short: Last high | sub: 85% or more
  body: high is every health point before the killing blow where health was at least FULL_HEALTH (0.85) of max (backend/defensives.py:1689). since is the time of the last one. If the player had 85% or more just before the killing blow itself, since is that moment (backend/defensives.py:1691). run is every hit after since (backend/defensives.py:1693).
  gotcha: The health line only covers the 15-second window. A player who was never at 85% in it has no high point, so run is the whole window and the death cannot be a one-shot or burst.
- title: Was it quick? | short: Quick? | sub: within 1 second
  body: quick is true when a high point exists and the killing blow came no more than REACTION_MS (1000 ms) after it (backend/defensives.py:1694). The same constant is the press cutoff in the replay, so a quick death is one nobody could react to.
- title: One-shot or burst | short: One-shot / burst | sub: one hit of 80% or not
  body: If quick and any single hit in run was at least ONE_SHOT_SHARE (0.80) of max health, deathType is oneShot; if quick without such a hit, burst; otherwise wasLow (backend/defensives.py:1695). Hit size is the whole hit, amount plus overkill plus absorbed (_full_hit, backend/defensives.py:1196). For quick deaths fromPct and burstMs record where they fell from and how fast (backend/defensives.py:1746).
- title: List the burst | short: Burst parts | sub: every ability that hit
  body: For a burst, result.burst lists every ability in run with how many times it hit, sorted by total damage, plus the hit count, total and milliseconds (backend/defensives.py:1749).
- title: Find the setup hit | short: Setup hit | sub: biggest since last high
  body: biggestHit is the largest hit before the killing blow, after since, of at least SETUP_HIT_SHARE (0.10) of max health (backend/defensives.py:1700). On a one-shot it is dropped unless it was itself one-shot sized, because the killing blow was the one hit (backend/defensives.py:1702). If the same ability hit them more than once since then, times, total and over are added (backend/defensives.py:1770).
- title: Check for rot | short: Rot? | sub: raid-wide only
  body: Hits in run are grouped by ability and the ability with the most damage is checked (backend/defensives.py:1714). It is rot only if the death was not quick, the ability is in RAID_WIDE, it hit at least ROT_MIN_HITS (3) times, it did at least ROT_SHARE (60%) of the damage in run, and none of its hits was ROT_MAX_HIT (35% of max) or more (backend/defensives.py:1716). Rot replaces biggestHit (backend/defensives.py:1723).
  gotcha: RAID_WIDE is measured, not curated: build_raid_wide.py keeps boss abilities whose median occurrence hits at least half the raid at once (backend/scripts/build_raid_wide.py:29). A heavy DoT on one player is not on it.
```

#### How the page phrases it

The backend sends data, not sentences. `frontend/src/DeathRow.js:249` turns it into the one-line context, checked in this order:

- `instakill`: "instant kill, with no damage to stop".
- `oneShot`: "one-shot from N%".
- `burst`: "burst from N%: K hits at once / in T".
- `rot` present: "worn down by <ability> (rot, K hits)".
- `biggestHit` present: "at N% after <ability> ×K" or "(P%, Ts before)".
- otherwise: "at N%, hit for P%".

The killing-blow tooltip (`frontend/src/DeathRow.js:264`) shows rows for Killing blow, Worn down by, Burst and Set up by; Set up by is hidden on burst deaths (`frontend/src/DeathRow.js:283`).

#### Killing-blow tooltip text

The description paragraph under the spell name comes from `abilityText`, built in `backend/app.py:658` for every death's killing-blow spell ID:

- `boss_spell_text.text_for(spell_id)` (`backend/boss_spell_text.py:7853`) looks the ID up in `SPELLS` and returns a shared entry from `TEXTS`. The module is generated by `scripts/build_boss_spell_text.py` from game data, with damage amounts left out (`backend/boss_spell_text.py:1`).
- If there is no entry, `BASIC_ABILITY_TEXT` covers "Melee" and "Falling" by name (`backend/app.py:103`).

## Reference

The thresholds, as found in code.

| Constant {threshold} | Value | Used for |
|---|---|---|
| `FULL_HEALTH` {threshold} | 0.85 | "high health": the reference point for every label (`backend/defensives.py:729`) |
| `REACTION_MS` {threshold} | 1000 ms | max time from high health to death for one-shot and burst (`backend/defensives.py:738`) |
| `ONE_SHOT_SHARE` {threshold} | 0.80 | single hit size of max health that makes a quick death a one-shot (`backend/defensives.py:740`) |
| `SETUP_HIT_SHARE` {threshold} | 0.10 | minimum size for the "set up by" hit (`backend/defensives.py:743`) |
| `ROT_MIN_HITS` {rot} | 3 | minimum hits from the raid-wide ability (`backend/defensives.py:747`) |
| `ROT_SHARE` {rot} | 0.6 | its minimum share of damage since last high (`backend/defensives.py:748`) |
| `ROT_MAX_HIT` {rot} | 0.35 | no single hit of it may reach this share of max health (`backend/defensives.py:749`) |
| `LETHAL_WINDOW_MS` {window} | 15000 ms | how far back hits are available at all (`backend/defensives.py:734`) |

Output fields that describe the death (`backend/defensives.py:1724`):

| Field {output} | Content |
|---|---|
| `deathType` {output} | `oneShot`, `burst`, `wasLow`, or `instakill` |
| `killingHit` {output} | name, size, pctOfMax, school |
| `hpBeforePct`, `overkill`, `maxHp` {output} | health left before the killing blow, damage beyond it, max health |
| `fromPct`, `burstMs` {output} | quick deaths only: health they fell from and how fast |
| `burst` {output} | burst only: hits, total, ms, abilities with times |
| `rot` {output} | name, abilityId, school, hits, total, pctOfMax, seconds |
| `biggestHit` {output} | name, abilityId, size, pctOfMax, school, ago; times, total, over when repeated |

## Context map

```context
depends-on: [[backend-defensive-analysis]] — the replay window and health line come from assess_survival
depends-on: [[game-data]] — raid_wide_damage.py and boss_spell_text.py, both generated
depends-on: [[warcraftlogs]] — DamageTaken hits with the target's health and instant kills
provides: deathType, burst, rot and biggestHit on each analyzed death
provides: abilityText, the killing blow's in-game description by spell ID
relied-on-by: [[frontend-results-view]] — DeathRow.js turns the fields into the context line and tooltip
relied-on-by: [[feat-results]] — the death breakdown officers read
```

## Invariants

- **MUST** classify from the hits since the player was last at 85% health or more (`backend/defensives.py:1689`); earlier damage had already been healed back.
- **MUST** require high health no more than 1 second before the killing blow for one-shot and burst (`backend/defensives.py:1694`).
- **NEVER** label a death rot unless the dominant ability is in `RAID_WIDE` (`backend/defensives.py:1716`); a mechanic a player walks into is their own damage, not raid healing falling behind.
- **NEVER** label a one-shot or burst as rot (`not quick`, `backend/defensives.py:1716`).

## Gotchas

- **wasLow is not shown as a word**: the backend's third type is `wasLow`; the page says "worn down by", "at N% after" or "at N%, hit for" depending on which of `rot` and `biggestHit` is present (`frontend/src/DeathRow.js:257`).
- **Instant kills skip classification**: an `instakill` killing blow returns early with no health data and every button marked as not saving (`backend/defensives.py:1587`).
- **No survival block, no description**: if the killing blow is missing or has no health of the player's own, `assess_survival` returns `None` and only the killing blow's name is shown (`backend/defensives.py:1603`).
- **Battle resses cut the window**: `_lethal_hits` drops everything before an earlier death of the same player, so a second death is judged only on the hits after the res (`backend/defensives.py:1524`).
- **Rot needs refreshing per tier**: a new raid's abilities are not rot until `build_raid_wide.py` has measured them into `backend/raid_wide_damage.py`.

## Glossary

- **High health**: 85% of max health or more (`FULL_HEALTH`).
- **One-shot**: high health under a second before death and a single hit of 80% of max health or more.
- **Burst**: high health under a second before death, with no single hit that big.
- **Rot**: worn down by repeated, smaller hits from one raid-wide ability.
- **Raid-wide ability**: a boss ability whose median occurrence hits at least half the raid at once, as measured into `RAID_WIDE`.
- **Setup hit**: the biggest hit of at least 10% max health since the player was last at high health.

## Related

- [[backend-defensive-analysis]] — the replay this classification shares its window with
- [[backend-death-counting]] — which deaths reach analysis at all
- [[game-data]] — the generated raid-wide and spell-text modules
- [[warcraftlogs]] — where the hits come from
- [[frontend-results-view]] — DeathRow renders these fields
- [[feat-results]] — the user-facing death breakdown
