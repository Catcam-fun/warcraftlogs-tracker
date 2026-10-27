import React, { useState } from 'react';
import { Icon, InfoTip, Tip, TipHead, schoolText } from './DeathRow';

const TOP = 5;

/* The Abilities tab: one card per boss ability (abilityStats.js), most deaths first, with the players who
   died to it ranked inside. Rank by deaths or by rate (deaths to it over their pulls on that boss);
   the choice applies to every card. */
export default function AbilityView({ abilities, abilityIcons, abilityText, classColors, cutoff }) {
  const [sortBy, setSortBy] = useState('deaths');
  const [open, setOpen] = useState(() => new Set());
  const toggle = (key) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  const ranked = (players) => (sortBy === 'deaths' ? players : [...players].sort(
    (x, y) => y.rate - x.rate || y.deaths - x.deaths || x.player.localeCompare(y.player)));
  const head = (key, label) => (
    <button type="button" className={`sortc${sortBy === key ? ' on' : ''}`} onClick={() => setSortBy(key)}
      aria-pressed={sortBy === key}>{label}{sortBy === key ? ' ▼' : ''}</button>
  );

  return (
    <>
      <div className="fpx-tabnote">
        What killed them, for the deaths that count: the first {cutoff} of each pull, never inside a wipe, with the
        filters above.
        <InfoTip>
          <p>Each card is one boss ability, the killing blow of those deaths. Players are ranked by how many times
            it killed them.</p>
          <p><b>Rate</b>: those deaths divided by their pulls on that boss, so a player with fewer pulls isn't
            ranked lower just for that. Click Deaths or Rate to rank by it.</p>
          <p>Cheat deaths and deaths the log has no killing blow for aren't counted.</p>
        </InfoTip>
      </div>
      {abilities.length === 0 ? (
        <div className="fpx-abempty">No deaths that count, with a killing blow in the log, for these filters.</div>
      ) : (
        <div className="fpx-abgrid">
          {abilities.map((a) => {
            const icon = abilityIcons?.[a.abilityId];
            const text = abilityText?.[a.abilityId];
            const all = open.has(a.key);
            const players = ranked(a.players);
            const shown = all ? players : players.slice(0, TOP);
            const top = players[0];
            // Hovering the ability (icon or name) shows the game's description of it.
            const spellTip = () => (
              <>
                <TipHead name={a.name} icon={icon} sub={a.boss} />
                {text ? <p className="desc">{schoolText(text)}</p> : <p className="desc">No description in the game data.</p>}
              </>
            );
            return (
              <div key={a.key} className="fpx-abcard">
                <div className="fpx-abhead">
                  <Tip className="abi" content={spellTip}><Icon name={a.name} icon={icon} className="big" /></Tip>
                  <span className="t">
                    <Tip className="nm" content={spellTip}>{a.name}</Tip>
                    <span className="tot">
                      {a.boss} · <b>{a.deaths}</b> death{a.deaths !== 1 ? 's' : ''} · {a.players.length} player{a.players.length !== 1 ? 's' : ''}
                    </span>
                  </span>
                </div>
                <div className="fpx-abrow h">
                  <span className="pl">Player</span>
                  {head('deaths', 'Deaths')}
                  <span>Pulls</span>
                  {head('rate', 'Rate')}
                </div>
                {shown.map((p) => (
                  <div key={p.player} className={`fpx-abrow${p === top ? ' lead' : ''}`}>
                    <span className="pl" style={{ color: classColors[p.class] || 'var(--fpx-ink)' }}>{p.player}</span>
                    <span className="n">{p.deaths}</span>
                    <span className="pu">{p.pulls}</span>
                    <span className="rt">{p.rate.toFixed(1)}%</span>
                  </div>
                ))}
                {players.length > TOP && (
                  <button type="button" className="fpx-abmore" onClick={() => toggle(a.key)}>
                    {all ? 'Show top 5' : `Show all ${players.length}`}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
