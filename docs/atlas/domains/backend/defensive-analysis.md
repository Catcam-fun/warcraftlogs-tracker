---
id: backend-defensive-analysis
title: Defensive Analysis
domain: backend
status: documented
summary:
  - "For every death that can count, the backend lists the player's defensives as active, available or on cooldown, plus their Healthstone and health potion."
  - "It replays every hit from the 15 seconds before the death with each ready defensive pressed at its best moment, and says whether it would have saved them."
  - "A press is never earlier than the ability was ready and never later than 1 second before the killing blow; extra health only counts while the player was below full."
  - "Talents and spec are read per pull from the log; ability numbers come from a per-patch catalog built from game data."
  - "The result is attached to each death as `defensives`, with a `survival` block the Results page renders verdict-first."
tagline: What a player had ready when they died, and whether pressing it would have kept them alive.
invariants:
  - "MUST: only deaths that can count (slot within the deaths tracked, not in a wipe, not a cheat death) get defensive analysis."
  - "MUST: a replayed press happens no earlier than the ability came off cooldown and at least REACTION_MS (1s) before the killing blow."
  - "MUST: extra health from a defensive counts only up to what the player was missing at that moment."
  - "MUST: talents and spec come from that pull's CombatantInfo, not the report's main spec."
  - "MUST: event queries scoped by fightIDs always carry an endTime."
  - "NEVER: credit an immunity against a spell listed in IGNORES_IMMUNITY."
  - "NEVER: assume a player carries a Healthstone or potion they never used in the log, unless a Warlock in the pull had a Soulwell."
anchors:
  analyze_death: "backend/defensives.py:528"
  assess_survival: "backend/defensives.py:1570"
  simulate: "backend/defensives.py:1322"
  lethal_window: "backend/defensives.py:730"
  reaction_ms: "backend/defensives.py:734"
  press_times: "backend/defensives.py:1527"
  catalog_for: "backend/defensives.py:122"
  has_ability: "backend/defensives.py:375"
  index_events: "backend/defensives.py:326"
  consumable_estimate: "backend/defensives.py:1120"
  keep: "backend/defensives.py:1204"
  fetch_combatants: "backend/defensives.py:218"
  fetch_death_windows: "backend/defensives.py:801"
  app_gate: "backend/app.py:575"
  app_counted: "backend/app.py:326"
links:
  - backend-death-descriptions
  - backend-death-counting
  - game-data
  - warcraftlogs
  - frontend-results-view
  - feat-results
content_hash: sha256:b4380ebd3593b5f8930c35dda6a0773353f7219a2a20243b00bc857f7d2cd377
---
## Summary

- `backend/defensives.py` answers one question per death: **what could this player have pressed, and would it have kept them alive?**
- Each death gets three lists (`active`, `available`, `cooldown`), a `healthstone` and `potion` status, and, when the hits before the death were fetched, a `survival` block with a per-button verdict (`backend/defensives.py:584`, `backend/defensives.py:700`).
- The verdict comes from a replay, not a guess: every hit in the 15 seconds before the killing blow (`LETHAL_WINDOW_MS`, `backend/defensives.py:730`) is walked again with the defensive pressed at the moment that saves the most (`backend/defensives.py:1559`).
- Ability values, cooldowns, charges, durations and the talents that change them come from the per-patch catalog (`backend/defensive_catalog.py`), picked by the date the report was logged (`backend/defensives.py:122`).
- How the death is described (one-shot, burst, rot, set up by) is a separate step of the same function; see [[backend-death-descriptions]].

## How it works

The analyze stream in `backend/app.py` drives everything. Per report it fetches the defensive events once, then calls `analyze_death` for each death that can count. Click each step.

```steps
- title: Pick the patch catalog | short: Pick catalog | sub: patch live on the log date
  body: catalog_for turns the report's start time into a UTC date and picks the last patch in PATCHES whose first live day is on or before it (backend/defensives.py:122). Each Catalog splits the patch's abilities into personal, external and consumable (healthstone, potion) and records every talent entry the analysis will ever read (backend/defensives.py:70). With no start time it falls back to the latest patch.
  gotcha: CATALOG_FINGERPRINT (backend/defensives.py:166) is part of the defensive cache key in backend/app.py:363, so a rebuilt catalog never reuses data fetched for an older one.
- title: Fetch defensive events | short: Fetch events | sub: one query at a time
  body: The pipeline reads talent loadouts first, alone, with fetch_combatants (backend/defensives.py:218, backend/app.py:377); each CombatantInfo event is trimmed to who, which pull, spec and talent picks as its page arrives (_loadout, backend/defensives.py:209). fetch_defensive_raw then runs its paged WCL queries one after another and reuses those loadouts (backend/defensives.py:229). Casts and Buffs cover the whole report range from 3 minutes before the first pull (ENCOUNTER_RESET_MS, backend/defensives.py:34) so a button pressed just before a pull counts. CombatantInfo and consumable Healing are scoped to the boss pulls. filter_defensive_raw then keeps only players who died (backend/defensives.py:270).
  gotcha: The queries are not filtered by player in WCL. The code comment records that source.id / target.id filters return nothing on Casts and Buffs, and the unfiltered query costs fewer points.
- title: Index per pull | short: Index per pull | sub: talents and spec by fight
  body: index_defensive_events groups casts and auras by player and stores talents and spec keyed by (fightID, playerID), because players swap between pulls (backend/defensives.py:326). Talent trees are trimmed to the catalog's relevant entries. A specID missing from SPEC_NAMES logs an Unknown specID warning and the report's spec stands in (backend/defensives.py:344). Self-heals from consumables are kept with max health, healing-taken multiplier, Versatility and fight ID (backend/defensives.py:355).
- title: Fetch the hits before deaths | short: Fetch hits | sub: one block per nearby pulls
  body: For deaths that can count, fetch_death_windows asks WCL for DamageTaken from LETHAL_WINDOW_MS before the first death to just after the last, filtered by target.name (backend/defensives.py:801). Pulls within WINDOW_BLOCK_SPAN_MS (15 minutes) share one block, and up to 20 blocks go in one request (backend/defensives.py:749, backend/defensives.py:751). Each page is filtered as it arrives: a damage event is kept only if it falls inside a counted death's window (backend/defensives.py:840). A report with no death that can count skips this fetch, and the defensive one, entirely (backend/app.py:387). fetch_instakills adds instant kills, which carry no damage (backend/defensives.py:847). merge_hits joins both by player (backend/defensives.py:885).
  gotcha: The name filter uses json.dumps with ensure_ascii=False (backend/defensives.py:825) so accented names match; an escaped name matches nobody.
- title: Gate the death | short: Gate | sub: only deaths that can count
  body: In backend/app.py:575 analyze_death runs only when defensive data exists, the death has a target ID, is not a cheat death, its slot is within max_cutoff and it is not in a wipe. The spec passed is pull_spec for that fight, with the report's spec as fallback (backend/app.py:581). The armor constant of the boss and whether a Warlock was in the pull (soulwell) are passed too (backend/app.py:593, backend/app.py:519).
- title: Sort the buttons | short: Sort buttons | sub: active, available, cooldown
  body: For every personal defensive the player has (_has_ability, backend/defensives.py:375), analyze_death marks it active if its aura was up, otherwise simulates charges and cooldown up to the death (backend/defensives.py:589). Abilities with a cooldown of 3 minutes or more only look at presses during the pull; shorter ones look back one full recharge cycle (backend/defensives.py:599). Available buttons record when they last came off cooldown in ready_since.
  gotcha: A single-charge button recast faster than its catalog cooldown (by more than CDR_TOLERANCE_MS) uses the observed shortest gap, since talents must have shortened it (backend/defensives.py:440).
- title: Check consumables | short: Consumables | sub: Healthstone and potion
  body: For each of healthstone and potion, the last use this pull decides whether it is still on cooldown; cooldowns reset between pulls (backend/defensives.py:628). An unused one is only scored if the player used that kind somewhere in this log, or, for a Healthstone, a Warlock was in the pull (backend/defensives.py:648). consumable_estimate turns it into a heal amount (backend/defensives.py:1120).
- title: Replay the window | short: Replay | sub: best press per button
  body: assess_survival takes the hits from up to 15s before the killing blow, never reaching back past an earlier death of theirs (_lethal_hits, backend/defensives.py:1506). For each ready button it tries candidate press moments (_press_times) and keeps the one that leaves the most extra health (_best_press). The button would have saved them when that extra health exceeds the killing blow's overkill (backend/defensives.py:1646). It also tries everything pressed together (backend/defensives.py:1666).
  gotcha: Healers' real heals are left as they were. The replay only adds the defensive's effect on top of the real health line.
```

#### The replay, in more detail

`_simulate` (`backend/defensives.py:1322`) walks the hits in time order from the press to the killing blow:

- **Reductions, immunities and armor** take their share off each hit they cover, then **shields** soak what is left until they run out (`backend/defensives.py:1415`). Each lasting effect ends at press plus its talented duration (`_talented_duration`, `backend/defensives.py:419`).
- **Max health increases** add health when pressed and take it back when they expire (`backend/defensives.py:1348`).
- **Heals** land when pressed, or tick by tick for heals over time (`HEAL_OVER_TIME`, `backend/defensives.py:487`).
- **The overheal rule.** Before each hit, the extra health is capped at what the player was actually missing then (`backend/defensives.py:1411`), and each heal is capped the same way when it lands (`backend/defensives.py:1391`). Their real heals would have overhealed the rest.

`_press_times` (`backend/defensives.py:1527`) only tries moments that can matter: the earliest allowed time, the latest (`REACTION_MS` before the killing blow, `backend/defensives.py:1537`), and one millisecond before and after each hit in between. Health only rises between hits, so these points bound every other moment. Effects that last until death and do nothing else are simply pressed as early as allowed.

#### Mitigation, armor and immunities

`_keep` (`backend/defensives.py:1204`) works out what share of a hit still lands:

- A **school** limit (magic, physical, a game-data school mask, melee, AoE) is checked by `_school_applies` (`backend/defensives.py:902`). An immunity needs every school of the hit to match; a reduction needs any.
- A hit with nothing mitigated at all ignores damage reduction (`_ignores_reduction`, `backend/defensives.py:931`); shields and heals still work on it.
- An immunity does nothing against a spell in `IGNORES_IMMUNITY` (`backend/defensives.py:1219`), the generated set in `backend/boss_spell_flags.py:4`.
- **Armor increases** use the player's real armor from the hit and the boss's armor constant K: reduction is `armor / (armor + K)`, capped at 85% (`ARMOR_CAP`, `backend/defensives.py:939`), and only the added part counts (`_armor_dr`, `backend/defensives.py:967`). K comes from `ARMOR_K` by difficulty, falling back to Mythic, Heroic, then Normal (`armor_constant`, `backend/defensives.py:942`). Whether armor reduces a physical spell comes from `IGNORES_ARMOR` and `REDUCED_BY_ARMOR` (`backend/armor_constants.py:134`); boss melee always counts (`backend/defensives.py:958`).
- Shields the player actually received in this log replace the catalog estimate with the real size (`observed`, `backend/defensives.py:659`).

#### Potions and Healthstones

`consumable_estimate` (`backend/defensives.py:1120`) picks the heal in this order:

- **Healthstone**: the median share of max health from the player's own uses in the report; else, for Demonic Healthstone, the tier's measured share in `DEMONIC_HEALTHSTONE_MEASURED` (`backend/defensives.py:53`); else the game-data value with talents.
- **Potion**: the median of their own heals with healing-taken buffs removed, then the buffs up at death put back; else the potion's typical heal; if that potion has none, the tier's `STANDARD_POTION` stands in (`backend/defensives.py:58`, `backend/defensives.py:1170`). Healing-taken talents are applied on top.
- `potion_rank` (`backend/defensives.py:1080`) reports which quality rank they drink from their own heals, and refuses to claim a rank when ranks are closer than `RANK_BONUS_MAX` (16%) apart (`backend/defensives.py:1077`).

## Reference

What `analyze_death` returns, attached as `death_event['defensives']` (`backend/app.py:596`).

| Field {death} | Meaning |
|---|---|
| `active` {death} | Defensives whose aura was up at death; externals carry `by` (who cast it) |
| `available` {death} | Ready but not pressed; may carry `boostedBy` (talents) and `withForm` (needs a form first) |
| `cooldown` {death} | Pressed earlier and not back: `readyIn`, `usedAgo` in seconds |
| `healthstone`, `potion` {death} | `usedAgo` (null if unused), `lastUsedAgo`, `readyIn`, `rank` for potions |
| `talentsKnown`, `activeKnown` {death} | Whether the pull's talents and the auras at death were in the log |
| `survival.wouldSave` {survival} | Name to `true` / `false` / `null` (cannot estimate) |
| `survival.details` {survival} | Per button: `amount` saved, `pressAgo`, `why` when it saves nothing, `effect`, `talents`, `source`, `samples`, `hot` |
| `survival.allTogetherWouldSave` {survival} | Everything ready pressed at its best shared moment |
| `survival.ignoresReduction`, `ignoresImmunity` {survival} | The killing blow ignored reductions or pierces immunities |
| `survival.window` {survival} | How many hits were replayed and from how many seconds before |
| `survival.deathType`, `killingHit`, `rot`, `burst`, `biggestHit` {describe} | The death description; see [[backend-death-descriptions]] |

Values of `details[].why` from `_explain` (`backend/defensives.py:1449`) and `assess_survival`:

| `why` {why} | When |
|---|---|
| `school` {why} | The effect is limited to a school the hit is not |
| `aoeUnknown` / `armorUnknown` {why} | The log cannot say whether it applies |
| `notArmor` {why} | An armor effect against a hit armor does not reduce |
| `pierces` {why} | An immunity against a spell in `IGNORES_IMMUNITY` |
| `noReduction` {why} | A reduction against a hit that ignored reduction |
| `fullHealth` / `tooFast` {why} | A heal with no missing health to fill in time |
| `readyTooLate` {why} | Not ready before the 1-second cutoff |
| `hotTooLate` {why} | No heal-over-time tick would have landed before the killing blow |
| `instakill` {why} | Instant kill: nothing to reduce, absorb or heal |

Also sent once per result by `backend/app.py`: `abilityInfo` (each ability's general effect, `ability_info`, `backend/defensives.py:147`) and `icons` (`backend/app.py:656`).

## Context map

```context
depends-on: [[game-data]] — defensive_catalog.py, armor_constants.py, boss_spell_flags.py, spell_icons.py
depends-on: [[warcraftlogs]] — Casts, Buffs, CombatantInfo, Healing, DamageTaken and instakill events
depends-on: [[backend-death-counting]] — slot and inWipe decide which deaths are analyzed
provides: per-death `defensives` with active / available / cooldown lists
provides: the `survival` replay verdict per button and all together
relied-on-by: [[backend-death-descriptions]] — the same function classifies how the death happened
relied-on-by: [[frontend-results-view]] — renders the verdicts and tooltips
relied-on-by: [[feat-results]] — the death breakdown a raid officer reads
```

## Invariants

- **MUST** analyze only deaths that can count: target known, not a cheat death, `slot <= max_cutoff`, not in a wipe (`backend/app.py:575`); the hits are fetched for the same set (`backend/app.py:326`).
- **MUST** press no earlier than the ability was ready (`ready_since`) and no later than `REACTION_MS` (1s) before the killing blow (`backend/defensives.py:1642`, `backend/defensives.py:1537`).
- **MUST** cap extra health at what the player was missing before each hit and at each heal (`backend/defensives.py:1411`, `backend/defensives.py:1391`); otherwise a defensive on a full-health player would look like it saved them.
- **MUST** read talents and spec from that pull's CombatantInfo (`backend/defensives.py:547`, `backend/app.py:581`); players change both between pulls.
- **MUST** send an `endTime` with every fightIDs-scoped events query (`backend/defensives.py:775`); WCL returns an empty second page without one.
- **NEVER** count an immunity against a spell in `IGNORES_IMMUNITY` (`backend/defensives.py:1219`).
- **NEVER** assume a carried Healthstone or potion the player never used in this log, unless a Warlock in the pull offered a Soulwell (`backend/defensives.py:648`).

## Gotchas

- **The killing blow's aura list decides what was up**: when a damaging killing blow exists, its `buffs` snapshot is the source of truth for active auras; aura events only add who cast them (`backend/defensives.py:567`). Without one, aura events decide, capped at 1.5 times the aura's longest duration plus a second in case a removal was missed (`backend/defensives.py:48`, `backend/defensives.py:507`).
- **Pressing a button proves you have it**: `_has_ability` accepts a button pressed this pull even if the talent record disagrees (`backend/defensives.py:380`). Abilities marked `evidence`, or a pull with no talent record, count only if cast somewhere in the log.
- **No killing blow with health data means no survival block**: `assess_survival` returns `None` when the killing blow is missing or its health belongs to someone else (`backend/defensives.py:1599`). `index_hits` strips health WCL attached from the source actor (`backend/defensives.py:873`).
- **Older logs do not mark AoE hits**: if a report has no hit with `isAoE`, AoE-only effects are judged unknown (`null`) instead of not applying (`logs_mark_aoe`, `backend/defensives.py:855`; `backend/defensives.py:914`).
- **Forms are judged as shift then press**: a button that needs a form the player was not in (Frenzied Regeneration needs Bear Form) is scored together with the form (`backend/defensives.py:674`, `backend/defensives.py:1637`).
- **Defensive data failure does not drop deaths**: if the defensive fetch fails, the report's deaths still count and the stream warns that defensive details are missing (`backend/app.py:405`, `backend/app.py:467`).

## Glossary

- **Lethal window**: the 15 seconds of hits before a killing blow that the replay walks (`LETHAL_WINDOW_MS`).
- **Reaction time**: the 1 second before the killing blow in which no press is allowed (`REACTION_MS`).
- **Overkill**: damage the killing blow dealt beyond the health the player had left; a defensive saves them if it adds more than this.
- **Catalog**: the per-patch table of defensives, potions and Healthstones built from game data (`backend/defensive_catalog.py`).
- **ready_since**: when an available button last came off cooldown; the earliest moment the replay may press it.
- **Armor constant**: the boss-specific K in `armor / (armor + K)`, measured from real pulls (`backend/armor_constants.py`).
- **Soulwell**: a Warlock's table of Healthstones; a Warlock in the pull means everyone is assumed to carry one.

## Related

- [[backend-death-descriptions]] — how the same replay window labels the death
- [[backend-death-counting]] — slots and wipes that decide which deaths are analyzed
- [[game-data]] — the generated catalog, armor, immunity and icon modules
- [[warcraftlogs]] — the event queries and their point costs
- [[frontend-results-view]] — where `defensives` and `survival` are rendered
- [[feat-results]] — the user-facing death breakdown
