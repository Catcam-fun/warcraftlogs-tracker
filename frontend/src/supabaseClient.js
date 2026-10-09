import { createClient } from '@supabase/supabase-js'

// Set at build time from the deploy's GitHub secrets (frontend/.env.local for
// local dev). The browser needs both, so they are visible in the live site's
// JavaScript; they are kept out of the repo, and the anon key only reaches
// what Supabase's row-level security allows.
const supabaseUrl = process.env.REACT_APP_SUPABASE_URL || 'http://localhost:54321'
const supabaseAnonKey = process.env.REACT_APP_SUPABASE_ANON_KEY || 'unset'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

/* "Stay logged in" unchecked: Supabase always persists the session, so we
   pair a localStorage flag with a session cookie (shared by all tabs,
   cleared when the browser closes). Flag set + cookie gone means the
   browser was closed since sign-in, and the session should end. */
const SESSION_ONLY_KEY = 'fp.sessionOnly';
const ALIVE_COOKIE = 'fp_session_alive';

export function setSessionOnly(sessionOnly) {
  try {
    if (sessionOnly) {
      localStorage.setItem(SESSION_ONLY_KEY, '1');
      document.cookie = `${ALIVE_COOKIE}=1; path=/; SameSite=Lax`;
    } else {
      localStorage.removeItem(SESSION_ONLY_KEY);
    }
  } catch { /* storage blocked: fall back to a normal persistent session */ }
}

export function sessionEndedByBrowserClose() {
  try {
    return localStorage.getItem(SESSION_ONLY_KEY) === '1'
      && !document.cookie.split('; ').some((c) => c.startsWith(`${ALIVE_COOKIE}=`));
  } catch {
    return false;
  }
}
