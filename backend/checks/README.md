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

The environment needs `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET` (the WarcraftLogs API client). They live in `.claude/settings.local.json`. Nothing is read from Supabase.

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
- `mitigation` cannot measure, and leaves out: Fiery Brand (it cuts the branded enemy's damage, which WCL already counts in the hit's unmitigated size), Dampen Harm (20% to 50% by hit size), Brewmaster Stagger ticks (never reduced at tick time), and a defensive on a spec the catalog doesn't give it to (Bear Form on a Guardian). It judges each defensive by the median gap over its hits, so one boss ability with an untracked modifier can't decide it. A reduction that grows with missing health (Bloody Fortitude on Icebound Fortitude) is predicted from the player's own health on each hit; hits without it are left out.
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
