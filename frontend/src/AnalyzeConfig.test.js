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
  expect(lineup.querySelectorAll('.fpx-boss')).toHaveLength(9);
  expect(within(lineup).getByText("Ula'tek")).toBeInTheDocument();
  expect(within(lineup).getByText('Nymrissa Wavecaller')).toBeInTheDocument();

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
