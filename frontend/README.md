# Floor Pov — frontend

The React site for Floor Pov, a WarcraftLogs death-analysis tool for WoW raid
guilds. It was bootstrapped with Create React App.

## Commands

Run these in `frontend/`:

- `npm start` — dev server at http://localhost:3000
- `npm test` — Jest tests in watch mode
- `npm run build` — production build into `build/`

## Which backend it talks to

`src/api.js` picks the Flask API URL:

- `REACT_APP_API_URL`, if it was set when the site was built;
- otherwise `http://localhost:5000` when the page is on `localhost` or `127.0.0.1`
  (run the backend locally from `backend/`);
- otherwise the production API, `https://REDACTED`.

## More

How the site works, page by page and down to file and line, is documented in the
Project Atlas: `docs/atlas/` (open `docs/atlas/build/index.html`). See its
Frontend section in particular.
