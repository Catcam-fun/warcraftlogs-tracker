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

      const response = await fetch('https://deathwarcraftlogs-api.onrender.com/api/analyze', {
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
              window.deathTrackerData = data.result;
              
              // Add export helper function
              window.exportDeathData = function(playerName = null) {
                const cutoff = 2; // Current cutoff value
                const events = window.deathTrackerData.events;
                const pullCutoffTimestamps = window.deathTrackerData.pullCutoffTimestamps;
                
                if (playerName) {
                  // Export specific player's data
                  const playerEvents = events[playerName] || [];
                  const output = {
                    player: playerName,
                    totalEvents: playerEvents.length,
                    byBoss: {},
                    pullBreakdown: []
                  };
                  
                  // Group by boss
                  playerEvents.forEach(ev => {
                    if (!output.byBoss[ev.boss]) {
                      output.byBoss[ev.boss] = { real: [], cheat: [] };
                    }
                    if (ev.isCheatDeath) {
                      output.byBoss[ev.boss].cheat.push(ev);
                    } else {
                      output.byBoss[ev.boss].real.push(ev);
                    }
                  });
                  
                  // Add pull-by-pull breakdown
                  const pullMap = {};
                  playerEvents.forEach(ev => {
                    const pullKey = `${ev.reportId}_${ev.fightId}`;
                    if (!pullMap[pullKey]) {
                      pullMap[pullKey] = {
                        pullKey,
                        boss: ev.boss,
                        real: [],
                        cheat: [],
                        cutoffTs: pullCutoffTimestamps[pullKey]?.[cutoff]
                      };
                    }
                    if (ev.isCheatDeath) {
                      pullMap[pullKey].cheat.push({
                        timestamp: ev.timestamp,
                        ability: ev.abilityName,
                        included: pullMap[pullKey].cutoffTs !== undefined && ev.timestamp <= pullMap[pullKey].cutoffTs
                      });
                    } else {
                      pullMap[pullKey].real.push({
                        timestamp: ev.timestamp,
                        ability: ev.abilityName,
                        included: pullMap[pullKey].cutoffTs !== undefined && ev.timestamp <= pullMap[pullKey].cutoffTs
                      });
                    }
                  });
                  
                  output.pullBreakdown = Object.values(pullMap);
                  
                  console.log(JSON.stringify(output, null, 2));
                  return output;
                } else {
                  // Export summary of all players
                  const output = {
                    totalPlayers: Object.keys(events).length,
                    cutoffUsed: cutoff,
                    playerSummaries: {}
                  };
                  
                  Object.keys(events).forEach(player => {
                    const playerEvents = events[player];
                    output.playerSummaries[player] = {
                      totalEvents: playerEvents.length,
                      realDeaths: playerEvents.filter(ev => !ev.isCheatDeath).length,
                      cheatDeaths: playerEvents.filter(ev => ev.isCheatDeath).length,
                      bosses: [...new Set(playerEvents.map(ev => ev.boss))]
                    };
                  });
                  
                  console.log(JSON.stringify(output, null, 2));
                  return output;
                }
              };
              
              // Character name normalization helper
              window.normalizeCharacterName = function(name) {
                if (!name) return name;
                // Remove accents and diacritics (same logic as backend)
                return name.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
              };
              
              // Improved export function with normalization
              window.exportAndCopy = function() {
                if (!window.deathTrackerData) {
                  console.error("❌ No deathTrackerData found! Run analysis first.");
                  return;
                }

                console.log("📊 Building export data...");
                
                const data = window.deathTrackerData;
                const events = data.events;
                const pullsMap = new Map();
                
                // Build pulls from events with name normalization
                for (const [playerName, playerEvents] of Object.entries(events)) {
                  for (const event of playerEvents) {
                    const pullKey = `${event.reportId}_${event.fightId}`;
                    if (!pullsMap.has(pullKey)) {
                      pullsMap.set(pullKey, {
                        reportId: event.reportId,
                        fightId: event.fightId,
                        boss: event.boss,
                        bossId: event.bossId,
                        pullNo: event.pullNo,
                        isKill: event.isKill,
                        deaths: []
                      });
                    }
                    pullsMap.get(pullKey).deaths.push({
                      name: window.normalizeCharacterName(event.player),
                      originalCharacter: event.originalCharacter,
                      timestamp: event.timestamp,
                      absTs: event.absTs,
                      abilityName: event.abilityName,
                      isCheatDeath: event.isCheatDeath,
                      rankWithinPull: event.rankWithinPull,
                      phase: event.phase
                    });
                  }
                }
                
                const rawPulls = Array.from(pullsMap.values()).sort((a, b) => a.pullNo - b.pullNo);
                const exportData = {
                  rawPulls: rawPulls,
                  meta: data.meta || {},
                  generatedAt: new Date().toISOString(),
                  source: "death-tracker-frontend"
                };
                
                // Show summary
                const totalDeaths = rawPulls.reduce((sum, p) => sum + p.deaths.length, 0);
                console.log(`\n✅ Export ready!`);
                console.log(`   ${rawPulls.length} pulls, ${totalDeaths} deaths`);
                console.log(`   ${JSON.stringify(exportData).length.toLocaleString()} characters`);
                
                // Try Clipboard API first, then fall back to copy() utility
                const jsonString = JSON.stringify(exportData, null, 2);
                
                // Method 1: Try Clipboard API (works in browser console)
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  navigator.clipboard.writeText(jsonString)
                    .then(() => {
                      console.log(`\n🎉 DATA COPIED TO CLIPBOARD!`);
                      console.log(`   Paste into a file called: death_data.json`);
                    })
                    .catch(() => {
                      // Method 2: Try Chrome DevTools copy() utility
                      try {
                        // eslint-disable-next-line no-undef
                        copy(exportData);
                        console.log(`\n🎉 DATA COPIED TO CLIPBOARD!`);
                        console.log(`   Paste into a file called: death_data.json`);
                      } catch (e) {
                        console.error("❌ Clipboard methods failed");
                        console.log("\n📋 Copy this manually:");
                        console.log(jsonString);
                      }
                    });
                } else {
                  // Method 2: Try Chrome DevTools copy() utility
                  try {
                    // eslint-disable-next-line no-undef
                    copy(exportData);
                    console.log(`\n🎉 DATA COPIED TO CLIPBOARD!`);
                    console.log(`   Paste into a file called: death_data.json`);
                  } catch (e) {
                    console.error("❌ Clipboard not available");
                    console.log("\n📋 Copy this manually:");
                    console.log(jsonString);
                  }
                }
                
                return exportData;
              };
              
              console.log("🎯 Analysis complete! Data exposed as window.deathTrackerData");
              console.log("💾 Export options:");
              console.log("  - window.exportAndCopy() - Copy full audit data (RECOMMENDED)");
              console.log("  - window.exportDeathData() - Export all deaths");
              console.log("  - window.exportDeathData('PlayerName') - Export specific player");
              console.log("📊 Summary:");
              console.log(`  Players: ${Object.keys(data.result.events).length}`);
              console.log(`  pullCutoffTimestamps: ${data.result.pullCutoffTimestamps ? 'Present' : 'MISSING'}`);
              
              if (data.result.pullCutoffTimestamps) {
                const sampleKey = Object.keys(data.result.pullCutoffTimestamps)[0];
                console.log(`  Sample cutoffs:`, data.result.pullCutoffTimestamps[sampleKey]);
              }
              
              // Check for missing deaths by boss
              const deathsByBoss = {};
              Object.values(data.result.events).flat().forEach(ev => {
                if (!deathsByBoss[ev.boss]) deathsByBoss[ev.boss] = 0;
                deathsByBoss[ev.boss]++;
              });
              console.log("  Deaths by boss:", deathsByBoss);
              
              setLoadingStage('');
              setLoading(false);
              setAbortController(null);
            }
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        setError('Analysis cancelled');
      } else {
        setError(err.message);
      }
      setLoadingStage('');
      setLoading(false);
      setAbortController(null);
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

    const hasCheatDeaths = config.enableCheatDeath;
    
    for (const player of Object.keys(eventsAll)) {
      const allPlayerEvents = eventsAll[player].filter(
        ev => (selectedBosses.size === 0 || selectedBosses.has(ev.boss)) &&
        ev.abilityName && ev.abilityName !== 'Unknown'
      );
      
      if (!allPlayerEvents.length) continue;

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

      // WINDOW-BASED FILTERING WITH MASS DEATH HANDLING:
      // 1. Get first X real deaths (by rankWithinPull)
      // 2. Use pullCutoffTimestamps to find the correct cutoff (handles mass deaths)
      // 3. Include cheat deaths that occurred BEFORE the cutoff
      
      // Get pullCutoffTimestamps from data (provided by backend)
      const pullCutoffTimestamps = data.pullCutoffTimestamps || {};
      
      // DEBUG: Log if pullCutoffTimestamps is missing
      if (Object.keys(pullCutoffTimestamps).length === 0) {
        console.warn("⚠️ pullCutoffTimestamps is empty or missing!");
      }
      
      // Group events by pull to apply window logic per-pull
      const eventsByPull = {};
      allPlayerEvents.forEach(ev => {
        const pullKey = `${ev.reportId}_${ev.fightId}`;
        if (!eventsByPull[pullKey]) {
          eventsByPull[pullKey] = { real: [], cheat: [], boss: ev.boss };
        }
        if (ev.isCheatDeath) {
          eventsByPull[pullKey].cheat.push(ev);
        } else {
          eventsByPull[pullKey].real.push(ev);
        }
      });
      
      // Collect deaths that fall within the cutoff window
      const realDeaths = [];
      const cheatDeaths = [];
      
      Object.entries(eventsByPull).forEach(([pullKey, pullData]) => {
        // Get the cutoff timestamp for this pull (mass-death-aware from backend)
        let pullCutoffTs = pullCutoffTimestamps[pullKey]?.[cutoff];
        
        // If exact cutoff doesn't exist, use the highest available cutoff
        // (handles case where user selected cutoff=5 but pull only has 2 deaths)
        if (pullCutoffTs === undefined) {
          const availableCutoffs = pullCutoffTimestamps[pullKey];
          if (availableCutoffs && Object.keys(availableCutoffs).length > 0) {
            // Get the highest cutoff timestamp available
            const maxAvailableCutoff = Math.max(...Object.keys(availableCutoffs).map(Number));
            pullCutoffTs = availableCutoffs[maxAvailableCutoff];
            
            // DEBUG log
            if (pullData.real.length > 0 || pullData.cheat.length > 0) {
              console.log(`ℹ️  Pull ${pullKey}: Using cutoff=${maxAvailableCutoff} timestamp (${(pullCutoffTs/1000).toFixed(1)}s) instead of cutoff=${cutoff}`);
            }
          } else {
            // No cutoff timestamps at all - pull contributes 0 deaths
            if (pullData.real.length > 0 || pullData.cheat.length > 0) {
              console.log(`⚠️  Pull ${pullKey}: No cutoff timestamps available, contributing 0 deaths`);
            }
            return; // Skip this pull
          }
        }
        
        // DEBUG: Show death timestamps for debugging when no deaths pass filter
        if (pullData.real.length > 0) {
          const wouldPass = pullData.real.filter(ev => ev.timestamp !== undefined && ev.timestamp <= pullCutoffTs);
          if (wouldPass.length === 0) {
            console.log(`❌ Pull ${pullKey} has ${pullData.real.length} real deaths but NONE pass filter!`);
            console.log(`   Cutoff timestamp: ${pullCutoffTs}ms`);
            pullData.real.slice(0, 3).forEach(ev => {
              console.log(`   Death: timestamp=${ev.timestamp}, absTs=${ev.absTs}, player=${ev.player}`);
              if (ev.timestamp !== undefined) {
                console.log(`   Check: ${ev.timestamp} <= ${pullCutoffTs} = ${ev.timestamp <= pullCutoffTs}`);
              } else {
                console.log(`   ERROR: timestamp is undefined!`);
              }
            });
          }
        }
        
        // Filter REAL deaths that occurred BEFORE OR AT the cutoff timestamp
        // (mass deaths are already excluded by backend's timestamp calculation)
        const pullRealDeaths = pullData.real.filter(ev => 
          ev.timestamp !== undefined && ev.timestamp <= pullCutoffTs
        );
        
        realDeaths.push(...pullRealDeaths);
        
        // Filter CHEAT deaths that occurred BEFORE OR AT the same cutoff timestamp
        const pullCheatDeaths = pullData.cheat.filter(ev => 
          ev.timestamp !== undefined && ev.timestamp <= pullCutoffTs
        );
        cheatDeaths.push(...pullCheatDeaths);
        
        // DEBUG: Log for pulls with cheat deaths
        if (pullData.cheat.length > 0 || pullKey.includes("11")) {
          console.log(`🔍 Pull ${pullKey} (${pullData.boss}):`);
          console.log(`  Real deaths in cutoff: ${pullRealDeaths.length}`);
          console.log(`  Cutoff timestamp: ${pullCutoffTs}ms (${(pullCutoffTs/1000).toFixed(1)}s)`);
          console.log(`  Cheat deaths in pull: ${pullData.cheat.length}`);
          console.log(`  Cheat deaths included: ${pullCheatDeaths.length}`);
          
          pullCheatDeaths.forEach(ev => {
            console.log(`    ✓ ${ev.player} cheat at ${(ev.timestamp/1000).toFixed(1)}s (<= ${(pullCutoffTs/1000).toFixed(1)}s)`);
          });
          
          const excluded = pullData.cheat.filter(ev => 
            ev.timestamp === undefined || ev.timestamp > pullCutoffTs
          );
          excluded.forEach(ev => {
            console.log(`    ✗ ${ev.player} cheat at ${(ev.timestamp/1000).toFixed(1)}s (> ${(pullCutoffTs/1000).toFixed(1)}s)`);
          });
        }
      });
      
      const realDeathCount = realDeaths.length;
      const cheatDeathCount = cheatDeaths.length;
      const totalDeathCount = realDeathCount + cheatDeathCount;
      
      const realRate = pulls > 0 ? (realDeathCount / pulls * 100) : 0;
      const totalRate = pulls > 0 ? (totalDeathCount / pulls * 100) : 0;
      
      if (searchQuery && !player.toLowerCase().includes(searchQuery.toLowerCase())) {
        continue;
      }

      // Group deaths by boss
      const deathsByBoss = {};
      realDeaths.forEach(ev => {
        if (!deathsByBoss[ev.boss]) {
          deathsByBoss[ev.boss] = [];
        }
        deathsByBoss[ev.boss].push(ev);
      });
      
      const cheatDeathsByBoss = {};
      cheatDeaths.forEach(ev => {
        if (!cheatDeathsByBoss[ev.boss]) {
          cheatDeathsByBoss[ev.boss] = [];
        }
        cheatDeathsByBoss[ev.boss].push(ev);
      });
      
      // Total deaths by boss = real + cheat
      const totalDeathsByBoss = {};
      realDeaths.forEach(ev => {
        if (!totalDeathsByBoss[ev.boss]) {
          totalDeathsByBoss[ev.boss] = [];
        }
        totalDeathsByBoss[ev.boss].push(ev);
      });
      cheatDeaths.forEach(ev => {
        if (!totalDeathsByBoss[ev.boss]) {
          totalDeathsByBoss[ev.boss] = [];
        }
        totalDeathsByBoss[ev.boss].push(ev);
      });

      // Top abilities for real deaths only
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
        realDeaths: realDeathCount,
        totalDeaths: totalDeathCount,
        cheatDeaths: cheatDeathCount,
        pulls, 
        realRate,
        totalRate,
        hasCheatDeaths,
        deathsByBoss,
        cheatDeathsByBoss,  // NEW: separate cheat deaths by boss
        totalDeathsByBoss,
        topAbilitiesByBoss
      });
    }

    return stats.sort((a, b) => b.realRate - a.realRate || b.realDeaths - a.realDeaths);
  };

  const getOverviewData = () => {
    if (!data) return { bosses: [], players: [], grid: {} };

    // Filter bosses based on selection
    const allBosses = Object.keys(data.bossParticipation).sort();
    const bosses = selectedBosses.size === 0 
      ? allBosses 
      : allBosses.filter(boss => selectedBosses.has(boss));
    
    const players = Object.keys(data.events).sort();
    const grid = {};

    const hasCheatDeaths = config.enableCheatDeath;
    const pullCutoffTimestamps = data.pullCutoffTimestamps || {};

    players.forEach(player => {
      grid[player] = {};
      
      const allPlayerEvents = data.events[player] || [];
      
      bosses.forEach(boss => {
        const bossPulls = data.bossParticipation[boss]?.[player]?.length || 0;
        
        // Window-based filtering for this boss with mass death handling
        const playerBossEvents = allPlayerEvents.filter(ev => ev.boss === boss);
        const bossPullMap = {};
        playerBossEvents.forEach(ev => {
          const pullKey = `${ev.reportId}_${ev.fightId}`;
          if (!bossPullMap[pullKey]) {
            bossPullMap[pullKey] = { real: [], cheat: [] };
          }
          if (ev.isCheatDeath) {
            bossPullMap[pullKey].cheat.push(ev);
          } else {
            bossPullMap[pullKey].real.push(ev);
          }
        });
        
        let bossRealDeaths = 0;
        let bossCheatDeaths = 0;
        Object.entries(bossPullMap).forEach(([pullKey, pullData]) => {
          // Get the cutoff timestamp for this pull
          let pullCutoffTs = pullCutoffTimestamps[pullKey]?.[cutoff];
          
          // If exact cutoff doesn't exist, use the highest available
          if (pullCutoffTs === undefined) {
            const availableCutoffs = pullCutoffTimestamps[pullKey];
            if (availableCutoffs && Object.keys(availableCutoffs).length > 0) {
              const maxAvailableCutoff = Math.max(...Object.keys(availableCutoffs).map(Number));
              pullCutoffTs = availableCutoffs[maxAvailableCutoff];
            } else {
              return; // No cutoffs, skip this pull
            }
          }
          
          // Filter real deaths by timestamp
          const pullRealDeaths = pullData.real.filter(ev => 
            ev.timestamp !== undefined && ev.timestamp <= pullCutoffTs
          );
          bossRealDeaths += pullRealDeaths.length;
          
          // Filter cheat deaths by same timestamp
          if (hasCheatDeaths) {
            bossCheatDeaths += pullData.cheat.filter(
              ev => ev.timestamp !== undefined && ev.timestamp <= pullCutoffTs
            ).length;
          }
        });
        
        const bossTotalDeaths = bossRealDeaths + bossCheatDeaths;
        
        const realRate = bossPulls > 0 ? (bossRealDeaths / bossPulls * 100) : null;
        const totalRate = bossPulls > 0 ? (bossTotalDeaths / bossPulls * 100) : null;
        
        grid[player][boss] = { 
          deaths: bossRealDeaths,
          totalDeaths: bossTotalDeaths,
          pulls: bossPulls, 
          rate: realRate,
          totalRate: totalRate,
          hasCheatDeaths
        };
      });

      // Calculate overall for selected bosses
      let totalPulls = 0;
      let totalRealDeaths = 0;
      let totalWithCheatDeaths = 0;
      
      if (selectedBosses.size === 0) {
        // Use window-based filtering for all bosses
        totalPulls = data.pullParticipation[player]?.length || 0;
        
        const pullMap = {};
        allPlayerEvents.forEach(ev => {
          const pullKey = `${ev.reportId}_${ev.fightId}`;
          if (!pullMap[pullKey]) {
            pullMap[pullKey] = { real: [], cheat: [] };
          }
          if (ev.isCheatDeath) {
            pullMap[pullKey].cheat.push(ev);
          } else {
            pullMap[pullKey].real.push(ev);
          }
        });
        
        let cheatDeathsCount = 0;
        Object.entries(pullMap).forEach(([pullKey, pullData]) => {
          // Get the cutoff timestamp for this pull
          let pullCutoffTs = pullCutoffTimestamps[pullKey]?.[cutoff];
          
          // If exact cutoff doesn't exist, use the highest available
          if (pullCutoffTs === undefined) {
            const availableCutoffs = pullCutoffTimestamps[pullKey];
            if (availableCutoffs && Object.keys(availableCutoffs).length > 0) {
              const maxAvailableCutoff = Math.max(...Object.keys(availableCutoffs).map(Number));
              pullCutoffTs = availableCutoffs[maxAvailableCutoff];
            } else {
              return; // No cutoffs, skip this pull
            }
          }
          
          // Filter real deaths by timestamp
          const pullRealDeaths = pullData.real.filter(ev => 
            ev.timestamp !== undefined && ev.timestamp <= pullCutoffTs
          );
          totalRealDeaths += pullRealDeaths.length;
          
          // Filter cheat deaths by same timestamp
          if (hasCheatDeaths) {
            cheatDeathsCount += pullData.cheat.filter(
              ev => ev.timestamp !== undefined && ev.timestamp <= pullCutoffTs
            ).length;
          }
        });
        
        totalWithCheatDeaths = totalRealDeaths + cheatDeathsCount;
      } else {
        bosses.forEach(boss => {
          totalPulls += data.bossParticipation[boss]?.[player]?.length || 0;
          totalRealDeaths += grid[player][boss].deaths;
          totalWithCheatDeaths += grid[player][boss].totalDeaths;
        });
      }
      
      grid[player].overall = {
        deaths: totalRealDeaths,
        totalDeaths: totalWithCheatDeaths,
        pulls: totalPulls,
        rate: totalPulls > 0 ? (totalRealDeaths / totalPulls * 100) : null,
        totalRate: totalPulls > 0 ? (totalWithCheatDeaths / totalPulls * 100) : null,
        hasCheatDeaths
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
    <div style={{ minHeight: '100vh', background: '#0d1117', color: '#e2e8f0', fontFamily: 'system-ui, -apple-system, sans-serif', position: 'relative', overflow: 'hidden' }}>
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
          zIndex: 10000
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

      {/* Halloween Decorations */}
      <div style={{ position: 'fixed', top: 0, left: 0, width: '200px', height: '200px', opacity: 0.15, pointerEvents: 'none', zIndex: 1 }}>
        <svg viewBox="0 0 200 200" style={{ width: '100%', height: '100%' }}>
          <path d="M0,0 L100,100 M0,20 L100,100 M0,40 L100,100 M0,60 L100,100 M0,80 L100,100" stroke="#fff" strokeWidth="1" fill="none"/>
          <path d="M0,0 L100,100 M20,0 L100,100 M40,0 L100,100 M60,0 L100,100 M80,0 L100,100" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="60" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="40" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="20" stroke="#fff" strokeWidth="1" fill="none"/>
        </svg>
      </div>
      
      <div style={{ position: 'fixed', top: 0, right: 0, width: '200px', height: '200px', opacity: 0.15, pointerEvents: 'none', zIndex: 1, transform: 'scaleX(-1)' }}>
        <svg viewBox="0 0 200 200" style={{ width: '100%', height: '100%' }}>
          <path d="M0,0 L100,100 M0,20 L100,100 M0,40 L100,100 M0,60 L100,100 M0,80 L100,100" stroke="#fff" strokeWidth="1" fill="none"/>
          <path d="M0,0 L100,100 M20,0 L100,100 M40,0 L100,100 M60,0 L100,100 M80,0 L100,100" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="60" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="40" stroke="#fff" strokeWidth="1" fill="none"/>
          <circle cx="100" cy="100" r="20" stroke="#fff" strokeWidth="1" fill="none"/>
        </svg>
      </div>

      <div style={{ position: 'fixed', top: '15%', right: '20%', fontSize: '32px', opacity: 0.4, animation: 'float 6s ease-in-out infinite', pointerEvents: 'none', zIndex: 1 }}>
        🦇
      </div>
      <div style={{ position: 'fixed', top: '25%', left: '15%', fontSize: '28px', opacity: 0.3, animation: 'float 8s ease-in-out infinite 2s', pointerEvents: 'none', zIndex: 1 }}>
        🦇
      </div>
      <div style={{ position: 'fixed', top: '40%', right: '10%', fontSize: '24px', opacity: 0.25, animation: 'float 7s ease-in-out infinite 4s', pointerEvents: 'none', zIndex: 1 }}>
        🦇
      </div>

      <div style={{ position: 'fixed', top: '20px', left: '20px', fontSize: '48px', opacity: 0.5, pointerEvents: 'none', zIndex: 1 }}>
        🎃
      </div>
      <div style={{ position: 'fixed', top: '20px', right: '20px', fontSize: '48px', opacity: 0.5, pointerEvents: 'none', zIndex: 1 }}>
        🎃
      </div>

      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px', position: 'relative', zIndex: 2 }}>
        <div style={{ background: '#1a1d23', borderRadius: '12px', padding: '24px', marginBottom: '20px', border: '1px solid #2d3238' }}>
          <h1 style={{ margin: '0 0 6px', fontSize: '28px', fontWeight: '700', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '10px', justifyContent: 'center' }}>
            <span>🎃</span>
            WarcraftLogs Death Tracker
            <span>💀</span>
          </h1>
          <p style={{ color: '#8b92a0', margin: 0, textAlign: 'center', fontSize: '14px' }}>Analyze raid deaths and performance metrics 👻</p>
        </div>

        {loading && (
          <div style={{ 
            position: 'fixed', 
            top: 0, 
            left: 0, 
            right: 0, 
            bottom: 0, 
            background: 'rgba(13, 17, 23, 0.98)', 
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
                border: '4px solid #2d3238', 
                borderTop: '4px solid #f97316',
                borderRadius: '50%',
                animation: 'spin 1s linear infinite',
                margin: '0 auto 24px'
              }} />
              <h2 style={{ margin: '0 0 16px', fontSize: '22px', fontWeight: '600', color: '#ffffff' }}>
                Analyzing Reports
              </h2>
              <div style={{ 
                padding: '14px 18px', 
                background: '#1a1d23', 
                borderRadius: '8px',
                border: '1px solid #2d3238',
                marginBottom: '16px',
                minHeight: '60px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <p style={{ 
                  margin: 0, 
                  fontSize: '14px', 
                  color: '#f97316', 
                  fontWeight: '500',
                  lineHeight: '1.6'
                }}>
                  {loadingStage || 'Starting analysis...'}
                </p>
              </div>
              <p style={{ color: '#8b92a0', fontSize: '13px', margin: '0 0 16px', lineHeight: '1.6' }}>
                Processing data from WarcraftLogs...<br />
                This may take a while
              </p>
              <button
                onClick={handleCancel}
                style={{
                  padding: '10px 24px',
                  background: '#ef4444',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '6px',
                  fontSize: '14px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  transition: 'all 0.2s'
                }}
                onMouseOver={(e) => e.target.style.background = '#dc2626'}
                onMouseOut={(e) => e.target.style.background = '#ef4444'}
              >
                Cancel Analysis
              </button>
            </div>
          </div>
        )}

        {!data && (
          <div style={{ background: '#1a1d23', borderRadius: '12px', padding: '24px', marginBottom: '20px', border: '1px solid #2d3238' }}>
            <h2 style={{ margin: '0 0 24px', fontSize: '18px', fontWeight: '600', color: '#ffffff' }}>Configuration</h2>
            
            <div style={{ marginBottom: '24px', padding: '14px 16px', background: 'rgba(249, 115, 22, 0.1)', border: '1px solid rgba(249, 115, 22, 0.3)', borderRadius: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'start', gap: '10px' }}>
                <div style={{ fontSize: '18px' }}>🎃</div>
                <div>
                  <h3 style={{ margin: '0 0 6px', fontSize: '14px', fontWeight: '600', color: '#f97316' }}>
                    Need API Credentials?
                  </h3>
                  <p style={{ margin: '0 0 6px', fontSize: '12px', color: '#cbd5e1', lineHeight: '1.6' }}>
                    You need a WarcraftLogs V2 API Client ID and Secret to use this tool.
                  </p>
                  <ol style={{ margin: '6px 0 0 16px', padding: 0, fontSize: '12px', color: '#cbd5e1', lineHeight: '1.7' }}>
                    <li>Go to <a href="https://www.warcraftlogs.com/api/clients/" target="_blank" rel="noopener noreferrer" style={{ color: '#f97316', textDecoration: 'underline' }}>WarcraftLogs API Clients</a></li>
                    <li>Click "Create a Client"</li>
                    <li>Enter a name (e.g., "Death Tracker")</li>
                    <li>For redirect URL, enter the website URL or just use: <code style={{ background: '#252930', padding: '2px 6px', borderRadius: '3px', fontSize: '11px' }}>http://localhost</code></li>
                    <li><strong>Do NOT check</strong> the "Public Client" box</li>
                    <li>Click "Create" and copy your Client ID and Client Secret</li>
                  </ol>
                </div>
              </div>
            </div>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '18px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Client ID (V2 API) *
                  </label>
                  <input
                    type="text"
                    name="clientId"
                    value={config.clientId}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Client Secret (V2 API) *
                  </label>
                  <input
                    type="password"
                    name="clientSecret"
                    value={config.clientSecret}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '18px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Guild Name *
                  </label>
                  <input
                    type="text"
                    name="guildName"
                    value={config.guildName}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Examples: Do Over, Complexity Limit, Method
                  </p>
                </div>

                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Server *
                  </label>
                  <input
                    type="text"
                    name="server"
                    value={config.server}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Remove spaces/apostrophes - Examples: Thrall, Area52, TwistingNether
                  </p>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '18px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Region *
                  </label>
                  <select
                    name="region"
                    value={config.region}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  >
                    <option value="us">US</option>
                    <option value="eu">EU</option>
                    <option value="kr">KR</option>
                    <option value="tw">TW</option>
                    <option value="cn">CN</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Difficulty *
                  </label>
                  <select
                    name="difficulty"
                    value={config.difficulty}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  >
                    <option value="3">Normal</option>
                    <option value="4">Heroic</option>
                    <option value="5">Mythic</option>
                  </select>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '18px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Report Zone ID
                  </label>
                  <input
                    type="text"
                    name="reportZone"
                    value={config.reportZone}
                    onChange={handleInputChange}
                    placeholder="44"
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    The raid zone ID (e.g., 44 for Manaforge Omega) - find in WarcraftLogs URLs
                  </p>
                </div>

                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Fight Zone ID
                  </label>
                  <input
                    type="text"
                    name="fightZone"
                    value={config.fightZone}
                    onChange={handleInputChange}
                    placeholder="2810"
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Same for entire raid (e.g., 2810 for Manaforge Omega) - matches Report Zone
                  </p>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '18px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Cutoff Date
                  </label>
                  <input
                    type="date"
                    name="cutoffDate"
                    value={config.cutoffDate}
                    onChange={handleInputChange}
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Only analyze reports before this date
                  </p>
                </div>

                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
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
                    style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Track only the first X deaths per pull (1-10)
                  </p>
                </div>
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                  Author Filters <span style={{ fontSize: '11px', color: '#64748b', fontWeight: '400' }}>(optional, comma-separated)</span>
                </label>
                <input
                  type="text"
                  name="authorFilters"
                  value={config.authorFilters}
                  onChange={handleInputChange}
                  placeholder="PlayerName1, PlayerName2, PlayerName3"
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                />
                <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                  Only analyze reports uploaded by these players
                </p>
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                  Character Groups <span style={{ fontSize: '11px', color: '#64748b', fontWeight: '400' }}>(optional, JSON format)</span>
                </label>
                <textarea
                  name="characterGroups"
                  value={config.characterGroups}
                  onChange={handleInputChange}
                  placeholder='{"MainCharacter": ["AltName1", "AltName2"], "AnotherMain": ["TheirAlt"]}'
                  rows="3"
                  style={{ width: '100%', padding: '10px 14px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', fontFamily: 'monospace', resize: 'vertical', boxSizing: 'border-box' }}
                />
                <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                  Merge alt characters with their mains for combined statistics
                </p>
              </div>

              <div style={{ marginTop: '8px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={config.enableCheatDeath}
                    onChange={(e) => setConfig({...config, enableCheatDeath: e.target.checked})}
                    style={{ cursor: 'pointer', width: '16px', height: '16px' }}
                  />
                  <span>Enable cheat death detection</span>
                  <span style={{ fontSize: '11px', color: '#f59e0b', fontWeight: '400' }}>(+20-30s slower)</span>
                </label>
                <p style={{ margin: '4px 0 0 24px', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                  Detects deaths prevented by Cauterize, Spirit of Redemption, Cheat Death, etc. Adds 1 API query per report.
                </p>
              </div>
            </div>

            {error && (
              <div style={{ marginTop: '20px', padding: '10px 14px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
                <AlertCircle size={18} />
                <span>{error}</span>
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={loading}
              style={{ marginTop: '24px', padding: '12px 24px', background: loading ? '#3d424a' : '#f97316', border: 'none', borderRadius: '6px', color: 'white', fontSize: '14px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1, display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              {loading ? (
                <>
                  <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />
                  Analyzing...
                </>
              ) : (
                <>
                  <Search size={18} />
                  Analyze Reports
                </>
              )}
            </button>
          </div>
        )}

        {data && (
          <div>
            <div style={{ background: '#1a1d23', borderRadius: '12px', padding: '16px', marginBottom: '20px', border: '1px solid #2d3238' }}>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '14px' }}>
                <button
                  onClick={() => setView('overview')}
                  style={{ padding: '8px 16px', background: view === 'overview' ? '#f97316' : '#2d3238', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer', fontSize: '13px', fontWeight: '600' }}
                >
                  Overview
                </button>
                <button
                  onClick={() => setView('players')}
                  style={{ padding: '8px 16px', background: view === 'players' ? '#f97316' : '#2d3238', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer', fontSize: '13px', fontWeight: '600' }}
                >
                  Players
                </button>
                <button
                  onClick={() => { setData(null); setError(''); setExpandedPlayers(new Set()); setSortConfig({ key: null, direction: 'asc' }); }}
                  style={{ padding: '8px 16px', background: '#2d3238', border: 'none', borderRadius: '6px', color: 'white', cursor: 'pointer', fontSize: '13px', fontWeight: '600', marginLeft: 'auto' }}
                >
                  New Analysis
                </button>
                <button
                  onClick={handleShare}
                  disabled={sharingData}
                  style={{ padding: '8px 16px', background: sharingData ? '#475569' : '#10b981', border: 'none', borderRadius: '6px', color: 'white', cursor: sharingData ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  {sharingData ? (
                    <>
                      <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                      Sharing...
                    </>
                  ) : (
                    <>
                      <Share2 size={14} />
                      Share
                    </>
                  )}
                </button>
              </div>

              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                <label style={{ fontSize: '13px', color: '#cbd5e1' }}>Deaths to count:</label>
                <select
                  value={cutoff}
                  onChange={(e) => setCutoff(parseInt(e.target.value))}
                  style={{ padding: '6px 10px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px' }}
                >
                  {[...Array(data.meta.maxCutoff)].map((_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {i + 1} {i === 0 ? 'Death' : 'Deaths'}
                    </option>
                  ))}
                </select>

                {config.enableCheatDeath && (() => {
                  // Count total cheat deaths detected
                  let cheatDeathCount = 0;
                  if (data && data.events) {
                    Object.values(data.events).forEach(playerEvents => {
                      playerEvents.forEach(ev => {
                        if (ev.isCheatDeath) {
                          cheatDeathCount++;
                        }
                      });
                    });
                  }
                  return cheatDeathCount > 0 && (
                    <>
                      <div style={{ marginLeft: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '11px', color: '#10b981', background: '#1a2e1a', padding: '3px 8px', borderRadius: '4px', fontWeight: '500' }}>
                          ✓ {cheatDeathCount} cheat deaths detected
                        </span>
                      </div>
                      <div style={{ marginLeft: '12px', fontSize: '11px', color: '#8b92a0', padding: '4px 8px', background: '#252930', borderRadius: '4px' }}>
                        Legend: <span style={{ color: '#cbd5e1' }}>Top</span> = Real deaths only, <span style={{ color: '#34d399' }}>Bottom (green)</span> = Including cheat deaths
                      </div>
                    </>
                  );
                })()}

                <div style={{ marginLeft: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Filter size={14} />
                  <span style={{ fontSize: '13px', color: '#cbd5e1' }}>Boss filters:</span>
                </div>
                {Object.keys(data.bossParticipation).sort().map(boss => (
                  <button
                    key={boss}
                    onClick={() => toggleBoss(boss)}
                    style={{ padding: '5px 10px', background: selectedBosses.has(boss) ? '#f97316' : '#2d3238', border: '1px solid ' + (selectedBosses.has(boss) ? '#f97316' : '#3d424a'), borderRadius: '14px', color: 'white', cursor: 'pointer', fontSize: '12px' }}
                  >
                    {boss}
                  </button>
                ))}
              </div>

              {view === 'players' && (
                <div style={{ marginTop: '14px' }}>
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search players..."
                    style={{ width: '100%', maxWidth: '300px', padding: '8px 12px', background: '#252930', border: '1px solid #3d424a', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px' }}
                  />
                </div>
              )}
            </div>

            {view === 'overview' && (() => {
              const { bosses, players, grid } = getOverviewData();
              const sortedPlayers = sortConfig.key ? sortOverviewData(bosses, players, grid, sortConfig.key) : players;
              
              return (
                <div style={{ background: '#1a1d23', borderRadius: '12px', padding: '16px', border: '1px solid #2d3238', overflowX: 'auto' }}>
                  <h2 style={{ margin: '0 0 14px', fontSize: '16px', fontWeight: '600', color: '#ffffff' }}>Death Rate Overview</h2>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                    <thead>
                      <tr style={{ background: '#252930' }}>
                        <th 
                          onClick={() => handleSort('player')}
                          style={{ padding: '10px', textAlign: 'left', borderBottom: '2px solid #3d424a', position: 'sticky', left: 0, background: '#252930', zIndex: 2, cursor: 'pointer', userSelect: 'none', color: '#ffffff' }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            Player {getSortIcon('player')}
                          </div>
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
                            const showBothStats = cellData.hasCheatDeaths && cellData.totalDeaths > cellData.deaths;
                            
                            return (
                              <td key={boss} style={{ padding: '10px', textAlign: 'center' }}>
                                {cellData.rate !== null ? (
                                  showBothStats ? (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                      <span style={{ color: cellData.rate > 50 ? '#f87171' : cellData.rate > 25 ? '#fbbf24' : '#34d399', fontWeight: '600', fontSize: '11px' }}>
                                        {cellData.rate.toFixed(1)}%
                                      </span>
                                      <span style={{ color: '#34d399', fontSize: '10px', fontWeight: '500' }}>
                                        ({cellData.totalRate.toFixed(1)}%)
                                      </span>
                                    </div>
                                  ) : (
                                    <span style={{ color: cellData.rate > 50 ? '#f87171' : cellData.rate > 25 ? '#fbbf24' : '#34d399', fontWeight: '600' }}>
                                      {cellData.rate.toFixed(1)}%
                                    </span>
                                  )
                                ) : (
                                  <span style={{ color: '#475569' }}>—</span>
                                )}
                              </td>
                            );
                          })}
                          <td style={{ padding: '10px', textAlign: 'center', fontWeight: '700' }}>
                            {grid[player].overall.rate !== null ? (
                              (() => {
                                const showBothStats = grid[player].overall.hasCheatDeaths && grid[player].overall.totalDeaths > grid[player].overall.deaths;
                                return showBothStats ? (
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', alignItems: 'center' }}>
                                    <span style={{ color: grid[player].overall.rate > 50 ? '#f87171' : grid[player].overall.rate > 25 ? '#fbbf24' : '#34d399', fontSize: '11px' }}>
                                      {grid[player].overall.rate.toFixed(1)}%
                                    </span>
                                    <span style={{ color: '#34d399', fontSize: '10px', fontWeight: '500' }}>
                                      ({grid[player].overall.totalRate.toFixed(1)}%)
                                    </span>
                                  </div>
                                ) : (
                                  <span style={{ color: grid[player].overall.rate > 50 ? '#f87171' : grid[player].overall.rate > 25 ? '#fbbf24' : '#34d399' }}>
                                    {grid[player].overall.rate.toFixed(1)}%
                                  </span>
                                );
                              })()
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
                {getFilteredStats().map(({ player, realDeaths, totalDeaths, cheatDeaths, pulls, realRate, totalRate, hasCheatDeaths, deathsByBoss, cheatDeathsByBoss, totalDeathsByBoss, topAbilitiesByBoss }) => {
                  const isExpanded = expandedPlayers.has(player);
                  const showBothStats = hasCheatDeaths && cheatDeaths > 0;
                  
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
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
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
                                    color: realRate > 50 ? '#f87171' : realRate > 25 ? '#fbbf24' : '#34d399',
                                    fontWeight: '600'
                                  }}>
                                    ({realRate.toFixed(1)}%)
                                  </span>
                                </p>
                                <p style={{ margin: 0, color: '#34d399' }}>
                                  <span style={{ color: '#8b92a0' }}>With cheat:</span> {totalDeaths} deaths / {pulls} pulls
                                  <span style={{ 
                                    marginLeft: '8px',
                                    color: totalRate > 50 ? '#f87171' : totalRate > 25 ? '#fbbf24' : '#34d399',
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
                        
                        <div style={{ fontSize: '18px', fontWeight: '700', color: realRate > 50 ? '#f87171' : realRate > 25 ? '#fbbf24' : '#34d399' }}>
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
            )}
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