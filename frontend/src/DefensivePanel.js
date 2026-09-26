import React from 'react';

/* Defensive picture for one death, as computed by backend/defensives.py:
   { active: [{name, kind, by?, major}], available: [{name, major}],
     cooldown: [{name, major, usedAgo, readyIn}], talentsKnown,
     healthstone: {usedAgo|null}, potion: {usedAgo|null} } */
// Saved reports and shares from before this feature carry an older shape; skip them.
const isCurrentShape = (d) => d && Array.isArray(d.active) && Array.isArray(d.available);

export function DeathDefensives({ d }) {
  if (!isCurrentShape(d)) return null;
  const personalActive = d.active.filter((a) => a.kind !== 'external');
  const externals = d.active.filter((a) => a.kind === 'external');
  const consumable = (label, c) => (
    <span className={`cons${c?.usedAgo != null ? ' used' : ''}`}>
      {label}: {c?.usedAgo != null ? `used ${c.usedAgo}s before` : 'not used'}
    </span>
  );

  return (
    <div className="fpx-defs">
      <div className="fpx-defs-row">
        <span className="lbl act">ACTIVE</span>
        {personalActive.length === 0 && externals.length === 0 && <span className="none">Nothing active</span>}
        {personalActive.map((a) => <span key={a.name} className="d act">{a.name}</span>)}
        {externals.map((a) => (
          <span key={`x-${a.name}`} className="d ext" title="Raid cooldown or external from another player">
            {a.name}{a.by ? ` · ${a.by}` : ''}
          </span>
        ))}
      </div>
      {d.available.length > 0 && (
        <div className="fpx-defs-row">
          <span className="lbl avail">AVAILABLE, UNUSED</span>
          {d.available.map((a) => (
            <span key={a.name} className={`d avail${a.major ? '' : ' minor'}`}
              title={a.major ? 'Off cooldown when they died' : 'Short-cooldown defensive (not counted in the summary)'}>
              {a.name}
            </span>
          ))}
        </div>
      )}
      {d.cooldown.length > 0 && (
        <div className="fpx-defs-row">
          <span className="lbl cd">ON COOLDOWN</span>
          {d.cooldown.map((a) => (
            <span key={a.name} className="d cd" title={`Pressed ${a.usedAgo}s before death; back ${a.readyIn}s after`}>
              {a.name} <small>used {a.usedAgo}s ago · back in {a.readyIn}s</small>
            </span>
          ))}
        </div>
      )}
      <div className="fpx-defs-row consumables">
        {consumable('Healthstone', d.healthstone)}
        {consumable('Health potion', d.potion)}
        {!d.talentsKnown && (
          <span className="note" title="No talent data for this pull: abilities count only if pressed somewhere in the log">
            talents not recorded; based on abilities pressed
          </span>
        )}
      </div>
    </div>
  );
}

/* Per-player rollup over the deaths that count toward their death rate. */
export function summarizeDefensives(deaths) {
  const summary = { withData: 0, withUnused: 0, unused: {} };
  deaths.forEach((death) => {
    const d = death.defensives;
    if (!isCurrentShape(d)) return;
    summary.withData += 1;
    const major = d.available.filter((a) => a.major);
    if (major.length > 0) summary.withUnused += 1;
    major.forEach((a) => { summary.unused[a.name] = (summary.unused[a.name] || 0) + 1; });
  });
  summary.topUnused = Object.entries(summary.unused).sort((a, b) => b[1] - a[1]).slice(0, 3);
  return summary;
}

export function DefensiveSummaryChip({ s }) {
  if (!s || s.withData === 0) return null;
  const tone = s.withUnused === 0 ? 'good' : s.withUnused / s.withData >= 0.5 ? 'bad' : 'warn';
  return (
    <span className={`fpx-pdef ${tone}`}
      title="Deaths where a major personal defensive (60s+ cooldown) was off cooldown and unused">
      {s.withUnused}/{s.withData} died with a defensive unused
    </span>
  );
}

export function DefensiveTopUnused({ s }) {
  if (!s || s.topUnused.length === 0) return null;
  return (
    <div className="fpx-abil">
      <span className="lbl">Most often unused at death</span>
      {s.topUnused.map(([name, n], i) => (
        <span key={name}>{i > 0 ? '   ·   ' : ''}{name} ({n})</span>
      ))}
    </div>
  );
}
