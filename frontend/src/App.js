import React, { useState, useEffect } from 'react';
import { Search, AlertCircle, Loader2, Filter, ChevronDown, ChevronRight, ExternalLink, ArrowUpDown, ArrowUp, ArrowDown, Share2, Copy, Check } from 'lucide-react';

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
  const [showShareModal, setShowShareModal] = useState(false);
  const [shareLink, setShareLink] = useState('');
  const [copied, setCopied] = useState(false);
  const [sharingData, setSharingData] = useState(false);

  // Check for shared results on component mount
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const shareId = urlParams.get('share');
    
    if (shareId) {
      loadSharedResults(shareId);
    }
  }, []);

  const loadSharedResults = async (shareId) => {
    setLoading(true);
    setLoadingStage('Loading shared results...');
    setError('');

    try {
      const response = await fetch(`https://deathwarcraftlogs-api.onrender.com/api/shared/${shareId}`);
      const result = await response.json();

      if (!result.success) {
        throw new Error(result.error || 'Failed to load shared results');
      }

      setData(result.data);
      if (result.config) {
        setConfig(result.config);
      }
      setLoading(false);
      setLoadingStage('');
    } catch (err) {
      setError(err.message);
      setLoading(false);
      setLoadingStage('');
    }
  };

  const handleShare = async () => {
    if (!data) return;

    setSharingData(true);
    try {
      const response = await fetch('https://deathwarcraftlogs-api.onrender.com/api/share', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          data: data,
          config: config
        })
      });

      const result = await response.json();

      if (!result.success) {
        throw new Error(result.error || 'Failed to create shareable link');
      }

      const shareUrl = `${window.location.origin}${window.location.pathname}?share=${result.shareId}`;
      setShareLink(shareUrl);
      setShowShareModal(true);
      setSharingData(false);
    } catch (err) {
      setError(`Failed to create shareable link: ${err.message}`);
      setSharingData(false);
    }
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(shareLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

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

  const formatTimestamp = (ts) => {
    const date = new Date(ts);
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

  const getAvailableBosses = () => {
    if (!data) return [];
    const bosses = new Set();
    Object.values(data.events).forEach(events => {
      events.forEach(ev => {
        if (ev.boss) bosses.add(ev.boss);
      });
    });
    return Array.from(bosses).sort();
  };

  const handleSort = (key) => {
    let direction = 'desc';
    if (sortConfig.key === key && sortConfig.direction === 'desc') {
      direction = 'asc';
    }
    setSortConfig({ key, direction });
  };

  const getSortIcon = (key) => {
    if (sortConfig.key !== key) {
      return <ArrowUpDown size={14} style={{ opacity: 0.3 }} />;
    }
    return sortConfig.direction === 'asc' 
      ? <ArrowUp size={14} /> 
      : <ArrowDown size={14} />;
  };

  return (
    <div style={{ 
      fontFamily: 'system-ui, -apple-system, sans-serif', 
      padding: '20px 20px 100px', 
      maxWidth: '1600px', 
      margin: '0 auto', 
      minHeight: '100vh', 
      background: 'linear-gradient(135deg, #0f0c1d 0%, #1a1425 50%, #0d0b15 100%)',
      position: 'relative'
    }}>
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: '40px' }}>
        <h1 style={{ 
          fontSize: '48px', 
          fontWeight: '900', 
          background: 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)', 
          WebkitBackgroundClip: 'text', 
          WebkitTextFillColor: 'transparent',
          margin: '0 0 10px',
          textShadow: '0 0 30px rgba(249, 115, 22, 0.3)'
        }}>
          ⚔️ WarcraftLogs Death Tracker ⚔️
        </h1>
        <p style={{ color: '#8b92a0', fontSize: '16px', margin: 0 }}>
          Track and analyze raid deaths from WarcraftLogs
        </p>
      </div>

      {/* Share Modal */}
      {showShareModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.8)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000
        }}>
          <div style={{
            background: '#1a1d23',
            padding: '30px',
            borderRadius: '12px',
            border: '2px solid #f97316',
            maxWidth: '500px',
            width: '90%'
          }}>
            <h2 style={{ 
              color: '#ffffff', 
              marginTop: 0, 
              marginBottom: '20px',
              fontSize: '24px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px'
            }}>
              <Share2 size={24} style={{ color: '#f97316' }} />
              Shareable Link Created!
            </h2>
            <p style={{ color: '#8b92a0', marginBottom: '15px' }}>
              Copy this link to share your analysis with others:
            </p>
            <div style={{
              background: '#252930',
              padding: '12px',
              borderRadius: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              marginBottom: '20px'
            }}>
              <input
                type="text"
                value={shareLink}
                readOnly
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  color: '#ffffff',
                  fontSize: '14px',
                  outline: 'none'
                }}
              />
              <button
                onClick={copyToClipboard}
                style={{
                  background: copied ? '#10b981' : '#f97316',
                  color: '#ffffff',
                  border: 'none',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '14px',
                  fontWeight: '600',
                  transition: 'all 0.2s'
                }}
              >
                {copied ? (
                  <>
                    <Check size={16} /> Copied!
                  </>
                ) : (
                  <>
                    <Copy size={16} /> Copy
                  </>
                )}
              </button>
            </div>
            <button
              onClick={() => {
                setShowShareModal(false);
                setCopied(false);
              }}
              style={{
                background: '#2d3238',
                color: '#ffffff',
                border: 'none',
                padding: '10px 20px',
                borderRadius: '6px',
                cursor: 'pointer',
                width: '100%',
                fontSize: '14px',
                fontWeight: '600'
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Configuration Form */}
      <div style={{ 
        background: '#1a1d23', 
        padding: '30px', 
        borderRadius: '12px', 
        marginBottom: '30px',
        border: '1px solid #2d3238'
      }}>
        <h2 style={{ 
          fontSize: '22px', 
          fontWeight: '700', 
          color: '#ffffff', 
          marginTop: 0, 
          marginBottom: '20px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}>
          <Filter size={22} style={{ color: '#f97316' }} />
          Configuration
        </h2>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '15px' }}>
          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Client ID *
            </label>
            <input
              type="text"
              name="clientId"
              value={config.clientId}
              onChange={handleInputChange}
              placeholder="Your WarcraftLogs Client ID"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Client Secret *
            </label>
            <input
              type="password"
              name="clientSecret"
              value={config.clientSecret}
              onChange={handleInputChange}
              placeholder="Your WarcraftLogs Client Secret"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Guild Name *
            </label>
            <input
              type="text"
              name="guildName"
              value={config.guildName}
              onChange={handleInputChange}
              placeholder="Guild Name"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Server *
            </label>
            <input
              type="text"
              name="server"
              value={config.server}
              onChange={handleInputChange}
              placeholder="Server Name"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Region
            </label>
            <select
              name="region"
              value={config.region}
              onChange={handleInputChange}
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            >
              <option value="us">US</option>
              <option value="eu">EU</option>
              <option value="kr">KR</option>
              <option value="tw">TW</option>
              <option value="cn">CN</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Report Zone ID
            </label>
            <input
              type="text"
              name="reportZone"
              value={config.reportZone}
              onChange={handleInputChange}
              placeholder="Zone ID (e.g., 44)"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Fight Zone ID
            </label>
            <input
              type="text"
              name="fightZone"
              value={config.fightZone}
              onChange={handleInputChange}
              placeholder="Fight Zone ID (e.g., 2810)"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Difficulty
            </label>
            <select
              name="difficulty"
              value={config.difficulty}
              onChange={handleInputChange}
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            >
              <option value="3">Normal</option>
              <option value="4">Heroic</option>
              <option value="5">Mythic</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Max Deaths Per Pull
            </label>
            <input
              type="number"
              name="maxCutoff"
              value={config.maxCutoff}
              onChange={handleInputChange}
              min="1"
              max="10"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Cutoff Date
            </label>
            <input
              type="date"
              name="cutoffDate"
              value={config.cutoffDate}
              onChange={handleInputChange}
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div style={{ gridColumn: '1 / -1' }}>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Author Filters (comma-separated)
            </label>
            <input
              type="text"
              name="authorFilters"
              value={config.authorFilters}
              onChange={handleInputChange}
              placeholder="Player1, Player2, Player3"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div style={{ gridColumn: '1 / -1' }}>
            <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '5px', fontWeight: '600' }}>
              Character Groups (JSON format)
            </label>
            <textarea
              name="characterGroups"
              value={config.characterGroups}
              onChange={handleInputChange}
              placeholder='{"MainChar": ["Alt1", "Alt2"]}'
              rows="3"
              style={{
                width: '100%',
                padding: '10px',
                background: '#252930',
                border: '1px solid #2d3238',
                borderRadius: '6px',
                color: '#ffffff',
                fontSize: '14px',
                fontFamily: 'monospace',
                boxSizing: 'border-box',
                resize: 'vertical'
              }}
            />
          </div>
        </div>

        <button
          onClick={handleSubmit}
          disabled={loading}
          style={{
            marginTop: '20px',
            padding: '12px 30px',
            background: loading ? '#475569' : 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)',
            color: '#ffffff',
            border: 'none',
            borderRadius: '8px',
            fontSize: '16px',
            fontWeight: '700',
            cursor: loading ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            transition: 'all 0.2s',
            boxShadow: loading ? 'none' : '0 4px 12px rgba(249, 115, 22, 0.3)'
          }}
        >
          {loading ? (
            <>
              <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />
              Analyzing...
            </>
          ) : (
            <>
              <Search size={18} />
              Analyze Deaths
            </>
          )}
        </button>
      </div>

      {/* Loading State */}
      {loading && (
        <div style={{
          background: '#1a1d23',
          padding: '30px',
          borderRadius: '12px',
          marginBottom: '30px',
          border: '1px solid #2d3238',
          textAlign: 'center'
        }}>
          <Loader2 size={48} style={{ color: '#f97316', animation: 'spin 1s linear infinite', marginBottom: '15px' }} />
          <p style={{ color: '#ffffff', fontSize: '16px', fontWeight: '600', margin: 0 }}>
            {loadingStage}
          </p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div style={{
          background: '#7f1d1d',
          padding: '20px',
          borderRadius: '8px',
          marginBottom: '30px',
          border: '1px solid #991b1b',
          display: 'flex',
          alignItems: 'center',
          gap: '12px'
        }}>
          <AlertCircle size={24} style={{ color: '#fca5a5', flexShrink: 0 }} />
          <p style={{ color: '#fef2f2', margin: 0, fontSize: '14px' }}>
            {error}
          </p>
        </div>
      )}

      {/* Results */}
      {data && (
        <div>
          {/* Results Header with Share Button */}
          <div style={{
            background: '#1a1d23',
            padding: '20px',
            borderRadius: '12px',
            marginBottom: '20px',
            border: '1px solid #2d3238',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '15px'
          }}>
            <div>
              <h2 style={{ 
                fontSize: '20px', 
                fontWeight: '700', 
                color: '#ffffff', 
                margin: '0 0 5px',
              }}>
                Analysis Results
              </h2>
              <p style={{ color: '#8b92a0', fontSize: '13px', margin: 0 }}>
                {data.meta?.guildName && `${data.meta.guildName} - `}
                {data.meta?.reportCount || 0} reports analyzed
                {data.meta?.generatedAt && ` • Generated ${data.meta.generatedAt}`}
              </p>
            </div>
            <button
              onClick={handleShare}
              disabled={sharingData}
              style={{
                padding: '10px 20px',
                background: sharingData ? '#475569' : 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: '600',
                cursor: sharingData ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                transition: 'all 0.2s',
                boxShadow: sharingData ? 'none' : '0 2px 8px rgba(16, 185, 129, 0.3)'
              }}
            >
              {sharingData ? (
                <>
                  <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                  Creating Link...
                </>
              ) : (
                <>
                  <Share2 size={16} />
                  Share Results
                </>
              )}
            </button>
          </div>

          {/* Filters */}
          <div style={{
            background: '#1a1d23',
            padding: '20px',
            borderRadius: '12px',
            marginBottom: '20px',
            border: '1px solid #2d3238'
          }}>
            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '8px', fontWeight: '600' }}>
                Death Rank Cutoff (showing deaths ranked 1-{cutoff})
              </label>
              <input
                type="range"
                min="1"
                max="10"
                value={cutoff}
                onChange={(e) => setCutoff(parseInt(e.target.value))}
                style={{ width: '100%', accentColor: '#f97316' }}
              />
              <div style={{ color: '#ffffff', fontSize: '14px', marginTop: '5px', fontWeight: '600' }}>
                Rank 1 to {cutoff}
              </div>
            </div>

            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '8px', fontWeight: '600' }}>
                Search Players
              </label>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by player name..."
                style={{
                  width: '100%',
                  padding: '10px',
                  background: '#252930',
                  border: '1px solid #2d3238',
                  borderRadius: '6px',
                  color: '#ffffff',
                  fontSize: '14px',
                  boxSizing: 'border-box'
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', color: '#8b92a0', fontSize: '13px', marginBottom: '8px', fontWeight: '600' }}>
                Filter by Boss
              </label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {getAvailableBosses().map(boss => (
                  <button
                    key={boss}
                    onClick={() => toggleBoss(boss)}
                    style={{
                      padding: '6px 12px',
                      background: selectedBosses.has(boss) ? '#f97316' : '#252930',
                      color: '#ffffff',
                      border: '1px solid',
                      borderColor: selectedBosses.has(boss) ? '#f97316' : '#2d3238',
                      borderRadius: '6px',
                      fontSize: '12px',
                      cursor: 'pointer',
                      transition: 'all 0.2s',
                      fontWeight: '600'
                    }}
                  >
                    {boss}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* View Tabs */}
          <div style={{
            display: 'flex',
            gap: '10px',
            marginBottom: '20px',
            background: '#1a1d23',
            padding: '10px',
            borderRadius: '12px',
            border: '1px solid #2d3238'
          }}>
            <button
              onClick={() => setView('overview')}
              style={{
                flex: 1,
                padding: '12px',
                background: view === 'overview' ? 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)' : 'transparent',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: '600',
                cursor: 'pointer',
                transition: 'all 0.2s'
              }}
            >
              Overview
            </button>
            <button
              onClick={() => setView('grid')}
              style={{
                flex: 1,
                padding: '12px',
                background: view === 'grid' ? 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)' : 'transparent',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: '600',
                cursor: 'pointer',
                transition: 'all 0.2s'
              }}
            >
              Boss Grid
            </button>
            <button
              onClick={() => setView('players')}
              style={{
                flex: 1,
                padding: '12px',
                background: view === 'players' ? 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)' : 'transparent',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: '600',
                cursor: 'pointer',
                transition: 'all 0.2s'
              }}
            >
              Player Details
            </button>
          </div>

          {/* Content Views */}
          <div style={{ marginBottom: '30px' }}>
            {view === 'overview' && (
              <div style={{ background: '#1a1d23', borderRadius: '12px', border: '1px solid #2d3238', overflow: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ background: '#252930' }}>
                      <th style={{ padding: '12px', textAlign: 'left', borderBottom: '2px solid #3d424a', fontWeight: '700', color: '#ffffff' }}>Rank</th>
                      <th style={{ padding: '12px', textAlign: 'left', borderBottom: '2px solid #3d424a', fontWeight: '700', color: '#ffffff' }}>Player</th>
                      <th style={{ padding: '12px', textAlign: 'center', borderBottom: '2px solid #3d424a', fontWeight: '700', color: '#ffffff' }}>Deaths</th>
                      <th style={{ padding: '12px', textAlign: 'center', borderBottom: '2px solid #3d424a', fontWeight: '700', color: '#ffffff' }}>Pulls</th>
                      <th style={{ padding: '12px', textAlign: 'center', borderBottom: '2px solid #3d424a', fontWeight: '700', color: '#ffffff' }}>Death Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {getFilteredStats().map((stat, idx) => (
                      <tr key={stat.player} style={{ borderBottom: '1px solid #2d3238' }}>
                        <td style={{ padding: '12px', color: idx < 3 ? '#f97316' : '#8b92a0', fontWeight: idx < 3 ? '700' : '400' }}>
                          {idx + 1}
                        </td>
                        <td style={{ padding: '12px', fontWeight: '600', color: '#ffffff' }}>{stat.player}</td>
                        <td style={{ padding: '12px', textAlign: 'center', color: '#e2e8f0' }}>{stat.deaths}</td>
                        <td style={{ padding: '12px', textAlign: 'center', color: '#e2e8f0' }}>{stat.pulls}</td>
                        <td style={{ padding: '12px', textAlign: 'center' }}>
                          <span style={{ 
                            color: stat.rate > 50 ? '#f87171' : stat.rate > 25 ? '#fbbf24' : '#34d399',
                            fontWeight: '700',
                            fontSize: '16px'
                          }}>
                            {stat.rate.toFixed(1)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {view === 'grid' && (() => {
              const stats = getFilteredStats();
              const bosses = getAvailableBosses().filter(b => selectedBosses.size === 0 || selectedBosses.has(b));
              
              const grid = {};
              stats.forEach(({ player }) => {
                grid[player] = {};
                let totalDeaths = 0;
                let totalPulls = 0;
                
                bosses.forEach(boss => {
                  const bossDeaths = data.events[player]?.filter(
                    ev => ev.boss === boss && ev.rankWithinPull <= cutoff && ev.abilityName && ev.abilityName !== 'Unknown'
                  ) || [];
                  const bossPulls = data.bossParticipation[boss]?.[player]?.length || 0;
                  const bossRate = bossPulls > 0 ? (bossDeaths.length / bossPulls * 100) : null;
                  
                  grid[player][boss] = {
                    deaths: bossDeaths.length,
                    pulls: bossPulls,
                    rate: bossRate
                  };
                  
                  totalDeaths += bossDeaths.length;
                  totalPulls += bossPulls;
                });
                
                grid[player].overall = {
                  deaths: totalDeaths,
                  pulls: totalPulls,
                  rate: totalPulls > 0 ? (totalDeaths / totalPulls * 100) : null
                };
              });

              let sortedPlayers = stats.map(s => s.player);
              if (sortConfig.key) {
                sortedPlayers.sort((a, b) => {
                  const key = sortConfig.key;
                  let aVal, bVal;
                  
                  if (key === 'overall') {
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
              }

              return (
                <div style={{ background: '#1a1d23', borderRadius: '12px', border: '1px solid #2d3238', overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '800px' }}>
                    <thead>
                      <tr style={{ background: '#252930' }}>
                        <th style={{ padding: '10px', textAlign: 'left', borderBottom: '2px solid #3d424a', fontWeight: '700', position: 'sticky', left: 0, background: '#252930', zIndex: 2, color: '#ffffff' }}>
                          Player
                        </th>
                        {bosses.map(boss => (
                          <th 
                            key={boss}
                            onClick={() => handleSort(boss)}
                            style={{ padding: '10px', textAlign: 'center', borderBottom: '2px solid #3d424a', minWidth: '80px', cursor: 'pointer', userSelect: 'none', color: '#ffffff' }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                              {boss} {getSortIcon(boss)}
                            </div>
                          </th>
                        ))}
                        <th 
                          onClick={() => handleSort('overall')}
                          style={{ padding: '10px', textAlign: 'center', borderBottom: '2px solid #3d424a', fontWeight: '700', minWidth: '80px', cursor: 'pointer', userSelect: 'none', color: '#ffffff' }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                            Overall {getSortIcon('overall')}
                          </div>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedPlayers.map(player => (
                        <tr key={player} style={{ borderBottom: '1px solid #2d3238' }}>
                          <td style={{ padding: '10px', fontWeight: '600', position: 'sticky', left: 0, background: '#1a1d23', zIndex: 1, color: '#ffffff' }}>{player}</td>
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
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {getFilteredStats().map(({ player, deaths, pulls, rate, deathsByBoss, topAbilitiesByBoss }) => {
                  const isExpanded = expandedPlayers.has(player);
                  return (
                    <div key={player} style={{ background: '#1a1d23', borderRadius: '8px', border: '1px solid #2d3238', overflow: 'hidden' }}>
                      <div 
                        onClick={() => togglePlayer(player)}
                        style={{ 
                          padding: '12px 16px', 
                          display: 'flex', 
                          justifyContent: 'space-between', 
                          alignItems: 'center', 
                          cursor: 'pointer',
                          background: isExpanded ? '#252930' : '#1a1d23',
                          transition: 'background 0.2s'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          <div>
                            <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '600', color: '#ffffff' }}>{player}</h3>
                            <p style={{ margin: '2px 0 0', fontSize: '12px', color: '#8b92a0' }}>
                              {deaths} deaths / {pulls} pulls
                            </p>
                          </div>
                        </div>
                        <div style={{ fontSize: '18px', fontWeight: '700', color: rate > 50 ? '#f87171' : rate > 25 ? '#fbbf24' : '#34d399' }}>
                          {rate.toFixed(1)}%
                        </div>
                      </div>

                      {isExpanded && (
                        <div style={{ padding: '0 16px 16px', borderTop: '1px solid #2d3238' }}>
                          {Object.entries(deathsByBoss).map(([boss, bossDeaths]) => {
                            const bossPulls = data.bossParticipation[boss]?.[player]?.length || 0;
                            const bossRate = bossPulls > 0 ? (bossDeaths.length / bossPulls * 100) : 0;
                            return (
                            <div key={boss} style={{ marginTop: '12px' }}>
                              <h4 style={{ margin: '0 0 10px', fontSize: '14px', fontWeight: '600', color: '#f97316' }}>
                                {boss} ({bossDeaths.length} deaths / {bossPulls} pulls - {bossRate.toFixed(1)}%)
                              </h4>
                              
                              {topAbilitiesByBoss[boss] && topAbilitiesByBoss[boss].length > 0 && (
                                <div style={{ marginBottom: '10px', padding: '8px 10px', background: '#252930', borderRadius: '4px' }}>
                                  <div style={{ fontSize: '11px', color: '#8b92a0', marginBottom: '4px' }}>Top Abilities:</div>
                                  <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                    {topAbilitiesByBoss[boss].map(([ability, count], idx) => (
                                      <span key={ability}>
                                        {idx + 1}. {ability} ({count}){idx < topAbilitiesByBoss[boss].length - 1 ? ' • ' : ''}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}

                              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                {bossDeaths
                                  .filter(death => death.abilityName && death.abilityName !== 'Unknown')
                                  .map((death, idx) => (
                                  <div key={idx} style={{ 
                                    display: 'flex', 
                                    justifyContent: 'space-between', 
                                    alignItems: 'center',
                                    padding: '8px 10px',
                                    background: '#252930',
                                    borderRadius: '4px',
                                    fontSize: '12px'
                                  }}>
                                    <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flex: 1 }}>
                                      <span style={{ color: '#64748b', minWidth: '55px' }}>Pull #{death.pullNo}</span>
                                      <span style={{ color: '#8b92a0', minWidth: '110px' }}>{formatTimestamp(death.absTs)}</span>
                                      <span style={{ color: '#e2e8f0' }}>{death.abilityName}</span>
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
                                        fontSize: '11px'
                                      }}
                                    >
                                      View Log <ExternalLink size={12} />
                                    </a>
                                  </div>
                                ))}
                              </div>
                            </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

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
        opacity: 0.4
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