# Checks: does the site agree with WarcraftLogs?

These checks read a real raid log straight from WarcraftLogs (WCL), run the site's own analysis on the same log, and compare the two. They never change the site. If a check fails, either the site is wrong or the check is wrong.

## How to run

From the repo folder:

```
cd backend
.venv\Scripts\python.exe -m checks all <target> [<target> ...]
```

Instead of `all` you can use:

- `source`: only the checks that compare against WCL's own data.
- `rules`: only the checks that hold the site to the owner's rules.
- a check name from the table below, for example `labels`.
- `find-logs`: picks one finished Mythic log per raid for you (see below).

Add `--json results.json` to also save the results to a file.

### Targets

A target is a report code and a raid key, joined by a colon:

```
2VtyDR4CF6PGLjbd:manaforge
```

The raid key must be one of the raids the site services (the keys of `RAID_ENCOUNTERS`, the Analyze page's raid choices). If WCL has no guild attached to the report, add the guild, its server and its region:

```
2VtyDR4CF6PGLjbd:manaforge:Honestly/Frostmourne/US
```

### Finding logs

```
.venv\Scripts\python.exe -m checks find-logs
```

This prints one target per raid, ready to paste. It looks at WCL's top Mythic rankings for the raid, prefers US and EU guilds, and takes the first report that has at least 3 Mythic wipes and ended more than 2 hours ago. If it cannot find one it prints `<raid>: no log found`. Give it raid keys to look up only those raids. It costs a few WCL points per raid.

### Keys

The environment needs `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET` (the WarcraftLogs API client) set. Nothing is read from or written to Supabase: the in-process analysis never reads or writes the shared report cache.

## What each check holds the site to

| Check | Family | Rule |
| --- | --- | --- |
| deaths | source | Deaths the site reads match WCL's Deaths table |
| selection | source | The pulls and kills the site kept match the guild's reports on WCL |
| participation | source | Who was in each kept pull, and who counts as roster, match WCL |
| state | source | Active, ready and health at death match WCL's auras, casts and Deaths table |
| durations | source | Defensive durations (catalog + talents) match real aura uses |
| mitigation | source | Catalog damage reductions match real hits with and without the defensive |
| slots | rules | Slots and wipes follow the owner's rules |
| counting | rules | A death counts when slot <= X and not in a wipe; defensives exist exactly on deaths that can count |
| labels | rules | Death labels follow the rules: one-shot, burst, rot (raid-wide only) or set up by |
| verdicts | rules | Would-save verdicts obey the press, overkill, immunity and instant-kill rules |
| defensives | rules | Talent entry IDs in the log match the catalog |

"source" checks compare against what WCL says. "rules" checks recompute the owner's rules separately and compare with what the site shows.

## What the results mean

- **pass**: the site agreed with the check on everything it looked at.
- **FAIL**: something differed. The output lists the first 10 items that differ.
- **skip**: the check could not run on this log (for example the guild or data it needs was missing). A skip is not a pass; it says why.

The exit code is non-zero if anything failed.

## When a check fails

A fail is either a site bug or a check bug. Look at the listed items and at the log on WCL first. Decide which side is wrong. Then show the owner what you found before changing any site code.

## Points

Each run prints how many WCL points it spent. The budget is 9000 an hour (measured 2026-10-07), so a whole sweep over every raid is fine, but do not run it in a loop.

## Limits

- Mythic only (difficulty 5).
- The end-to-end run sends no alt groups (`characterGroups`), so alt merging is not covered.
- Cheat deaths are switched off in the run.
- `mitigation` cannot measure, and leaves out: Brewmaster Stagger ticks (never reduced at tick time), and a defensive on a spec the catalog doesn't give it to (Bear Form on a Guardian).
- In The War Within, Fiery Brand cuts the branded enemy's damage (the catalog marks it `from_target`, from the game data), which WCL already counts in the hit's unmitigated size. `mitigation` measures it on raw sizes instead: two back-to-back hits from the same enemy with the same ability, one branded and one not, at most 3 seconds apart. Comparing all branded hits with all unbranded ones would read too low, because boss abilities such as Liquefy grow over their cast and players brand at the start. From Midnight (12.0.0) Fiery Brand is a buff on the Demon Hunter that cuts every hit, measured like any other buff.
- Dampen Harm takes 20% to 50%, more off larger hits (the catalog's `dr_hit`, from the game data). `mitigation` predicts each hit: the catalog's 20%, plus 30% times the hit's size (after the player's other reductions) as a share of max health, capped at 50%. Hits without the player's health on them are left out.
- A reduction per stack (Sentinel: 2% a stack, 15 stacks dropping one a second) is left out of `mitigation`: a hit's aura list says the aura was up, not how many stacks.
- A reduction that grows with missing health (Bloody Fortitude on Icebound Fortitude) is predicted from the player's own health on each hit; hits without it are left out.
- `mitigation` judges each defensive by the median gap over its hits (pairs, for The War Within's Fiery Brand), so one boss ability with an untracked modifier can't decide it. A failure line reads "measured X, catalog Y over N hits" (N pairs for The War Within's Fiery Brand); where each hit has its own prediction (Dampen Harm, Bloody Fortitude) it reads "measured X, predicted Y (catalog Z)", Y being the mean per-hit prediction.
- A pass means the catalog's numbers match real hits, not that the site applies them correctly.
- The Dampen Harm rule was fitted and confirmed on Brewmaster logs only. It is unverified whether WCL lists a second Demon Hunter's brand on a hit, which matters only with two Vengeance Demon Hunters in a raid.
- `state` compares the site's max HP with WCL's just before the killing hit, worked out separately from WCL's own data: the max on the player's last own-health hit (resourceActor 2, or 1 on self-damage), with the auras its list and the killing hit's differ by sized from game data (`max_health_auras.py`) with the player's talents and spec from WCL's CombatantInfo, evaluated by the checks' own code, not the site's. A death whose max can't be sized (a size not in the data, or a talent-dependent size with no loadout in the log) is skipped, and the check says how many and why. An aura whose size depends on talents or spec is sized with its caster's loadout (a warrior's Rallying Cry with Battlefield Commander is x1.12 on everyone), the caster from the player's aura events; without the caster or their loadout the death is skipped with the reason. It reads the player's heals in the 50 ms before the killing hit when the hit was partly absorbed, its aura list gained or lost an aura, or it took more than the list-based max; only when a heal landed there does it read the Buffs table, for an aura the killing hit set off (Last Resort's Metamorphosis) or a cheat-death aura used up as it healed (Guardian Spirit: its band ends just before its heal), whose heal is not health they had. The killing hit's own max is logged after the death stripped the player's auras, so it is never used alone. A stacking max-health aura on the player's hits (Sentinel) counts per stack, read from the player's Buffs and Debuffs events in the 15 s before (both by `sourceID`, the unit that has the aura: `targetID` returns the player's own casts on anyone); when its stacks can't be told, the death is skipped with the reason. `labels` uses the same max and health and measures every hit against the max it landed at. Each counted death reads its damage taken (about 1 point).
- `state` reads an active defensive as up at death when its aura band reaches the death event or the moment the death stripped the player's auras (the earliest end of a cluster, in the second before the death event, of at least two bands up since the pull started ending within 150 ms of each other, and more than half of those that end there; one such band ending alone is not a strip). WCL's death event can come 100+ ms after that strip. A battle-rezzed player's second death has no such band and uses the death event.

## Last known-good logs

| Raid key | Target | Date |
| --- | --- | --- |
| midnight-s2-all | `FaC4AgJ8vMTfP1VN:midnight-s2-all:Tony Halme Pro Skater/Stormreaver/EU` | 2026-10-08 |
| manaforge | `2VtyDR4CF6PGLjbd:manaforge:Honestly/Frostmourne/US` | 2026-10-08 |
| undermine | `yYZJNhcDk37Tj4AM:undermine:Honestly/Frostmourne/US` | 2026-10-08 |
| nerubar | `WgYbA1r7fXdZKtPF:nerubar:Advance/Draenor/EU` | 2026-10-08 |
| voidspire | `P6CwHkgFR9Krf1Bz:voidspire:Honestly/Frostmourne/US` | 2026-10-08 |
| dreamrift | `k2YL7RG89c3MTWnF:dreamrift:Vindicatum/Icecrown/US` | 2026-10-08 |
| queldanas | `D6RNkvp9qBZfHXYz:queldanas:Honestly/Frostmourne/US` | 2026-10-08 |
| midnight-all | `P6CwHkgFR9Krf1Bz:midnight-all:Honestly/Frostmourne/US` | 2026-10-08 |

A single `all` run costs about 200-500 WCL points; a sweep of four raids at once costs about 1300-1700, measured on the shared key (each run's own points line includes whatever else the key spent at the same time). `state` reads every counted death (no cap).
