# Floor Pov

[floorpov.gg](https://floorpov.gg) is a death-analysis site for World of Warcraft raid guilds. It reads a guild's
Mythic raid logs from [WarcraftLogs](https://www.warcraftlogs.com), counts each player's deaths per boss, and for
every death that counts explains how it happened (one-shot, burst, worn down or set up) and whether a defensive,
potion or Healthstone would have saved them.

## Layout

- `frontend/`: the React site (Create React App). See `frontend/README.md`.
- `backend/`: the Flask API that fetches the logs and runs the analysis.
  - `analysis.py`: which pulls count, death slots and wipes.
  - `defensives.py`: the per-death replay of defensives, potions and Healthstones.
  - `defensive_catalog.py`, `max_health_auras.py`, `spell_icons.py`: generated from game data by the
    `scripts/build_*.py` scripts. Don't edit them by hand; rerun the scripts.
  - `checks/`: `python -m checks`, which compares what the site shows with WarcraftLogs and recomputes its
    rules independently on a real log (see `backend/checks/README.md`).
- `infra/`: how the site and API are hosted (see `infra/README.md`).

## Running the tests

- Backend, from `backend/` with Python 3.12: `python -m unittest`
- Frontend, from `frontend/`: `npm test`

The checks in `backend/checks/` need a WarcraftLogs API client in `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET`.
Every push to `main` deploys the site and API.
