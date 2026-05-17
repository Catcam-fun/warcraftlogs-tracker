import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Play, LogIn, LogOut, Settings as SettingsIcon, ChevronRight,
  Home, Crosshair, Grid3x3, Skull, Users, ChevronsLeft, ChevronsRight
} from 'lucide-react';

/* Real encounters from the live BOSS_ORDER catalog (App.js). Render
   art slots into the --img var per tile once boss renders land. */
const BOSS_STRIP = [
  // Manaforge Omega
  ['Plexus Sentinel', 'MANAFORGE OMEGA'],
  ["Loom'ithar", 'MANAFORGE OMEGA'],
  ['Soulbinder Naazindhri', 'MANAFORGE OMEGA'],
  ['Forgeweaver Araz', 'MANAFORGE OMEGA'],
  ['The Soul Hunters', 'MANAFORGE OMEGA'],
  ['Fractillus', 'MANAFORGE OMEGA'],
  ['Nexus-King Salhadaar', 'MANAFORGE OMEGA'],
  ['Dimensius, the All-Devouring', 'MANAFORGE OMEGA'],
  // Nerub'ar Palace
  ['Ulgrax the Devourer', "NERUB'AR PALACE"],
  ['The Bloodbound Horror', "NERUB'AR PALACE"],
  ['Sikran, Captain of the Sureki', "NERUB'AR PALACE"],
  ["Rasha'nan", "NERUB'AR PALACE"],
  ["Broodtwister Ovi'nax", "NERUB'AR PALACE"],
  ["Nexus-Princess Ky'veza", "NERUB'AR PALACE"],
  ['The Silken Court', "NERUB'AR PALACE"],
  ['Queen Ansurek', "NERUB'AR PALACE"],
  // Liberation of Undermine
  ['Vexie and the Geargrinders', 'LIBERATION OF UNDERMINE'],
  ['Cauldron of Carnage', 'LIBERATION OF UNDERMINE'],
  ['Rik Reverb', 'LIBERATION OF UNDERMINE'],
  ['Stix Bunkjunker', 'LIBERATION OF UNDERMINE'],
  ['Sprocketmonger Lockenstock', 'LIBERATION OF UNDERMINE'],
  ['One-Armed Bandit', 'LIBERATION OF UNDERMINE'],
  ["Mug'Zee, Heads of Security", 'LIBERATION OF UNDERMINE'],
  ['Chrome King Gallywix', 'LIBERATION OF UNDERMINE'],
  // The Voidspire (Midnight S1)
  ['Imperator Averzian', 'THE VOIDSPIRE'],
  ['Vorasius', 'THE VOIDSPIRE'],
  ['Fallen-King Salhadaar', 'THE VOIDSPIRE'],
  ['Vaelgor & Ezzorak', 'THE VOIDSPIRE'],
  ['Lightblinded Vanguard', 'THE VOIDSPIRE'],
  ['Crown of the Cosmos', 'THE VOIDSPIRE'],
  // The Dreamrift / March on Quel'Danas (Midnight S1)
  ['Chimaerus, the Undreamt God', 'THE DREAMRIFT'],
  ["Belo'ren", "MARCH ON QUEL'DANAS"],
  ["L'ura", "MARCH ON QUEL'DANAS"],
];

/* Multi-boss / council encounters — tiles show all members (fit-to-frame
   so none get cropped), matching the pipeline's COUNCIL set. */
const COUNCIL = new Set([
  'the-soul-hunters', 'vaelgor-ezzorak', 'cauldron-of-carnage',
  'the-silken-court', 'lightblinded-vanguard',
]);

/* Only capabilities the app actually delivers today. */
const FEATURES = [
  [Grid3x3, 'var(--fpx-kill)', 'Per-pull death grid',
    'Every death mapped player × boss × pull, Adventure-Guide ordered. Sort, search, and expand any name to see exactly where the floor opened up.'],
  [Skull, 'var(--fpx-regress)', 'Wipe-cascade detection',
    'Mass-death events detected, grouped, and de-duplicated across repeated pulls — with cheat-death prevention recognized for signed-in accounts.'],
  [Users, 'var(--fpx-c-mage)', 'Roster-aware review',
    'WoW class colors as tokens, alts grouped to mains, low-attendance trimmed, and a read-only share link for the rest of the raid.'],
];

/* Official Midnight key art + cinematic stills (press kit), self-hosted
   and web-optimized. One is chosen at random per page load. */
const BACKGROUNDS = [
  'against-the-void', 'hope-shall-rise', 'darkness-devours', 'stand-as-one',
  'cinematic-1', 'cinematic-2', 'cinematic-3', 'cinematic-4', 'immolation-1',
  'supremacy-1', 'supremacy-2', 'supremacy-3', 'supremacy-4',
];

const UPDATES = [
  ['Midnight Season 1 support', "The Voidspire, The Dreamrift, and March on Quel'Danas are wired for raid-night review.", 'MAR 17'],
  ['Cheat Death detection', 'Signed-in accounts can isolate prevented lethal events with improved deduplication.', 'DEC 8'],
  ['The War Within coverage', 'Death tracking spans the full current raid catalog, Adventure-Guide ordered.', 'NOV 20'],
];

export default function LandingPage({
  onRunAnalysis, onSavedReports,
  user, onShowAuthModal, onShowSettings, onLogout,
}) {
  const [railCollapsed, setRailCollapsed] = useState(false);
  const bg = useMemo(
    () => BACKGROUNDS[Math.floor(Math.random() * BACKGROUNDS.length)],
    [],
  );
  return (
    <>
      <div className="fpx-atmos base" />
      <div
        className="fpx-atmos artimg"
        style={{
          backgroundImage:
            `url(${process.env.PUBLIC_URL}/art/backgrounds/${bg}.jpg), ` +
            `url(${process.env.PUBLIC_URL}/art/landing-keyart.svg)`,
        }}
      />
      <div className="fpx-atmos scrim" />
      <div className="fpx-embers" aria-hidden="true">
        {Array.from({ length: 22 }).map((_, i) => (
          <i key={i} style={{
            left: `${(i * 4.6 + 2) % 100}%`,
            animationDuration: `${12 + (i % 7) * 2.4}s`,
            animationDelay: `${-(i * 1.9) % 17}s`,
            transform: `scale(${0.6 + (i % 5) * 0.22})`,
          }} />
        ))}
      </div>
      <div className="fpx-atmos vignette" />
      <div className="fpx-atmos grain" />

      <main className="fpx-land">
        <div className={`fpx-shell${railCollapsed ? ' collapsed' : ''}`}>
          {/* ░ LEFT RAIL — lean, honest, collapsible ░ */}
          <aside className={`fpx-rail${railCollapsed ? ' collapsed' : ''}`}>
            <div className="fpx-railhead">
              <div className="fpx-brand" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
                <div className="mk">FP</div>
                <div className="wm">FLOOR&nbsp;POV<small>DEATH ANALYSIS</small></div>
              </div>
              <button
                className="fpx-railtoggle"
                onClick={() => setRailCollapsed((v) => !v)}
                aria-label={railCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                title={railCollapsed ? 'Expand' : 'Collapse'}
              >
                {railCollapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
              </button>
            </div>

            <nav className="fpx-navsec">
              <h4>FLOOR POV</h4>
              <button className="fpx-nav on" title="Home">
                <Home /><span className="lbl">Home</span>
              </button>
              <button className="fpx-nav" onClick={onRunAnalysis} title="Run Analysis">
                <Crosshair /><span className="lbl">Run Analysis</span>
              </button>
            </nav>
          </aside>

          {/* ░ MAIN ░ */}
          <div className="fpx-main">
            <div className="fpx-top fpx-rv">
              <div className="fpx-crumbs">FLOOR POV&nbsp; /&nbsp; <b>HOME</b></div>
              <div className="fpx-auth">
                {user ? (
                  <>
                    <button className="fpx-btn ghost sm" onClick={onShowSettings}>
                      <SettingsIcon size={15} /> Settings
                    </button>
                    <button className="fpx-btn ghost sm" onClick={onLogout}>
                      <LogOut size={15} /> Logout
                    </button>
                  </>
                ) : (
                  <button className="fpx-btn ghost sm" onClick={onShowAuthModal}>
                    <LogIn size={15} /> Sign In
                  </button>
                )}
              </div>
            </div>

            {/* editorial hero */}
            <section className="fpx-hero">
              <h1>
                <span className="l1 fpx-rv" style={{ animationDelay: '.05s' }}>Not another parse.</span>
                <span className="l2 fpx-rv" style={{ animationDelay: '.12s' }}>YOUR WIPE, FRAME BY FRAME.</span>
              </h1>
              <p className="fpx-rv" style={{ animationDelay: '.2s' }}>
                Floor Pov reads a WarcraftLogs report and rebuilds the raid night around
                death — who fell each pull, where the wipes cascaded, and which bosses
                kept ending you. No spreadsheet required.
              </p>
              <div className="fpx-cta fpx-rv" style={{ animationDelay: '.28s' }}>
                <button className="fpx-btn" onClick={onRunAnalysis}>
                  <Play size={18} /> Run Analysis
                </button>
                <button className="fpx-btn ghost" onClick={user ? onRunAnalysis : onShowAuthModal}>
                  {user ? <><Crosshair size={17} /> Go to analysis</> : <><LogIn size={17} /> Sign in</>}
                  <ChevronRight size={16} />
                </button>
              </div>
            </section>

            {/* boss strip */}
            <section className="fpx-strip fpx-rv" style={{ animationDelay: '.34s' }}>
              <div className="lab">RAID CATALOG · DEATH-TRACKED</div>
              <div className="fpx-track">
                {[...BOSS_STRIP, ...BOSS_STRIP].map(([name, zone], i) => {
                  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
                  return (
                    <div
                      className={`fpx-boss${COUNCIL.has(slug) ? ' council' : ''}`} key={i}
                      style={{ '--img': `url(${process.env.PUBLIC_URL}/art/bosses/${slug}.webp)` }}
                    >
                      <div className="art" />
                      <div className="cap">
                        <div className="nm">{name}</div>
                        <div className="zn">{zone}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* what it finds */}
            <div className="fpx-slab fpx-rv"><h3>WHAT IT FINDS</h3><span>read straight off the log</span><div className="rule" /></div>
            <section className="fpx-feats">
              {FEATURES.map(([Icon, color, title, body], i) => (
                <div className="fpx-feat fpx-rv" key={title} style={{ animationDelay: `${.06 * i}s` }}>
                  <div className="ic"><Icon style={{ color }} /></div>
                  <h4>{title}</h4>
                  <p>{body}</p>
                </div>
              ))}
            </section>

            {/* recent updates */}
            <div className="fpx-slab fpx-rv"><h3>RECENT UPDATES</h3><span>shipped to raid night</span><div className="rule" /></div>
            <section className="fpx-updates">
              {UPDATES.map(([title, copy, date]) => (
                <div className="fpx-upd fpx-rv" key={title}>
                  <div>
                    <h5>{title}</h5>
                    <p>{copy}</p>
                  </div>
                  <div className="dt">{date}</div>
                </div>
              ))}
            </section>
          </div>
        </div>

        {/* full-width footer */}
        <footer className="fpx-footer">
          <div className="fpx-footwrap">
            <div className="cols">
              <div>
                <h6>Floor Pov</h6>
                <p className="blurb">
                  A focused raid-death review tool for World of Warcraft guilds,
                  built on WarcraftLogs data. Find the floor before the next pull timer.
                </p>
              </div>
              <div>
                <h6>Resources</h6>
                <a href="https://www.warcraftlogs.com/" target="_blank" rel="noopener noreferrer">WarcraftLogs</a>
                <a href="https://www.warcraftlogs.com/api/clients" target="_blank" rel="noopener noreferrer">WarcraftLogs API</a>
              </div>
              <div>
                <h6>Legal</h6>
                <Link to="/terms">Terms of Service</Link>
                <Link to="/privacy">Privacy Policy</Link>
              </div>
            </div>
            <div className="legal">
              © {new Date().getFullYear()} Floor Pov. Not affiliated with or endorsed by Blizzard
              Entertainment. World of Warcraft and related artwork and trademarks are the property
              of Blizzard Entertainment, Inc. Key art © Blizzard Entertainment.
            </div>
          </div>
        </footer>
      </main>
    </>
  );
}
