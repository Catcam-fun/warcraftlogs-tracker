import { whyText } from './DeathRow';

test('a can\'t-tell names the earlier hit it is about, not the killing blow', () => {
  expect(whyText({ why: 'armorUnknown', whyHit: 'Cleave' }, 'Frost Bolt'))
    .toBe('it isn\'t known whether armor reduces Cleave');
  expect(whyText({ why: 'armorUnknown' }, 'Frost Bolt')).toBe('it isn\'t known whether armor reduces Frost Bolt');
  expect(whyText({ why: 'aoeUnknown', whyHit: 'Cleave' }, 'Frost Bolt'))
    .toBe('This log doesn\'t mark area damage, so this can\'t be checked');
});
