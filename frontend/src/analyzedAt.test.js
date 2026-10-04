import { analyzedAt } from './analyzedAt';

test('reads the time the analysis ran, not the time it is viewed', () => {
  expect(analyzedAt({ generatedAt: '2026-09-01T18:30:00Z' }).toISOString()).toBe('2026-09-01T18:30:00.000Z');
});

test('older results without a time zone were stamped by the server in UTC', () => {
  expect(analyzedAt({ generatedAt: '2026-09-01 18:30:00' }).toISOString()).toBe('2026-09-01T18:30:00.000Z');
});

test('no stamp or a bad one gives no date instead of today', () => {
  expect(analyzedAt({})).toBeNull();
  expect(analyzedAt(undefined)).toBeNull();
  expect(analyzedAt({ generatedAt: 'not a date' })).toBeNull();
});
