/* What a visitor sees when something fails: a short, plain message. Raw
   errors can carry addresses or service names; those never reach the page
   (the details stay in the browser console). Messages written for people,
   like the API's own errors or "Invalid login credentials", pass through. */

const NETWORK = /failed to fetch|networkerror|network request failed|load failed|fetch failed/i;
const INTERNAL = /https?:\/\/|supabase|lambda|cloudfront|amazon|\baws\b|cloudflare|workers\.dev|traceback|typeerror|syntaxerror|referenceerror/i;

export const CONNECTION = "Couldn't reach the server. Check your connection and try again.";

export function friendlyError(err, fallback) {
  const message = (err && err.message) || '';
  if (NETWORK.test(message)) return CONNECTION;
  if (!message || INTERNAL.test(message)) return fallback;
  return message;
}
