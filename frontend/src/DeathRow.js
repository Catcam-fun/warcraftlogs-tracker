import React, { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/* One death as a single row: the killing blow, a health bar, and a strip of
   ability icons (active / ready / on cooldown), each with a hover tooltip
   carrying the numbers behind its verdict.

   Data (from the backend):
     death.defensives: see backend/defensives.py analyze_death. With a killing
       blow, survival.details[name] = {amount, why?, school?, effect?, talents?,
       source?, typical?, pressAgo?} (defensives._explain, assess_survival):
       judged over the seconds before the death (survival.window), with the
       biggest hit of those seconds in survival.biggestHit.
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
const secsFine = (ms) => (ms < 1000 ? `${(ms / 1000).toFixed(2).replace(/0$/, '')}s` : `${(ms / 1000).toFixed(1)}s`);

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
    case 'tooFast': return 'their health only dropped in the last second, too fast to react';
    case 'readyTooLate': return 'it came off cooldown less than a second before they died';
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

/* Where a consumable's heal comes from, in one line. */
function sourceText(det, inf) {
  const sm = det.samples;
  if (det.source === 'log' && sm) {
    const what = inf?.kind === 'healthstone' ? 'Healthstone' : 'potion';
    const range = sm.min != null
      ? (sm.min === sm.max ? fmt(sm.min) : `${fmt(sm.min)}–${fmt(sm.max)}`)
      : `${sm.minShare === sm.maxShare ? pct(sm.minShare) : `${pct(sm.minShare)}–${pct(sm.maxShare)}`} of max health`;
    const rank = det.rank?.rank ? `; the middle reaches the ${det.rank.rank} tooltip` : '';
    return `Heal from their own ${sm.n} ${what}${sm.n === 1 ? '' : 's'} in these pulls (${range})${rank}, with their healing buffs at death.`;
  }
  if (det.source === 'typical') return "None used in these pulls: the tier's typical heal.";
  if (det.source === 'gameData') return 'Heal from the game data.';
  return null;
}

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

const TipHead = ({ name, icons, icon, sub, glyph, quality }) => (
  <div className="th"><Icon name={glyph || name} icons={icons} icon={icon} quality={quality} />
    <div><b>{name}</b>{sub && <small>{sub}</small>}</div></div>
);
const Row = ({ a, b, cls }) => <div className="r"><span className={cls}>{a}</span><span>{b}</span></div>;

/* ---------- the row ---------- */

export function DeathRow({ death, icons, abilityIcons, abilityInfo, abilityText, killCounts, logHref, timeLabel }) {
  const d = death.defensives;
  const current = isCurrentShape(d);
  const s = current ? d.survival : null;
  // WarcraftLogs gives no killing ability when the log has no hit or instant kill for the death.
  const notLogged = death.abilityName === 'Unknown';
  const hitName = notLogged ? 'Killing blow not in the log' : death.abilityName;
  const kills = killCounts?.[`${death.boss}|${death.abilityName}`];
  const info = (n) => abilityInfo?.[n];
  // Killing blows by spell ID: names aren't unique (a boss's Tempest isn't the Shaman's).
  const kbIcon = abilityIcons?.[death.abilityId];
  const kbSchool = s?.killingHit.school;

  const instakill = s?.deathType === 'instakill';
  const ctx = death.isCheatDeath ? 'prevented death (cheat death)'
    : notLogged ? 'the log has no hit for this death'
    : !s ? (current ? 'no killing blow recorded' : '')
    : instakill ? 'instant kill, with no damage to stop'
    : s.deathType === 'oneShot'
      ? `one-shot from ${s.fromPct ?? s.hpBeforePct}%${s.burstMs ? ` in ${secsFine(s.burstMs)}` : ''} · died by ${fmt(s.overkill)}`
      : s.rot
        ? `worn down by ${s.rot.name} (rot, ${s.rot.hits} hits) · died by ${fmt(s.overkill)}`
      : s.biggestHit
        ? `at ${s.hpBeforePct}% after ${s.biggestHit.name}${s.biggestHit.times > 1 ? ` ×${s.biggestHit.times}` : ` (${s.biggestHit.pctOfMax}%${s.biggestHit.ago >= 0.1 ? `, ${s.biggestHit.ago}s before` : ''})`} · died by ${fmt(s.overkill)}`
        : `at ${s.hpBeforePct}%, hit for ${s.killingHit.pctOfMax}% · died by ${fmt(s.overkill)}`;

  const killTip = () => (
    <>
      <TipHead name={hitName} glyph={notLogged ? '?' : null} icon={kbIcon}
        sub={<>{death.boss}{schoolName(kbSchool) && <> · <School mask={kbSchool}>{schoolName(kbSchool)}</School></>}</>} />
      {abilityText?.[death.abilityId] && <p className="desc">{schoolText(abilityText[death.abilityId])}</p>}
      {s && !instakill && (
        <div className="kv">
          <Row a="Killing blow" b={<>{fmt(s.killingHit.size)} <i>· {s.killingHit.pctOfMax}% of max HP</i></>} />
          {s.rot && (
            <Row a="Worn down by" b={<span className="stack">
              <span><School mask={s.rot.school}>{s.rot.name}</School> <i>· rot</i></span>
              <small>{s.rot.hits} hits, {fmt(s.rot.total)} over {s.rot.seconds}s</small></span>} />
          )}
          {s.biggestHit && (
            <Row a="Set up by" b={<span className="stack">
              <span><School mask={s.biggestHit.school}>{s.biggestHit.name}</School> {fmt(s.biggestHit.size)} <i>· {s.biggestHit.pctOfMax}%</i></span>
              <small>{s.biggestHit.times > 1
                ? `${s.biggestHit.times} hits, ${fmt(s.biggestHit.total)} over ${s.biggestHit.over}s`
                : s.biggestHit.ago >= 0.1 ? `${s.biggestHit.ago}s before` : 'same moment'}</small></span>} />
          )}
          <Row a="Health before it" b={<>{fmt(s.maxHp * s.hpBeforePct / 100)} <i>· {s.hpBeforePct}%</i></>} />
          <Row a="Died by" b={fmt(s.overkill)} />
        </div>
      )}
      {instakill && <div className="note warn">Instant kill: the game killed them outright, with no damage to reduce, absorb or heal. Only avoiding the mechanic prevents it.</div>}
      {s?.ignoresImmunity && <div className="note warn">Goes through immunities (Ice Block, Divine Shield…)</div>}
      {s?.ignoresReduction && <div className="note warn">Ignores damage reduction (shields and heals still work)</div>}
      {notLogged && <p>WarcraftLogs recorded no hit or instant kill for this death, so what killed them isn't known and defensives can't be checked against it.</p>}
      {!s && current && !notLogged && <p>No hit with health data was recorded for this death, so defensives can't be checked against it.</p>}
      {(kills > 0 && !notLogged) || (s?.window && !instakill) ? (
        <div className="src">
          {kills > 0 && !notLogged && `Killed ${kills} raider${kills === 1 ? '' : 's'} in these pulls. `}
          {s?.window && !instakill && `Defensives are judged on the last ${Math.round(s.window.fromAgo)}s.`}
        </div>
      ) : null}
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
    const rank = det?.rank;
    const sub = [inf?.kind === 'external' ? 'External' : null,
      inf?.kind === 'potion' ? (rank?.rank ? `${cap(rank.rank)} rank` : rank ? 'rank unknown' : null) : null]
      .filter(Boolean).join(' · ');
    const verdict = !det || !s ? null
      : v === true ? <div className="vd g">✓ Saves them · {fmt(det.amount - s.overkill)} to spare</div>
      : det.why === 'needsTimeline' ? <div className="vd n">Can't tell: the log's health before this death couldn't be read</div>
      : det.why ? <div className="vd b">✗ Doesn't help<small>{cap(whyText(det, hitName) || '')}</small></div>
      : det.amount > 0 ? <div className="vd b">✗ Not enough · {fmt(s.overkill - det.amount)} short</div>
      : null;
    return (
      <>
        <TipHead name={name} icons={icons} sub={sub || null}
          quality={inf?.kind === 'potion' ? qualityArt(rank) : null} />
        {verdict}
        {!det && s && v == null && <div className="vd n">Can't estimate this one (not simple damage reduction, absorb or healing)</div>}
        {!s && <div className="vd n">Off cooldown when they died</div>}
        {det && s && det.amount > 0 && (
          <div className="kv">
            {det.hot
              ? <Row a="Heals before death" b={`${fmt(det.hot.landed ?? det.amount)} of ${fmt(det.hot.full)}`} />
              : heals && fullHeal > det.amount + 1
                ? <Row a="Would heal" b={`${fmt(det.amount)} · all missing`} />
                : <Row a={heals ? 'Would heal' : 'Would prevent'} b={fmt(det.amount)} />}
            {det.hot && withForm[name] && det.hot.landed != null && det.amount > det.hot.landed + 1 && (
              <Row a={`With ${withForm[name]}`} b={fmt(det.amount)} />
            )}
            {det.hot && <Row a="Ticks in time" b={`${det.hot.ticks} of ${det.hot.of}`} />}
            <Row a="They died by" b={fmt(s.overkill)} />
            {det.pressAgo != null && <Row a="Press" b={`${det.pressAgo}s before death`} />}
          </div>
        )}
        {talents.length > 0 && (
          <div className="kv">
            {talents.map((t) => <Row key={`${t.talent}-${t.field}`} a={t.talent} b={TALENT_TEXT(t)} cls="tal" />)}
          </div>
        )}
        {det?.soulwell && <div className="note">Not used in this log, but a Warlock's Soulwell had one for them.</div>}
        {withForm[name] && <div className="note">Needs {withForm[name]}: checked as shifting into it first.</div>}
        <p className="desc">{det?.source === 'log' && det.samples
          ? (inf?.cooldownMs ? `${secs(inf.cooldownMs)} cooldown.` : '')
          : effectText(inf ? inf.effect : effect, inf)}</p>
        {det?.source && <div className="src">{sourceText(det, inf)}</div>}
      </>
    );
  };

  const strip = [];
  if (current) {
    d.active.forEach((a) => strip.push(
      <Tip key={`a-${a.name}`} className="i act" content={() => (
        <>
          <TipHead name={a.name} icons={icons} sub={a.kind === 'external' ? `External${a.by ? ` from ${a.by}` : ''}` : null} />
          <div className="vd gold">Active when they died</div>
          <p className="desc">{effectText(info(a.name)?.effect, info(a.name))}</p>
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
          <TipHead name={c.name} icons={icons} quality={qualityArt(c.rank)}
            sub={c.rank ? (c.rank.rank ? `${cap(c.rank.rank)} rank` : 'rank unknown') : null} />
          <div className="vd n">On cooldown · {c.text}</div>
          <p className="desc">{effectText(info(c.name)?.effect, info(c.name))}</p>
        </>
      )}><Icon name={c.name} icons={icons} quality={qualityArt(c.rank)} />{c.label && <span className="t">{c.label}</span>}</Tip>
    ));
  }
  const saves = s ? Object.values(s.wouldSave || {}).filter((v) => v === true).length : 0;

  return (
    <div className={`fpx-drow${death.isCheatDeath ? ' cheat' : ''}`}>
      <Tip className="kb" content={killTip}>
        <Icon name={notLogged ? '?' : death.abilityName} icon={kbIcon} className="big" />
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
