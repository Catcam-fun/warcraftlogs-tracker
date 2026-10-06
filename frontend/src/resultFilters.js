/* Results-page filters survive loading another result. Keep the ones that
   still make sense for it: the deaths-tracked cutoff can't exceed the new
   result's maximum, and boss choices must be bosses it has. Returns the
   same object when nothing needs to change. */
export function fitFiltersToResult(filters, result) {
  if (!result) return filters;
  const max = Number(result.meta?.maxCutoff) || filters.cutoff;
  const bosses = result.bossParticipation || {};
  const cutoff = Math.min(filters.cutoff, max);
  const kept = [...filters.selectedBosses].filter((b) => b in bosses);
  if (cutoff === filters.cutoff && kept.length === filters.selectedBosses.size) return filters;
  return { cutoff, selectedBosses: new Set(kept) };
}
