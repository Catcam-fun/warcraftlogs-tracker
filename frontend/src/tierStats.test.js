import { selectKills, tally, specLabel } from './tierStats';

// specs: 0 = Mage-Frost, 1 = Priest-Holy; abilities 0 and 1.
const patch = {
  name: '12.1',
  bosses: {
    10: [
      [[0, 0, 1], [1, 0, 0, 2, 1, 1]],
      [[0, 1, 1], [1, 0, 1]],
      [[0, 0, 0], []],
    ],
    20: [
      [[0, 1], [1, 1, 0, 2, 1, 0, 3, 0, 1]],
    ],
  },
};

test('first X kills of each boss', () => {
  expect(selectKills(patch, 10, 1)).toEqual([['10', [0, 0, 1], [1, 0, 0, 2, 1, 1]]]);
  expect(selectKills(patch, '10', 2)).toHaveLength(2);
  expect(selectKills(patch, null, 2)).toHaveLength(3);
  expect(selectKills(patch, null, 0)).toHaveLength(4);
  expect(selectKills(patch, '99', 0)).toEqual([]);
});

test('only the first X deaths of each kill count', () => {
  const one = tally(selectKills(patch, null, 0), 1);
  expect(one.deaths).toBe(3);
  expect(one.abilities).toEqual([
    { boss: '10', index: 0, deaths: 2, share: 2 / 3 },
    { boss: '20', index: 1, deaths: 1, share: 1 / 3 },
  ]);
  const all = tally(selectKills(patch, null, 0), 20);
  expect(all.deaths).toBe(6);
});

test('deaths per kill by spec divide by how many played it', () => {
  const t = tally(selectKills(patch, null, 0), 20);
  // Mage-Frost: 7 players across the kills, 3 deaths. Priest-Holy: 4 players, 3 deaths.
  expect(t.specs).toEqual([
    { index: 1, deaths: 3, players: 4, perKill: 0.75 },
    { index: 0, deaths: 3, players: 7, perKill: 3 / 7 },
  ]);
});

test('spec labels read like the game', () => {
  expect(specLabel('DeathKnight-Frost')).toEqual({ cls: 'DeathKnight', label: 'Frost Death Knight' });
  expect(specLabel('Hunter-BeastMastery').label).toBe('Beast Mastery Hunter');
});
