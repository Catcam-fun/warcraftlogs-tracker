/* Tier stats: deaths across public Mythic kills, for the Stats page.
   Data: public/stats/<raid>.json, built by backend/scripts/build_tier_stats.py.
     specs:     ["Mage-Frost", ...]
     abilities: [[spell ID, name, icon, in-game description], ...]
     patches:   [{ name, bosses: { encounterID: [kill, ...] in kill order } }]
       kill = [[spec index of every player], [slot, ability index, spec index, ...]]
   A death counts for "first X deaths" when its slot is X or less; deaths in a
   wipe are already left out of the file, as in an analysis (deathCounting.js). */

export const KILL_OPTIONS = [10, 25, 50, 100, 250, 500, 1000, 0]; // 0 = every kill
export const MAX_DEATHS = 20;

/* The kills a selection covers: the first `firstKills` (0 = all) of each chosen
   boss (null = every boss), as [encounterID, roster, deaths]. */
export function selectKills(patch, bossId, firstKills) {
  const ids = bossId ? [String(bossId)] : Object.keys(patch.bosses);
  return ids.flatMap((id) => {
    const ks = patch.bosses[id] || [];
    return (firstKills ? ks.slice(0, firstKills) : ks).map(([roster, deaths]) => [id, roster, deaths]);
  });
}

/* Counted deaths by killing ability (per boss: every boss's Melee is its own),
   and death rate by spec, over some kills (selectKills).
   Returns { kills, deaths, abilities: [{ boss, index, deaths, share }],
             specs: [{ index, deaths, players, perKill }] }, both sorted biggest first. */
export function tally(kills, firstDeaths) {
  const byAbility = new Map();
  const deathsBySpec = new Map();
  const playersBySpec = new Map();
  let deaths = 0;
  for (const [boss, roster, ds] of kills) {
    for (const s of roster) playersBySpec.set(s, (playersBySpec.get(s) || 0) + 1);
    for (let i = 0; i < ds.length; i += 3) {
      if (ds[i] > firstDeaths) continue;
      deaths += 1;
      const key = `${boss}:${ds[i + 1]}`;
      byAbility.set(key, (byAbility.get(key) || 0) + 1);
      deathsBySpec.set(ds[i + 2], (deathsBySpec.get(ds[i + 2]) || 0) + 1);
    }
  }
  const abilities = [...byAbility].map(([key, n]) => {
    const [boss, index] = key.split(':');
    return { boss, index: Number(index), deaths: n, share: deaths ? n / deaths : 0 };
  }).sort((a, b) => b.deaths - a.deaths || a.index - b.index);
  const specs = [...playersBySpec].map(([index, players]) => {
    const d = deathsBySpec.get(index) || 0;
    return { index, deaths: d, players, perKill: d / players };
  }).sort((a, b) => b.perKill - a.perKill || b.players - a.players);
  return { kills: kills.length, deaths, abilities, specs };
}

const CLASS_NAMES = { DeathKnight: 'Death Knight', DemonHunter: 'Demon Hunter' };
const SPEC_NAMES = { BeastMastery: 'Beast Mastery' };

/* "DeathKnight-Frost" -> { cls: "DeathKnight", label: "Frost Death Knight" } */
export function specLabel(key) {
  const [cls, spec] = key.split('-');
  return { cls, label: `${SPEC_NAMES[spec] || spec} ${CLASS_NAMES[cls] || cls}` };
}
