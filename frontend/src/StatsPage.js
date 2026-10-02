import React, { useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Icon, Tip, TipHead } from './DeathRow';
import { KILL_OPTIONS, MAX_DEATHS, selectKills, specLabel, tally } from './tierStats';

/* Tier stats from public WarcraftLogs kills (not from anyone's analysis):
   which boss abilities kill raiders, and how often each spec dies. */

const CLASS_COLORS = {
  DeathKnight: 'var(--fpx-c-dk)', DemonHunter: 'var(--fpx-c-dh)', Druid: 'var(--fpx-c-druid)',
  Evoker: 'var(--fpx-c-evoker)', Hunter: 'var(--fpx-c-hunter)', Mage: 'var(--fpx-c-mage)',
  Monk: 'var(--fpx-c-monk)', Paladin: 'var(--fpx-c-paladin)', Priest: 'var(--fpx-c-priest)',
  Rogue: 'var(--fpx-c-rogue)', Shaman: 'var(--fpx-c-shaman)', Warlock: 'var(--fpx-c-warlock)',
  Warrior: 'var(--fpx-c-warrior)',
};
const TOP_ABILITIES = 15;
const pct = (x) => `${(x * 100).toFixed(x >= 0.1 ? 0 : 1)}%`;
const num = (n) => n.toLocaleString('en-US');
const fmtDate = (ms) => new Date(ms).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

function Bar({ value, max, color }) {
  return (
    <span className="fpx-stbar-track">
      <span className="fpx-stbar-fill" style={{ width: `${max ? (value / max) * 100 : 0}%`, background: color }} />
    </span>
  );
}

export default function StatsPage({ raid }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [patchName, setPatchName] = useState(null);
  const [bossId, setBossId] = useState('');
  const [firstKills, setFirstKills] = useState(0);
  const [firstDeaths, setFirstDeaths] = useState(2);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let live = true;
    fetch(`${process.env.PUBLIC_URL}/stats/${raid.key}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
      .then((d) => live && setData(d))
      .catch(() => live && setError('Tier stats could not be loaded. Try again in a moment.'));
    return () => { live = false; };
  }, [raid.key]);

  const patches = useMemo(() => (data?.patches || []).filter((p) => Object.keys(p.bosses).length), [data]);
  const patch = patches.find((p) => p.name === patchName) || patches[patches.length - 1];

  // This tier's bosses with kills in the patch, in the raid's order.
  const bosses = useMemo(() => {
    if (!data || !patch) return [];
    const order = (name) => { const i = raid.bosses.indexOf(name); return i < 0 ? 99 : i; };
    return data.bosses.filter((b) => patch.bosses[b.id]?.length).sort((a, b) => order(a.name) - order(b.name));
  }, [data, patch, raid.bosses]);
  const bossName = useMemo(() => Object.fromEntries((data?.bosses || []).map((b) => [String(b.id), b.name])), [data]);

  const mostKills = Math.max(0, ...(bossId ? [patch?.bosses[bossId]?.length || 0]
    : bosses.map((b) => patch.bosses[b.id].length)));
  const killOptions = KILL_OPTIONS.filter((n) => n === 0 || n < mostKills);
  const kills = firstKills && firstKills < mostKills ? firstKills : 0;

  const t = useMemo(() => (patch ? tally(selectKills(patch, bossId || null, kills), firstDeaths) : null),
    [patch, bossId, kills, firstDeaths]);

  if (error) return <div className="fpx-rempty">{error}</div>;
  if (!data) return <div className="fpx-rempty"><Loader2 size={16} className="fpx-spin" /> Loading tier stats…</div>;
  if (!patch) return <div className="fpx-rempty">No Mythic kills logged for {raid.name} yet.</div>;

  const abilities = showAll ? t.abilities : t.abilities.slice(0, TOP_ABILITIES);
  const maxShare = t.abilities[0]?.share || 0;
  const maxRate = t.specs[0]?.perKill || 0;
  const scope = bossId ? bossName[bossId] : 'all bosses';
  const killLabel = kills ? `first ${num(kills)} kills${bossId ? '' : ' of each boss'}` : 'every kill';

  return (
    <div className="fpx-results fpx-stats">
      <div className="fpx-pagehead fpx-rv">
        <div>
          <h2>{raid.name} · Mythic</h2>
          <p>
            Every guild's first Mythic kill of each boss with a public WarcraftLogs log, in the order they happened.
            Deaths count as in an analysis: a kill's first {firstDeaths} {firstDeaths === 1 ? 'death' : 'deaths'},
            leaving out mass deaths (8 in 8 seconds).
          </p>
        </div>
      </div>

      <div className="fpx-filters fpx-rv">
        <div className="fpx-frow">
          <label className="fpx-flabel">Patch
            <select value={patch.name} onChange={(e) => setPatchName(e.target.value)}>
              {patches.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          </label>
          <label className="fpx-flabel">Boss
            <select value={bossId} onChange={(e) => setBossId(e.target.value)}>
              <option value="">All bosses</option>
              {bosses.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </label>
          <label className="fpx-flabel">Kills
            <select value={kills} onChange={(e) => setFirstKills(Number(e.target.value))}>
              {killOptions.map((n) => (
                <option key={n} value={n}>{n ? `First ${num(n)}` : `All (${num(mostKills)}${bossId ? '' : ' max'})`}</option>
              ))}
            </select>
          </label>
          <label className="fpx-flabel">Deaths
            <select value={firstDeaths} onChange={(e) => setFirstDeaths(Number(e.target.value))}>
              {Array.from({ length: MAX_DEATHS }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>First {n}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="fpx-stsum">
          <b>{num(t.kills)}</b> kills · <b>{num(t.deaths)}</b> deaths counted · {scope}, {killLabel}
          {data.updated && <span> · updated {fmtDate(data.updated)}</span>}
        </div>
      </div>

      <div className="fpx-stgrid">
        <section className="fpx-rpanel fpx-rv">
          <div className="fpx-rpanel-h"><h4>WHAT'S KILLING RAIDERS</h4><span className="sub">share of counted deaths</span></div>
          {abilities.length === 0 ? <div className="fpx-rempty">No deaths counted.</div> : (
            <ol className="fpx-stlist">
              {abilities.map((a, i) => {
                const [id, name, icon, text] = data.abilities[a.index];
                return (
                  <li key={`${a.boss}:${id}`}>
                    <Tip className="fpx-strow" content={() => (
                      <>
                        <TipHead name={name} icon={icon} sub={bossName[a.boss]} />
                        {text && <p className="desc">{text}</p>}
                        <div className="kv">
                          <div className="r"><span>Deaths</span><span>{num(a.deaths)} of {num(t.deaths)}</span></div>
                          <div className="r"><span>Share</span><span>{pct(a.share)}</span></div>
                        </div>
                      </>
                    )}>
                      <span className="rk">{i + 1}</span>
                      <Icon name={name} icon={icon} />
                      <span className="nm">
                        <span className="t">{name}{!bossId && <small>{bossName[a.boss]}</small>}</span>
                        <Bar value={a.share} max={maxShare} color="linear-gradient(90deg,var(--fpx-kill-2),var(--fpx-kill))" />
                      </span>
                      <span className="v">{pct(a.share)}</span>
                    </Tip>
                  </li>
                );
              })}
            </ol>
          )}
          {t.abilities.length > TOP_ABILITIES && (
            <button className="fpx-btn ghost sm fpx-stmore" onClick={() => setShowAll((v) => !v)}>
              {showAll ? `Top ${TOP_ABILITIES}` : `Show all ${t.abilities.length}`}
            </button>
          )}
        </section>

        <section className="fpx-rpanel fpx-rv">
          <div className="fpx-rpanel-h"><h4>SURVIVAL BY SPEC</h4><span className="sub">deaths per player per kill</span></div>
          {t.specs.length === 0 ? <div className="fpx-rempty">No kills.</div> : (
            <ol className="fpx-stlist">
              {t.specs.map((s, i) => {
                const { cls, label } = specLabel(data.specs[s.index]);
                return (
                  <li key={s.index}>
                    <Tip className="fpx-strow" content={() => (
                      <>
                        <div className="th"><div><b style={{ color: CLASS_COLORS[cls] }}>{label}</b></div></div>
                        <div className="kv">
                          <div className="r"><span>Played in these kills</span><span>{num(s.players)}</span></div>
                          <div className="r"><span>Deaths counted</span><span>{num(s.deaths)}</span></div>
                          <div className="r"><span>Deaths per kill</span><span>{s.perKill.toFixed(3)}</span></div>
                        </div>
                      </>
                    )}>
                      <span className="rk">{i + 1}</span>
                      <span className="dot" style={{ background: CLASS_COLORS[cls] }} />
                      <span className="nm">
                        <span className="t">{label}<small>{num(s.players)} played</small></span>
                        <Bar value={s.perKill} max={maxRate} color={CLASS_COLORS[cls]} />
                      </span>
                      <span className="v">{s.perKill.toFixed(2)}</span>
                    </Tip>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}
