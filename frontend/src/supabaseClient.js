import { createClient } from '@supabase/supabase-js'

const supabaseUrl = 'https://eckershozscyedwfswsy.supabase.co'
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVja2Vyc2hvenNjeWVkd2Zzd3N5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM2NjM5MTEsImV4cCI6MjA3OTIzOTkxMX0.F1YkqGeJiYWte_EOW78DjNmqegWwy6TUaDE48LsA3HM'

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
