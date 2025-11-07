import React, { useState, useEffect } from 'react';
import { Search, AlertCircle, Loader2, Filter, ChevronDown, ChevronRight, ExternalLink, ArrowUpDown, ArrowUp, ArrowDown, Share2, Copy, Check } from 'lucide-react';

// Automatically detect if running locally or in production
const API_URL = window.location.hostname === 'localhost' 
  ? 'http://localhost:5000' 
  : 'https://deathwarcraftlogs-api.onrender.com';

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
    characterGroups: '',
    enableCheatDeath: false  // Optional cheat death detection (slower)
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
  const [abortController, setAbortController] = useState(null);

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
      const response = await fetch(`${API_URL}/api/shared/${shareId}`);
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
      const response = await fetch(`${API_URL}/api/share`, {
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

  const handleCancel = () => {
    if (abortController) {
      abortController.abort();
      setAbortController(null);
    }
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

    // Create abort controller for cancellation
    const controller = new AbortController();
    setAbortController(controller);

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

      const response = await fetch(`${API_URL}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal
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
              
              // DEBUG: Expose data globally and log summary
              window.__deathData = data.result;
              
              console.log("=== Death Data Loaded ===");
              console.log("Total players:", Object.keys(data.result.events).length);
              console.log("Has cheat deaths:", Object.values(data.result.events).some(events => 
                events.some(e => e.isCheatDeath)
              ));
              console.log("Data available at: window.__deathData");
            } else if (data.stage) {
              setLoadingStage(data.message || '');
            }
          }
        }
      }

      setLoading(false);
      setLoadingStage('');
      setAbortController(null);
    } catch (err) {
      if (err.name === 'AbortError') {
        setError('Analysis cancelled by user');
      } else {
        setError(err.message);
      }
      setLoading(false);
      setLoadingStage('');
      setAbortController(null);
    }
  };

  const getWCLLink = (reportId, fightId) => {
    return `https://www.warcraftlogs.com/reports/${reportId}#fight=${fightId}`;
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

  const getPercentageColor = (percentage, allPercentages) => {
    if (!allPercentages || allPercentages.length === 0) return '#e2e8f0';
    
    const sorted = [...allPercentages].sort((a, b) => a - b);
    const percentile = sorted.indexOf(percentage) / sorted.length;
    
    if (percentile < 0.25) return '#34d399';
    if (percentile < 0.5) return '#fbbf24';
    if (percentile < 0.75) return '#fb923c';
    return '#f87171';
  };

  const togglePlayerExpanded = (player) => {
    setExpandedPlayers(prev => {
      const newSet = new Set(prev);
      if (newSet.has(player)) {
        newSet.delete(player);
      } else {
        newSet.add(player);
      }
      return newSet;
    });
  };

  const toggleBossFilter = (boss) => {
    setSelectedBosses(prev => {
      const newSet = new Set(prev);
      if (newSet.has(boss)) {
        newSet.delete(boss);
      } else {
        newSet.add(boss);
      }
      return newSet;
    });
  };

  const requestSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  const getSortIcon = (columnKey) => {
    if (sortConfig.key !== columnKey) {
      return <ArrowUpDown size={14} style={{ opacity: 0.3 }} />;
    }
    return sortConfig.direction === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} />;
  };

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #1a1d24 0%, #2d3238 100%)', color: '#e2e8f0', padding: '20px', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: '30px' }}>
          <h1 style={{ 
            fontSize: '48px', 
            fontWeight: '900', 
            margin: '0 0 8px', 
            background: 'linear-gradient(135deg, #f97316 0%, #fb923c 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            textShadow: '0 4px 12px rgba(249, 115, 22, 0.3)'
          }}>
            ☠️ WarcraftLogs Death Tracker
          </h1>
          <p style={{ fontSize: '14px', color: '#8b92a0', margin: 0 }}>
            Track and analyze raid deaths with precision • Version 2.5.1
          </p>
        </div>

        <div style={{ background: '#252930', borderRadius: '12px', padding: '24px', marginBottom: '24px', boxShadow: '0 4px 20px rgba(0,0,0,0.3)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Client ID *</label>
              <input
                type="text"
                name="clientId"
                value={config.clientId}
                onChange={handleInputChange}
                placeholder="Your WCL Client ID"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Client Secret *</label>
              <input
                type="password"
                name="clientSecret"
                value={config.clientSecret}
                onChange={handleInputChange}
                placeholder="Your WCL Client Secret"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Guild Name *</label>
              <input
                type="text"
                name="guildName"
                value={config.guildName}
                onChange={handleInputChange}
                placeholder="e.g., Ethical"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Server *</label>
              <input
                type="text"
                name="server"
                value={config.server}
                onChange={handleInputChange}
                placeholder="e.g., Area 52"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Region</label>
              <select
                name="region"
                value={config.region}
                onChange={handleInputChange}
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              >
                <option value="us">US</option>
                <option value="eu">EU</option>
                <option value="kr">KR</option>
                <option value="tw">TW</option>
                <option value="cn">CN</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Report Zone ID</label>
              <input
                type="text"
                name="reportZone"
                value={config.reportZone}
                onChange={handleInputChange}
                placeholder="e.g., 44 (TWW S1)"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Fight Zone ID</label>
              <input
                type="text"
                name="fightZone"
                value={config.fightZone}
                onChange={handleInputChange}
                placeholder="e.g., 2810 (Nerub-ar Palace)"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Difficulty</label>
              <select
                name="difficulty"
                value={config.difficulty}
                onChange={handleInputChange}
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              >
                <option value="3">Normal</option>
                <option value="4">Heroic</option>
                <option value="5">Mythic</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Max Cutoff Deaths</label>
              <input
                type="number"
                name="maxCutoff"
                value={config.maxCutoff}
                onChange={handleInputChange}
                placeholder="e.g., 5"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Date Cutoff</label>
              <input
                type="date"
                name="cutoffDate"
                value={config.cutoffDate}
                onChange={handleInputChange}
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div style={{ gridColumn: '1 / -1' }}>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Report Owner Filters (comma-separated)</label>
              <input
                type="text"
                name="authorFilters"
                value={config.authorFilters}
                onChange={handleInputChange}
                placeholder="e.g., Player1, Player2"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px' }}
              />
            </div>

            <div style={{ gridColumn: '1 / -1' }}>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '600', color: '#cbd5e1' }}>Character Groups (JSON format)</label>
              <textarea
                name="characterGroups"
                value={config.characterGroups}
                onChange={handleInputChange}
                placeholder='{"MainCharacter": ["Alt1", "Alt2"]}'
                rows="3"
                style={{ width: '100%', padding: '10px', background: '#1a1d24', border: '1px solid #3d4451', borderRadius: '6px', color: '#e2e8f0', fontSize: '14px', fontFamily: 'monospace' }}
              />
            </div>

            <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="checkbox"
                id="enableCheatDeath"
                checked={config.enableCheatDeath}
                onChange={(e) => setConfig(prev => ({ ...prev, enableCheatDeath: e.target.checked }))}
                style={{ width: '18px', height: '18px', cursor: 'pointer' }}
              />
              <label htmlFor="enableCheatDeath" style={{ fontSize: '13px', fontWeight: '600', color: '#34d399', cursor: 'pointer' }}>
                Enable Cheat Death Detection (Adds ~10-30s per report analyzed)
              </label>
            </div>
          </div>

          <div style={{ marginTop: '20px', display: 'flex', gap: '12px' }}>
            <button
              onClick={handleSubmit}
              disabled={loading}
              style={{
                flex: 1,
                padding: '14px',
                background: loading ? '#64748b' : 'linear-gradient(135deg, #f97316 0%, #fb923c 100%)',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                fontSize: '15px',
                fontWeight: '700',
                cursor: loading ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
                boxShadow: loading ? 'none' : '0 4px 12px rgba(249, 115, 22, 0.4)',
                transition: 'all 0.2s'
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

            {loading && (
              <button
                onClick={handleCancel}
                style={{
                  padding: '14px 24px',
                  background: '#dc2626',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  fontSize: '15px',
                  fontWeight: '700',
                  cursor: 'pointer',
                  boxShadow: '0 4px 12px rgba(220, 38, 38, 0.4)',
                  transition: 'all 0.2s'
                }}
              >
                Cancel
              </button>
            )}
          </div>

          {loading && loadingStage && (
            <div style={{ 
              marginTop: '16px', 
              padding: '12px', 
              background: '#1a1d24', 
              borderRadius: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              fontSize: '13px',
              color: '#34d399'
            }}>
              <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
              {loadingStage}
            </div>
          )}

          {error && (
            <div style={{ 
              marginTop: '16px', 
              padding: '12px', 
              background: '#7f1d1d', 
              borderRadius: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              fontSize: '13px',
              color: '#fca5a5'
            }}>
              <AlertCircle size={16} />
              {error}
            </div>
          )}
        </div>

        {data && (
          <div style={{ background: '#252930', borderRadius: '12px', padding: '24px', boxShadow: '0 4px 20px rgba(0,0,0,0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <h2 style={{ margin: '0 0 4px', fontSize: '24px', fontWeight: '800', color: '#ffffff' }}>Analysis Results</h2>
                <p style={{ margin: 0, fontSize: '13px', color: '#8b92a0' }}>
                  {data.meta.reportCount} reports • {data.meta.zone} • Difficulty: {data.meta.difficulty} • Generated: {data.meta.generatedAt}
                </p>
              </div>

              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  onClick={handleShare}
                  disabled={sharingData}
                  style={{
                    padding: '10px 20px',
                    background: sharingData ? '#64748b' : 'linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%)',
                    color: 'white',
                    border: 'none',
                    borderRadius: '8px',
                    fontSize: '14px',
                    fontWeight: '700',
                    cursor: sharingData ? 'not-allowed' : 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    boxShadow: sharingData ? 'none' : '0 4px 12px rgba(59, 130, 246, 0.4)',
                    transition: 'all 0.2s'
                  }}
                >
                  {sharingData ? (
                    <>
                      <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                      Sharing...
                    </>
                  ) : (
                    <>
                      <Share2 size={16} />
                      Share Results
                    </>
                  )}
                </button>

                <button
                  onClick={() => setView(view === 'overview' ? 'detailed' : 'overview')}
                  style={{
                    padding: '10px 20px',
                    background: '#3d4451',
                    color: '#e2e8f0',
                    border: 'none',
                    borderRadius: '8px',
                    fontSize: '14px',
                    fontWeight: '600',
                    cursor: 'pointer',
                    transition: 'all 0.2s'
                  }}
                >
                  {view === 'overview' ? '📊 Overview' : '📋 Detailed'}
                </button>
              </div>
            </div>

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
                zIndex: 1000,
                padding: '20px'
              }}>
                <div style={{
                  background: '#252930',
                  borderRadius: '12px',
                  padding: '32px',
                  maxWidth: '500px',
                  width: '100%',
                  boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)'
                }}>
                  <h3 style={{ margin: '0 0 16px', fontSize: '20px', fontWeight: '700', color: '#ffffff' }}>
                    Share Your Results
                  </h3>
                  <p style={{ margin: '0 0 16px', fontSize: '14px', color: '#8b92a0' }}>
                    Copy this link to share your death analysis with others:
                  </p>
                  <div style={{
                    display: 'flex',
                    gap: '8px',
                    marginBottom: '20px'
                  }}>
                    <input
                      type="text"
                      value={shareLink}
                      readOnly
                      style={{
                        flex: 1,
                        padding: '10px',
                        background: '#1a1d24',
                        border: '1px solid #3d4451',
                        borderRadius: '6px',
                        color: '#e2e8f0',
                        fontSize: '13px',
                        fontFamily: 'monospace'
                      }}
                    />
                    <button
                      onClick={copyToClipboard}
                      style={{
                        padding: '10px 20px',
                        background: copied ? '#34d399' : '#3b82f6',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        fontSize: '14px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        transition: 'all 0.2s'
                      }}
                    >
                      {copied ? (
                        <>
                          <Check size={16} />
                          Copied!
                        </>
                      ) : (
                        <>
                          <Copy size={16} />
                          Copy
                        </>
                      )}
                    </button>
                  </div>
                  <button
                    onClick={() => setShowShareModal(false)}
                    style={{
                      width: '100%',
                      padding: '10px',
                      background: '#3d4451',
                      color: '#e2e8f0',
                      border: 'none',
                      borderRadius: '6px',
                      fontSize: '14px',
                      fontWeight: '600',
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}
                  >
                    Close
                  </button>
                </div>
              </div>
            )}

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '600', color: '#cbd5e1' }}>
                Death Cutoff: <span style={{ color: '#f97316', fontWeight: '800' }}>{cutoff}</span>
              </label>
              <input
                type="range"
                min="1"
                max={data.meta.maxCutoff}
                value={cutoff}
                onChange={(e) => setCutoff(parseInt(e.target.value))}
                style={{ width: '100%' }}
              />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                <Filter size={16} style={{ color: '#8b92a0' }} />
                <span style={{ fontSize: '14px', fontWeight: '600', color: '#cbd5e1' }}>Filter by Boss:</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {(() => {
                  const bossList = Object.keys(data.bossParticipation || {});
                  return bossList.map(boss => (
                    <button
                      key={boss}
                      onClick={() => toggleBossFilter(boss)}
                      style={{
                        padding: '8px 14px',
                        background: selectedBosses.has(boss) ? '#f97316' : '#3d4451',
                        color: selectedBosses.has(boss) ? 'white' : '#cbd5e1',
                        border: 'none',
                        borderRadius: '6px',
                        fontSize: '13px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        transition: 'all 0.2s'
                      }}
                    >
                      {boss}
                    </button>
                  ));
                })()}
              </div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <input
                type="text"
                placeholder="Search players..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  width: '100%',
                  padding: '12px',
                  background: '#1a1d24',
                  border: '1px solid #3d4451',
                  borderRadius: '8px',
                  color: '#e2e8f0',
                  fontSize: '14px'
                }}
              />
            </div>

            {view === 'overview' && (() => {
              const filteredData = {};

              for (const [player, deaths] of Object.entries(data.events)) {
                if (searchQuery && !player.toLowerCase().includes(searchQuery.toLowerCase())) {
                  continue;
                }

                const relevantDeaths = deaths.filter(d => {
                  if (selectedBosses.size > 0 && !selectedBosses.has(d.boss)) {
                    return false;
                  }

                  const pullKey = `${d.reportId}_${d.fightId}`;
                  const pullCutoffTs = data.pullCutoffTimestamps?.[pullKey]?.[cutoff];
                  
                  if (pullCutoffTs === undefined) {
                    return true;
                  }

                  return d.timestamp <= pullCutoffTs;
                });

                if (relevantDeaths.length > 0) {
                  filteredData[player] = relevantDeaths;
                }
              }

              const tableData = Object.entries(filteredData).map(([player, deaths]) => {
                const realDeaths = deaths.filter(d => !d.isCheatDeath);
                const pulls = new Set(deaths.map(d => `${d.reportId}_${d.fightId}`)).size;
                const realRate = pulls > 0 ? (realDeaths.length / pulls * 100) : 0;
                const totalRate = pulls > 0 ? (deaths.length / pulls * 100) : 0;
                
                return {
                  player,
                  realDeaths: realDeaths.length,
                  totalDeaths: deaths.length,
                  pulls,
                  realRate,
                  totalRate
                };
              });

              if (sortConfig.key) {
                tableData.sort((a, b) => {
                  const aVal = a[sortConfig.key];
                  const bVal = b[sortConfig.key];
                  const modifier = sortConfig.direction === 'asc' ? 1 : -1;
                  return (aVal < bVal ? -1 : aVal > bVal ? 1 : 0) * modifier;
                });
              }

              const allRealRates = tableData.map(d => d.realRate);
              const allTotalRates = tableData.map(d => d.totalRate);

              return (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: 0 }}>
                    <thead>
                      <tr style={{ background: '#1a1d24' }}>
                        <th 
                          onClick={() => requestSort('player')}
                          style={{ 
                            padding: '14px', 
                            textAlign: 'left', 
                            fontSize: '13px', 
                            fontWeight: '700', 
                            color: '#8b92a0', 
                            textTransform: 'uppercase',
                            cursor: 'pointer',
                            userSelect: 'none',
                            borderBottom: '2px solid #3d4451'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            Player
                            {getSortIcon('player')}
                          </div>
                        </th>
                        <th 
                          onClick={() => requestSort('realDeaths')}
                          style={{ 
                            padding: '14px', 
                            textAlign: 'center', 
                            fontSize: '13px', 
                            fontWeight: '700', 
                            color: '#8b92a0', 
                            textTransform: 'uppercase',
                            cursor: 'pointer',
                            userSelect: 'none',
                            borderBottom: '2px solid #3d4451'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                            Real Deaths
                            {getSortIcon('realDeaths')}
                          </div>
                        </th>
                        <th 
                          onClick={() => requestSort('totalDeaths')}
                          style={{ 
                            padding: '14px', 
                            textAlign: 'center', 
                            fontSize: '13px', 
                            fontWeight: '700', 
                            color: '#34d399', 
                            textTransform: 'uppercase',
                            cursor: 'pointer',
                            userSelect: 'none',
                            borderBottom: '2px solid #3d4451'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                            With Cheat
                            {getSortIcon('totalDeaths')}
                          </div>
                        </th>
                        <th 
                          onClick={() => requestSort('pulls')}
                          style={{ 
                            padding: '14px', 
                            textAlign: 'center', 
                            fontSize: '13px', 
                            fontWeight: '700', 
                            color: '#8b92a0', 
                            textTransform: 'uppercase',
                            cursor: 'pointer',
                            userSelect: 'none',
                            borderBottom: '2px solid #3d4451'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                            Pulls
                            {getSortIcon('pulls')}
                          </div>
                        </th>
                        <th 
                          onClick={() => requestSort('realRate')}
                          style={{ 
                            padding: '14px', 
                            textAlign: 'center', 
                            fontSize: '13px', 
                            fontWeight: '700', 
                            color: '#8b92a0', 
                            textTransform: 'uppercase',
                            cursor: 'pointer',
                            userSelect: 'none',
                            borderBottom: '2px solid #3d4451'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                            Real Rate
                            {getSortIcon('realRate')}
                          </div>
                        </th>
                        <th 
                          onClick={() => requestSort('totalRate')}
                          style={{ 
                            padding: '14px', 
                            textAlign: 'center', 
                            fontSize: '13px', 
                            fontWeight: '700', 
                            color: '#34d399', 
                            textTransform: 'uppercase',
                            cursor: 'pointer',
                            userSelect: 'none',
                            borderBottom: '2px solid #3d4451'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                            With Cheat Rate
                            {getSortIcon('totalRate')}
                          </div>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {tableData.map(({ player, realDeaths, totalDeaths, pulls, realRate, totalRate }) => (
                        <tr key={player} style={{ background: '#252930', borderBottom: '1px solid #2d3238' }}>
                          <td style={{ padding: '14px', fontSize: '14px', fontWeight: '600', color: '#ffffff' }}>{player}</td>
                          <td style={{ padding: '14px', textAlign: 'center', fontSize: '14px', color: '#e2e8f0' }}>{realDeaths}</td>
                          <td style={{ padding: '14px', textAlign: 'center', fontSize: '14px', color: '#34d399' }}>{totalDeaths}</td>
                          <td style={{ padding: '14px', textAlign: 'center', fontSize: '14px', color: '#8b92a0' }}>{pulls}</td>
                          <td style={{ padding: '14px', textAlign: 'center', fontSize: '16px', fontWeight: '700', color: getPercentageColor(realRate, allRealRates) }}>
                            {realRate.toFixed(1)}%
                          </td>
                          <td style={{ padding: '14px', textAlign: 'center', fontSize: '16px', fontWeight: '700', color: getPercentageColor(totalRate, allTotalRates) }}>
                            {totalRate.toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })()}

            {view === 'detailed' && (() => {
              const filteredData = {};

              for (const [player, deaths] of Object.entries(data.events)) {
                if (searchQuery && !player.toLowerCase().includes(searchQuery.toLowerCase())) {
                  continue;
                }

                const relevantDeaths = deaths.filter(d => {
                  if (selectedBosses.size > 0 && !selectedBosses.has(d.boss)) {
                    return false;
                  }

                  const pullKey = `${d.reportId}_${d.fightId}`;
                  const pullCutoffTs = data.pullCutoffTimestamps?.[pullKey]?.[cutoff];
                  
                  if (pullCutoffTs === undefined) {
                    return true;
                  }

                  return d.timestamp <= pullCutoffTs;
                });

                if (relevantDeaths.length > 0) {
                  filteredData[player] = relevantDeaths;
                }
              }

              const playersList = Object.entries(filteredData).map(([player, deaths]) => {
                const realDeaths = deaths.filter(d => !d.isCheatDeath);
                const pulls = new Set(deaths.map(d => `${d.reportId}_${d.fightId}`)).size;
                const realRate = pulls > 0 ? (realDeaths.length / pulls * 100) : 0;
                const totalRate = pulls > 0 ? (deaths.length / pulls * 100) : 0;

                return {
                  player,
                  deaths,
                  realDeaths: realDeaths.length,
                  totalDeaths: deaths.length,
                  pulls,
                  realRate,
                  totalRate
                };
              });

              if (sortConfig.key) {
                playersList.sort((a, b) => {
                  const aVal = a[sortConfig.key];
                  const bVal = b[sortConfig.key];
                  const modifier = sortConfig.direction === 'asc' ? 1 : -1;
                  return (aVal < bVal ? -1 : aVal > bVal ? 1 : 0) * modifier;
                });
              }

              const allRealRates = playersList.map(d => d.realRate);
              const allTotalRates = playersList.map(d => d.totalRate);

              return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {playersList.map(({ player, deaths, realDeaths, totalDeaths, pulls, realRate, totalRate }) => {
                  const isExpanded = expandedPlayers.has(player);
                  
                  const deathsByBoss = {};
                  const totalDeathsByBoss = {};
                  
                  deaths.forEach(death => {
                    if (!deathsByBoss[death.boss]) {
                      deathsByBoss[death.boss] = [];
                      totalDeathsByBoss[death.boss] = [];
                    }
                    
                    totalDeathsByBoss[death.boss].push(death);
                    
                    if (!death.isCheatDeath) {
                      deathsByBoss[death.boss].push(death);
                    }
                  });

                  const topAbilitiesByBoss = {};
                  Object.entries(deathsByBoss).forEach(([boss, bossDeaths]) => {
                    const abilityCounts = {};
                    bossDeaths.forEach(d => {
                      if (d.abilityName && d.abilityName !== 'Unknown') {
                        abilityCounts[d.abilityName] = (abilityCounts[d.abilityName] || 0) + 1;
                      }
                    });
                    
                    topAbilitiesByBoss[boss] = Object.entries(abilityCounts)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 3);
                  });

                  const hasAnyCheatDeaths = deaths.some(d => d.isCheatDeath);
                  const showBothStats = config.enableCheatDeath && hasAnyCheatDeaths;

                  return (
                    <div key={player} style={{ background: '#2d3238', borderRadius: '8px', overflow: 'hidden' }}>
                      <div 
                        onClick={() => togglePlayerExpanded(player)}
                        style={{ 
                          padding: '16px', 
                          cursor: 'pointer', 
                          display: 'flex', 
                          justifyContent: 'space-between', 
                          alignItems: 'center',
                          transition: 'background 0.2s'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                          {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          <div style={{ flex: 1 }}>
                            <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '600', color: '#ffffff' }}>{player}</h3>
                            
                            {showBothStats ? (
                              // Show BOTH statistics when cheat death detection is on
                              <div style={{ margin: '4px 0 0', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                <p style={{ margin: 0, color: '#e2e8f0' }}>
                                  <span style={{ color: '#8b92a0' }}>Real only:</span> {realDeaths} deaths / {pulls} pulls
                                  <span style={{ 
                                    marginLeft: '8px',
                                    color: getPercentageColor(realRate, allRealRates),
                                    fontWeight: '600'
                                  }}>
                                    ({realRate.toFixed(1)}%)
                                  </span>
                                </p>
                                <p style={{ margin: 0, color: '#34d399' }}>
                                  <span style={{ color: '#8b92a0' }}>With cheat:</span> {totalDeaths} deaths / {pulls} pulls
                                  <span style={{ 
                                    marginLeft: '8px',
                                    color: getPercentageColor(totalRate, allTotalRates),
                                    fontWeight: '600'
                                  }}>
                                    ({totalRate.toFixed(1)}%)
                                  </span>
                                </p>
                              </div>
                            ) : (
                              // Show simple stats when no cheat deaths
                              <p style={{ margin: '2px 0 0', fontSize: '12px', color: '#8b92a0' }}>
                                {realDeaths} deaths / {pulls} pulls
                              </p>
                            )}
                          </div>
                        </div>
                        
                        <div style={{ fontSize: '18px', fontWeight: '700', color: getPercentageColor(realRate, allRealRates) }}>
                          {realRate.toFixed(1)}%
                        </div>
                      </div>

                      {isExpanded && (
                        <div style={{ padding: '0 16px 16px', borderTop: '1px solid #2d3238' }}>
                          {Object.entries(deathsByBoss).map(([boss, bossDeaths]) => {
                            const bossPulls = data.bossParticipation[boss]?.[player]?.length || 0;
                            const realDeathCount = bossDeaths.length;
                            const totalBossDeaths = totalDeathsByBoss[boss] || [];
                            const totalDeathCount = totalBossDeaths.length;
                            const cheatDeathCount = totalBossDeaths.filter(d => d.isCheatDeath).length;
                            const bossRealRate = bossPulls > 0 ? (realDeathCount / bossPulls * 100) : 0;
                            const bossTotalRate = bossPulls > 0 ? (totalDeathCount / bossPulls * 100) : 0;
                            
                            return (
                            <div key={boss} style={{ marginTop: '12px' }}>
                              <h4 style={{ margin: '0 0 10px', fontSize: '14px', fontWeight: '600', color: '#f97316' }}>
                                {boss}
                                {showBothStats && cheatDeathCount > 0 ? (
                                  <div style={{ fontSize: '12px', fontWeight: '400', marginTop: '4px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                    <span style={{ color: '#cbd5e1' }}>
                                      Real: {realDeathCount} / {bossPulls} pulls - {bossRealRate.toFixed(1)}%
                                    </span>
                                    <span style={{ color: '#34d399' }}>
                                      With cheat: {totalDeathCount} / {bossPulls} pulls - {bossTotalRate.toFixed(1)}%
                                    </span>
                                  </div>
                                ) : (
                                  <span style={{ fontSize: '12px', fontWeight: '400', color: '#cbd5e1', marginLeft: '8px' }}>
                                    ({realDeathCount} / {bossPulls} pulls - {bossRealRate.toFixed(1)}%)
                                  </span>
                                )}
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
                                {(showBothStats ? totalBossDeaths : bossDeaths)
                                  .filter(death => death.abilityName && death.abilityName !== 'Unknown')
                                  .map((death, idx) => (
                                  <div key={idx} style={{ 
                                    display: 'flex', 
                                    justifyContent: 'space-between', 
                                    alignItems: 'center',
                                    padding: '8px 10px',
                                    background: death.isCheatDeath ? '#2d3a2d' : '#252930',
                                    borderLeft: death.isCheatDeath ? '3px solid #34d399' : 'none',
                                    borderRadius: '4px',
                                    fontSize: '12px'
                                  }}>
                                    <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flex: 1 }}>
                                      <span style={{ color: '#64748b', minWidth: '55px' }}>Pull #{death.pullNo}</span>
                                      <span style={{ color: '#8b92a0', minWidth: '110px' }}>{formatTimestamp(death.absTs)}</span>
                                      {death.isCheatDeath && (
                                        <span style={{ 
                                          color: '#34d399', 
                                          fontSize: '10px', 
                                          fontWeight: '600',
                                          padding: '2px 6px',
                                          background: '#1a2e1a',
                                          borderRadius: '3px',
                                          marginRight: '8px'
                                        }}>
                                          CHEAT
                                        </span>
                                      )}
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
              );
            })()}
          </div>
        )}
      </div>

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