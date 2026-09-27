/* Which deaths count toward "first X deaths per pull".

   The backend tags every death with:
     slot:   which death of the pull it was (1 = first); a player who dies,
             is rezzed and dies again takes two. For a cheat death: real
             deaths so far + 1.
     inWipe: part of a mass death (only real deaths make a wipe).
   A death counts when slot <= X and it isn't part of a wipe. Cheat deaths
   never take a slot from a real death.

   Results saved before those fields existed fall back to the old per-pull
   cutoff timestamps. */

function legacyCutoff(pullCutoffTimestamps, pullKey, cutoff) {
  const cuts = pullCutoffTimestamps?.[pullKey];
  if (!cuts) return undefined;
  if (cuts[cutoff] !== undefined) return cuts[cutoff];
  const keys = Object.keys(cuts).map(Number);
  return keys.length ? cuts[Math.max(...keys)] : undefined;
}

export function isCounted(ev, cutoff, pullCutoffTimestamps) {
  if (ev.slot !== undefined) {
    return ev.slot <= cutoff && !ev.inWipe;
  }
  const ts = legacyCutoff(pullCutoffTimestamps, `${ev.reportId}_${ev.fightId}`, cutoff);
  return ts !== undefined && ev.timestamp !== undefined && ev.timestamp <= ts;
}

/* Split a player's events into the real and cheat deaths that count. */
export function countedDeaths(events, cutoff, pullCutoffTimestamps) {
  const real = [];
  const cheat = [];
  events.forEach((ev) => {
    if (!isCounted(ev, cutoff, pullCutoffTimestamps)) return;
    (ev.isCheatDeath ? cheat : real).push(ev);
  });
  return { real, cheat };
}
