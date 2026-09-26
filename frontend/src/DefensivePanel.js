import React from 'react';

/* Defensive picture for one death, as computed by backend/defensives.py:
   { active: [{name, kind, major?}], activeKnown, available: [{name, major}],
     cooldown: [{name, major, usedAgo, readyIn}], talentsKnown,
     healthstone: {usedAgo|null}, potion: {usedAgo|null},
     survival?: { deathType: 'oneShot'|'wasLow', killingHit: {name, size, pctOfMax},
                  hpBeforePct, overkill, maxHp,
                  wouldSave: {name: true|false|null}, allTogetherWouldSave } } */

// Saved reports and shares from before this feature carry an older shape; skip them.
const isCurrentShape = (d) => d && Array.isArray(d.active) && Array.isArray(d.available);

const fmt = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : `${n}`);

const SAVE_TITLES = {
  true: 'Pressed in time, this alone would have kept them alive through the killing blow',
  false: 'Would not have been enough on its own against the killing blow',
  null: "Can't estimate this one (its effect isn't simple damage reduction, absorb or healing)",
};

function HowTheyDied({ s }) {
  if (!s) return null;
  const hit = `${s.killingHit.name} hit for ${s.killingHit.pctOfMax}% of max health`;
  return (
    <div className="fpx-defs-row how">
      <span className={`lbl ${s.deathType === 'oneShot' ? 'one' : 'low'}`}>
        {s.deathType === 'oneShot' ? 'ONE-SHOT' : 'WAS LOW'}
      </span>
      <span className="txt">
        {s.deathType === 'oneShot'
          ? `One-shot from ${s.hpBeforePct}% health: ${hit}`
          : `At ${s.hpBeforePct}% health when ${hit}`}
        <small> · died by {fmt(s.overkill)}</small>
      </span>
    </div>
  );
}

export function DeathDefensives({ d }) {
  if (!isCurrentShape(d)) return null;
  const s = d.survival;
  const saves = (name) => (s ? s.wouldSave?.[name] : undefined);
  const personalActive = d.active.filter((a) => a.kind !== 'external');
  const externals = d.active.filter((a) => a.kind === 'external');
  const noneSavesAlone = s && !Object.values(s.wouldSave || {}).some((v) => v === true);

  const consumable = (label, c) => {
    const used = c?.usedAgo != null;
    const couldSave = !used && saves(label === 'Healthstone' ? healthstoneName(s) : potionName(s));
    return (
      <span className={`cons${used ? ' used' : ''}${couldSave ? ' save' : ''}`}>
        {label}: {used ? `used ${c.usedAgo}s before` : 'not used'}
        {couldSave ? ' (would have saved them)' : ''}
      </span>
    );
  };

  return (
    <div className="fpx-defs">
      <HowTheyDied s={s} />
      <div className="fpx-defs-row">
        <span className="lbl act">ACTIVE</span>
        {personalActive.length === 0 && externals.length === 0 && (
          d.activeKnown === false
            ? <span className="none" title="No recorded killing blow for this death, so its auras aren't known">Unknown (no recorded killing blow)</span>
            : <span className="none">Nothing active</span>
        )}
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
          {d.available.map((a) => {
            const v = saves(a.name);
            return (
              <span key={a.name}
                className={`d avail${a.major ? '' : ' minor'}${v === true ? ' save' : ''}${v === false ? ' short' : ''}`}
                title={s ? SAVE_TITLES[String(v ?? null)] : 'Off cooldown when they died'}>
                {v === true && '✓ '}{a.name}
              </span>
            );
          })}
          {noneSavesAlone && s.allTogetherWouldSave && (
            <span className="combo">all of these together would have saved them</span>
          )}
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

// The consumable the backend scored (it names the specific Healthstone / potion they carry).
const HEALTHSTONES = ['Healthstone', 'Demonic Healthstone'];
const healthstoneName = (s) => Object.keys(s?.wouldSave || {}).find((n) => HEALTHSTONES.includes(n));
const potionName = (s) => Object.keys(s?.wouldSave || {}).find((n) => /Potion/.test(n));

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
