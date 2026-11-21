import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  LogIn, LogOut, Settings as SettingsIcon, ChevronRight,
  Search, Loader2, AlertCircle, Info, KeyRound, ExternalLink,
} from 'lucide-react';
import FpxRail from './FpxRail';
import { SEASON_TWO_RAIDS } from './seasonTwoRaids';

/* Mirrors RAID_ZONES / BOSS_ORDER in App.js. Visual layer only — the
   key is what gets written to config.selectedRaid (handleRaidChange). */
const RAIDS = [
  { key: 'manaforge', name: 'Manaforge Omega', exp: 'THE WAR WITHIN', final: 'Dimensius, the All-Devouring',
    bossIds: [3129, 3131, 3130, 3132, 3122, 3133, 3134, 3135],
    bosses: ['Plexus Sentinel', "Loom'ithar", 'Soulbinder Naazindhri', 'Forgeweaver Araz', 'The Soul Hunters', 'Fractillus', 'Nexus-King Salhadaar', 'Dimensius, the All-Devouring'] },
  { key: 'undermine', name: 'Liberation of Undermine', exp: 'THE WAR WITHIN', final: 'Chrome King Gallywix',
    bossIds: [3009, 3010, 3011, 3012, 3013, 3014, 3015, 3016],
    bosses: ['Vexie and the Geargrinders', 'Cauldron of Carnage', 'Rik Reverb', 'Stix Bunkjunker', 'Sprocketmonger Lockenstock', 'One-Armed Bandit', "Mug'Zee, Heads of Security", 'Chrome King Gallywix'] },
  { key: 'nerubar', name: "Nerub'ar Palace", exp: 'THE WAR WITHIN', final: 'Queen Ansurek',
    bossIds: [2902, 2917, 2898, 2918, 2919, 2920, 2921, 2922],
    bosses: ['Ulgrax the Devourer', 'The Bloodbound Horror', 'Sikran, Captain of the Sureki', "Rasha'nan", "Broodtwister Ovi'nax", "Nexus-Princess Ky'veza", 'The Silken Court', 'Queen Ansurek'] },
  { key: 'midnight-all', name: 'Midnight Season 1', exp: 'MIDNIGHT', final: "L'ura",
    bossIds: [3176, 3177, 3179, 3178, 3180, 3181, 3306, 3182, 3183],
    bosses: ['Imperator Averzian', 'Vorasius', 'Fallen-King Salhadaar', 'Vaelgor & Ezzorak', 'Lightblinded Vanguard', 'Crown of the Cosmos', 'Chimaerus, the Undreamt God', "Belo'ren", "L'ura"] },
  ...SEASON_TWO_RAIDS,
];
const COUNCIL = new Set(['the-soul-hunters', 'vaelgor-ezzorak', 'cauldron-of-carnage', 'the-silken-court', 'lightblinded-vanguard',
  'entombed-sentinels', 'the-twin-fangs', 'the-coiled-altar']);
const slug = (n) => n.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const bossImg = (n) => `${process.env.PUBLIC_URL}/art/bosses/${slug(n)}.webp`;

/* Each raid's bosses and their encounter IDs (same order), for the boss picker. */
export const RAID_BOSS_IDS = Object.fromEntries(RAIDS.map((r) => [r.key, { bosses: r.bosses, ids: r.bossIds }]));

/* config.selectedBosses when every boss was deselected. Never sent: the Analyze button is off. */
export const NO_BOSSES = 'none';

/* The chosen bosses of a raid as encounter IDs. config.selectedBosses holds them; an empty list,
   or one naming none of this raid's bosses (left over from another raid), means every boss. */
export function chosenBossIds(raidKey, selectedBosses) {
  const ids = RAID_BOSS_IDS[raidKey]?.ids || [];
  if (selectedBosses === NO_BOSSES) return [];
  const picked = ids.filter((id) => (selectedBosses || []).map(Number).includes(id));
  return picked.length ? picked : ids;
}

/* "2 of 10 bosses" when some bosses were left out of an analysis, else ''. */
export function bossScopeLabel(raidKey, selectedBosses) {
  const ids = RAID_BOSS_IDS[raidKey]?.ids || [];
  const n = chosenBossIds(raidKey, selectedBosses).length;
  return ids.length && n < ids.length ? `${n} of ${ids.length} bosses` : '';
}

export default function AnalyzeConfig({
  config, onChange, onRaidChange, onSubmit, setConfig,
  loading, error, user, onShowAuth, onShowSettings, onLogout, onShowInfo, onHome,
}) {
  const navigate = useNavigate();
  const [railCollapsed, setRailCollapsed] = useState(false);
  const selected = RAIDS.find((r) => r.key === config.selectedRaid) || RAIDS[0];
  const chosen = chosenBossIds(selected.key, config.selectedBosses);
  // Every boss is stored as an empty list, so a later new boss is in by default; none as NO_BOSSES.
  const stored = (ids) => (ids.length === selected.bossIds.length ? []
    : ids.length === 0 ? NO_BOSSES : selected.bossIds.filter((id) => ids.includes(id)));
  const setChosen = (ids) => setConfig((prev) => ({ ...prev, selectedBosses: stored(ids) }));
  // From the latest choice, so two quick clicks both count.
  const toggleBoss = (id) => setConfig((prev) => {
    const now = chosenBossIds(selected.key, prev.selectedBosses);
    return { ...prev, selectedBosses: stored(now.includes(id) ? now.filter((x) => x !== id) : [...now, id]) };
  });
  const allChosen = chosen.length === selected.bossIds.length;
  const noBoss = chosen.length === 0;

  const raidCard = (raid) => {
    return (
      <button key={raid.key} type="button"
        aria-label={raid.name}
        aria-pressed={config.selectedRaid === raid.key}
        className={`fpx-raidcard${config.selectedRaid === raid.key ? ' on' : ''}`}
        onClick={() => onRaidChange({ target: { name: 'selectedRaid', value: raid.key } })}>
        <div className="rc-art" style={{ backgroundImage: `url(${bossImg(raid.final)})` }} />
        <div className="rc-meta">
          <span className="rc-exp">{raid.exp}</span>
          <span className="rc-name">{raid.name}</span>
          <span className="rc-cnt">{raid.bosses.length} {raid.bosses.length === 1 ? 'boss' : 'bosses'}</span>
        </div>
        {config.selectedRaid === raid.key && <span className="rc-tick" aria-hidden="true">✦</span>}
      </button>
    );
  };

  const field = (label, name, type = 'text', hint = null, extra = null) => (
    <div className="fpx-field">
      <label>{label}</label>
      {type === 'select' ? (
        <select name={name} value={config[name]} onChange={onChange}>{extra}</select>
      ) : (
        <input type={type} name={name} value={config[name]} onChange={onChange}
          min={type === 'number' ? 1 : undefined} max={type === 'number' ? 10 : undefined} />
      )}
      {hint && <p className="hint">{hint}</p>}
    </div>
  );

  return (
    <>
      <div className="fpx-atmos base" />
      <div className="fpx-atmos vignette" />
      <div className="fpx-atmos grain" />

      <main className="fpx-land">
        <div className={`fpx-shell${railCollapsed ? ' collapsed' : ''}`}>
          <FpxRail
            collapsed={railCollapsed}
            onToggle={() => setRailCollapsed((v) => !v)}
            active="analyze"
            onHome={onHome}
            onAnalyze={() => {}}
            onResults={() => navigate('/results')}
          />

          <div className="fpx-main fpx-analyze">
            <div className="fpx-top fpx-rv">
              <div className="fpx-crumbs">ANALYSIS&nbsp; /&nbsp; <b>CONFIGURE</b></div>
              <div className="fpx-auth">
                {user ? (
                  <>
                    <button className="fpx-btn ghost sm" onClick={onShowSettings}><SettingsIcon size={15} /> Settings</button>
                    <button className="fpx-btn ghost sm" onClick={onLogout}><LogOut size={15} /> Logout</button>
                  </>
                ) : (
                  <button className="fpx-btn ghost sm" onClick={onShowAuth}><LogIn size={15} /> Sign In</button>
                )}
              </div>
            </div>

            <div className="fpx-pagehead fpx-rv">
              <div>
                <h2>Configure analysis</h2>
                <p>Pick the raid, point us at your guild's WarcraftLogs, and run the death review.</p>
              </div>
              <button className="fpx-btn ghost sm" onClick={onShowInfo}>
                <Info size={15} /> How it works
              </button>
            </div>

            {/* RAID PICKER */}
            <div className="fpx-slab fpx-rv">
              <h3 id="raid-picker-heading">RAID</h3>
              <span>select the tier to analyze</span><div className="rule" />
            </div>
            <section className="fpx-raidgrid fpx-rv" aria-labelledby="raid-picker-heading">
              {RAIDS.map(raidCard)}
            </section>

            {/* selected raid's lineup */}
            <div className="fpx-slab fpx-rv" style={{ marginTop: 30 }}>
              <h3 id="selected-raid-heading">{selected.name.toUpperCase()}</h3>
              <span>click a boss to leave it out or add it back</span><div className="rule" />
              <span className="fpx-bosscount">{`${chosen.length} of ${selected.bossIds.length} bosses selected`}</span>
              {!allChosen && (
                <button type="button" className="fpx-link" aria-label="Select all bosses"
                  onClick={() => setChosen(selected.bossIds)}>Select all</button>
              )}
              {!noBoss && (
                <button type="button" className="fpx-link" aria-label="Deselect all bosses"
                  onClick={() => setChosen([])}>Deselect all</button>
              )}
            </div>
            <section className="fpx-lineup fpx-rv" aria-labelledby="selected-raid-heading">
              {selected.bosses.map((b, i) => {
                const id = selected.bossIds[i];
                const on = chosen.includes(id);
                return (
                  <div key={b} className={`fpx-boss pick${COUNCIL.has(slug(b)) ? ' council' : ''}${on ? '' : ' off'}`}
                    style={{ '--img': `url(${bossImg(b)})` }}>
                    <div className="art" />
                    <div className="cap"><div className="nm">{b}</div></div>
                    <button type="button" className="fpx-boss-toggle" aria-label={b} aria-pressed={on}
                      title={on ? 'Leave this boss out' : 'Include this boss'}
                      onClick={() => toggleBoss(id)} />
                  </div>
                );
              })}
            </section>
            {noBoss && (
              <div className="fpx-bosswarn fpx-rv" role="alert">
                No bosses selected. Pick at least one boss to analyze.
              </div>
            )}

            {/* CONFIG FORM */}
            <div className="fpx-slab fpx-rv" style={{ marginTop: 34 }}>
              <h3>CREDENTIALS &amp; SCOPE</h3><span>WarcraftLogs V2 API</span><div className="rule" /></div>

            {!user && (
              <div className="fpx-callout fpx-rv">
                <KeyRound size={17} />
                <div>
                  <b>Need API credentials?</b> Create a WarcraftLogs V2 client (Client ID + Secret),
                  this browser remembers them, or <button className="fpx-link" onClick={onShowAuth}>sign in</button> to keep them on your account.
                  <a className="fpx-link" href="https://www.warcraftlogs.com/api/clients/" target="_blank" rel="noopener noreferrer">
                    WarcraftLogs API Clients <ExternalLink size={12} />
                  </a>
                </div>
              </div>
            )}

            <section className="fpx-form fpx-rv">
              <div className="fpx-grid2">
                {field('Client ID (V2 API) *', 'clientId', 'text',
                  user ? '✓ Auto-fills from your account' : 'Required · remembered in this browser')}
                {field('Client Secret (V2 API) *', 'clientSecret', 'password',
                  user ? '✓ Auto-fills from your account' : 'Required · remembered in this browser')}
              </div>
              <div className="fpx-grid2">
                {field('Guild Name *', 'guildName', 'text', 'Exactly as on WarcraftLogs — e.g. Do Over, Method')}
                {field('Server *', 'server', 'text', 'As in-game, spaces OK — e.g. Thrall, Area 52')}
              </div>
              <div className="fpx-grid2">
                {field('Region *', 'region', 'select', null,
                  <>
                    <option value="us">US</option><option value="eu">EU</option>
                    <option value="kr">KR</option><option value="tw">TW</option><option value="cn">CN</option>
                  </>)}
                {field('Difficulty *', 'difficulty', 'select', null,
                  <>
                    <option value="3">Normal</option><option value="4">Heroic</option><option value="5">Mythic</option>
                  </>)}
              </div>
              <div className="fpx-grid2">
                <div className="fpx-field">
                  <label>Start Date (optional)</label>
                  <div className="fpx-daterow">
                    <input type="date" name="startDate" value={config.startDate} onChange={onChange} />
                    {config.startDate && <button type="button" className="fpx-clear"
                      onClick={() => setConfig((p) => ({ ...p, startDate: '' }))}>Clear</button>}
                  </div>
                  <p className="hint">Blank = from the start of the tier</p>
                </div>
                <div className="fpx-field">
                  <label>End Date (optional)</label>
                  <div className="fpx-daterow">
                    <input type="date" name="endDate" value={config.endDate} onChange={onChange} />
                    {config.endDate && <button type="button" className="fpx-clear"
                      onClick={() => setConfig((p) => ({ ...p, endDate: '' }))}>Clear</button>}
                  </div>
                  <p className="hint">Blank = up to today</p>
                </div>
              </div>
              <div className="fpx-grid2">
                {field('Max Deaths to Track', 'maxCutoff', 'number',
                  'First X deaths per pull (1–10) — focuses on early mechanic failures')}
                <div className="fpx-field">
                  <label>Cheat Death Detection</label>
                  <label className={`fpx-check${user ? '' : ' disabled'}`}>
                    <input type="checkbox" checked={config.enableCheatDeath}
                      disabled={!user}
                      onChange={(e) => user && setConfig({ ...config, enableCheatDeath: e.target.checked })} />
                    <span>Calculate Cheat Deaths <em>(+20–30s)</em></span>
                  </label>
                  <p className="hint">
                    {user ? 'Saves from a lethal hit: Cheat Death, Cauterize, Purgatory, Last Resort, Defy Fate, Restitution, Kill or Be Killed, Guardian Spirit, Ardent Defender'
                      : <>Account required — <button className="fpx-link" onClick={onShowAuth}>sign in</button></>}
                  </p>
                </div>
              </div>
              <div className="fpx-grid2">
                <div className="fpx-field">
                  <label>Guild Roster</label>
                  <label className="fpx-check">
                    <input type="checkbox" checked={config.rosterOnly !== false}
                      onChange={(e) => setConfig({ ...config, rosterOnly: e.target.checked })} />
                    <span>Only count guild members</span>
                  </label>
                  <p className="hint">
                    {config.rosterOnly !== false
                      ? "Only players on the guild's WarcraftLogs roster count. Trials or pugs who aren't in the guild yet are left out."
                      : "Everyone in the guild's reports counts, including trials and pugs not on the roster."}
                  </p>
                </div>
              </div>
            </section>

            {error && (
              <div className="fpx-error fpx-rv"><AlertCircle size={18} /><span>{error}</span></div>
            )}

            <div className="fpx-runrow fpx-rv">
              <button className="fpx-btn" onClick={onSubmit} disabled={loading || noBoss}
                title={noBoss ? 'Pick at least one boss to analyze' : undefined}
                style={{ opacity: loading || noBoss ? 0.65 : 1, cursor: loading || noBoss ? 'not-allowed' : 'pointer' }}>
                {loading ? <><Loader2 size={18} className="fpx-spin" /> Analyzing…</>
                  : <><Search size={18} /> Analyze Reports <ChevronRight size={16} /></>}
              </button>
            </div>

            <div className="fpx-note fpx-rv">
              <h6>Why death counts may vary</h6>
              <p>Slight run-to-run differences (a death here or there) come from newly uploaded
                reports, timestamp edge cases, or WarcraftLogs API updates. They don't
                meaningfully move death-rate percentages — accuracy over perfect consistency.</p>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
