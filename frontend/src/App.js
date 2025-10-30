import React, { useState } from 'react';
import { Search, AlertCircle, Loader2, Filter, ChevronDown, ChevronRight, ExternalLink, ArrowUpDown, ArrowUp, ArrowDown, X } from 'lucide-react';

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
    cutoffDate: '',
    authorFilters: '',
    characterGroups: ''
  });

  const [includeCheatEvents, setIncludeCheatEvents] = useState(false);
  const [cancelCtrl, setCancelCtrl] = useState(null);

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
        } catch {
          throw new Error('Invalid JSON format for character groups');
        }
      }

      const payload = {
        ...config,
        authorFilters: config.authorFilters.split(',').map(s => s.trim()).filter(Boolean),
        characterGroups,
        includeCheatEvents
      };

      const controller = new AbortController();
      const signal = controller.signal;
      setCancelCtrl(controller);

      const response = await fetch('https://deathwarcraftlogs-api.onrender.com/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal
      });
      if (!response.ok) throw new Error('Failed to connect to server');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      let lastChunkAt = Date.now();
      const IDLE_LIMIT_MS = 45000;
      const idleWatch = setInterval(() => {
        if (Date.now() - lastChunkAt > IDLE_LIMIT_MS) {
          controller.abort();
          clearInterval(idleWatch);
          setError('No data received for 45s. Canceled (throttle/slow page). Try again.');
          setLoading(false);
          setLoadingStage('');
        }
      }, 5000);

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          lastChunkAt = Date.now();

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const chunk = JSON.parse(line.slice(6));
            if (chunk.error) {
              throw new Error(chunk.error);
            } else if (chunk.stage) {
              setLoadingStage(chunk.message || chunk.stage);
            } else if (chunk.result) {
              setData(chunk.result);
              setLoadingStage('');
              setLoading(false);
            }
          }
        }
      } finally {
        clearInterval(idleWatch);
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
      setLoading(false);
      setLoadingStage('');
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
      grid[p].overall = { deaths: totalDeaths, pulls: totalPulls, rate: totalPulls > 0 ? (totalDeaths / totalPulls * 100) : null };
    });
    retu
