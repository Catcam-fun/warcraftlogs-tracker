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
- otherwise the page's own host: the site and API share one address (CloudFront serves the API under `/api`).

## More

See the repository's top-level `README.md` for the backend and how the two fit together.
