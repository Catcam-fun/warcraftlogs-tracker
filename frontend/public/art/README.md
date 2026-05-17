# Background / game art — self-hosted

Downloaded once and committed (no third-party runtime dependency, no
hotlink fragility, faster, survives the source going away).

## Landing background

`backgrounds/` — the official WoW: Midnight press kit (key art +
cinematic stills), each downscaled to ~2200px / q72 JPG for web.
**One is chosen at random per page load** (see `BACKGROUNDS` in
`src/LandingPage.js`). Heavily scrimmed by CSS so detail is muted.

`landing-keyart.svg` — procedural void stand-in; only renders if a
chosen background fails to load (graceful fallback).

### Adding/replacing backgrounds
Drop a web-sized JPG in `backgrounds/`, add its slug to the
`BACKGROUNDS` array in `LandingPage.js`, `npm run build`. Done.

## Boss strip

`bosses/` — per-boss tile art, drop-in by exact filename. See
`bosses/README.md` for the required names and where to source them.

## Attribution / usage

Floor Pov is a non-commercial fan tool. Blizzard fan-content & press
assets are used under Blizzard's fan content guidelines. The site footer
carries the required non-affiliation + trademark + key-art notices. If
usage ever becomes commercial, revisit this.
