import React, { useState } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import AnalyzeConfig from './AnalyzeConfig';

// CRA's Jest resolver predates React Router 7's package exports.
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn() }), { virtual: true });

function Picker({ onRaidChange }) {
  const [config, setConfig] = useState({
    selectedRaid: 'manaforge', clientId: '', clientSecret: '', guildName: '',
    server: '', region: 'us', difficulty: '4', startDate: '', endDate: '',
    maxCutoff: '5', enableCheatDeath: false,
  });
  return <AnalyzeConfig config={config} setConfig={setConfig}
    onChange={jest.fn()} onSubmit={jest.fn()}
    onRaidChange={(event) => {
      onRaidChange(event);
      setConfig((previous) => ({ ...previous, selectedRaid: event.target.value }));
    }} />;
}

test('one Season 2 choice combines both raids alongside the existing tiers', () => {
  const onRaidChange = jest.fn();
  render(<Picker onRaidChange={onRaidChange} />);
  const picker = screen.getByRole('region', { name: 'RAID' });
  const seasonTwo = within(picker).getByRole('button', { name: 'Midnight Season 2' });
  const seasonOne = within(picker).getByRole('button', { name: 'Midnight Season 1' });
  expect(within(picker).getAllByRole('button')).toHaveLength(5);
  expect(screen.queryByText(/earlier tiers|previous raids/i)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'The Venomous Abyss' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'The Tidebound Grotto' })).not.toBeInTheDocument();

  fireEvent.click(seasonTwo);
  expect(onRaidChange).toHaveBeenLastCalledWith({
    target: { name: 'selectedRaid', value: 'midnight-s2-all' },
  });
  expect(seasonTwo).toHaveAttribute('aria-pressed', 'true');
  expect(seasonOne).toHaveAttribute('aria-pressed', 'false');
  const lineup = screen.getByRole('region', { name: 'MIDNIGHT SEASON 2' });
  expect(lineup.querySelectorAll('.fpx-boss')).toHaveLength(10);
  expect(within(lineup).getByText("Ula'tek")).toBeInTheDocument();
  expect(within(lineup).getByText('Nymrissa Wavecaller')).toBeInTheDocument();
  expect(within(lineup).getByText("Kith'ix")).toBeInTheDocument();

  fireEvent.click(seasonOne);
  expect(onRaidChange).toHaveBeenLastCalledWith({
    target: { name: 'selectedRaid', value: 'midnight-all' },
  });
  expect(seasonTwo).toHaveAttribute('aria-pressed', 'false');
  expect(seasonOne).toHaveAttribute('aria-pressed', 'true');
  const firstSeasonLineup = screen.getByRole('region', { name: 'MIDNIGHT SEASON 1' });
  expect(firstSeasonLineup.querySelectorAll('.fpx-boss')).toHaveLength(9);
  expect(within(firstSeasonLineup).queryByText('Nymrissa Wavecaller')).not.toBeInTheDocument();

  fireEvent.click(within(picker).getByRole('button', { name: 'Manaforge Omega' }));
  expect(screen.getByRole('region', { name: 'MANAFORGE OMEGA' })
    .querySelectorAll('.fpx-boss')).toHaveLength(8);
});

function BossPicker({ onConfig }) {
  const [config, setConfig] = useState({
    selectedRaid: 'manaforge', selectedBosses: [], clientId: '', clientSecret: '', guildName: '',
    server: '', region: 'us', difficulty: '5', startDate: '', endDate: '',
    maxCutoff: '5', enableCheatDeath: false,
  });
  onConfig(config);
  return <AnalyzeConfig config={config} setConfig={setConfig}
    onChange={jest.fn()} onSubmit={jest.fn()} onRaidChange={jest.fn()} />;
}

test('bosses can be left out of the analysis, never all of them', () => {
  let config;
  render(<BossPicker onConfig={(c) => { config = c; }} />);
  const lineup = screen.getByRole('region', { name: 'MANAFORGE OMEGA' });
  const tile = (name) => within(lineup).getByRole('button', { name });
  // Every boss is in by default; an empty list means all of them.
  lineup.querySelectorAll('.fpx-boss-toggle').forEach((b) => expect(b).toHaveAttribute('aria-pressed', 'true'));
  expect(screen.getByText('All 8 bosses')).toBeInTheDocument();

  fireEvent.click(tile('Dimensius, the All-Devouring'));
  expect(tile('Dimensius, the All-Devouring')).toHaveAttribute('aria-pressed', 'false');
  expect(config.selectedBosses).toEqual([3129, 3131, 3130, 3132, 3122, 3133, 3134]);
  expect(screen.getByText('7 of 8 bosses')).toBeInTheDocument();

  // Only one boss.
  fireEvent.click(screen.getByRole('button', { name: 'Only Nexus-King Salhadaar' }));
  expect(config.selectedBosses).toEqual([3134]);
  // The last boss can't be left out.
  fireEvent.click(tile('Nexus-King Salhadaar'));
  expect(config.selectedBosses).toEqual([3134]);
  expect(tile('Nexus-King Salhadaar')).toHaveAttribute('aria-pressed', 'true');

  // Back to every boss: stored as an empty list.
  fireEvent.click(screen.getByRole('button', { name: 'Select all bosses' }));
  expect(config.selectedBosses).toEqual([]);
});

test('a choice left from another raid reads as every boss', () => {
  let config;
  function Stale() {
    const [c, setC] = useState({ selectedRaid: 'nerubar', selectedBosses: [3134], region: 'us', difficulty: '5',
      clientId: '', clientSecret: '', guildName: '', server: '', startDate: '', endDate: '', maxCutoff: '5' });
    config = c;
    return <AnalyzeConfig config={c} setConfig={setC} onChange={jest.fn()} onSubmit={jest.fn()} onRaidChange={jest.fn()} />;
  }
  render(<Stale />);
  const lineup = screen.getByRole('region', { name: "NERUB'AR PALACE" });
  lineup.querySelectorAll('.fpx-boss-toggle').forEach((b) => expect(b).toHaveAttribute('aria-pressed', 'true'));
  fireEvent.click(within(lineup).getByRole('button', { name: 'Queen Ansurek' }));
  expect(config.selectedBosses).toEqual([2902, 2917, 2898, 2918, 2919, 2920, 2921]);
});

test('every raid lists one encounter ID per boss', () => {
  const { RAID_BOSS_IDS } = require('./AnalyzeConfig');
  Object.values(RAID_BOSS_IDS).forEach(({ bosses, ids }) => {
    expect(ids).toHaveLength(bosses.length);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
