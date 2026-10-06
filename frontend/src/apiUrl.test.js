// On AWS the site and its API share one CloudFront address, so the build
// sets REACT_APP_API_URL=same-origin and calls go to /api/... on the page's host.
jest.mock('./supabaseClient', () => ({ supabase: { auth: { getSession: jest.fn() } } }));

function apiUrlWith(value) {
  const before = process.env.REACT_APP_API_URL;
  if (value === undefined) delete process.env.REACT_APP_API_URL;
  else process.env.REACT_APP_API_URL = value;
  let url;
  jest.isolateModules(() => { url = require('./api').API_URL; });
  if (before === undefined) delete process.env.REACT_APP_API_URL;
  else process.env.REACT_APP_API_URL = before;
  return url;
}

test('same-origin builds call the API on the page\'s own host', () => {
  expect(apiUrlWith('same-origin')).toBe('');
});

test('an explicit URL still wins, and the default is unchanged', () => {
  expect(apiUrlWith('https://api.example.com')).toBe('https://api.example.com');
  expect(apiUrlWith(undefined)).toBe('http://localhost:5000');   // jsdom runs on localhost
});
