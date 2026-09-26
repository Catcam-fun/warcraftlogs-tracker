# Boss strip art — auto-sourced

All 42 boss tiles are filled with **official Blizzard creature renders**,
fetched fully automatically (no credentials, no manual screenshots).

## How it works (pipeline)

`frontend/scripts/fetch-boss-renders.py`:

1. For each boss name, query **wago.tools** DB2 (public, no auth):
   - `JournalEncounter/csv` → JournalEncounter ID
   - `JournalEncounterCreature/csv` → CreatureDisplayInfoID
2. Download the official render from Blizzard's public CDN:
   `https://render.worldofwarcraft.com/us/npcs/zoom/creature-display-<id>.jpg`
3. Cut out the background, composite council members side by side, and
   save 300px tall → `public/art/bosses/<slug>.webp`

`<slug>` = boss name lowercased, non-alphanumerics → `-`
(same rule as `LandingPage.js`), so tiles pick them up automatically.

## Updating for a new raid

1. Add the new boss names to `BOSSES` in
   `frontend/scripts/fetch-boss-renders.py` **and** to `BOSS_STRIP`
   in `src/LandingPage.js` (multi-boss fights also go in `COUNCIL`
   in both files).
2. `python frontend/scripts/fetch-boss-renders.py "Boss One" "Boss Two"`
   (writes the `.webp`s straight into this folder; needs Pillow).
3. Look at the results; if a journal creature renders badly, pin a
   display ID in `DISPLAY_OVERRIDE`. `npm run build`. Done.

It resolved 33/33 including unreleased Midnight bosses. If a future
boss misses, the script logs it (`_results.json`) for a manual grab.

> Official Blizzard art, used under fan-content guidelines; footer
> carries the non-affiliation + trademark notices.
