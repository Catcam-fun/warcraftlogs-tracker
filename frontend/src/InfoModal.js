import React from 'react';
import { X, Info } from 'lucide-react';

const SECTIONS = [
  {
    h: 'Data collection & processing',
    p: 'Floor Pov analyses raid death data from WarcraftLogs by:',
    li: [
      'Fetching all guild reports for your selected raid and difficulty',
      'Processing death events from each pull',
      'Tracking player participation across all fights',
      'Calculating death rates (deaths per pull) for each player and boss',
    ],
  },
  {
    h: 'Data validation & completeness',
    p: "Multiple verification steps keep the data complete and accurate:",
    li: [
      ['Comprehensive report fetching', 'retrieves every available report for your guild in the date range, so no logs are missed'],
      ['Participation tracking', 'cross-references player presence across all fights for accurate "pulls participated" counts'],
      ['Fight boundary validation', 'verifies fight start/end timestamps so all deaths within valid encounters are captured'],
      ['Missing-data detection', 'identifies and handles cases where WarcraftLogs data is incomplete or corrupted'],
    ],
  },
  {
    h: 'Deduplication & accuracy',
    p: 'Smart deduplication keeps results honest:',
    li: [
      ['Report-level dedup', 'the same pull can appear in multiple uploaders’ reports — these are detected and merged by fight timestamp and encounter'],
      ['Name normalization', 'handles accents and special characters (e.g. "Catëlynn" vs "Catelynn")'],
      ['Death-window filtering', 'only counts deaths inside the valid fight window'],
      ['Mass-death detection', 'identifies raid wipes (7+ deaths within 10s) to set fight boundaries correctly'],
    ],
  },
  {
    h: 'Why death counts may vary between runs',
    p: 'Slight differences between runs of the same guild are normal:',
    li: [
      ['New reports uploaded', 'members may add logs between runs'],
      ['Timestamp edge cases', 'deaths exactly at a fight boundary can be handled differently'],
      ['WarcraftLogs API updates', 'the upstream source occasionally corrects historical data'],
    ],
    note: "It's usually a death or two per character and doesn't meaningfully move death-rate percentages — the tool prioritises accuracy over perfect consistency.",
  },
  {
    h: 'Cheat-death detection',
    tag: 'SIGNED-IN',
    p: 'For signed-in accounts, Floor Pov can detect deaths prevented by defensive abilities — Cauterize, Spirit of Redemption, Cheat Death, Purgatory, Divine Shield, and more.',
    note: 'Adds one API call per report and ~20–30s to analysis time.',
  },
  {
    h: 'Character grouping (alts)',
    p: 'Group alts with their mains to see combined deaths, pulls participated, and death rate.',
  },
  {
    h: 'Questions or issues?',
    p: 'Floor Pov is in active alpha. If you hit bugs or have ideas:',
    li: [
      'Check the recent updates in the footer',
      'Report issues or request features (contact info coming soon)',
      'Join the Discord community (link coming soon)',
    ],
  },
];

export default function InfoModal({ onClose }) {
  return (
    <div className="fpx-mov" onClick={onClose}>
      <div className="fpx-mcard" onClick={(e) => e.stopPropagation()}>
        <div className="fpx-mhead">
          <h2><Info size={20} /> How Floor Pov works</h2>
          <button className="fpx-mclose" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="fpx-mbody">
          {SECTIONS.map((s) => (
            <section className="fpx-msec" key={s.h}>
              <h3>{s.h}{s.tag && <span className="fpx-mtag">{s.tag}</span>}</h3>
              {s.p && <p>{s.p}</p>}
              {s.li && (
                <ul>
                  {s.li.map((item, i) => (
                    <li key={i}>
                      {Array.isArray(item) ? <><b>{item[0]}</b> — {item[1]}</> : item}
                    </li>
                  ))}
                </ul>
              )}
              {s.note && <p className="fpx-mnote">{s.note}</p>}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
