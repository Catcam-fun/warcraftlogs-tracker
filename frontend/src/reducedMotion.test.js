import { prefersReducedMotion } from './reducedMotion';

afterEach(() => { delete window.matchMedia; });

test('follows the reduce-motion setting', () => {
  window.matchMedia = (q) => ({ matches: q === '(prefers-reduced-motion: reduce)' });
  expect(prefersReducedMotion()).toBe(true);
  window.matchMedia = () => ({ matches: false });
  expect(prefersReducedMotion()).toBe(false);
});

test('assumes motion is fine when the browser cannot say', () => {
  expect(prefersReducedMotion()).toBe(false);
});
