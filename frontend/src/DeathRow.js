import React, { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/* One death as a single row: the killing blow, a health bar, and a strip of
   ability icons (active / ready / on cooldown), each with a hover tooltip
   carrying the numbers behind its verdict.

   Data (from the backend):
     death.defensives: see backend/defensives.py analyze_death. With a killing
       blow, survival.details[name] = {amount, why?, school?, effect?, talents?,
       source?, typical?} (defensives._explain).
     icons:       {abilityName: icon file name} for render.worldofwarcraft.com.
     abilityInfo: {name: {kind, cooldownMs, auraMs, charges, effect, typicalHeal?}}.
     abilityText: {spell ID: in-game description} for killing blows (death.abilityId).
     killCounts:  {"boss|ability": counted deaths to it in these results}. */

const ICON_URL = (icon) => `https://render.worldofwarcraft.com/us/icons/56/${icon}.jpg`;
const isCurrentShape = (d) => d && Array.isArray(d.active) && Array.isArray(d.available);

export const fmt = (n) => {
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e3) return `${Math.round(n / 1e3)}k`;
  return `${Math.round(n)}`;
};
const secs = (ms) => (ms >= 60000 && ms % 60000 === 0 ? `${ms / 60000} min` : `${Math.round(ms / 1000)}s`);
const pct = (v) => `${Math.round(v * 1000) / 10}%`;

const SCHOOL_BITS = [[1, 'Physical'], [2, 'Holy'], [4, 'Fire'], [8, 'Nature'], [16, 'Frost'], [32, 'Shadow'], [64, 'Arcane']];
const schoolName = (mask) => {
  if (!mask) return null;
  const names = SCHOOL_BITS.filter(([b]) => mask & b).map(([, n]) => n);
  if (!names.length) return null;
  return names.length > 2 ? 'Chaos' : names.join(' + ');
};
const SCOPE = { magic: 'magic ', physical: 'physical ', aoe: 'area ', melee: 'melee ' };

/* Plain-English effect of an ability, from its components. */
function effectText(effect, info) {
  const parts = (effect || []).map((c) => {
    const scope = SCOPE[c.school] || '';
    if (c.immune) return c.school === 'melee' ? 'Dodges all melee attacks' : `Immune to ${scope}damage`;
    if (c.dr) return `Reduces ${scope}damage taken by ${pct(c.dr)}`;
    if (c.absorb) return `Absorbs ${scope}damage equal to ${pct(c.absorb)} of max health`;
    if (c.absorb_amount) return `Absorbs ${fmt(c.absorb_amount)} ${scope}damage`;
    if (c.hp) return `Increases max health by ${pct(c.hp)}`;
    if (c.heal) return `Heals ${pct(c.heal)} of max health`;
    if (c.heal_amount) return `Heals ${fmt(c.heal_amount)}`;
    return null;
  }).filter(Boolean);
  if (!parts.length && info?.typicalHeal) parts.push(`Heals about ${fmt(info.typicalHeal)}`);
  let text = parts.join('. ');
  if (info?.auraMs && text) text += ` for ${secs(info.auraMs)}`;
  if (info?.cooldownMs) {
    text += `${text ? '. ' : ''}${secs(info.cooldownMs)} cooldown`;
    if (info.charges > 1) text += `, ${info.charges} charges`;
  }
  return text ? `${text}.` : '';
}

function whyText(d, hitName) {
  switch (d.why) {
    case 'school':
      return d.school === 'melee' ? `${hitName} isn't a melee attack`
        : d.school === 'aoe' ? `${hitName} isn't area damage`
        : d.school === 'magic' ? `${hitName} isn't magic damage`
        : `${hitName} isn't physical damage`;
    case 'pierces': return `${hitName} goes through immunities`;
    case 'noReduction': return 'Nothing reduced this hit, so damage reduction doesn\'t work on it';
    case 'fullHealth': return 'They were at full health, so a heal can\'t help';
    case 'aoeUnknown': return 'This log doesn\'t mark area damage, so this can\'t be checked';
    default: return null;
  }
}

const TALENT_TEXT = (t) => ('add' in t ? `+${pct(t.add * t.rank)}` : `×${Math.round((1 + (t.mult - 1) * t.rank) * 100) / 100}`);
const SOURCE_TEXT = {
  log: 'From their own heals from it in these boss pulls.',
  typical: "None of theirs in these boss pulls, so the tier's typical heal is used.",
  gameData: 'From the game data.',
};

/* ---------- tooltip ---------- */

function TipBox({ anchor, children }) {
  const ref = useRef(null);
  const [style, setStyle] = useState({ left: anchor.left, top: anchor.bottom + 8, visibility: 'hidden' });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    const left = Math.max(8, Math.min(anchor.left, window.innerWidth - w - 8));
    const below = anchor.bottom + 8;
    const top = below + h > window.innerHeight - 8 ? Math.max(8, anchor.top - h - 8) : below;
    setStyle({ left, top, visibility: 'visible' });
  }, [anchor]);
  return createPortal(<div ref={ref} className="fpx-tip" style={style} role="tooltip">{children}</div>, document.body);
}

export function Tip({ content, className, children }) {
  const ref = useRef(null);
  const [anchor, setAnchor] = useState(null);
  const show = () => ref.current && setAnchor(ref.current.getBoundingClientRect());
  const hide = () => setAnchor(null);
  return (
    <span ref={ref} className={className} tabIndex={0}
      onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {children}
      {anchor && <TipBox anchor={anchor}>{content()}</TipBox>}
    </span>
  );
}

// Blizzard's icon server doesn't have every new icon; WarcraftLogs hosts them all.
const ICON_FALLBACK = (icon) => `https://assets.rpglogs.com/img/warcraft/abilities/${icon}.jpg`;

function Icon({ name, icons, className = '' }) {
  const icon = icons?.[name];
  const [tries, setTries] = useState(0);
  if (!icon || tries > 1) return <span className={`fpx-ico none ${className}`}>{(name || '?').charAt(0)}</span>;
  return <img className={`fpx-ico ${className}`} src={(tries ? ICON_FALLBACK : ICON_URL)(icon)} alt="" loading="lazy"
    onError={() => setTries((t) => t + 1)} />;
}

const TipHead = ({ name, icons, sub }) => (
  <div className="th"><Icon name={name} icons={icons} /><div><b>{name}</b>{sub && <small>{sub}</small>}</div></div>
);
const Row = ({ a, b, cls }) => <div className="r"><span className={cls}>{a}</span><span>{b}</span></div>;

/* ---------- the row ---------- */

export function DeathRow({ death, icons, abilityInfo, abilityText, killCounts, logHref, timeLabel }) {
  const d = death.defensives;
  const current = isCurrentShape(d);
  const s = current ? d.survival : null;
  const hitName = death.abilityName === 'Unknown' ? 'Unknown ability' : death.abilityName;
  const kills = killCounts?.[`${death.boss}|${death.abilityName}`];
  const info = (n) => abilityInfo?.[n];

  const ctx = death.isCheatDeath ? 'prevented death (cheat death)'
    : !s ? (current ? 'no killing blow recorded' : '')
    : s.deathType === 'oneShot'
      ? `one-shot from ${s.hpBeforePct}% health · died by ${fmt(s.overkill)}`
      : `at ${s.hpBeforePct}% health, hit for ${s.killingHit.pctOfMax}% of max · died by ${fmt(s.overkill)}`;

  const killTip = () => (
    <>
      <TipHead name={hitName} icons={icons} sub={[death.boss, s && schoolName(s.killingHit.school)].filter(Boolean).join(' · ')} />
      {abilityText?.[death.abilityId] && <p>{abilityText[death.abilityId]}</p>}
      {s && <Row a="This hit" b={`${fmt(s.killingHit.size)} (${s.killingHit.pctOfMax.toLocaleString()}% of max health)`} />}
      {s && <Row a="Health before it" b={`${s.hpBeforePct}% (${fmt(s.maxHp * s.hpBeforePct / 100)})`} />}
      {s && <Row a="They died by" b={fmt(s.overkill)} />}
      {kills > 0 && <Row a="Killed in these pulls" b={`${kills} raider${kills === 1 ? '' : 's'}`} />}
      {s?.ignoresImmunity && <div className="note warn">Goes through immunities (Ice Block, Divine Shield…)</div>}
      {s?.ignoresReduction && <div className="note warn">Nothing reduced this hit, so damage reduction doesn't work on it (shields and heals still do)</div>}
      {!s && current && <p>No hit with health data was recorded for this death, so defensives can't be checked against it.</p>}
    </>
  );

  const readyTip = (name, v) => () => {
    const det = s?.details?.[name];
    const inf = info(name);
    const talents = det?.talents || [];
    const effect = det?.effect || inf?.effect;
    const heals = (effect || []).length > 0 && effect.every((c) => c.heal != null || c.heal_amount != null);
    const fullHeal = heals && s ? effect.reduce((t, c) => t + (c.heal_amount || 0) + (c.heal || 0) * s.maxHp, 0) : 0;
    return (
      <>
        <TipHead name={name} icons={icons} sub={inf?.kind === 'external' ? 'External' : null} />
        <p>{effectText(inf ? inf.effect : effect, inf)}</p>
        {talents.map((t) => <Row key={t.talent} a={t.talent} b={TALENT_TEXT(t)} cls="tal" />)}
        {det && s && det.amount > 0 && (
          <>
            {heals && fullHeal > det.amount + 1
              ? <Row a="Would heal" b={`${fmt(det.amount)} (all they were missing)`} />
              : <Row a={heals ? 'Would heal' : 'Would prevent'} b={fmt(det.amount)} />}
            <Row a="They died by" b={fmt(s.overkill)} />
          </>
        )}
        {det && s && (
          v === true ? <div className="res g">Survives with {fmt(det.amount - s.overkill)} to spare</div>
            : det.why ? <div className="res b">Doesn't help: {whyText(det, hitName)}</div>
            : det.amount > 0 ? <div className="res b">Not enough: {fmt(s.overkill - det.amount)} short</div>
            : null
        )}
        {!det && s && v == null && <div className="res b">Can't estimate this one (not simple damage reduction, absorb or healing)</div>}
        {!s && <div className="res b">Off cooldown when they died</div>}
        {det?.source && <div className="src">{SOURCE_TEXT[det.source]}</div>}
      </>
    );
  };

  const strip = [];
  if (current) {
    d.active.forEach((a) => strip.push(
      <Tip key={`a-${a.name}`} className="i act" content={() => (
        <>
          <TipHead name={a.name} icons={icons} sub={a.kind === 'external' ? `External${a.by ? ` from ${a.by}` : ''}` : null} />
          <p>{effectText(info(a.name)?.effect, info(a.name))}</p>
          <div className="res gold">Active when they died</div>
        </>
      )}><Icon name={a.name} icons={icons} /></Tip>
    ));
    if (d.active.length) strip.push(<span key="s1" className="sep" />);
    const ready = [
      ...d.available.map((a) => a.name),
      ...Object.keys(s?.consumables || {}),
    ];
    ready.forEach((name) => {
      const v = s?.wouldSave?.[name];
      strip.push(
        <Tip key={`r-${name}`} className={`i ${v === true ? 'ok' : 'no'}`} content={readyTip(name, v)}>
          <Icon name={name} icons={icons} />
        </Tip>
      );
    });
    const cds = [
      ...d.cooldown.map((c) => ({ name: c.name, label: `${c.readyIn}s`, text: `Pressed ${c.usedAgo}s before they died; back ${c.readyIn}s after` })),
      ...['healthstone', 'potion'].filter((k) => d[k]?.usedAgo != null).map((k) => ({
        name: d[k].name || (k === 'potion' ? 'Health Potion' : 'Healthstone'), label: '',
        text: `Used ${d[k].usedAgo}s before they died (once per pull)` })),
    ];
    if (cds.length) strip.push(<span key="s2" className="sep" />);
    cds.forEach((c) => strip.push(
      <Tip key={`c-${c.name}`} className="i cd" content={() => (
        <>
          <TipHead name={c.name} icons={icons} />
          <p>{effectText(info(c.name)?.effect, info(c.name))}</p>
          <div className="res b">On cooldown: {c.text}</div>
        </>
      )}><Icon name={c.name} icons={icons} />{c.label && <span className="t">{c.label}</span>}</Tip>
    ));
  }
  const saves = s ? Object.values(s.wouldSave || {}).filter((v) => v === true).length : 0;

  return (
    <div className={`fpx-drow${death.isCheatDeath ? ' cheat' : ''}`}>
      <Tip className="kb" content={killTip}>
        <Icon name={death.abilityName} icons={icons} className="big" />
        <span className="kbt">
          <span className="an">#{death.pullNo} · {hitName}{death.isCheatDeath && <span className="fpx-cheatbadge">CHEAT</span>}</span>
          {ctx && <span className="cx">{ctx}{s?.ignoresImmunity ? <em> · through immunities</em> : null}</span>}
        </span>
      </Tip>
      <span className="hp" title={s ? `${s.hpBeforePct}% health before the killing blow` : undefined}>
        {s && <><span className="bar"><i style={{ width: `${Math.min(s.hpBeforePct, 100)}%` }} /></span>
          <small>{s.hpBeforePct}% health before</small></>}
      </span>
      <span className="strip">
        {strip}
        {s && !saves && s.allTogetherWouldSave && (
          <Tip className="all" content={() => <p>No single one would have been enough, but everything they had ready, used together, would have kept them alive.</p>}>
            all together ✓
          </Tip>
        )}
        {current && !d.talentsKnown && (
          <Tip className="note" content={() => <p>No talent data for this pull, so abilities count only if they pressed them somewhere in the log.</p>}>
            ?
          </Tip>
        )}
      </span>
      <span className="end">
        <a href={logHref} target="_blank" rel="noopener noreferrer" className="fpx-wcl">View log ↗</a>
        <small>{timeLabel}</small>
      </span>
    </div>
  );
}
