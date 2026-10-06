/* Whether the visitor asked their system for reduced motion. */
export function prefersReducedMotion() {
  try {
    return Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  } catch {
    return false;
  }
}
