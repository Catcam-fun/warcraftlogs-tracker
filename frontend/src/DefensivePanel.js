import React from 'react';
import { Tip } from './DeathRow';

/* Per-player defensive summaries. Each death's own row is DeathRow.js.
   Defensive picture for one death, as computed by backend/defensives.py:
   { active: [{name, kind, major?}], activeKnown, available: [{name, major}],
     cooldown: [{name, major, usedAgo, readyIn}], talentsKnown,
     healthstone: {usedAgo|null}, potion: {usedAgo|null},
     survival?: { deathType: 'oneShot'|'burst'|'wasLow'|'instakill', killingHit: {name, size, pctOfMax, school},
                  hpBeforePct, overkill, maxHp, ignoresReduction, ignoresImmunity,
                  wouldSave: {name: true|false|null}, allTogetherWouldSave,
                  window: {hits, fromAgo}, biggestHit?, oneShotHit?, fromPct?, burstMs?,
                  avoidable?: {verdict: true|false|null, hits: [{name, id, times, pctOfMax, unsure?}],
                               windowLimited} } }
   Verdicts replay the seconds before the death (a one-shot: high health at
   most 1.5s before it). Only deaths that can count carry this.
   Available entries may carry boostedBy: [talent names that strengthen it]. */

// Saved reports and shares from before this feature carry an older shape; skip them.
const isCurrentShape = (d) => d && Array.isArray(d.active) && Array.isArray(d.available);

/* Per-player rollup over the deaths that count toward their death rate. */
export function summarizeDefensives(deaths) {
  const summary = { withData: 0, withUnused: 0, unused: {}, assessed: 0, preventable: 0, oneShots: 0, savers: {},
    avoidable: 0, avoidableAssessed: 0 };
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
    if (s.deathType === 'oneShot' || s.deathType === 'instakill') summary.oneShots += 1;
    const savers = Object.entries(s.wouldSave || {}).filter(([, v]) => v === true).map(([n]) => n);
    if (savers.length > 0 || s.allTogetherWouldSave) summary.preventable += 1;
    savers.forEach((n) => { summary.savers[n] = (summary.savers[n] || 0) + 1; });
    // Results from before avoidable deaths, and deaths it couldn't judge, aren't counted.
    const verdict = s.avoidable?.verdict;
    if (verdict === true || verdict === false) summary.avoidableAssessed += 1;
    if (verdict === true) summary.avoidable += 1;
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
  const chip = (cls, text, meaning) => (
    <Tip className={`fpx-pdef ${cls}`} content={() => <p>{meaning}</p>}>{text} <i className="fpx-i">i</i></Tip>
  );
  return (
    <>
      {chip(tone, `${s.preventable}/${s.assessed} preventable`,
        'Deaths where a defensive, Healthstone or potion they had ready would have kept them alive.')}
      {s.avoidableAssessed > 0 && chip(
        s.avoidable === 0 ? 'good' : s.avoidable / s.avoidableAssessed >= 0.5 ? 'bad' : 'warn',
        `${s.avoidable}/${s.avoidableAssessed} avoidable`,
        'Deaths decided by damage they could have dodged by moving (pools, frontals, waves, things landing on '
        + 'the floor), taken since they were last at 85% health: without it they would have lived.')}
      {s.oneShots > 0 && chip('neutral', `${s.oneShots} one-shot${s.oneShots !== 1 ? 's' : ''}`,
        'One hit of 80%+ of their max health within 1.5 seconds of being at 85%+ health, a killing blow bigger '
        + 'than their whole max health, or an instant kill by a mechanic.')}
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
