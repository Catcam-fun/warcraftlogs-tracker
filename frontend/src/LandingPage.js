import React from 'react';
import { BarChart3, Clock3, FolderOpen, Play, Shield, Skull, Sparkles, Users } from 'lucide-react';

const timeline = [
  ['00:43', 'First death', 'Shadow crash clipped melee', 'danger'],
  ['01:18', 'No defensive', 'Personal cooldowns still available', 'warning'],
  ['02:02', 'Mass event', 'Seven deaths within ten seconds', 'danger'],
  ['03:41', 'Recovery', 'External healing stabilized the pull', 'good']
];

const updates = [
  ['Midnight Raid Support', 'The Voidspire, The Dreamrift, and March on Quel\'Danas are ready for raid-night review.', 'Mar 17'],
  ['Cheat Death Detection', 'Logged-in users can identify prevented lethal events with improved deduplication.', 'Dec 8'],
  ['The War Within Coverage', 'Death tracking is available across the current raid catalog.', 'Nov 20']
];

export default function LandingPage({ onRunAnalysis, onSavedReports }) {
  return (
    <main className="fp-landing landing-shell">
      <section className="landing-hero">
        <div>
          <div className="landing-eyebrow">WarcraftLogs death investigation</div>
          <h1 className="landing-title">Floor Pov</h1>
          <p className="landing-copy">
            A focused raid review cockpit for finding early deaths, missing defensives, repeated boss patterns,
            and wipe cascades before the next pull timer starts.
          </p>
          <div className="landing-actions">
            <button className="btn btn-primary" onClick={onRunAnalysis}>
              <Play size={18} />
              Run Analysis
            </button>
            {onSavedReports && (
              <button className="btn" onClick={onSavedReports}>
                <FolderOpen size={18} />
                Saved Reports
              </button>
            )}
          </div>
        </div>

        <div className="investigation-board surface-panel">
          <div className="stat-grid">
            <div className="stat-tile">
              <p className="stat-label">Deaths Tracked</p>
              <p className="stat-value">128</p>
            </div>
            <div className="stat-tile">
              <p className="stat-label">Pulls Reviewed</p>
              <p className="stat-value">34</p>
            </div>
          </div>
          {timeline.map(([time, label, detail, tone]) => (
            <div className="timeline-row" key={`${time}-${label}`}>
              <strong style={{ color: 'var(--color-gold-2)' }}>{time}</strong>
              <span>
                <b>{label}</b>
                <br />
                <span style={{ color: 'var(--color-muted)', fontSize: 13 }}>{detail}</span>
              </span>
              <span style={{ color: tone === 'good' ? 'var(--color-green)' : tone === 'warning' ? 'var(--color-gold-2)' : 'var(--color-red)' }}>
                {tone === 'good' ? <Shield size={18} /> : <Skull size={18} />}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="feature-grid">
        <div className="feature-card surface-panel">
          <Clock3 color="var(--color-gold-2)" />
          <h3>Early Pull Focus</h3>
          <p>Track the first deaths per pull and keep late wipe noise from hiding mechanical failures.</p>
        </div>
        <div className="feature-card surface-panel">
          <BarChart3 color="var(--color-blue)" />
          <h3>Boss Pattern Charts</h3>
          <p>Compare deaths, pull counts, rates, and player outliers in a single visual system.</p>
        </div>
        <div className="feature-card surface-panel">
          <Users color="var(--color-green)" />
          <h3>Roster-Aware Review</h3>
          <p>Group alts with mains, filter low attendance, and keep class colors visible in dense tables.</p>
        </div>
      </section>

      <section className="updates-list">
        <div className="landing-eyebrow">Recent updates</div>
        {updates.map(([title, copy, date]) => (
          <div className="update-card surface-panel" key={title}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
              <h3 style={{ margin: 0 }}>{title}</h3>
              <span style={{ color: 'var(--color-subtle)', whiteSpace: 'nowrap' }}>{date}</span>
            </div>
            <p style={{ color: 'var(--color-muted)', marginBottom: 0 }}>{copy}</p>
          </div>
        ))}
        <Sparkles size={1} aria-hidden="true" />
      </section>
    </main>
  );
}
