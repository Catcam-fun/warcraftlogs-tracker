import { renderToStaticMarkup } from 'react-dom/server';
import { activeTip } from './DeathRow';

const barkskin = { kind: 'personal', cooldownMs: 60000, auraMs: 8000, charges: 1, effect: [{ dr: 0.2 }] };
const text = (a, inf) => renderToStaticMarkup(activeTip(a, inf, {})()).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/&#x27;/g, "'");

test('an active defensive reads the talented numbers and lists the talents', () => {
  const a = {
    name: 'Barkskin', kind: 'personal', talentsKnown: true, effect: [{ dr: 0.3 }], auraMs: 12000, cooldownMs: 60000,
    charges: 1, talents: [{ talent: 'Oakskin', field: 'dr', rank: 1, add: 0.1 },
      { talent: 'Improved Barkskin', field: 'duration', rank: 1, add_ms: 4000 }],
  };
  const t = text(a, barkskin);
  expect(t).toContain('Reduces damage taken by 30% for 12s. 1 min cooldown.');
  expect(t).toContain('Oakskin +10%');
  expect(t).toContain('Improved Barkskin +4s duration');
  expect(t).not.toContain('unknown');
});

test('an external reads its caster\'s cooldown; unknown talents say so; old results show the base text', () => {
  const ironbark = { kind: 'external', cooldownMs: 90000, auraMs: 12000, charges: 1, effect: [{ dr: 0.2 }] };
  const a = { name: 'Ironbark', kind: 'external', by: 'Treehugger', talentsKnown: true, auraMs: 16000, cooldownMs: 70000,
    charges: 1, effect: [{ dr: 0.2 }], talents: [{ talent: 'Improved Ironbark', field: 'cooldown', rank: 1, add_ms: -20000 }] };
  const t = text(a, ironbark);
  expect(t).toContain('External from Treehugger');
  expect(t).toContain('for 16s. 70s cooldown.');
  expect(t).toContain('Improved Ironbark −20s cooldown');
  const unknown = text({ name: 'Ironbark', kind: 'external', by: 'Treehugger', talentsKnown: false }, ironbark);
  expect(unknown).toContain('for 12s. 90s cooldown.');
  expect(unknown).toContain('Treehugger\'s talents unknown: base values shown.');
  const old = text({ name: 'Barkskin', kind: 'personal' }, barkskin);
  expect(old).toContain('Reduces damage taken by 20% for 8s. 1 min cooldown.');
  expect(old).not.toContain('unknown');
});

test('an external from the game text shows the talented numbers after it, never the base effect beside talents', () => {
  const ironbark = { kind: 'external', cooldownMs: 90000, auraMs: 12000, charges: 1, effect: [],
    description: 'The target\'s skin becomes as tough as Ironwood, reducing damage taken by 20% for 12 sec.' };
  const a = { name: 'Ironbark', kind: 'external', by: 'Treehugger', talentsKnown: true, auraMs: 16000, cooldownMs: 70000,
    charges: 1, talents: [{ talent: 'Improved Ironbark', field: 'cooldown', rank: 1, add_ms: -20000 },
      { talent: 'Regenerative Heartwood', field: 'duration', rank: 1, add_ms: 4000 }] };
  const t = text(a, ironbark);
  expect(t).toContain('reducing damage taken by 20% for 12 sec. 70s cooldown.');
  expect(t).toContain('With these talents: lasts 16s, 70s cooldown.');
  // A known loadout with no effect of its own doesn't borrow the base numbers.
  const bark = { kind: 'personal', cooldownMs: 60000, auraMs: 8000, charges: 1, effect: [{ dr: 0.2 }] };
  expect(text({ name: 'Barkskin', kind: 'personal', talentsKnown: true, cooldownMs: 60000, charges: 1 }, bark))
    .not.toContain('20%');
});

test('who the talents are unknown for: a named caster, no player caster, or the player themselves', () => {
  const ps = { kind: 'external', cooldownMs: 180000, auraMs: 8000, charges: 1, effect: [{ dr: 0.4 }] };
  expect(text({ name: 'Spirit Link Totem', kind: 'external', talentsKnown: false, casterUnknown: true }, ps))
    .toContain('Caster unknown (the aura names no player): base values shown.');
  const self = text({ name: 'Pain Suppression', kind: 'external', talentsKnown: false }, ps);
  expect(self).toContain('Talents unknown: base values shown.');
  expect(self).not.toContain('caster');
  expect(text({ name: 'Pain Suppression', kind: 'external', by: 'Holypriest', talentsKnown: true, specKnown: false }, ps))
    .toContain('Holypriest\'s spec isn\'t in the log: spec passives not included.');
});

test('a talent that takes some off reads with a minus sign, and two rows of one talent both show', () => {
  const feint = { kind: 'personal', cooldownMs: 15000, auraMs: 6000, charges: 1, effect: [{ dr: 0.4, school: 'aoe' }] };
  const a = { name: 'Feint', kind: 'personal', talentsKnown: true, auraMs: 6000, cooldownMs: 15000, charges: 1,
    effect: [{ dr: 0.286, school: 'aoe' }, { dr: 0.2 }],
    talents: [{ talent: 'Elusiveness', field: 'dr', rank: 1, add: -4 / 35, school: 'aoe' },
      { talent: 'Elusiveness', field: 'dr', rank: 1, add: 0.2 }] };
  const t = text(a, feint);
  expect(t).toContain('Elusiveness −11.4% vs area damage');
  expect(t).toContain('Elusiveness +20%');
  expect(t).toContain('Reduces area damage taken by 28.6%. Reduces damage taken by 20%');
});
