import React, { useState, useEffect } from 'react';
import { Search, AlertCircle, Loader2, Filter, ChevronDown, ChevronRight, ExternalLink, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

export default function WarcraftLogsApp() {
  const [config, setConfig] = useState({
    clientId: '',
    clientSecret: '',
    guildName: '',
    server: '',
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
  const [loadingStage, setLoadingStage] = useState('');
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [cutoff, setCutoff] = useState(2);
  const [selectedBosses, setSelectedBosses] = useState(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [view, setView] = useState('overview');
  const [expandedPlayers, setExpandedPlayers] = useState(new Set());
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });

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
    setLoadingStage('Initializing...');
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

      const payload = {
        ...config,
        authorFilters: config.authorFilters.split(',').map(s => s.trim()).filter(Boolean),
        characterGroups
      };

      // Use EventSource for SSE
      const eventSource = new EventSource(
        'https://deathwarcraftlogs-api.onrender.com/api/analyze?' + 
        new URLSearchParams({ config: JSON.stringify(payload) })
      );

      // Actually, EventSource doesn't support POST, so we'll use fetch with streaming
      const response = await fetch('https://deathwarcraftlogs-api.onrender.com/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error('Failed to connect to server');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            
            if (data.error) {
              throw new Error(data.error);
            } else if (data.message) {
              setLoadingStage(data.message);
            } else if (data.result) {
              setData(data.result);
              setLoadingStage('');
              setLoading(false);
            }
          }
        }
      }
    } catch (err) {
      setError(err.message);
      setLoadingStage('');
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

  const togglePlayer = (player) => {
    const newExpanded = new Set(expandedPlayers);
    if (newExpanded.has(player)) {
      newExpanded.delete(player);
    } else {
      newExpanded.add(player);
    }
    setExpandedPlayers(newExpanded);
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
        (selectedBosses.size === 0 || selectedBosses.has(ev.boss)) &&
        ev.abilityName && ev.abilityName !== 'Unknown'
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

      const deathsByBoss = {};
      evs.forEach(ev => {
        if (!deathsByBoss[ev.boss]) {
          deathsByBoss[ev.boss] = [];
        }
        deathsByBoss[ev.boss].push(ev);
      });

      const topAbilitiesByBoss = {};
      Object.keys(deathsByBoss).forEach(boss => {
        const abilityCounts = {};
        deathsByBoss[boss].forEach(death => {
          const ability = death.abilityName || 'Unknown';
          if (ability !== 'Unknown') {
            abilityCounts[ability] = (abilityCounts[ability] || 0) + 1;
          }
        });
        topAbilitiesByBoss[boss] = Object.entries(abilityCounts)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5);
      });

      stats.push({ 
        player, 
        deaths: evs.length, 
        pulls, 
        rate,
        deathsByBoss,
        topAbilitiesByBoss
      });
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

  const sortOverviewData = (bosses, players, grid, key) => {
    const sorted = [...players].sort((a, b) => {
      let aVal, bVal;

      if (key === 'player') {
        return sortConfig.direction === 'asc' 
          ? a.localeCompare(b) 
          : b.localeCompare(a);
      } else if (key === 'overall') {
        aVal = grid[a].overall.rate ?? -1;
        bVal = grid[b].overall.rate ?? -1;
      } else {
        aVal = grid[a][key]?.rate ?? -1;
        bVal = grid[b][key]?.rate ?? -1;
      }

      if (sortConfig.direction === 'asc') {
        return aVal - bVal;
      } else {
        return bVal - aVal;
      }
    });

    return sorted;
  };

  const handleSort = (key) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
    }));
  };

  const getSortIcon = (key) => {
    if (sortConfig.key !== key) return <ArrowUpDown size={14} />;
    return sortConfig.direction === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} />;
  };

  const formatTimestamp = (absTs) => {
    const date = new Date(absTs);
    return date.toLocaleString('en-US', { 
      month: 'short', 
      day: 'numeric', 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  };

  const getWCLLink = (reportId, fightId) => {
    return `https://www.warcraftlogs.com/reports/${reportId}#fight=${fightId}&type=deaths`;
  };

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #4a5568 0%, #2d3748 100%)', color: '#e2e8f0', fontFamily: 'system-ui, -apple-system, sans-serif', position: 'relative', overflow: 'hidden' }}>
      {/* Halloween Decorations */}
      {/* Spider Web - Top Left */}
      <div style={{ position: 'fixed', top: 0, left: 0, width: '200px', height: '200px', opacity: 0.2, pointerEvents: 'none', zIndex: 1 }}>
        <svg viewBox="0 0 200 200" style={{ width: '100%', height: '100%' }}>
          <path d="M0,0 L100,100 M0,20 L100,100 M0,40 L100,100 M0,60 L100,100 M0,80 L100,100" stroke="#fff" strokeWidth="1" fill="none"/>
          <path d="M0,0 L100,100 M20,0 L100,100 M40,0 L100,100 M60,0 L100,100 M80,0 L100,100" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="60" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="40" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="20" stroke="#fff" strokeWidth="1" fill="none"/>
        </svg>
      </div>
      
      {/* Spider Web - Top Right */}
      <div style={{ position: 'fixed', top: 0, right: 0, width: '200px', height: '200px', opacity: 0.2, pointerEvents: 'none', zIndex: 1, transform: 'scaleX(-1)' }}>
        <svg viewBox="0 0 200 200" style={{ width: '100%', height: '100%' }}>
          <path d="M0,0 L100,100 M0,20 L100,100 M0,40 L100,100 M0,60 L100,100 M0,80 L100,100" stroke="#fff" strokeWidth="1" fill="none"/>
          <path d="M0,0 L100,100 M20,0 L100,100 M40,0 L100,100 M60,0 L100,100 M80,0 L100,100" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="60" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="40" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="20" stroke="#fff" strokeWidth="1" fill="none"/>
        </svg>
      </div>

      {/* Flying Bats */}
      <div style={{ position: 'fixed', top: '15%', right: '20%', fontSize: '32px', opacity: 0.6, animation: 'float 6s ease-in-out infinite', pointerEvents: 'none', zIndex: 1 }}>
        🦇
      </div>
      <div style={{ position: 'fixed', top: '25%', left: '15%', fontSize: '28px', opacity: 0.5, animation: 'float 8s ease-in-out infinite 2s', pointerEvents: 'none', zIndex: 1 }}>
        🦇
      </div>
      <div style={{ position: 'fixed', top: '40%', right: '10%', fontSize: '24px', opacity: 0.4, animation: 'float 7s ease-in-out infinite 4s', pointerEvents: 'none', zIndex: 1 }}>
        🦇
      </div>

      {/* Pumpkins in corners */}
      <div style={{ position: 'fixed', top: '20px', left: '20px', fontSize: '48px', opacity: 0.7, pointerEvents: 'none', zIndex: 1 }}>
        🎃
      </div>
      <div style={{ position: 'fixed', top: '20px', right: '20px', fontSize: '48px', opacity: 0.7, pointerEvents: 'none', zIndex: 1 }}>
        🎃
      </div>

      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px', position: 'relative', zIndex: 2 }}>
        <div style={{ background: 'rgba(74, 85, 104, 0.4)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '32px', marginBottom: '24px', border: '1px solid rgba(203, 213, 225, 0.1)' }}>
          <h1 style={{ margin: '0 0 8px', fontSize: '32px', fontWeight: '700', color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: '12px', justifyContent: 'center' }}>
            <span>🎃</span>
            WarcraftLogs Death Tracker
            <span>💀</span>
          </h1>
          <p style={{ color: '#cbd5e1', margin: 0, textAlign: 'center' }}>Analyze raid deaths and performance metrics 👻</p>
        </div>

        {loading && (
          <div style={{ 
            position: 'fixed', 
            top: 0, 
            left: 0, 
            right: 0, 
            bottom: 0, 
            background: 'rgba(45, 55, 72, 0.98)', 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'center', 
            zIndex: 9999,
            backdropFilter: 'blur(8px)'
          }}>
            <div style={{ textAlign: 'center', maxWidth: '500px', padding: '40px' }}>
              <div style={{ 
                width: '80px', 
                height: '80px', 
                border: '4px solid rgba(203, 213, 225, 0.2)', 
                borderTop: '4px solid #f97316',
                borderRadius: '50%',
                animation: 'spin 1s linear infinite',
                margin: '0 auto 24px'
              }} />
              <h2 style={{ margin: '0 0 16px', fontSize: '24px', fontWeight: '600', color: '#e2e8f0' }}>
                Analyzing Reports
              </h2>
              <div style={{ 
                padding: '16px 20px', 
                background: 'rgba(74, 85, 104, 0.4)', 
                borderRadius: '8px',
                border: '1px solid rgba(203, 213, 225, 0.2)',
                marginBottom: '16px',
                minHeight: '60px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <p style={{ 
                  margin: 0, 
                  fontSize: '15px', 
                  color: '#f97316', 
                  fontWeight: '500',
                  lineHeight: '1.6'
                }}>
                  {loadingStage || 'Starting analysis...'}
                </p>
              </div>
              <p style={{ color: '#94a3b8', fontSize: '13px', margin: '0', lineHeight: '1.6' }}>
                Processing data from WarcraftLogs...<br />
                This may take a while
              </p>
            </div>
          </div>
        )}

        {!data && (
          <div style={{ background: 'rgba(74, 85, 104, 0.4)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '32px', marginBottom: '24px', border: '1px solid rgba(203, 213, 225, 0.1)' }}>
            <h2 style={{ margin: '0 0 32px', fontSize: '20px', fontWeight: '600' }}>Configuration</h2>
            
            {/* API Credentials Info Box */}
            <div style={{ marginBottom: '28px', padding: '16px 20px', background: 'rgba(249, 115, 22, 0.15)', border: '1px solid rgba(249, 115, 22, 0.4)', borderRadius: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'start', gap: '12px' }}>
                <div style={{ fontSize: '20px' }}>🎃</div>
                <div>
                  <h3 style={{ margin: '0 0 8px', fontSize: '15px', fontWeight: '600', color: '#f97316' }}>
                    Need API Credentials?
                  </h3>
                  <p style={{ margin: '0 0 8px', fontSize: '13px', color: '#e2e8f0', lineHeight: '1.6' }}>
                    You need a WarcraftLogs V2 API Client ID and Secret to use this tool.
                  </p>
                  <ol style={{ margin: '8px 0 0 16px', padding: 0, fontSize: '13px', color: '#e2e8f0', lineHeight: '1.8' }}>
                    <li>Go to <a href="https://www.warcraftlogs.com/api/clients/" target="_blank" rel="noopener noreferrer" style={{ color: '#f97316', textDecoration: 'underline' }}>WarcraftLogs API Clients</a></li>
                    <li>Click "Create a Client"</li>
                    <li>Enter a name (e.g., "Death Tracker")</li>
                    <li>For redirect URL, enter the website URL or just use: <code style={{ background: '#2d3748', padding: '2px 6px', borderRadius: '4px', fontSize: '12px' }}>http://localhost</code></li>
                    <li><strong>Do NOT check</strong> the "Public Client" box</li>
                    <li>Click "Create" and copy your Client ID and Client Secret</li>
                  </ol>
                </div>
              </div>
            </div>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
              {/* Row 1 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                    Client ID (V2 API) *
                  </label>
                  <input
                    type="text"
                    name="clientId"
                    value={config.clientId}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
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
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                </div>
              </div>

              {/* Row 2 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                    Guild Name *
                  </label>
                  <input
                    type="text"
                    name="guildName"
                    value={config.guildName}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b', lineHeight: '1.4' }}>
                    Examples: Do Over, Complexity Limit, Method
                  </p>
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
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b', lineHeight: '1.4' }}>
                    Remove spaces/apostrophes - Examples: Thrall, Area52, TwistingNether
                  </p>
                </div>
              </div>

              {/* Row 3 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                    Region *
                  </label>
                  <select
                    name="region"
                    value={config.region}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
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
                    Difficulty *
                  </label>
                  <select
                    name="difficulty"
                    value={config.difficulty}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                  >
                    <option value="3">Normal</option>
                    <option value="4">Heroic</option>
                    <option value="5">Mythic</option>
                  </select>
                </div>
              </div>

              {/* Row 4 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                    Report Zone ID
                  </label>
                  <input
                    type="text"
                    name="reportZone"
                    value={config.reportZone}
                    onChange={handleInputChange}
                    placeholder="44"
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b', lineHeight: '1.4' }}>
                    The raid zone ID (e.g., 44 for Manaforge Omega) - find in WarcraftLogs URLs
                  </p>
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
                    placeholder="2810"
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b', lineHeight: '1.4' }}>
                    Same for entire raid (e.g., 2810 for Manaforge Omega) - matches Report Zone
                  </p>
                </div>
              </div>

              {/* Row 5 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                    Cutoff Date
                  </label>
                  <input
                    type="date"
                    name="cutoffDate"
                    value={config.cutoffDate}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b', lineHeight: '1.4' }}>
                    Only analyze reports before this date
                  </p>
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
                    placeholder="5"
                    style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b', lineHeight: '1.4' }}>
                    Track only the first X deaths per pull (1-10)
                  </p>
                </div>
              </div>

              {/* Row 6 - Author Filters */}
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Author Filters <span style={{ fontSize: '12px', color: '#64748b', fontWeight: '400' }}>(optional, comma-separated)</span>
                </label>
                <input
                  type="text"
                  name="authorFilters"
                  value={config.authorFilters}
                  onChange={handleInputChange}
                  placeholder="PlayerName1, PlayerName2, PlayerName3"
                  style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', boxSizing: 'border-box' }}
                />
                <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b', lineHeight: '1.4' }}>
                  Only analyze reports uploaded by these players
                </p>
              </div>

              {/* Row 7 - Character Groups */}
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: '#cbd5e1' }}>
                  Character Groups <span style={{ fontSize: '12px', color: '#64748b', fontWeight: '400' }}>(optional, JSON format)</span>
                </label>
                <textarea
                  name="characterGroups"
                  value={config.characterGroups}
                  onChange={handleInputChange}
                  placeholder='{"MainCharacter": ["AltName1", "AltName2"], "AnotherMain": ["TheirAlt"]}'
                  rows="3"
                  style={{ width: '100%', padding: '12px 16px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px', fontFamily: 'monospace', resize: 'vertical', boxSizing: 'border-box' }}
                />
                <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#64748b', lineHeight: '1.4' }}>
                  Merge alt characters with their mains for combined statistics
                </p>
              </div>
            </div>

            {error && (
              <div style={{ marginTop: '24px', padding: '12px 16px', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <AlertCircle size={20} />
                <span>{error}</span>
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={loading}
              style={{ marginTop: '32px', padding: '14px 28px', background: loading ? '#718096' : '#f97316', border: 'none', borderRadius: '8px', color: 'white', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1, display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              {loading ? (
                <>
                  <Loader2 size={20} style={{ animation: 'spin 1s linear infinite' }} />
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
            <div style={{ background: 'rgba(74, 85, 104, 0.4)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '20px', marginBottom: '24px', border: '1px solid rgba(203, 213, 225, 0.1)' }}>
              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '16px' }}>
                <button
                  onClick={() => setView('overview')}
                  style={{ padding: '8px 16px', background: view === 'overview' ? '#f97316' : '#718096', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
                >
                  Overview
                </button>
                <button
                  onClick={() => setView('players')}
                  style={{ padding: '8px 16px', background: view === 'players' ? '#f97316' : '#718096', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
                >
                  Players
                </button>
                <button
                  onClick={() => { setData(null); setError(''); setExpandedPlayers(new Set()); setSortConfig({ key: null, direction: 'asc' }); }}
                  style={{ padding: '8px 16px', background: '#718096', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '14px', fontWeight: '500', marginLeft: 'auto' }}
                >
                  New Analysis
                </button>
              </div>

              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                <label style={{ fontSize: '14px', color: '#cbd5e1' }}>Deaths to count:</label>
                <select
                  value={cutoff}
                  onChange={(e) => setCutoff(parseInt(e.target.value))}
                  style={{ padding: '8px 12px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
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
                    style={{ padding: '6px 12px', background: selectedBosses.has(boss) ? '#f97316' : '#718096', border: '1px solid ' + (selectedBosses.has(boss) ? '#f97316' : '#94a3b8'), borderRadius: '16px', color: 'white', cursor: 'pointer', fontSize: '13px' }}
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
                    style={{ width: '100%', maxWidth: '300px', padding: '8px 12px', background: '#2d3748', border: '1px solid #4a5568', borderRadius: '8px', color: '#e2e8f0', fontSize: '14px' }}
                  />
                </div>
              )}
            </div>

            {view === 'overview' && (() => {
              const { bosses, players, grid } = getOverviewData();
              const sortedPlayers = sortConfig.key ? sortOverviewData(bosses, players, grid, sortConfig.key) : players;
              
              return (
                <div style={{ background: 'rgba(74, 85, 104, 0.4)', backdropFilter: 'blur(10px)', borderRadius: '16px', padding: '20px', border: '1px solid rgba(203, 213, 225, 0.1)', overflowX: 'auto' }}>
                  <h2 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: '600' }}>Death Rate Overview</h2>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                    <thead>
                      <tr style={{ background: '#718096' }}>
                        <th 
                          onClick={() => handleSort('player')}
                          style={{ padding: '10px', textAlign: 'left', borderBottom: '2px solid #94a3b8', position: 'sticky', left: 0, background: '#718096', zIndex: 2, cursor: 'pointer', userSelect: 'none' }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            Player {getSortIcon('player')}
                          </div>
                        </th>
                        {bosses.map(boss => (
                          <th 
                            key={boss} 
                            onClick={() => handleSort(boss)}
                            style={{ padding: '10px', textAlign: 'center', borderBottom: '2px solid #94a3b8', minWidth: '80px', cursor: 'pointer', userSelect: 'none' }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                              {boss} {getSortIcon(boss)}
                            </div>
                          </th>
                        ))}
                        <th 
                          onClick={() => handleSort('overall')}
                          style={{ padding: '10px', textAlign: 'center', borderBottom: '2px solid #94a3b8', fontWeight: '700', minWidth: '80px', cursor: 'pointer', userSelect: 'none' }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                            Overall {getSortIcon('overall')}
                          </div>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedPlayers.map(player => (
                        <tr key={player} style={{ borderBottom: '1px solid #718096' }}>
                          <td style={{ padding: '10px', fontWeight: '600', position: 'sticky', left: 0, background: 'rgba(74, 85, 104, 0.95)', zIndex: 1 }}>{player}</td>
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
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {getFilteredStats().map(({ player, deaths, pulls, rate, deathsByBoss, topAbilitiesByBoss }) => {
                  const isExpanded = expandedPlayers.has(player);
                  return (
                    <div key={player} style={{ background: 'rgba(74, 85, 104, 0.4)', backdropFilter: 'blur(10px)', borderRadius: '12px', border: '1px solid rgba(203, 213, 225, 0.1)', overflow: 'hidden' }}>
                      <div 
                        onClick={() => togglePlayer(player)}
                        style={{ 
                          padding: '16px 20px', 
                          display: 'flex', 
                          justifyContent: 'space-between', 
                          alignItems: 'center', 
                          cursor: 'pointer',
                          background: isExpanded ? 'rgba(74, 85, 104, 0.6)' : 'transparent',
                          transition: 'background 0.2s'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                          {isExpanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
                          <div>
                            <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '600' }}>{player}</h3>
                            <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#94a3b8' }}>
                              {deaths} deaths / {pulls} pulls
                            </p>
                          </div>
                        </div>
                        <div style={{ fontSize: '28px', fontWeight: '700', color: rate > 50 ? '#f87171' : rate > 25 ? '#fbbf24' : '#34d399' }}>
                          {rate.toFixed(1)}%
                        </div>
                      </div>

                      {isExpanded && (
                        <div style={{ padding: '0 20px 20px', borderTop: '1px solid rgba(148, 163, 184, 0.1)' }}>
                          {Object.entries(deathsByBoss).map(([boss, bossDeaths]) => (
                            <div key={boss} style={{ marginTop: '16px' }}>
                              <h4 style={{ margin: '0 0 12px', fontSize: '16px', fontWeight: '600', color: '#f97316' }}>
                                {boss} ({bossDeaths.length} deaths)
                              </h4>
                              
                              {topAbilitiesByBoss[boss] && topAbilitiesByBoss[boss].length > 0 && (
                                <div style={{ marginBottom: '12px', padding: '8px 12px', background: 'rgba(74, 85, 104, 0.3)', borderRadius: '6px' }}>
                                  <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Top Abilities:</div>
                                  <div style={{ fontSize: '13px', color: '#cbd5e1' }}>
                                    {topAbilitiesByBoss[boss].map(([ability, count], idx) => (
                                      <span key={ability}>
                                        {idx + 1}. {ability} ({count}){idx < topAbilitiesByBoss[boss].length - 1 ? ' • ' : ''}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}

                              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                {bossDeaths
                                  .filter(death => death.abilityName && death.abilityName !== 'Unknown')
                                  .map((death, idx) => (
                                  <div key={idx} style={{ 
                                    display: 'flex', 
                                    justifyContent: 'space-between', 
                                    alignItems: 'center',
                                    padding: '10px 12px',
                                    background: 'rgba(45, 55, 72, 0.5)',
                                    borderRadius: '6px',
                                    fontSize: '13px'
                                  }}>
                                    <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flex: 1 }}>
                                      <span style={{ color: '#64748b', minWidth: '60px' }}>Pull #{death.pullNo}</span>
                                      <span style={{ color: '#94a3b8', minWidth: '120px' }}>{formatTimestamp(death.absTs)}</span>
                                      <span style={{ color: '#cbd5e1' }}>{death.abilityName}</span>
                                    </div>
                                    <a 
                                      href={getWCLLink(death.reportId, death.fightId)} 
                                      target="_blank" 
                                      rel="noopener noreferrer"
                                      style={{ 
                                        display: 'flex', 
                                        alignItems: 'center', 
                                        gap: '4px', 
                                        color: '#f97316', 
                                        textDecoration: 'none',
                                        fontSize: '12px'
                                      }}
                                    >
                                      View Log <ExternalLink size={14} />
                                    </a>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tombstones at the bottom */}
      <div style={{ 
        position: 'fixed', 
        bottom: 0, 
        left: 0, 
        right: 0, 
        height: '80px', 
        display: 'flex', 
        justifyContent: 'space-around', 
        alignItems: 'flex-end',
        padding: '0 40px',
        pointerEvents: 'none',
        zIndex: 1,
        opacity: 0.6
      }}>
        <div style={{ fontSize: '64px' }}>🪦</div>
        <div style={{ fontSize: '56px' }}>🪦</div>
        <div style={{ fontSize: '60px' }}>🪦</div>
        <div style={{ fontSize: '52px' }}>🪦</div>
        <div style={{ fontSize: '58px' }}>🪦</div>
        <div style={{ fontSize: '54px' }}>🪦</div>
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes float {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-20px); }
        }
      `}</style>
    </div>
  );
}