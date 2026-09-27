import React from 'react';

/* Per-player defensive summaries. Each death's own row is DeathRow.js.
   Defensive picture for one death, as computed by backend/defensives.py:
   { active: [{name, kind, major?}], activeKnown, available: [{name, major}],
     cooldown: [{name, major, usedAgo, readyIn}], talentsKnown,
     healthstone: {usedAgo|null}, potion: {usedAgo|null},
     survival?: { deathType: 'oneShot'|'wasLow', killingHit: {name, size, pctOfMax},
                  hpBeforePct, overkill, maxHp, ignoresReduction, ignoresImmunity,
                  wouldSave: {name: true|false|null}, allTogetherWouldSave } }
   Available entries may carry boostedBy: [talent names that strengthen it]. */

// Saved reports and shares from before this feature carry an older shape; skip them.
const isCurrentShape = (d) => d && Array.isArray(d.active) && Array.isArray(d.available);

/* Per-player rollup over the deaths that count toward their death rate. */
export function summarizeDefensives(deaths) {
  const summary = { withData: 0, withUnused: 0, unused: {}, assessed: 0, preventable: 0, oneShots: 0, savers: {} };
  deaths.forEach((death) => {
    const d = death.defensives;
    if (!isCurrentShape(d)) return;
    summary.withData += 1;
    const major = d.available.filter((a) => a.major);
    if (major.length > 0) summary.withUnused += 1;
    major.forEach((a) => { summary.unused[a.name] = (summary.unused[a.name] || 0) + 1; });

    const s = d.survival;
    if (!s) return;
    summary.assessed += 1;
    if (s.deathType === 'oneShot') summary.oneShots += 1;
    const savers = Object.entries(s.wouldSave || {}).filter(([, v]) => v === true).map(([n]) => n);
    if (savers.length > 0 || s.allTogetherWouldSave) summary.preventable += 1;
    savers.forEach((n) => { summary.savers[n] = (summary.savers[n] || 0) + 1; });
  });
  summary.topUnused = Object.entries(summary.unused).sort((a, b) => b[1] - a[1]).slice(0, 3);
  summary.topSavers = Object.entries(summary.savers).sort((a, b) => b[1] - a[1]).slice(0, 3);
  return summary;
}

export function DefensiveSummaryChip({ s }) {
  if (!s || s.withData === 0) return null;
  if (s.assessed === 0) {
    // Older results without killing-blow data: fall back to "unused" counts.
    const tone = s.withUnused === 0 ? 'good' : s.withUnused / s.withData >= 0.5 ? 'bad' : 'warn';
    return (
      <span className={`fpx-pdef ${tone}`}
        title="Deaths where a major personal defensive (60s+ cooldown) was off cooldown and unused">
        {s.withUnused}/{s.withData} died with a defensive unused
      </span>
    );
  }
  const tone = s.preventable === 0 ? 'good' : s.preventable / s.assessed >= 0.5 ? 'bad' : 'warn';
  return (
    <>
      <span className={`fpx-pdef ${tone}`}
        title="Deaths where a defensive, Healthstone or potion they had ready would have covered the killing blow">
        {s.preventable}/{s.assessed} preventable
      </span>
      {s.oneShots > 0 && (
        <span className="fpx-pdef neutral" title="Killed by a single hit from 85%+ health">
          {s.oneShots} one-shot{s.oneShots !== 1 ? 's' : ''}
        </span>
      )}
    </>
  );
}

export function DefensiveTopUnused({ s }) {
  if (!s) return null;
  const rows = s.topSavers?.length ? s.topSavers : s.topUnused;
  if (!rows || rows.length === 0) return null;
  return (
    <div className="fpx-abil">
      <span className="lbl">{s.topSavers?.length ? 'Would have saved them most often' : 'Most often unused at death'}</span>
      {rows.map(([name, n], i) => (
        <span key={name}>{i > 0 ? '   ·   ' : ''}{name} ({n})</span>
      ))}
    </div>
  );
}
