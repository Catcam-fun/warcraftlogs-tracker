import React, { useState } from 'react';
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

  const [includeCheatEvents, setIncludeCheatEvents] = useState(false);

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
        try { characterGroups = JSON.parse(config.characterGroups); }
        catch { throw new Error('Invalid JSON format for character groups'); }
      }

      const payload = {
        ...config,
        authorFilters: config.authorFilters.split(',').map(s => s.trim()).filter(Boolean),
        characterGroups,
        includeCheatEvents
      };

      const response = await fetch('https://deathwarcraftlogs-api.onrender.com/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) throw new Error('Failed to connect to server');

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
          if (!line.startsWith('data: ')) continue;
          const chunk = JSON.parse(line.slice(6));
          if (chunk.error) throw new Error(chunk.error);
          else if (chunk.message) setLoadingStage(chunk.message);
          else if (chunk.result) { setData(chunk.result); setLoadingStage(''); setLoading(false); }
        }
      }
    } catch (err) {
      setError(err.message);
      setLoadingStage('');
      setLoading(false);
    }
  };

  const toggleBoss = (boss) => {
    const next = new Set(selectedBosses);
    next.has(boss) ? next.delete(boss) : next.add(boss);
    setSelectedBosses(next);
  };

  const togglePlayer = (player) => {
    const next = new Set(expandedPlayers);
    next.has(player) ? next.delete(player) : next.add(player);
    setExpandedPlayers(next);
  };

  // === your existing helpers (unchanged) ================================
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
      if (selectedBosses.size === 0) pulls = pullsMap[player]?.length || 0;
      else {
        for (const boss of selectedBosses) {
          if (bossPart[boss]?.[player]) pulls += bossPart[boss][player].length;
        }
      }

      const rate = pulls > 0 ? (evs.length / pulls * 100) : 0;
      if (searchQuery && !player.toLowerCase().includes(searchQuery.toLowerCase())) continue;

      const deathsByBoss = {};
      evs.forEach(ev => {
        deathsByBoss[ev.boss] = deathsByBoss[ev.boss] || [];
        deathsByBoss[ev.boss].push(ev);
      });

      const topAbilitiesByBoss = {};
      Object.keys(deathsByBoss).forEach(boss => {
        const counts = {};
        deathsByBoss[boss].forEach(d => {
          const ab = d.abilityName || 'Unknown';
          if (ab !== 'Unknown') counts[ab] = (counts[ab] || 0) + 1;
        });
        topAbilitiesByBoss[boss] = Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,5);
      });

      stats.push({ player, deaths: evs.length, pulls, rate, deathsByBoss, topAbilitiesByBoss });
    }
    return stats.sort((a,b)=> b.rate - a.rate || b.deaths - a.deaths);
  };

  const getOverviewData = () => {
    if (!data) return { bosses: [], players: [], grid: {} };
    const bosses = Object.keys(data.bossParticipation).sort();
    const players = Object.keys(data.events).sort();
    const grid = {};
    players.forEach(p => {
      grid[p] = {};
      bosses.forEach(boss => {
        const pulls = data.bossParticipation[boss]?.[p]?.length || 0;
        const deaths = data.events[p]?.filter(ev => ev.boss === boss && ev.rankWithinPull <= cutoff).length || 0;
        const rate = pulls > 0 ? (deaths / pulls * 100) : null;
        grid[p][boss] = { deaths, pulls, rate };
      });
      const totalPulls = data.pullParticipation[p]?.length || 0;
      const totalDeaths = data.events[p]?.filter(ev => ev.rankWithinPull <= cutoff).length || 0;
      grid[p].overall = { deaths: totalDeaths, pulls: totalPulls, rate: totalPulls>0 ? (totalDeaths/totalPulls*100) : null };
    });
    return { bosses, players, grid };
  };

  const sortOverviewData = (bosses, players, grid, key) => {
    const sorted = [...players].sort((a,b)=>{
      if (key === 'player') return (sortConfig.direction==='asc' ? a.localeCompare(b) : b.localeCompare(a));
      const aVal = key==='overall' ? (grid[a].overall.rate ?? -1) : (grid[a][key]?.rate ?? -1);
      const bVal = key==='overall' ? (grid[b].overall.rate ?? -1) : (grid[b][key]?.rate ?? -1);
      return sortConfig.direction==='asc' ? aVal - bVal : bVal - aVal;
    });
    return sorted;
  };

  const handleSort = (key) => setSortConfig(prev => ({ key, direction: prev.key===key && prev.direction==='asc' ? 'desc' : 'asc' }));
  const getSortIcon = (key) => sortConfig.key !== key ? <ArrowUpDown size={14} /> : (sortConfig.direction === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} />);

  const formatTimestamp = (absTs) => new Date(absTs).toLocaleString('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
  const getWCLLink = (reportId, fightId) => `https://www.warcraftlogs.com/reports/${reportId}#fight=${fightId}&type=deaths`;

  // === UI ================================================================
  return (
    <div style={{ minHeight: '100vh', background: '#0d1117', color: '#e2e8f0', fontFamily: 'system-ui, -apple-system, sans-serif', position: 'relative' }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px' }}>
        <div style={{ background: '#1a1d23', borderRadius: '12px', padding: '24px', marginBottom: '20px', border: '1px solid #2d3238' }}>
          <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: '#fff', textAlign: 'center' }}>WarcraftLogs Death Tracker</h1>
          <p style={{ color: '#8b92a0', margin: 0, textAlign: 'center', fontSize: 14 }}>Analyze raid deaths and cheat-death triggers</p>
        </div>

        {loading && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(13,17,23,0.98)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 99 }}>
            <div style={{ textAlign: 'center', maxWidth: 500, padding: 40 }}>
              <div style={{ width: 80, height: 80, border: '4px solid #2d3238', borderTop: '4px solid #f97316', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 24px' }} />
              <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 600, color: '#fff' }}>Analyzing Reports</h2>
              <div style={{ padding: '14px 18px', background: '#1a1d23', borderRadius: 8, border: '1px solid #2d3238', marginBottom: 16, minHeight: 60, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <p style={{ margin: 0, fontSize: 14, color: '#f97316', fontWeight: 500, lineHeight: 1.6 }}>{loadingStage || 'Starting analysis...'}</p>
              </div>
              <p style={{ color: '#8b92a0', fontSize: 13, margin: 0 }}>Processing data from WarcraftLogs...<br/>This may take a while</p>
            </div>
          </div>
        )}

        {!data && (
          <div style={{ background: '#1a1d23', borderRadius: 12, padding: 24, marginBottom: 20, border: '1px solid #2d3238' }}>
            <h2 style={{ margin: '0 0 16px', fontSize: 18, fontWeight: 600, color: '#fff' }}>Configuration</h2>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 18 }}>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Client ID *</label>
                <input type="text" name="clientId" value={config.clientId} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Client Secret *</label>
                <input type="password" name="clientSecret" value={config.clientSecret} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 18, marginTop: 14 }}>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Guild Name *</label>
                <input type="text" name="guildName" value={config.guildName} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Server *</label>
                <input type="text" name="server" value={config.server} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 18, marginTop: 14 }}>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Region *</label>
                <select name="region" value={config.region} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }}>
                  <option value="us">US</option><option value="eu">EU</option><option value="kr">KR</option><option value="tw">TW</option><option value="cn">CN</option>
                </select>
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Difficulty *</label>
                <select name="difficulty" value={config.difficulty} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }}>
                  <option value="3">Normal</option><option value="4">Heroic</option><option value="5">Mythic</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 18, marginTop: 14 }}>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Report Zone ID</label>
                <input type="text" name="reportZone" value={config.reportZone} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Fight Zone ID</label>
                <input type="text" name="fightZone" value={config.fightZone} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 18, marginTop: 14 }}>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Cutoff Date</label>
                <input type="date" name="cutoffDate" value={config.cutoffDate} onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Max Deaths to Track</label>
                <input type="number" name="maxCutoff" value={config.maxCutoff} min="1" max="10" onChange={handleInputChange}
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
              <input id="toggleCheats" type="checkbox" checked={includeCheatEvents} onChange={e=>setIncludeCheatEvents(e.target.checked)} />
              <label htmlFor="toggleCheats" style={{ fontSize: 13, color: '#cbd5e1' }}>
                Include “Cheat-Death” events (Cheat Death, Purgatory, Ardent Defender, Cauterize, Guardian Spirit, Spirit of Redemption, Reincarnation)
              </label>
            </div>

            <div style={{ marginTop: 10 }}>
              <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Author Filters (optional, comma-separated)</label>
              <input type="text" name="authorFilters" value={config.authorFilters} onChange={handleInputChange}
                style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }} />
            </div>

            <div style={{ marginTop: 10 }}>
              <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: '#cbd5e1' }}>Character Groups (JSON)</label>
              <textarea name="characterGroups" value={config.characterGroups} onChange={handleInputChange}
                placeholder='{"Main":["Alt1","Alt2"],"AnotherMain":["AltX"]}' rows={3}
                style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: 6, color: '#e2e8f0', fontFamily: 'monospace' }} />
            </div>

            {error && (
              <div style={{ marginTop: 20, padding: '10px 14px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 6, display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                <AlertCircle size={18} /><span>{error}</span>
              </div>
            )}

            <button onClick={handleSubmit} disabled={loading}
              style={{ marginTop: 24, padding: '12px 24px', background: loading ? '#3d424a' : '#f97316', border: 'none', borderRadius: 6, color: '#fff', fontSize: 14, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              {loading ? (<><Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />Analyzing...</>) : (<><Search size={18} />Analyze Reports</>)}
            </button>
          </div>
        )}

        {data && (
          <div>
            {/* top controls block unchanged */}
            <div style={{ background: '#1a1d23', borderRadius: 12, padding: 16, marginBottom: 20, border: '1px solid #2d3238' }}>
              {/* … boss chips, cutoff, tabs (same as your file) … */}
            </div>

            {/* PLAYERS view: add a Cheat-Death section inside each expanded card */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {getFilteredStats().map(({ player, deaths, pulls, rate, deathsByBoss, topAbilitiesByBoss }) => {
                const isExpanded = expandedPlayers.has(player);
                return (
                  <div key={player} style={{ background: '#1a1d23', borderRadius: 8, border: '1px solid #2d3238', overflow: 'hidden' }}>
                    <div onClick={() => togglePlayer(player)} style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', background: isExpanded ? '#252930' : '#1a1d23' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        <div>
                          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: '#fff' }}>{player}</h3>
                          <p style={{ margin: '2px 0 0', fontSize: 12, color: '#8b92a0' }}>{deaths} deaths / {pulls} pulls</p>
                        </div>
                      </div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: rate > 50 ? '#f87171' : rate > 25 ? '#fbbf24' : '#34d399' }}>
                        {rate.toFixed(1)}%
                      </div>
                    </div>

                    {isExpanded && (
                      <div style={{ padding: '0 16px 16px', borderTop: '1px solid #2d3238' }}>
                        {/* existing per-boss deaths block … */}

                        {/* Cheat-Death Triggers (only if returned & user toggled it on) */}
                        {data.meta.includeCheatEvents && data.cheatEvents && data.cheatEvents[player] && (
                          <div style={{ marginTop: 12 }}>
                            <h4 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 600, color: '#f97316' }}>Cheat-Death Triggers</h4>
                            {(data.cheatEvents[player] || []).map((ev, idx) => (
                              <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', background: '#252930', borderRadius: 4, fontSize: 12, marginBottom: 6 }}>
                                <div style={{ display: 'flex', gap: 10, alignItems: 'center', flex: 1 }}>
                                  <span style={{ color: '#64748b', minWidth: 55 }}>Pull #{ev.pullNo}</span>
                                  <span style={{ color: '#8b92a0', minWidth: 110 }}>{formatTimestamp(ev.absTs)}</span>
                                  <span style={{ color: '#e2e8f0' }}>{ev.abilityName}</span>
                                  <span style={{ color: '#8b92a0' }}>— {ev.boss}</span>
                                </div>
                                <a href={getWCLLink(ev.reportId, ev.fightId)} target="_blank" rel="noopener noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#f97316', textDecoration: 'none', fontSize: 11 }}>
                                  View Log <ExternalLink size={12} />
                                </a>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <style>{`@keyframes spin {from{transform:rotate(0)} to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}
