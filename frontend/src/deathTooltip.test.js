import React from 'react';
import { render } from '@testing-library/react';
import { deathKind, deathSentence, HealthSteps } from './DeathRow';

const say = (s, kb = { name: 'Oblivion', school: 106 }) => render(<p>{deathSentence(s, kb)}</p>).container.textContent;
const base = { maxHp: 1000, overkill: 0, killingHit: { pctOfMax: 20 } };

test('a killing blow far past their max health says how many times over', () => {
  const s = { ...base, deathType: 'oneShot', hpBeforePct: 67, overkill: 4050 };
  expect(say(s)).toBe('Oblivion hit for more than 4 times their max health. Nothing survives that.');
});

test('a burst names the abilities and where they started', () => {
  const s = { ...base, deathType: 'burst', hpBeforePct: 20, fromPct: 100,
    burst: { ms: 0, abilities: [{ name: 'Primal Spellstorm', school: 64, times: 1 }, { name: 'Infusion Tether', school: 64, times: 1 }] } };
  expect(say(s)).toBe('Primal Spellstorm and Infusion Tether hit at the same moment and took them from full health to dead.');
  const one = { ...s, fromPct: 71, burst: { ms: 0, abilities: [{ name: 'Crushing Gravity', school: 106, times: 3 }] } };
  expect(say(one)).toBe('Crushing Gravity hit them 3 times at the same moment and took them from 71% health to dead.');
});

test('the kind of death follows the backend labels', () => {
  expect(deathKind({ deathType: 'wasLow', rot: { name: 'x' } })).toBe('rot');
  expect(deathKind({ deathType: 'wasLow', biggestHit: { name: 'x' } })).toBe('setUp');
  expect(deathKind({ deathType: 'wasLow' })).toBe('low');
});

test('the steps spell out their health hit by hit, and how far past zero', () => {
  const s = { ...base, overkill: 85000, steps: { from: 100, earlier: 0, items: [
    { name: 'Primal Spellstorm', school: 64, times: 1, took: 80, left: 20 },
    { name: 'Infusion Tether', school: 64, times: 1, took: 20, left: null }] } };
  const text = render(<HealthSteps s={s} />).container.textContent;
  expect(text).toContain('Started at full health');
  expect(text).toContain('Primal Spellstorm took 80%, leaving 20%');
  expect(text).toContain('Infusion Tether took the last 20% and killed them (85k past zero)');
});
