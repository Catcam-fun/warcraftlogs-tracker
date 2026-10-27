import { groupPulls } from './groupPulls';

/* The Abilities tab: who died to each boss ability, most deaths first.
   `stats` is the Results page's filtered player list, so its deathsByBoss
   already holds only the deaths that count (first X, no wipes, no cheat
   deaths) with every filter and alt group applied. Abilities are keyed by
   boss and spell ID: names aren't unique (a boss's Tempest isn't the
   Shaman's). Deaths with no killing blow in the log are left out. */
export function abilityStats(stats, bossParticipation, characterGroups) {
  const byKey = new Map();
  stats.forEach(({ player, class: playerClass, deathsByBoss }) => {
    Object.entries(deathsByBoss || {}).forEach(([boss, deaths]) => {
      deaths.forEach((d) => {
        if (!d.abilityName || d.abilityName === 'Unknown') return;
        const key = `${boss}|${d.abilityId ?? d.abilityName}`;
        if (!byKey.has(key)) {
          byKey.set(key, { key, boss, abilityId: d.abilityId, name: d.abilityName, deaths: 0, byPlayer: new Map() });
        }
        const a = byKey.get(key);
        a.deaths += 1;
        if (!a.byPlayer.has(player)) {
          const pulls = groupPulls(bossParticipation?.[boss], player, characterGroups);
          a.byPlayer.set(player, { player, class: playerClass, deaths: 0, pulls });
        }
        a.byPlayer.get(player).deaths += 1;
      });
    });
  });

  return [...byKey.values()].map(({ byPlayer, ...a }) => {
    const players = [...byPlayer.values()]
      .map((p) => ({ ...p, rate: p.pulls > 0 ? (p.deaths / p.pulls) * 100 : 0 }))
      .sort((x, y) => y.deaths - x.deaths || y.rate - x.rate || x.player.localeCompare(y.player));
    return { ...a, players };
  }).sort((x, y) => y.deaths - x.deaths || y.players.length - x.players.length);
}
