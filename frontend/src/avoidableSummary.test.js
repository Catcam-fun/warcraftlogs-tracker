import { summarizeDefensives } from './DefensivePanel';
import { avoidableLine } from './DeathRow';

const death = (avoidable) => ({
  defensives: {
    active: [], available: [], cooldown: [],
    survival: { deathType: 'wasLow', wouldSave: {}, ...(avoidable === undefined ? {} : { avoidable }) },
  },
});
const wave = { name: 'Caustic Waves', id: 1, times: 2, pctOfMax: 38 };

test('counts avoidable deaths', () => {
  const s = summarizeDefensives([
    death({ verdict: true, hits: [wave], windowLimited: false }),
    death({ verdict: true, hits: [wave], windowLimited: false }),
    death({ verdict: false, hits: [], windowLimited: false }),
  ]);
  expect(s.avoidable).toBe(2);
  expect(s.avoidableAssessed).toBe(3);
});

test('null verdict is not assessed', () => {
  const s = summarizeDefensives([death({ verdict: null, hits: [{ ...wave, unsure: true }], windowLimited: false })]);
  expect(s.avoidable).toBe(0);
  expect(s.avoidableAssessed).toBe(0);
});

test('ignores results without avoidable', () => {
  const s = summarizeDefensives([death(undefined), death({ verdict: true, hits: [wave], windowLimited: false })]);
  expect(s.avoidable).toBe(1);
  expect(s.avoidableAssessed).toBe(1);
});

test('the avoidable damage line names hits with times and share of max health', () => {
  expect(avoidableLine({ verdict: true, hits: [wave, { name: 'Pool', id: 2, times: 1, pctOfMax: 5 }] }))
    .toBe('Caustic Waves ×2 · 38%, Pool · 5%');
  expect(avoidableLine({ verdict: null, hits: [{ ...wave, unsure: true }] }))
    .toBe('Caustic Waves ×2 · 38% (unsure)');
  expect(avoidableLine({ verdict: false, hits: [] })).toBe('');
});
