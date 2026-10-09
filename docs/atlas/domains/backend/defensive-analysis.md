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
  analyze_death: "backend/defensives.py:591"
  assess_survival: "backend/defensives.py:1949"
  simulate: "backend/defensives.py:1485"
  lethal_window: "backend/defensives.py:849"
  reaction_ms: "backend/defensives.py:853"
  press_times: "backend/defensives.py:1690"
  catalog_for: "backend/defensives.py:150"
  has_ability: "backend/defensives.py:418"
  index_events: "backend/defensives.py:369"
  consumable_estimate: "backend/defensives.py:1283"
  keep: "backend/defensives.py:1367"
  fetch_combatants: "backend/defensives.py:246"
  fetch_death_windows: "backend/defensives.py:937"
  app_gate: "backend/app.py:583"
  app_counted: "backend/app.py:325"
links:
  - backend-death-descriptions
  - backend-death-counting
  - game-data
  - warcraftlogs
  - frontend-results-view
  - feat-results
content_hash: sha256:2432ed595cb8ab3e94b8ae50fc64c62a8b150f8d4713db250f2a7ba591b32dc0
---
## Summary

- `backend/defensives.py` answers one question per death: **what could this player have pressed, and would it have kept them alive?**
- Each death gets three lists (`active`, `available`, `cooldown`), a `healthstone` and `potion` status, and, when the hits before the death were fetched, a `survival` block with a per-button verdict (`backend/defensives.py:655`, `backend/defensives.py:817`).
- The verdict comes from a replay, not a guess: every hit in the 15 seconds before the killing blow (`LETHAL_WINDOW_MS`, `backend/defensives.py:849`) is walked again with the defensive pressed at the moment that saves the most (`backend/defensives.py:1722`).
- Ability values, cooldowns, charges, durations and the talents that change them come from the per-patch catalog (`backend/defensive_catalog.py`), picked by the date the report was logged (`backend/defensives.py:150`).
- How the death is described (one-shot, burst, rot, set up by) is a separate step of the same function; see [[backend-death-descriptions]].

## How it works

The analyze stream in `backend/app.py` drives everything. Per report it fetches the defensive events once, then calls `analyze_death` for each death that can count. Click each step.

```steps
- title: Pick the patch catalog | short: Pick catalog | sub: patch live on the log date
  body: catalog_for turns the report's start time into a UTC date and picks the last patch in PATCHES whose first live day is on or before it (backend/defensives.py:150). Each Catalog splits the patch's abilities into personal, external and consumable (healthstone, potion) and records every talent entry the analysis will ever read (backend/defensives.py:92). With no start time it falls back to the latest patch.
  gotcha: CATALOG_FINGERPRINT (backend/defensives.py:194) is part of the defensive cache key in backend/app.py:364, so a rebuilt catalog never reuses data fetched for an older one.
- title: Fetch defensive events | short: Fetch events | sub: one query at a time
  body: The pipeline reads talent loadouts first, alone, with fetch_combatants (backend/defensives.py:246, backend/app.py:378); each CombatantInfo event is trimmed to who, which pull, spec and talent picks as its page arrives (_loadout, backend/defensives.py:237). fetch_defensive_raw then runs its paged WCL queries one after another and reuses those loadouts (backend/defensives.py:257). Casts start at cast_lookback (backend/defensives.py:257): 3 minutes before the first pull, or for long cooldowns back to the end of the last boss encounter before it (at most the longest tracked cooldown, Lay on Hands' 10 minutes), since a press after that encounter ended carries into the pull; buffs start 3 minutes before the first pull. CombatantInfo and consumable Healing are scoped to the boss pulls. filter_defensive_raw then keeps the casts, buffs and heals of the players who died, and every player's loadout: an aura another player cast on someone who died is sized with the caster's talents (backend/defensives.py:311).
  gotcha: The queries are not filtered by player in WCL. The code comment records that source.id / target.id filters return nothing on Casts and Buffs, and the unfiltered query costs fewer points.
- title: Index per pull | short: Index per pull | sub: talents and spec by fight
  body: index_defensive_events groups casts and auras by player and stores talents and spec keyed by (fightID, playerID), because players swap between pulls (backend/defensives.py:369). Talent trees are trimmed to the catalog's relevant entries, which include every talent that changes an aura's max health (MAX_HEALTH_ENTRIES). A specID missing from SPEC_NAMES logs an Unknown specID warning and the report's spec stands in (backend/defensives.py:387). Self-heals from consumables are kept with max health, healing-taken multiplier, Versatility and fight ID (backend/defensives.py:398).
- title: Fetch the hits before deaths | short: Fetch hits | sub: one block per nearby pulls
  body: For deaths that can count, fetch_death_windows asks WCL for DamageTaken from LETHAL_WINDOW_MS before the first death to just after the last, filtered by target.name (backend/defensives.py:937). Pulls within WINDOW_BLOCK_SPAN_MS (15 minutes) share one block, and up to 20 blocks go in one request (backend/defensives.py:872, backend/defensives.py:874). Each page is filtered as it arrives: a damage event is kept only if it falls inside a counted death's window (backend/defensives.py:997). A report with no death that can count skips this fetch, and the defensive one, entirely (backend/app.py:388). fetch_instakills adds instant kills, which carry no damage (backend/defensives.py:1010). merge_hits joins both by player (backend/defensives.py:1048). One more block in the same request, from the All stream over all those pulls, reads on the players who died (WINDOW_EXTRAS_IDS) the heals a killing hit can set off with their cheat-death auras' absorbs and removals (features.KILLING_HIT_HEALS: Defy Fate, Cauterize, Guardian Spirit, Ardent Defender, Embrace the Shadow, Void Reconstitution; Last Resort's absorb and Metamorphosis heal), the stack changes of stacking max-health auras (Sentinel, Bone Shield) and the aura events of auras sized by a loadout (who cast them: Rallying Cry): measured 15.0 -> 19.4 points on a 27-pull report, warm cache. Reading only the auras the dying players' hits list, in a second request after the hits, saved nothing (most of the block's events are heals). The All stream can't replace DamageTaken: it leaves the aura list off damage events. The windows' cache key (app.py) carries WINDOW_EXTRAS_KEY, a hash of those IDs, so windows cached without them are not reused; CACHE_VERSION is unchanged, so a report's other cached data stays valid.
  gotcha: The name filter uses json.dumps with ensure_ascii=False (backend/defensives.py:974) so accented names match; an escaped name matches nobody.
- title: Gate the death | short: Gate | sub: only deaths that can count
  body: In backend/app.py:583 analyze_death runs only when defensive data exists, the death has a target ID, is not a cheat death, its slot is within max_cutoff and it is not in a wipe. The spec passed is pull_spec for that fight, with the report's spec as fallback (backend/app.py:589). The armor constant of the boss and whether a Warlock was in the pull (soulwell) are passed too (backend/app.py:601, backend/app.py:527).
- title: Sort the buttons | short: Sort buttons | sub: active, available, cooldown
  body: For every personal defensive the player has (_has_ability, backend/defensives.py:418), analyze_death marks it active if its aura was up, otherwise replays its charges up to the death (_replay, backend/defensives.py:504). Abilities with a cooldown of 3 minutes or more reset when a boss encounter ends, wipe or kill (any boss encounter of the report, kept or not), so they look at presses since the last encounter that ended before this pull: a press after a wipe carries into the next pull (backend/defensives.py:682); shorter ones replay every earlier press in the report, charges coming back one at a time from the first spend (backend/defensives.py:701). Each press counts with the talents and spec of the latest kept pull that had started by then (a press in an unkept pull or between pulls uses the previous kept pull's), or the first kept pull's for a press before it, since talents change only out of combat (loadout_at, backend/defensives.py:669). A cast of a spell in the entry's reset_by brings it back at once: Cold Snap every charge of Ice Barrier, Ice Block and Ice Cold; Black Ox Brew every charge of Celestial Brew up to 12.0.1, one charge from 12.0.5. Available buttons record when they last came off cooldown in ready_since, so a press is never credited before the cast that put it on cooldown has run out or a reset brought it back, even when that cast was more than one cooldown before the death.
  gotcha: A single-charge button recast faster than its talented cooldown (by more than CDR_TOLERANCE_MS), with no reset cast in between and, for a cooldown of 3 minutes or more, no boss encounter end in between (the encounter reset), uses the observed shortest gap, since something must have shortened it (_inferred_cooldown, backend/defensives.py:487); a gap a reset falls in measures the reset, not the cooldown. The game data doesn't say when the reset happens; the end is taken from logs. Across 14 reports, 35 presses made between pulls were pressed again in the next pull, never sooner than their cooldown allows from the press between pulls: one Frost Mage pressed Ice Cold again 1.2 s after the 180 s cooldown from a press 123 s before the pull ran out, and the one shorter gap, a Protection Paladin's Guardian of Ancient Kings (212 s of 300 s), is covered by Gift of the Golden Val'kyr (1 s per Avenger's Shield hit, 69 hits) and Righteous Protector (1.5 s per Holy Power spender, 47 casts). Without the report's encounter list the site falls back to this pull's start. For a cooldown cut by play rather than a fixed talent (Red Thirst on Vampiric Blood, Keg Smash and Tiger Palm on Celestial Brew, Natural Mending on Exhilaration before 12.0, Shifting Power on Mage cooldowns), the shortest gap is the best cycle seen, not the cycle at the death, so that ready time is an estimate.
- title: Check consumables | short: Consumables | sub: Healthstone and potion
  body: For each of healthstone and potion, the last use this pull decides whether it is still on cooldown; cooldowns reset between pulls (backend/defensives.py:738). An unused one is only scored if the player used that kind somewhere in this log, or, for a Healthstone, a Warlock was in the pull (backend/defensives.py:758). consumable_estimate turns it into a heal amount (backend/defensives.py:1283).
- title: Replay the window | short: Replay | sub: best press per button
  body: assess_survival takes the hits from up to 15s before the killing blow, never reaching back past an earlier death of theirs (_lethal_hits, backend/defensives.py:1669). For each ready button it tries candidate press moments (_press_times) and keeps the one that leaves the most extra health (_best_press). The button would have saved them when that extra health exceeds the killing blow's overkill (backend/defensives.py:2040). It also tries everything pressed together (backend/defensives.py:2060).
  gotcha: Healers' real heals are left as they were. The replay only adds the defensive's effect on top of the real health line.
```

#### The replay, in more detail

`_simulate` (`backend/defensives.py:1485`) walks the hits in time order from the press to the killing blow:

- **Reductions, immunities and armor** take their share off each hit they cover, then **shields** soak what is left until they run out (`backend/defensives.py:1578`). Each lasting effect ends at press plus its talented duration (`_talented_duration`, `backend/defensives.py:462`).
- **Max health increases** add health when pressed and take it back when they expire (`backend/defensives.py:1511`).
- **Heals** land when pressed, or tick by tick for heals over time (`HEAL_OVER_TIME`, `backend/defensives.py:550`).
- **The overheal rule.** Before each hit, the extra health is capped at what the player was actually missing then (`backend/defensives.py:1574`), and each heal is capped the same way when it lands (`backend/defensives.py:1554`). Their real heals would have overhealed the rest.

`_press_times` (`backend/defensives.py:1690`) only tries moments that can matter: the earliest allowed time, the latest (`REACTION_MS` before the killing blow, `backend/defensives.py:1700`), and one millisecond before and after each hit in between. Health only rises between hits, so these points bound every other moment. Effects that last until death and do nothing else are simply pressed as early as allowed.

#### Mitigation, armor and immunities

`_keep` (`backend/defensives.py:1367`) works out what share of a hit still lands:

- A **school** limit (magic, physical, a game-data school mask, melee, AoE) is checked by `_school_applies` (`backend/defensives.py:1065`). An immunity needs every school of the hit to match; a reduction needs any.
- A hit with nothing mitigated at all ignores damage reduction (`_ignores_reduction`, `backend/defensives.py:1094`); shields and heals still work on it.
- An immunity does nothing against a spell in `IGNORES_IMMUNITY` (`backend/defensives.py:1382`), the generated set in `backend/boss_spell_flags.py:4`.
- **Armor increases** use the player's real armor from the hit and the boss's armor constant K: reduction is `armor / (armor + K)`, capped at 85% (`ARMOR_CAP`, `backend/defensives.py:1102`), and only the added part counts (`_armor_dr`, `backend/defensives.py:1130`). K comes from `ARMOR_K` by difficulty, falling back to Mythic, Heroic, then Normal (`armor_constant`, `backend/defensives.py:1105`). Whether armor reduces a physical spell comes from `IGNORES_ARMOR` and `REDUCED_BY_ARMOR` (`backend/armor_constants.py:134`); boss melee always counts (`backend/defensives.py:1121`).
- Shields the player actually received in this log replace the catalog estimate with the real size (`observed`, `backend/defensives.py:769`).

#### Potions and Healthstones

`consumable_estimate` (`backend/defensives.py:1283`) picks the heal in this order:

- **Healthstone**: the median share of max health from the player's own uses in the report; else, for Demonic Healthstone, the tier's measured share in `DEMONIC_HEALTHSTONE_MEASURED` (`backend/defensives.py:55`); else the game-data value with talents.
- **Potion**: the median of their own heals with healing-taken buffs removed, then the buffs up at death put back; else the potion's typical heal; if that potion has none, the tier's `STANDARD_POTION` stands in (`backend/defensives.py:60`, `backend/defensives.py:1333`). Healing-taken talents are applied on top.
- `potion_rank` (`backend/defensives.py:1243`) reports which quality rank they drink from their own heals, and refuses to claim a rank when ranks are closer than `RANK_BONUS_MAX` (16%) apart (`backend/defensives.py:1240`).

## Reference

What `analyze_death` returns, attached as `death_event['defensives']` (`backend/app.py:608`).

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
| `survival.deathType`, `killingHit`, `rot`, `burst`, `oneShotHit`, `biggestHit` {describe} | The death description; see [[backend-death-descriptions]] |

Values of `details[].why` from `_explain` (`backend/defensives.py:1612`) and `assess_survival`:

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

Also sent once per result by `backend/app.py`: `abilityInfo` (each ability's general effect, `ability_info`, `backend/defensives.py:175`) and `icons` (`backend/app.py:668`).

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

- **MUST** analyze only deaths that can count: target known, not a cheat death, `slot <= max_cutoff`, not in a wipe (`backend/app.py:583`); the hits are fetched for the same set (`backend/app.py:325`).
- **MUST** press no earlier than the ability was ready (`ready_since`) and no later than `REACTION_MS` (1s) before the killing blow (`backend/defensives.py:2036`, `backend/defensives.py:1700`).
- **MUST** cap extra health at what the player was missing before each hit and at each heal (`backend/defensives.py:1574`, `backend/defensives.py:1554`); otherwise a defensive on a full-health player would look like it saved them.
- **MUST** read talents and spec from that pull's CombatantInfo (`backend/defensives.py:618`, `backend/app.py:589`); players change both between pulls.
- **MUST** send an `endTime` with every fightIDs-scoped events query (`backend/defensives.py:911`); WCL returns an empty second page without one.
- **NEVER** count an immunity against a spell in `IGNORES_IMMUNITY` (`backend/defensives.py:1382`).
- **NEVER** assume a carried Healthstone or potion the player never used in this log, unless a Warlock in the pull offered a Soulwell (`backend/defensives.py:758`).

## Gotchas

- **The killing blow's aura list decides what was up**: when a damaging killing blow exists, its `buffs` snapshot is the source of truth for active auras; aura events only add who cast them (`backend/defensives.py:638`). Without one, aura events decide, capped at 1.5 times the aura's longest duration plus a second in case a removal was missed (`backend/defensives.py:50`, `backend/defensives.py:570`).
- **Pressing a button proves you have it**: `_has_ability` accepts a button pressed this pull even if the talent record disagrees (`backend/defensives.py:423`). Abilities marked `evidence`, or a pull with no talent record, count only if cast somewhere in the log.
- **No killing blow with health data means no survival block**: `assess_survival` returns `None` when the killing blow is missing or its health belongs to someone else (`backend/defensives.py:1986`). `index_hits` strips health WCL attached from the source actor (`backend/defensives.py:1036`).
- **Older logs do not mark AoE hits**: if a report has no hit with `isAoE`, AoE-only effects are judged unknown (`null`) instead of not applying (`logs_mark_aoe`, `backend/defensives.py:1018`; `backend/defensives.py:1077`).
- **Forms are judged as shift then press**: a button that needs a form the player was not in (Frenzied Regeneration needs Bear Form) is scored together with the form (`backend/defensives.py:784`, `backend/defensives.py:2031`).
- **Defensive data failure does not drop deaths**: if the defensive fetch fails, the report's deaths still count and the stream warns that defensive details are missing (`backend/app.py:413`, `backend/app.py:475`).

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
