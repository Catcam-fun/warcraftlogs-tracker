import React, { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/* One death as a single row: the killing blow, a health bar, and a strip of
   ability icons (active / ready / on cooldown), each with a hover tooltip
   carrying the numbers behind its verdict.

   Data (from the backend):
     death.defensives: see backend/defensives.py analyze_death. With a killing
       blow, survival.details[name] = {amount, why?, school?, effect?, talents?,
       source?, typical?} (defensives._explain).
     icons:       {defensive name: icon file name} for render.worldofwarcraft.com.
     abilityIcons: {spell ID: icon file name} for killing blows (death.abilityId).
     abilityInfo: {name: {kind, cooldownMs, auraMs, charges, effect, typicalHeal?, description?}}.
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

// Damage schools and their colours in the game's combat log.
const SCHOOL_BITS = [[1, 'Physical'], [2, 'Holy'], [4, 'Fire'], [8, 'Nature'], [16, 'Frost'], [32, 'Shadow'], [64, 'Arcane']];
const SCHOOL_COLORS = { 1: '#FFFF00', 2: '#FFE680', 4: '#FF8000', 8: '#4DFF4D', 16: '#80FFFF', 32: '#8080FF', 64: '#FF80FF' };
// The game's names for mixed schools, by school mask.
const MIXED_SCHOOLS = {
  3: 'Holystrike', 5: 'Flamestrike', 9: 'Stormstrike', 17: 'Froststrike', 33: 'Shadowstrike', 65: 'Spellstrike',
  6: 'Radiant', 10: 'Holystorm', 18: 'Holyfrost', 34: 'Twilight', 66: 'Divine', 12: 'Volcanic', 20: 'Frostfire',
  36: 'Shadowflame', 68: 'Spellfire', 24: 'Froststorm', 40: 'Plague', 72: 'Astral', 48: 'Shadowfrost',
  80: 'Spellfrost', 96: 'Spellshadow', 28: 'Elemental', 106: 'Cosmic', 124: 'Chromatic', 126: 'Magic', 127: 'Chaos',
};
const SCHOOL_MASKS = Object.fromEntries([
  ...SCHOOL_BITS.map(([b, n]) => [n, b]), ...Object.entries(MIXED_SCHOOLS).map(([m, n]) => [n, Number(m)]),
]);
const schoolName = (mask) => {
  if (!mask) return null;
  if (MIXED_SCHOOLS[mask]) return MIXED_SCHOOLS[mask];
  const names = SCHOOL_BITS.filter(([b]) => mask & b).map(([, n]) => n);
  return names.length ? names.join(' + ') : null;
};

/* A school's name in its colour; a mixed school shades through each of its colours. */
function School({ mask, children }) {
  const colors = SCHOOL_BITS.filter(([b]) => mask & b).map(([b]) => SCHOOL_COLORS[b]);
  if (!colors.length) return <>{children}</>;
  const style = colors.length === 1 ? { color: colors[0] }
    : { backgroundImage: `linear-gradient(90deg, ${colors.join(', ')})`, WebkitBackgroundClip: 'text',
        backgroundClip: 'text', color: 'transparent' };
  return <span className="school" style={style}>{children}</span>;
}

const SCHOOL_WORDS = new RegExp(`\\b(${Object.keys(SCHOOL_MASKS).join('|')})(?= damage\\b)`, 'g');
/* Description text with each "<school> damage" coloured. */
function schoolText(text) {
  const parts = [];
  let last = 0;
  text.replace(SCHOOL_WORDS, (m, name, at) => {
    parts.push(text.slice(last, at), <School key={at} mask={SCHOOL_MASKS[name]}>{name}</School>);
    last = at + m.length;
    return m;
  });
  parts.push(text.slice(last));
  return parts;
}
const SCOPE = { magic: 'magic ', physical: 'physical ', aoe: 'area ', melee: 'melee ' };

/* What an ability does: worked out from its components (exact, talents
   applied), else its in-game description, plus its cooldown. */
function effectText(effect, info) {
  // Exact numbers first (catalog components); the game's text when there are none (externals).
  if (info?.description && info.kind !== 'potion' && !(effect || []).length) {
    const cd = info.cooldownMs && !/cooldown/i.test(info.description)
      ? ` ${secs(info.cooldownMs)} cooldown${info.charges > 1 ? `, ${info.charges} charges` : ''}.` : '';
    return info.description + cd;
  }
  const parts = (effect || []).map((c) => {
    const scope = typeof c.school === 'number' ? `${schoolScope(c.school)} ` : SCOPE[c.school] || '';
    const over = c.over_ms ? ` over ${secs(c.over_ms)}` : '';
    if (c.immune) return c.school === 'melee' ? 'Dodges all melee attacks' : `Immune to ${scope}damage`;
    if (c.dr) return `Reduces ${scope}damage taken by ${pct(c.dr)}`;
    if (c.dr_missing) return `Reduces damage taken by up to ${pct(c.dr_missing)} more, the lower their health`;
    if (c.armor) return `Increases armor by ${pct(c.armor)}`;
    if (c.absorb) return `Absorbs ${scope}damage equal to ${pct(c.absorb)} of max health`;
    if (c.absorb_amount) return `Absorbs ${fmt(c.absorb_amount)} ${scope}damage`;
    if (c.hp) return c.current ? `Increases current and max health by ${pct(c.hp)}` : `Increases max health by ${pct(c.hp)}`;
    if (c.heal) return `Heals ${pct(c.heal)} of max health${over}`;
    if (c.heal_amount) return `Heals ${fmt(c.heal_amount)}${over}`;
    if (c.heal_taken) return `Increases healing received by ${pct(c.heal_taken)}`;
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
    case 'instakill': return 'it was an instant kill, with no damage to reduce, absorb or heal';
    case 'hotTooLate': return 'it came off cooldown too late for any of its heal to land before this hit';
    case 'notArmor': return `armor doesn't reduce ${hitName}`;
    case 'armorUnknown': return `it isn't known whether armor reduces ${hitName}`;
    default: return null;
  }
}

// Which damage an effect limited to some schools covers, in words.
const schoolScope = (school) => {
  if (school === 'magic' || school === 126) return 'magic';
  if (school === 62) return 'magic except arcane';
  if (typeof school === 'number') return (schoolName(school) || 'magic').toLowerCase();
  return { physical: 'physical', aoe: 'area damage', melee: 'melee' }[school] || school;
};

// What a talent-added effect adds, by the field it fills (defensives._resolve).
const ADDS_WHAT = {
  dr: 'damage reduction', dr_missing: 'damage reduction at low health', armor: 'armor', hp: 'max health',
  heal: 'heal', heal_taken: 'healing received', absorb: 'shield',
};
const TALENT_TEXT = (t) => {
  if ('adds' in t) {
    if (t.field === 'absorb' && t.adds > 1) return `adds a ${fmt(t.adds)} shield`;
    const vs = t.school ? ` vs ${schoolScope(t.school)}` : '';
    return `adds ${pct(t.adds * t.rank)}${t.field === 'absorb' ? ' of max health as a' : ''} ${ADDS_WHAT[t.field] || ''}${vs}`.trim();
  }
  return 'add' in t ? `+${pct(t.add * t.rank)}` : `×${Math.round((1 + (t.mult - 1) * t.rank) * 100) / 100}`;
};
/* What their own potions / Healthstones healed in these boss pulls. */
function ownUsesText(sm, info) {
  const what = info?.kind === 'healthstone' ? 'Healthstone' : 'potion';
  const range = sm.min != null
    ? (sm.min === sm.max ? fmt(sm.min) : `${fmt(sm.min)} to ${fmt(sm.max)}`)
    : (sm.minShare === sm.maxShare ? `${pct(sm.minShare)} of max health`
      : `${pct(sm.minShare)} to ${pct(sm.maxShare)} of max health`);
  const cd = info?.cooldownMs ? ` ${secs(info.cooldownMs)} cooldown.` : '';
  return `Their ${sm.n} ${what}${sm.n === 1 ? '' : 's'} in these boss pulls healed ${range}.${cd}`;
}

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
// The game's own quality overlays for potions in the bags (UI atlas crops in
// public/art/quality): The War Within's three ranks, Midnight's two.
const QUALITY_ART = { 3: ['tww-1', 'tww-2', 'tww-3'], 2: ['midnight-1', 'midnight-2'] };
export const qualityArt = (rank) => {
  if (!rank?.rank || !rank.ranks) return null;
  const i = rank.ranks.findIndex((r) => r.rank === rank.rank);
  const art = QUALITY_ART[rank.ranks.length]?.[i];
  return art ? `/art/quality/${art}.png` : null;
};

/* The potion rank a player most likely drinks (defensives.potion_rank). */
function PotionRank({ rank }) {
  if (!rank) return null;
  const art = qualityArt(rank);
  return (
    <>
      {rank.rank
        ? <Row a="Likely drinking" b={<>{art && <img className="fpx-qual-inline" src={art} alt="" />}{cap(rank.rank)} rank</>} cls="tal" />
        : <Row a="Likely drinking" b="can't tell" />}
      <div className="src">
        {rank.rank
          ? `From ${rank.n > 1 ? `the middle of their ${rank.n} potion heals` : 'their potion heal'} in these pulls, with Versatility and healing buffs taken out: it reaches the ${rank.rank} tooltip.`
          : `This tier's ranks heal within ${rank.unknown}% of each other, less than players' own healing bonuses, so the log can't show which one they drink.`}
      </div>
    </>
  );
}

const SOURCE_TEXT = {
  log: 'Estimate: the middle of their own heals from it, with the healing buffs they had when they died.',
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

function Icon({ name, icons, icon: given, className = '', quality }) {
  const icon = given || icons?.[name];
  const [tries, setTries] = useState(0);
  const img = !icon || tries > 1
    ? <span className={`fpx-ico none ${className}`}>{(name || '?').charAt(0)}</span>
    : <img className={`fpx-ico ${className}`} src={(tries ? ICON_FALLBACK : ICON_URL)(icon)} alt="" loading="lazy"
      onError={() => setTries((t) => t + 1)} />;
  if (!quality) return img;
  // The potion's rank, as the game marks it on the item in the bags.
  return <span className="fpx-qualwrap">{img}<img className="fpx-qual" src={quality} alt="" /></span>;
}

const TipHead = ({ name, icons, icon, sub }) => (
  <div className="th"><Icon name={name} icons={icons} icon={icon} /><div><b>{name}</b>{sub && <small>{sub}</small>}</div></div>
);
const Row = ({ a, b, cls }) => <div className="r"><span className={cls}>{a}</span><span>{b}</span></div>;

/* ---------- the row ---------- */

export function DeathRow({ death, icons, abilityIcons, abilityInfo, abilityText, killCounts, logHref, timeLabel }) {
  const d = death.defensives;
  const current = isCurrentShape(d);
  const s = current ? d.survival : null;
  const hitName = death.abilityName === 'Unknown' ? 'Unknown ability' : death.abilityName;
  const kills = killCounts?.[`${death.boss}|${death.abilityName}`];
  const info = (n) => abilityInfo?.[n];
  // Killing blows by spell ID: names aren't unique (a boss's Tempest isn't the Shaman's).
  const kbIcon = abilityIcons?.[death.abilityId];
  const kbSchool = s?.killingHit.school;

  const instakill = s?.deathType === 'instakill';
  const ctx = death.isCheatDeath ? 'prevented death (cheat death)'
    : !s ? (current ? 'no killing blow recorded' : '')
    : instakill ? 'instant kill: the mechanic killed them outright, with no damage'
    : s.deathType === 'oneShot'
      ? `one-shot from ${s.hpBeforePct}% health · died by ${fmt(s.overkill)}`
      : `at ${s.hpBeforePct}% health, hit for ${s.killingHit.pctOfMax}% of max · died by ${fmt(s.overkill)}`;

  const killTip = () => (
    <>
      <TipHead name={hitName} icon={kbIcon}
        sub={<>{death.boss}{schoolName(kbSchool) && <> · <School mask={kbSchool}>{schoolName(kbSchool)}</School></>}</>} />
      {abilityText?.[death.abilityId] && <p>{schoolText(abilityText[death.abilityId])}</p>}
      {s && !instakill && <Row a="This hit" b={`${fmt(s.killingHit.size)} (${s.killingHit.pctOfMax.toLocaleString()}% of max health)`} />}
      {s && !instakill && <Row a="Health before it" b={`${s.hpBeforePct}% (${fmt(s.maxHp * s.hpBeforePct / 100)})`} />}
      {s && !instakill && <Row a="They died by" b={fmt(s.overkill)} />}
      {instakill && <div className="note warn">Instant kill: the game killed them outright, with no damage to reduce, absorb or heal. Only avoiding the mechanic prevents it.</div>}
      {kills > 0 && <Row a="Killed in these pulls" b={`${kills} raider${kills === 1 ? '' : 's'}`} />}
      {s?.ignoresImmunity && <div className="note warn">Goes through immunities (Ice Block, Divine Shield…)</div>}
      {s?.ignoresReduction && <div className="note warn">Nothing reduced this hit, so damage reduction doesn't work on it (shields and heals still do)</div>}
      {!s && current && <p>No hit with health data was recorded for this death, so defensives can't be checked against it.</p>}
    </>
  );

  const withForm = Object.fromEntries((current ? d.available : []).filter((a) => a.withForm).map((a) => [a.name, a.withForm]));
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
        {withForm[name] && <div className="note">Needs {withForm[name]}: checked as shifting into it, then pressing {name}.</div>}
        <p>{det?.source === 'log' && det.samples ? ownUsesText(det.samples, inf)
          : effectText(inf ? inf.effect : effect, inf)}</p>
        {talents.map((t) => <Row key={`${t.talent}-${t.field}`} a={t.talent} b={TALENT_TEXT(t)} cls="tal" />)}
        {det?.hot && (
          <Row a={`Heals over ${secs(info(name)?.auraMs || 0)}`}
            b={`${det.hot.ticks} of ${det.hot.of} ticks land before the hit`} />
        )}
        {det && s && det.amount > 0 && det.hot && (
          <>
            <Row a="Would heal before the hit" b={`${fmt(det.hot.landed ?? det.amount)} of ${fmt(det.hot.full)}`} />
            {withForm[name] && det.hot.landed != null && det.amount > det.hot.landed + 1 && (
              <Row a={`With ${withForm[name]}, all together`} b={fmt(det.amount)} />
            )}
            <Row a="They died by" b={fmt(s.overkill)} />
          </>
        )}
        {det && s && det.amount > 0 && !det.hot && (
          <>
            {heals && fullHeal > det.amount + 1
              ? <Row a="Would heal" b={`${fmt(det.amount)} (all they were missing)`} />
              : <Row a={heals ? 'Would heal' : 'Would prevent'} b={fmt(det.amount)} />}
            <Row a="They died by" b={fmt(s.overkill)} />
          </>
        )}
        {det && s && (
          v === true ? <div className="res g">Survives with {fmt(det.amount - s.overkill)} to spare</div>
            : det.why === 'needsTimeline'
              ? <div className="res b">Can't tell: it heals over time, and the log's health for the seconds before this death couldn't be read</div>
            : det.why ? <div className="res b">Doesn't help: {whyText(det, hitName)}</div>
            : det.amount > 0 ? <div className="res b">Not enough: {fmt(s.overkill - det.amount)} short</div>
            : null
        )}
        {!det && s && v == null && <div className="res b">Can't estimate this one (not simple damage reduction, absorb or healing)</div>}
        {!s && <div className="res b">Off cooldown when they died</div>}
        {det?.source && <div className="src">{SOURCE_TEXT[det.source]}</div>}
        {inf?.kind === 'potion' && <PotionRank rank={det?.rank} />}
        {det?.hot && <div className="src">Checked as if pressed early enough for every tick to land before the hit (never before it was off cooldown), using their real health in those seconds.</div>}
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
          <Icon name={name} icons={icons} quality={qualityArt(s?.details?.[name]?.rank)} />
        </Tip>
      );
    });
    const cds = [
      ...d.cooldown.map((c) => ({ name: c.name, label: `${c.readyIn}s`, text: `Pressed ${c.usedAgo}s before they died; back ${c.readyIn}s after` })),
      ...['healthstone', 'potion'].filter((k) => d[k]?.usedAgo != null).map((k) => ({
        name: d[k].name || (k === 'potion' ? 'Health Potion' : 'Healthstone'),
        rank: d[k].rank,
        label: d[k].readyIn != null ? `${d[k].readyIn}s` : '',
        text: d[k].readyIn != null
          ? `Used ${d[k].usedAgo}s before they died; back ${d[k].readyIn}s after`
          : `Used ${d[k].usedAgo}s before they died` })),
    ];
    if (cds.length) strip.push(<span key="s2" className="sep" />);
    cds.forEach((c) => strip.push(
      <Tip key={`c-${c.name}`} className="i cd" content={() => (
        <>
          <TipHead name={c.name} icons={icons} />
          <p>{effectText(info(c.name)?.effect, info(c.name))}</p>
          <div className="res b">On cooldown: {c.text}</div>
          {c.rank && <PotionRank rank={c.rank} />}
        </>
      )}><Icon name={c.name} icons={icons} quality={qualityArt(c.rank)} />{c.label && <span className="t">{c.label}</span>}</Tip>
    ));
  }
  const saves = s ? Object.values(s.wouldSave || {}).filter((v) => v === true).length : 0;

  return (
    <div className={`fpx-drow${death.isCheatDeath ? ' cheat' : ''}`}>
      <Tip className="kb" content={killTip}>
        <Icon name={death.abilityName} icon={kbIcon} className="big" />
        <span className="kbt">
          <span className="an">#{death.pullNo} · {hitName}{death.isCheatDeath && <span className="fpx-cheatbadge">CHEAT</span>}</span>
          {ctx && <span className="cx">{ctx}{s?.ignoresImmunity ? <em> · through immunities</em> : null}</span>}
        </span>
      </Tip>
      <span className="hp" title={s ? `${s.hpBeforePct}% health before the killing blow` : undefined}>
        {s && !instakill && <><span className="bar"><i style={{ width: `${Math.min(s.hpBeforePct, 100)}%` }} /></span>
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
