# Site art (self-hosted)

Everything here is committed and served by the site itself; nothing is hotlinked.

- `backgrounds/` — landing-page backgrounds, `<slug>.jpg`, 2200px wide, JPEG
  quality 72, progressive. One is picked per page load: from
  `CURRENT_TIER_BACKGROUNDS` half the time (`CURRENT_TIER_CHANCE`), otherwise
  from `BACKGROUNDS` (both in `src/LandingPage.js`). To add one, drop the file
  here and add its slug to the right list; when a new tier ships, move the
  previous tier's slugs down into `BACKGROUNDS`.
- `landing-keyart.svg` — fallback shown only if the chosen background fails to load.
- `bosses/` — boss tiles for the landing strip and the Analyze page; see
  `bosses/README.md`.
- `quality/` — item-quality icons used in death rows on the Results page (`src/DeathRow.js`).
- `<boss>-loader.webm` + `.jpg` — the looping model video on the analysis
  loading screen and its first-frame still (`src/App.js`).

The footer carries the Blizzard non-affiliation, trademark and key-art notice.
If the site ever becomes commercial, revisit the use of this art.

Full detail: `docs/atlas`, page "Landing Page and Art" (frontend).
