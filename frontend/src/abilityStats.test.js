import { abilityStats } from './abilityStats';

const death = (boss, abilityId, abilityName) => ({ boss, abilityId, abilityName });

// Player stats as the Results page builds them: deathsByBoss already holds only the deaths that count.
const stats = [
  { player: 'Ana', class: 'Priest', deathsByBoss: {
    Vorasius: [death('Vorasius', 1, 'Crush'), death('Vorasius', 1, 'Crush'), death('Vorasius', 2, 'Tempest')],
  } },
  { player: 'Bo', class: 'Mage', deathsByBoss: {
    Vorasius: [death('Vorasius', 1, 'Crush')],
    "L'ura": [death("L'ura", 2, 'Tempest'), death("L'ura", 0, 'Unknown')],
  } },
];
const bossParticipation = {
  Vorasius: { Ana: ['a', 'b', 'c', 'd'], Bo: ['a', 'b'], BoAlt: ['e', 'f'] },
  "L'ura": { Bo: ['x', 'y', 'z'] },
};

test('abilities are ranked by deaths, players inside each by deaths', () => {
  const out = abilityStats(stats, bossParticipation, {});
  expect(out.map((a) => `${a.boss}:${a.name}:${a.deaths}`)).toEqual([
    'Vorasius:Crush:3', 'Vorasius:Tempest:1', "L'ura:Tempest:1",
  ]);
  expect(out[0].players.map((p) => [p.player, p.deaths])).toEqual([['Ana', 2], ['Bo', 1]]);
});

test('each player\'s rate is their deaths to it over their pulls on that boss', () => {
  const crush = abilityStats(stats, bossParticipation, {})[0];
  expect(crush.players[0]).toMatchObject({ player: 'Ana', pulls: 4, rate: 50 });
  expect(crush.players[1]).toMatchObject({ player: 'Bo', pulls: 2, rate: 50 });
});

test('a merged alt\'s pulls count toward the main', () => {
  const crush = abilityStats(stats, bossParticipation, { Bo: ['BoAlt'] })[0];
  expect(crush.players[1]).toMatchObject({ player: 'Bo', pulls: 4, rate: 25 });
});

test('the same spell on two bosses is two entries; deaths with no killing blow are left out', () => {
  const out = abilityStats(stats, bossParticipation, {});
  expect(out.filter((a) => a.name === 'Tempest').map((a) => a.boss)).toEqual(['Vorasius', "L'ura"]);
  expect(out.some((a) => a.name === 'Unknown')).toBe(false);
});

test('players tied on deaths: the higher rate first, then by name', () => {
  const tied = [
    { player: 'Cy', class: 'Rogue', deathsByBoss: { B: [death('B', 9, 'Pool')] } },
    { player: 'Al', class: 'Rogue', deathsByBoss: { B: [death('B', 9, 'Pool')] } },
    { player: 'Di', class: 'Rogue', deathsByBoss: { B: [death('B', 9, 'Pool')] } },
  ];
  const parts = { B: { Cy: ['1', '2'], Al: ['1', '2'], Di: ['1'] } };
  expect(abilityStats(tied, parts, {})[0].players.map((p) => p.player)).toEqual(['Di', 'Al', 'Cy']);
});
