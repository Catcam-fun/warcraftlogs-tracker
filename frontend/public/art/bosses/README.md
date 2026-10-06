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
   `frontend/scripts/fetch-boss-renders.py`, to `BOSS_STRIP` in
   `src/LandingPage.js`, and to the raid's entry in `src/AnalyzeConfig.js`
   (its `final` boss is the raid-card art, its `bosses` list the lineup).
   Multi-boss fights also go in `COUNCIL` in all three files.
2. `python frontend/scripts/fetch-boss-renders.py "Boss One" "Boss Two"`
   (writes the `.webp`s straight into this folder; needs Pillow).
3. Look at every result. If a boss's name doesn't match its journal
   encounter, pin the encounter ID in `ENC_OVERRIDE` (keyed by lowercased
   name). If a journal creature renders badly, pin display IDs in
   `DISPLAY_OVERRIDE` (keyed by slug); the list replaces the journal's
   models, so for a council list every member. `npm run build`. Done.

Each run prints a summary and writes `frontend/scripts/_boss_results.json`
with every boss's status, so a miss (`no_enc`, `no_disp`, `err:…`) can be
fixed with an override or grabbed by hand.

> Official Blizzard art, used under fan-content guidelines; footer
> carries the non-affiliation + trademark notices.
