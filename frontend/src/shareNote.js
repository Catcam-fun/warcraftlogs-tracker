/* A warning to show with a new share link, or null. The server keeps a link
   only in memory when its database is unavailable; such a link stops working
   when the server restarts or sleeps, well before the usual 72 hours. */
export function shareNote(body) {
  return body && body.ephemeral
    ? "Couldn't store this link permanently: it will stop working when the server restarts. Try sharing again later for a link that lasts 72 hours."
    : null;
}
