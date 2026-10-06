import { fitFiltersToResult } from './resultFilters';

const result = {
  meta: { maxCutoff: 3 },
  bossParticipation: { Vorasius: {}, "L'ura": {} },
};

test('a cutoff above the new result\'s maximum is lowered to it', () => {
  expect(fitFiltersToResult({ cutoff: 5, selectedBosses: new Set() }, result).cutoff).toBe(3);
  expect(fitFiltersToResult({ cutoff: 2, selectedBosses: new Set() }, result).cutoff).toBe(2);
});

test('boss choices from another raid are dropped; ones in this result stay', () => {
  const out = fitFiltersToResult({ cutoff: 2, selectedBosses: new Set(['Vorasius', 'Queen Ansurek']) }, result);
  expect([...out.selectedBosses]).toEqual(['Vorasius']);
});

test('nothing to fit without a result', () => {
  const filters = { cutoff: 4, selectedBosses: new Set(['X']) };
  expect(fitFiltersToResult(filters, null)).toBe(filters);
});
