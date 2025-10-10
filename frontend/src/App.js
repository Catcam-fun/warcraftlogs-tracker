import React, { useState } from 'react';
import { Search, AlertCircle, Loader2, Download, Filter, TrendingUp } from 'lucide-react';

export default function WarcraftLogsApp() {
  const [config, setConfig] = useState({
    clientId: '',
    clientSecret: '',
    guildName: 'Do Over',
    server: 'Thrall',
    region: 'us',
    reportZone: '44',
    fightZone: '2810',
    difficulty: '5',
    maxCutoff: '5',
    cutoffDate: '2025-10-10',
    authorFilters: '',
    characterGroups: ''
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [cutoff, setCutoff] = useState(2);
  const [selectedBosses, setSelectedBosses] = useState(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [view, setView] = useState('overview');

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setConfig(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async () => {
    if (!config.clientId || !config.clientSecret || !config.guildName || !config.server) {
      setError('Please fill in all required fields (Client ID, Client Secret, Guild Name, and Server)');
      return;
    }

    setLoading(true);
    setError('');
    setData(null);

    try {
      let characterGroups = {};
      if (config.characterGroups.trim()) {
        try {
          characterGroups = JSON.parse(config.characterGroups);
        } catch (e) {
          throw new Error('Invalid JSON format for character groups');
        }
      }

      const response = await fetch('https://deathwarcraftlogs-api.onrender.com/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...config,
          authorFilters: config.authorFilters.split(',').map(s => s.trim()).filter(Boolean),
          characterGroups
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to fetch data');
      }

      const result = await response.json();
      setData(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleBoss = (boss) => {
    const newSelected = new Set(selectedBosses);
    if (newSelected.has(boss)) {
      newSelected.delete(boss);
    } else {
      newSelected.add(boss);
    }
    setSelectedBosses(newSelected);
  };

  const getFilteredStats = () => {
    if (!data) return [];

    const stats = [];
    const eventsAll = data.events;
    const pullsMap = data.pullParticipation;
    const bossPart = data.bossParticipation;

    for (const player of Object.keys(eventsAll)) {
      const evs = eventsAll[player].filter(
        ev => ev.rankWithinPull <= cutoff && 
        (selectedBosses.size === 0 || selectedBosses.has(ev.boss))
      );
      
      if (!evs.length) continue;

      let pulls = 0;
      if (selectedBosses.size === 0) {
        pulls = pullsMap[player]?.length || 0;
      } else {
        for (const boss of selectedBosses) {
          if (bossPart[boss]?.[player]) {
            pulls += bossPart[boss][player].length;
          }
        }
      }

      const rate = pulls > 0 ? (evs.length / pulls * 100) : 0;
      
      if (searchQuery && !player.toLowerCase().includes(searchQuery.toLowerCase())) {
        continue;
      }

      stats.push({ player, deaths: evs.length, pulls, rate });
    }

    return stats.sort((a, b) => b.rate - a.rate || b.deaths - a.deaths);
  };

  const getOverviewData = () => {
    if (!data) return { bosses: [], players: [], grid: {} };

    const bosses = Object.keys(data.bossParticipation).sort();
    const players = Object.keys(data.events).sort();
    const grid = {};

    players.forEach(player => {
      grid[player] = {};
      bosses.forEach(boss => {
        const bossPulls = data.bossParticipation[boss]?.[player]?.length || 0;
        const bossDeaths = data.events[player]?.filter(
          ev => ev.boss === boss && ev.rankWithinPull <= cutoff
        ).length || 0;
        const rate = bossPulls > 0 ? (bossDeaths / bossPulls * 100) : null;
        grid[player][boss] = { deaths: bossDeaths, pulls: bossPulls, rate };
      });

      const totalPulls = data.pullParticipation[player]?.length || 0;
      const totalDeaths = data.events[player]?.filter(
        ev => ev.rankWithinPull <= cutoff
      ).length || 0;
      grid[player].overall = {
        deaths: totalDeaths,
        pulls: totalPulls,
        rate: totalPulls > 0 ? (totalDeaths / totalPulls * 100) : null
      };
    });

    return { bosses, players, grid };
  };

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)', color: '#e2e8f0', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px' }}>
        <div style={{ background: 'rgba(30, 41, 59, 0.6)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '32px', marginBottom: '24px', border: '1px solid rgba(148, 163, 184, 0.1)' }}>
          <h1 style={{ margin: '0 0 8px', fontSize: '32px', fontWeight: '700', background: 'linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            WarcraftLogs Death Tracker
          </h1>
          <p style={{ color: '#94a3b8', margin: 0 }}>Analyze raid deaths and performance metrics</p>
        </div>

        {!data && (
          <div style={{ background: 'rgba(30, 41, 59, 0.6)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '32px', marginBottom: '24px', border: '1px solid rgba(148, 163, 184, 0.1)' }}>
            <h2 style={{ margin: '0 0 24px', fontSize: '20px', fontWeight: '600' }}>Configuration</h2>
            
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '20px' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Client ID (V2 API) *
                </label>
                <input
                  type="text"
                  name="clientId"
                  value={config.clientId}
                  onChange={handleInputChange}
                  placeholder="Your V2 Client ID"
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Client Secret (V2 API) *
                </label>
                <input
                  type="password"
                  name="clientSecret"
                  value={config.clientSecret}
                  onChange={handleInputChange}
                  placeholder="Your V2 Client Secret"
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Guild Name *
                </label>
                <input
                  type="text"
                  name="guildName"
                  value={config.guildName}
                  onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Server *
                </label>
                <input
                  type="text"
                  name="server"
                  value={config.server}
                  onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Region *
                </label>
                <select
                  name="region"
                  value={config.region}
                  onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                >
                  <option value="us">US</option>
                  <option value="eu">EU</option>
                  <option value="kr">KR</option>
                  <option value="tw">TW</option>
                  <option value="cn">CN</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Report Zone ID
                </label>
                <input
                  type="text"
                  name="reportZone"
                  value={config.reportZone}
                  onChange={handleInputChange}
                  placeholder="e.g., 44"
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Fight Zone ID
                </label>
                <input
                  type="text"
                  name="fightZone"
                  value={config.fightZone}
                  onChange={handleInputChange}
                  placeholder="e.g., 2810"
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Difficulty
                </label>
                <select
                  name="difficulty"
                  value={config.difficulty}
                  onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                >
                  <option value="3">Normal</option>
                  <option value="4">Heroic</option>
                  <option value="5">Mythic</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Cutoff Date
                </label>
                <input
                  type="date"
                  name="cutoffDate"
                  value={config.cutoffDate}
                  onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Max Deaths to Track
                </label>
                <input
                  type="number"
                  name="maxCutoff"
                  value={config.maxCutoff}
                  onChange={handleInputChange}
                  min="1"
                  max="10"
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div style={{ gridColumn: '1 / -1' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Author Filters (comma-separated)
                </label>
                <input
                  type="text"
                  name="authorFilters"
                  value={config.authorFilters}
                  onChange={handleInputChange}
                  placeholder="e.g., Player1, Player2"
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                />
              </div>

              <div style={{ gridColumn: '1 / -1' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Character Groups (JSON format)
                </label>
                <textarea
                  name="characterGroups"
                  value={config.characterGroups}
                  onChange={handleInputChange}
                  placeholder='{"MainName": ["Alt1", "Alt2"]}'
                  rows="3"
                  style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', fontFamily: 'monospace', resize: 'vertical' }}
                />
              </div>
            </div>

            {error && (
              <div style={{ marginTop: '20px', padding: '12px 16px', background: '#7f1d1d', border: '1px solid #991b1b', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <AlertCircle size={20} />
                <span>{error}</span>
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={loading}
              style={{ marginTop: '24px', padding: '12px 24px', background: 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)', border: 'none', borderRadius: '8px', color: 'white', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1, display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              {loading ? (
                <>
                  <Loader2 size={20} className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} />
                  Analyzing...
                </>
              ) : (
                <>
                  <Search size={20} />
                  Analyze Reports
                </>
              )}
            </button>
          </div>
        )}

        {data && (
          <div>
            <div style={{ background: 'rgba(30, 41, 59, 0.6)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '20px', marginBottom: '24px', border: '1px solid rgba(148, 163, 184, 0.1)' }}>
              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '16px' }}>
                <button
                  onClick={() => setView('overview')}
                  style={{ padding: '8px 16px', background: view === 'overview' ? '#3b82f6' : '#334155', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
                >
                  Overview
                </button>
                <button
                  onClick={() => setView('players')}
                  style={{ padding: '8px 16px', background: view === 'players' ? '#3b82f6' : '#334155', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
                >
                  Players
                </button>
                <button
                  onClick={() => { setData(null); setError(''); }}
                  style={{ padding: '8px 16px', background: '#334155', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '14px', fontWeight: '500', marginLeft: 'auto' }}
                >
                  New Analysis
                </button>
              </div>

              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                <label style={{ fontSize: '14px', color: '#cbd5e1' }}>Deaths to count:</label>
                <select
                  value={cutoff}
                  onChange={(e) => setCutoff(parseInt(e.target.value))}
                  style={{ padding: '8px 12px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                >
                  {[...Array(data.meta.maxCutoff)].map((_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {i + 1} {i === 0 ? 'Death' : 'Deaths'}
                    </option>
                  ))}
                </select>

                <div style={{ marginLeft: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Filter size={16} />
                  <span style={{ fontSize: '14px', color: '#cbd5e1' }}>Boss filters:</span>
                </div>
                {Object.keys(data.bossParticipation).sort().map(boss => (
                  <button
                    key={boss}
                    onClick={() => toggleBoss(boss)}
                    style={{ padding: '6px 12px', background: selectedBosses.has(boss) ? '#3b82f6' : '#334155', border: '1px solid ' + (selectedBosses.has(boss) ? '#60a5fa' : '#475569'), borderRadius: '16px', color: 'white', cursor: 'pointer', fontSize: '13px' }}
                  >
                    {boss}
                  </button>
                ))}
              </div>

              {view === 'players' && (
                <div style={{ marginTop: '16px' }}>
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search players..."
                    style={{ width: '100%', maxWidth: '300px', padding: '8px 12px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                  />
                </div>
              )}
            </div>

            {view === 'overview' && (() => {
              const { bosses, players, grid } = getOverviewData();
              return (
                <div style={{ background: 'rgba(30, 41, 59, 0.6)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '20px', border: '1px solid rgba(148, 163, 184, 0.1)', overflowX: 'auto' }}>
                  <h2 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: '600' }}>Death Rate Overview</h2>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                    <thead>
                      <tr style={{ background: '#1e293b' }}>
                        <th style={{ padding: '10px', textAlign: 'left', borderBottom: '2px solid #334155', position: 'sticky', left: 0, background: '#1e293b', zIndex: 1 }}>Player</th>
                        {bosses.map(boss => (
                          <th key={boss} style={{ padding: '10px', textAlign: 'center', borderBottom: '2px solid #334155', minWidth: '80px' }}>{boss}</th>
                        ))}
                        <th style={{ padding: '10px', textAlign: 'center', borderBottom: '2px solid #334155', fontWeight: '700', minWidth: '80px' }}>Overall</th>
                      </tr>
                    </thead>
                    <tbody>
                      {players.map(player => (
                        <tr key={player} style={{ borderBottom: '1px solid #334155' }}>
                          <td style={{ padding: '10px', fontWeight: '600', position: 'sticky', left: 0, background: 'rgba(30, 41, 59, 0.95)', zIndex: 1 }}>{player}</td>
                          {bosses.map(boss => {
                            const cellData = grid[player][boss];
                            return (
                              <td key={boss} style={{ padding: '10px', textAlign: 'center' }}>
                                {cellData.rate !== null ? (
                                  <span style={{ color: cellData.rate > 50 ? '#f87171' : cellData.rate > 25 ? '#fbbf24' : '#34d399', fontWeight: '600' }}>
                                    {cellData.rate.toFixed(1)}%
                                  </span>
                                ) : (
                                  <span style={{ color: '#475569' }}>—</span>
                                )}
                              </td>
                            );
                          })}
                          <td style={{ padding: '10px', textAlign: 'center', fontWeight: '700' }}>
                            {grid[player].overall.rate !== null ? (
                              <span style={{ color: grid[player].overall.rate > 50 ? '#f87171' : grid[player].overall.rate > 25 ? '#fbbf24' : '#34d399' }}>
                                {grid[player].overall.rate.toFixed(1)}%
                              </span>
                            ) : (
                              <span style={{ color: '#475569' }}>—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })()}

            {view === 'players' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {getFilteredStats().map(({ player, deaths, pulls, rate }) => (
                  <div key={player} style={{ background: 'rgba(30, 41, 59, 0.6)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '20px', border: '1px solid rgba(148, 163, 184, 0.1)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                      <div>
                        <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '600' }}>{player}</h3>
                        <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#94a3b8' }}>
                          {deaths} deaths / {pulls} pulls
                        </p>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: '28px', fontWeight: '700', color: rate > 50 ? '#f87171' : rate > 25 ? '#fbbf24' : '#34d399' }}>
                          {rate.toFixed(1)}%
                        </div>
                      </div>
                    </div>
                    
                    <div style={{ fontSize: '13px', color: '#cbd5e1' }}>
                      {Object.entries(
                        data.events[player]
                          .filter(ev => ev.rankWithinPull <= cutoff && (selectedBosses.size === 0 || selectedBosses.has(ev.boss)))
                          .reduce((acc, ev) => {
                            acc[ev.boss] = (acc[ev.boss] || 0) + 1;
                            return acc;
                          }, {})
                      )
                        .sort((a, b) => b[1] - a[1])
                        .map(([boss, count]) => `${boss}: ${count}`)
                        .join(' • ')}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .animate-spin {
          animation: spin 1s linear infinite;
        }
      `}</style>
    </div>
  );
}