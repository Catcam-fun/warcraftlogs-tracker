import { supabase } from './supabaseClient';

/* Single source of truth for the backend URL. Set REACT_APP_API_URL at
   build time to point a deploy elsewhere; otherwise localhost talks to a
   local backend and everything else to production. */
const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
export const API_URL = process.env.REACT_APP_API_URL
  || (isLocal ? 'http://localhost:5000' : 'https://deathwarcraftlogs-api.onrender.com');

/* Analysis config fields that must never leave the browser except in the
   /api/analyze call itself (not in shares, saves, or local history). */
const SECRET_KEYS = ['clientId', 'clientSecret'];

export function stripSecrets(config) {
  if (!config || typeof config !== 'object') return config;
  const copy = { ...config };
  SECRET_KEYS.forEach((k) => { delete copy[k]; });
  return copy;
}

/* fetch() against the backend. With `auth: true` the current Supabase
   session's access token is attached so the server knows who is asking
   (and the call fails fast when signed out); `auth: 'optional'` attaches
   it only if there is one. Resolves to { ok, status, body } and never
   throws on HTTP or network errors (only on abort). */
export async function apiFetch(path, { auth = false, method = 'GET', body, signal } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) {
    const { data: { session } } = await supabase.auth.getSession();
    if (session) headers.Authorization = `Bearer ${session.access_token}`;
    else if (auth !== 'optional') return { ok: false, status: 401, body: { error: 'Please sign in again.' } };
  }
  let response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    return { ok: false, status: 0, body: { error: "Couldn't reach the server. It may be waking up; try again in a minute." } };
  }
  let parsed = null;
  try { parsed = await response.json(); } catch { parsed = null; }
  return { ok: response.ok, status: response.status, body: parsed || {} };
}
