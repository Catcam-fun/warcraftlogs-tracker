/* When an analysis ran, from the backend's meta.generatedAt. Older results
   carry "YYYY-MM-DD HH:MM:SS" with no zone; the server runs in UTC, so
   those are read as UTC. Returns a Date, or null when there's no usable
   stamp (the page then shows no date rather than today's). */
export function analyzedAt(meta) {
  const raw = meta && meta.generatedAt;
  if (!raw || typeof raw !== 'string') return null;
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(raw);
  const date = new Date(hasZone ? raw : `${raw.replace(' ', 'T')}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}
