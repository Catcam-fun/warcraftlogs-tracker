import { supabase } from './supabaseClient';

/* Single source of truth for the backend URL. The site and its API share
   one host (CloudFront serves the API under /api), so calls go to the page's
   own host. Set REACT_APP_API_URL at build time to point a build elsewhere
   ("same-origin" forces the page's own host); localhost talks to a local
   backend. */
const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
const configured = process.env.REACT_APP_API_URL;
export const API_URL = configured === 'same-origin' ? ''
  : configured || (isLocal ? 'http://localhost:5000' : '');

/* Analysis config fields that must never leave the browser except in the
   /api/analyze call itself (not in shares, saves, or local history). */
const SECRET_KEYS = ['clientId', 'clientSecret'];

/* The WarcraftLogs Client ID and Secret are remembered in this browser
   (localStorage), signed in or not, so nobody has to paste them again.
   Storage can be missing or blocked (private windows, previews); every
   access is guarded and the form just starts empty then. */
const LOCAL_CREDS_KEY = 'fpx.wclCredentials';

export function loadLocalCredentials() {
  try {
    const saved = JSON.parse(localStorage.getItem(LOCAL_CREDS_KEY) || 'null');
    if (saved && typeof saved === 'object') {
      return { clientId: String(saved.clientId || ''), clientSecret: String(saved.clientSecret || '') };
    }
  } catch { /* unavailable or unreadable: start empty */ }
  return { clientId: '', clientSecret: '' };
}

export function saveLocalCredentials(clientId, clientSecret) {
  try {
    if (clientId || clientSecret) {
      localStorage.setItem(LOCAL_CREDS_KEY, JSON.stringify({ clientId, clientSecret }));
    } else {
      localStorage.removeItem(LOCAL_CREDS_KEY);
    }
  } catch { /* unavailable: nothing to remember */ }
}

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
/* Text as gzip bytes, or null when the browser can't compress. Big
   analyses (shares, saves) are many MB; Lambda refuses request bodies over
   6 MB, and JSON shrinks about 10x. The API reads either form. */
async function gzipText(text) {
  if (typeof CompressionStream === 'undefined' || typeof TextEncoder === 'undefined') return null;
  const stream = new CompressionStream('gzip');
  const writer = stream.writable.getWriter();
  writer.write(new TextEncoder().encode(text));
  writer.close();
  const reader = stream.readable.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { done, value: chunk } = await reader.read();
    if (done) break;
    chunks.push(chunk);
    total += chunk.length;
  }
  const out = new Uint8Array(total);
  let at = 0;
  chunks.forEach((c) => { out.set(c, at); at += c.length; });
  return out;
}

export async function apiFetch(path, { auth = false, method = 'GET', body, signal, compress = false } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let payload = body === undefined ? undefined : JSON.stringify(body);
  if (body !== undefined && compress) {
    const zipped = await gzipText(payload);
    if (zipped) {
      payload = zipped;
      headers['Content-Encoding'] = 'gzip';
    }
  }
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
      body: payload,
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
