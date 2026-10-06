import { groupPulls } from './groupPulls';

const bossParticipation = {
  Vorasius: { Main: ['r1_1', 'r1_2'], Alt: ['r2_1'] },
};

test('a merged player counts the pulls of every character in the group', () => {
  expect(groupPulls(bossParticipation.Vorasius, 'Main', { Main: ['Alt'] })).toBe(3);
});

test('an ungrouped player, or a boss nobody pulled, counts what is there', () => {
  expect(groupPulls(bossParticipation.Vorasius, 'Alt', {})).toBe(1);
  expect(groupPulls(undefined, 'Main', { Main: ['Alt'] })).toBe(0);
});
