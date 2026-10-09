import { whyText } from './DeathRow';

test('a can\'t-tell names the earlier hit it is about, not the killing blow', () => {
  expect(whyText({ why: 'armorUnknown', whyHit: 'Cleave' }, 'Frost Bolt'))
    .toBe('it isn\'t known whether armor reduces Cleave');
  expect(whyText({ why: 'armorUnknown' }, 'Frost Bolt')).toBe('it isn\'t known whether armor reduces Frost Bolt');
  expect(whyText({ why: 'aoeUnknown', whyHit: 'Cleave' }, 'Frost Bolt'))
    .toBe('This log doesn\'t mark area damage, so this can\'t be checked');
});

test("armor that reduces the hit, but whose size isn't known, says what is missing", () => {
  expect(whyText({ why: 'armorValueUnknown', missing: 'armor' }, 'Melee'))
    .toBe("their armor isn't in the log at Melee, so what more armor would take off it can't be worked out");
  expect(whyText({ why: 'armorValueUnknown', missing: 'constant', whyHit: 'Cleave' }, 'Melee'))
    .toBe("the boss's armor constant isn't known, so what more armor would take off Cleave can't be worked out");
});
