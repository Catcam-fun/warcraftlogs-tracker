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
    charges: 1, talents: [{ talent: 'Improved Ironbark', field: 'cooldown', rank: 1, add_ms: -20000 }] };
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
