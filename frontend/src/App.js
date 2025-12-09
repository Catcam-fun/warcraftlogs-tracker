import React, { useState, useEffect } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Search, AlertCircle, Loader2, Filter, ChevronDown, ChevronRight, ExternalLink, ArrowUpDown, ArrowUp, ArrowDown, Share2, Copy, Check, LogOut, Settings as SettingsIcon, Info, X } from 'lucide-react';
import { supabase } from './supabaseClient';
import Auth from './Auth';
import Settings from './Settings';
import LandingPage from './LandingPage';
import TermsOfService from './TermsOfService';
import PrivacyPolicy from './PrivacyPolicy';
// import SaveReportDialog from './SaveReportDialog'; // DISABLED - Save Reports feature
// import SavedReports from './SavedReports'; // DISABLED - Save Reports feature
import AppHeader from './AppHeader';

// Automatically detect if running locally or in production
const API_URL = window.location.hostname === 'localhost' 
  ? 'http://localhost:5000' 
  : 'https://deathwarcraftlogs-api.onrender.com';


// Raid Zone Definitions
const RAID_ZONES = {
  'manaforge': {
    name: 'Manaforge Omega',
    reportZone: '44',
    fightZone: '2810'
  },
  'undermine': {
    name: 'Liberation of Undermine',
    reportZone: '42',
    fightZone: '2769'
  },
  'nerubar': {
    name: "Nerub'ar Palace",
    reportZone: '38',
    fightZone: '2657'
  }
};

// Boss Ordering (Adventure Guide order)
const BOSS_ORDER = {
  'manaforge': [
    'Plexus Sentinel',
    "Loom'ithar",
    'Soulbinder Naazindhri',
    'Forgeweaver Araz',
    'The Soul Hunters',
    'Fractillus',
    'Nexus-King Salhadaar',
    'Dimensius, the All-Devouring'
  ],
  'undermine': [
    'Vexie and the Geargrinders',
    'Cauldron of Carnage',
    'Rik Reverb',
    'Stix Bunkjunker',
    'Sprocketmonger Lockenstock',
    'One-Armed Bandit',
    "Mug'Zee, Heads of Security",
    'Chrome King Gallywix'
  ],
  'nerubar': [
    'Ulgrax the Devourer',
    'The Bloodbound Horror',
    'Sikran, Captain of the Sureki',
    "Rasha'nan",
    "Broodtwister Ovi'nax",
    'Nexus-Princess Ky\'veza',
    'The Silken Court',
    'Queen Ansurek'
  ]
};

// WoW Class Colors (standard across all WoW sites/addons)
const WOW_CLASS_COLORS = {
  "DeathKnight": "#C41E3A",
  "DemonHunter": "#A330C9",
  "Druid": "#FF7C0A",
  "Evoker": "#33937F",
  "Hunter": "#AAD372",
  "Mage": "#3FC7EB",
  "Monk": "#00FF98",
  "Paladin": "#F48CBA",
  "Priest": "#FFFFFF",
  "Rogue": "#FFF468",
  "Shaman": "#0070DD",
  "Warlock": "#8788EE",
  "Warrior": "#C69B6D",
};

// Helper function to sort bosses by Adventure Guide order
const sortBossesByOrder = (bosses, raidZone) => {
  const order = BOSS_ORDER[raidZone] || [];
  if (order.length === 0) {
    // Fallback to alphabetical if no ordering defined
    return [...bosses].sort();
  }
  
  return [...bosses].sort((a, b) => {
    const aIndex = order.indexOf(a);
    const bIndex = order.indexOf(b);
    
    // If both bosses are in the order, sort by their position
    if (aIndex !== -1 && bIndex !== -1) {
      return aIndex - bIndex;
    }
    // If only one is in the order, prioritize it
    if (aIndex !== -1) return -1;
    if (bIndex !== -1) return 1;
    // If neither is in the order, sort alphabetically
    return a.localeCompare(b);
  });
};

// Scroll to top component
function ScrollToTop() {
  const { pathname } = useLocation();
  
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  
  return null;
}

export default function WarcraftLogsApp() {
  const navigate = useNavigate();
  const location = useLocation();
  
  // Authentication state
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const [config, setConfig] = useState({
    clientId: '',
    clientSecret: '',
    guildName: '',
    server: '',
    region: 'us',
    selectedRaid: 'manaforge',  // Default to Manaforge Omega
    reportZone: '44',
    fightZone: '2810',
    difficulty: '5',
    maxCutoff: '5',
    startDate: '',  // Optional: leave blank to include all reports from the beginning
    endDate: '',  // Optional: leave blank to include all reports
    authorFilters: '',
    characterGroups: '',
    enableCheatDeath: false,  // Optional cheat death detection (slower)
    enableDefensiveTracking: false  // Optional defensive ability tracking
  });

  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState('');
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [cutoff, setCutoff] = useState(2);
  const [selectedBosses, setSelectedBosses] = useState(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedPlayers, setExpandedPlayers] = useState(new Set());
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });
  const [overviewCollapsed, setOverviewCollapsed] = useState(true);
  const [showShareModal, setShowShareModal] = useState(false);
  const [shareLink, setShareLink] = useState('');
  const [copied, setCopied] = useState(false);
  const [sharingData, setSharingData] = useState(false);
  const [abortController, setAbortController] = useState(null);
  const [hiddenPlayers, setHiddenPlayers] = useState(new Set());
  const [minPulls, setMinPulls] = useState(0);
  const [characterGroups, setCharacterGroups] = useState({}); // { "MainName": ["Alt1", "Alt2"] }
  const [showGroupingUI, setShowGroupingUI] = useState(false);
  const [selectedForGrouping, setSelectedForGrouping] = useState(new Set());
  const [showTermsModal, setShowTermsModal] = useState(false);
  const [showInfoModal, setShowInfoModal] = useState(false);
  const [showAlphaBanner, setShowAlphaBanner] = useState(true);
  // const [showSaveDialog, setShowSaveDialog] = useState(false); // DISABLED - Save Reports feature


  // Check authentication status on mount
  useEffect(() => {
    // Get initial session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null);
      setAuthLoading(false);
    });

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  // Load API credentials when user logs in
  useEffect(() => {
    if (user) {
      loadAPICredentials();
    }
  }, [user]);

  const loadSharedResults = async (shareId) => {
    console.log('[Share] Loading shared results for ID:', shareId);
    setLoading(true);
    setLoadingStage('Loading shared results...');
    setError('');

    try {
      const url = `${API_URL}/api/shared/${shareId}`;
      console.log('[Share] Fetching from:', url);
      
      const response = await fetch(url);
      console.log('[Share] Response status:', response.status);
      
      const result = await response.json();
      console.log('[Share] Response data:', result);

      if (!result.success) {
        throw new Error(result.error || 'Shared results not found');
      }

      console.log('[Share] Successfully loaded data');
      setData(result.data);
      if (result.config) {
        setConfig(prevConfig => ({
          ...prevConfig,
          ...result.config
        }));
      }
      setLoading(false);
      setLoadingStage('');
    } catch (err) {
      console.error('[Share] Error loading shared results:', err);
      setError(`Failed to load shared results: ${err.message}`);
      setLoading(false);
      setLoadingStage('');
    }
  };

  // DISABLED - Save Reports feature
  // const handleLoadSavedReport = (reportData) => {
  //   console.log('[SavedReports] Loading saved report');
  //   setData(reportData);
  //   navigate('/');
  // };

  // Load shared results when share parameter is present
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const shareId = urlParams.get('share');
    
    console.log('[Share] URL changed, share param:', shareId, 'current data:', data ? 'exists' : 'none');
    
    if (shareId && !data && !loading) {  // Only load if we don't already have data and aren't already loading
      console.log('[Share] Triggering load for:', shareId);
      loadSharedResults(shareId);
    }
  }, [location.search, data, loading]);

  // IndexedDB helper functions for large data storage
  const saveToIndexedDB = async (key, value) => {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('FloorPovDB', 1);
      
      request.onerror = () => reject(request.error);
      
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains('analysisData')) {
          db.createObjectStore('analysisData');
        }
      };
      
      request.onsuccess = (event) => {
        const db = event.target.result;
        const transaction = db.transaction(['analysisData'], 'readwrite');
        const store = transaction.objectStore('analysisData');
        const putRequest = store.put(value, key);
        
        putRequest.onsuccess = () => {
          db.close();
          resolve();
        };
        
        putRequest.onerror = () => {
          db.close();
          reject(putRequest.error);
        };
      };
    });
  };

  const loadFromIndexedDB = async (key) => {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('FloorPovDB', 1);
      
      request.onerror = () => reject(request.error);
      
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains('analysisData')) {
          db.createObjectStore('analysisData');
        }
      };
      
      request.onsuccess = (event) => {
        const db = event.target.result;
        
        // Check if object store exists
        if (!db.objectStoreNames.contains('analysisData')) {
          db.close();
          resolve(null);
          return;
        }
        
        const transaction = db.transaction(['analysisData'], 'readonly');
        const store = transaction.objectStore('analysisData');
        const getRequest = store.get(key);
        
        getRequest.onsuccess = () => {
          db.close();
          resolve(getRequest.result);
        };
        
        getRequest.onerror = () => {
          db.close();
          reject(getRequest.error);
        };
      };
    });
  };

  // Load from IndexedDB on initial mount
  useEffect(() => {
    // Only attempt to load if we don't have data yet
    if (data || loading) return;
    
    const loadData = async () => {
      try {
        const savedData = await loadFromIndexedDB('sharedAnalysisData');
        if (savedData) {
          console.log('[Persistence] Loading data from IndexedDB');
          
          // If this came from SharedResults, it has a specific structure
          if (savedData.data && savedData.config) {
            setData(savedData.data);
            setConfig(prevConfig => ({
              ...prevConfig,
              ...savedData.config
            }));
          } else {
            // Otherwise it's just the raw data
            setData(savedData);
          }
          
          // Clean up the loadShared URL parameter if present
          const urlParams = new URLSearchParams(window.location.search);
          if (urlParams.get('loadShared') === 'true') {
            navigate(location.pathname, { replace: true });
          }
        }
      } catch (err) {
        console.error('[Persistence] Error loading from IndexedDB:', err);
      }
    };
    
    loadData();
  }, []); // Run once on mount

  // Save data to IndexedDB whenever it changes (for refresh persistence)
  useEffect(() => {
    if (data) {
      const saveData = async () => {
        try {
          console.log('[Persistence] Saving data to IndexedDB');
          await saveToIndexedDB('sharedAnalysisData', { data, config });
          console.log('[Persistence] Data saved successfully');
        } catch (err) {
          console.error('[Persistence] Error saving to IndexedDB:', err);
        }
      };
      
      saveData();
    }
  }, [data, config]);

  const loadAPICredentials = async () => {
    try {
      const { data, error } = await supabase
        .from('api_credentials')
        .select('client_id, client_secret')
        .eq('user_id', user.id)
        .single();

      if (error) {
        // No credentials saved yet, that's okay
        if (error.code !== 'PGRST116') {
          console.error('Error loading credentials:', error);
        }
        return;
      }

      if (data) {
        setConfig(prev => ({
          ...prev,
          clientId: data.client_id || '',
          clientSecret: data.client_secret || ''
        }));
      }
    } catch (err) {
      console.error('Error loading API credentials:', err);
    }
  };

  const saveAPICredentials = async (clientId, clientSecret) => {
    if (!user) return;

    try {
      // Check if credentials already exist
      const { data: existing } = await supabase
        .from('api_credentials')
        .select('id')
        .eq('user_id', user.id)
        .single();

      if (existing) {
        // Update existing credentials
        const { error } = await supabase
          .from('api_credentials')
          .update({
            client_id: clientId,
            client_secret: clientSecret,
            last_used: new Date().toISOString()
          })
          .eq('user_id', user.id);

        if (error) throw error;
      } else {
        // Insert new credentials
        const { error } = await supabase
          .from('api_credentials')
          .insert({
            user_id: user.id,
            client_id: clientId,
            client_secret: clientSecret
          });

        if (error) throw error;
      }
    } catch (err) {
      console.error('Error saving API credentials:', err);
    }
  };

  const handleLogout = async () => {
    await supabase.auth.signOut();
    setUser(null);
    setData(null); // Clear any loaded data
    setConfig(prev => ({ ...prev, enableCheatDeath: false })); // Disable cheat death for non-logged-in users
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

  const handleRaidChange = (e) => {
    const raidKey = e.target.value;
    const raid = RAID_ZONES[raidKey];
    setConfig(prev => ({
      ...prev,
      selectedRaid: raidKey,
      reportZone: raid.reportZone,
      fightZone: raid.fightZone
    }));
  };

  const handleSubmit = async () => {
    if (!config.clientId || !config.clientSecret || !config.guildName || !config.server) {
      setError('Please fill in all required fields (Client ID, Client Secret, Guild Name, and Server)');
      return;
    }

    // Save API credentials if user is logged in
    if (user) {
      await saveAPICredentials(config.clientId, config.clientSecret);
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
                  return;
                }
                
                const data = window.deathTrackerData;
                const events = data.events;
                const pullsMap = new Map();
                
                // Build pulls from events with name normalization
                for (const playerEvents of Object.values(events)) {
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
                
                // Try Clipboard API first, then fall back to copy() utility
                const jsonString = JSON.stringify(exportData, null, 2);
                
                // Method 1: Try Clipboard API (works in browser console)
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  navigator.clipboard.writeText(jsonString)
                    .catch(() => {
                      // Method 2: Try Chrome DevTools copy() utility
                      try {
                        // eslint-disable-next-line no-undef
                        copy(exportData);
                      } catch (e) {
                        // Silently fail
                      }
                    });
                } else {
                  // Method 2: Try Chrome DevTools copy() utility
                  try {
                    // eslint-disable-next-line no-undef
                    copy(exportData);
                  } catch (e) {
                    // Silently fail
                  }
                }
                
                return exportData;
              };
              
              setLoadingStage('');
              setLoading(false);
              setAbortController(null);
              
              // Navigate to results page after analysis completes
              navigate('/results');
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

  const togglePlayerVisibility = (player) => {
    const newHidden = new Set(hiddenPlayers);
    if (newHidden.has(player)) {
      newHidden.delete(player);
    } else {
      newHidden.add(player);
    }
    setHiddenPlayers(newHidden);
  };

  const getFilteredStats = () => {
    if (!data) return [];

    const stats = [];
    const eventsAll = data.events;
    const pullsMap = data.pullParticipation;
    const bossPart = data.bossParticipation;

    const hasCheatDeaths = config.enableCheatDeath;
    
    // Build a map of all characters to their main (for grouped alts)
    const charToMain = {};
    Object.entries(characterGroups).forEach(([main, alts]) => {
      alts.forEach(alt => {
        charToMain[alt] = main;
      });
    });
    
    // Get unique players (mains + ungrouped characters) - exclude grouped alts
    const groupedAlts = new Set(Object.keys(charToMain));
    const basePlayers = Object.keys(eventsAll);
    const players = basePlayers.filter(p => !groupedAlts.has(p));
    
    for (const player of players) {
      // Get events for this player and their alts (if any)
      const alts = characterGroups[player] || [];
      const allCharacters = [player, ...alts];
      
      // Combine events from all characters in the group
      const allPlayerEventsUnfiltered = allCharacters.flatMap(char => eventsAll[char] || []);
      
      const allPlayerEvents = allPlayerEventsUnfiltered.filter(
        ev => (selectedBosses.size === 0 || selectedBosses.has(ev.boss))
      );
      
      if (!allPlayerEvents.length) continue;

      // Combine pulls from all characters in the group
      let pulls = 0;
      if (selectedBosses.size === 0) {
        pulls = allCharacters.reduce((total, char) => {
          return total + (pullsMap[char]?.length || 0);
        }, 0);
      } else {
        for (const boss of selectedBosses) {
          for (const char of allCharacters) {
            if (bossPart[boss]?.[char]) {
              pulls += bossPart[boss][char].length;
            }
          }
        }
      }

      // WINDOW-BASED FILTERING WITH MASS DEATH HANDLING:
      // 1. Get first X real deaths (by rankWithinPull)
      // 2. Use pullCutoffTimestamps to find the correct cutoff (handles mass deaths)
      // 3. Include cheat deaths that occurred BEFORE the cutoff
      
      // Get pullCutoffTimestamps from data (provided by backend)
      const pullCutoffTimestamps = data.pullCutoffTimestamps || {};
      
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
          } else {
            // No cutoff timestamps at all - pull contributes 0 deaths
            return; // Skip this pull
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


      // Extract class/spec from PRIMARY character (not alts) to ensure consistent coloring
      const primaryCharEvents = eventsAll[player] || [];
      const playerClass = primaryCharEvents.length > 0 ? (primaryCharEvents[0].class || "Unknown") : 
                         (allPlayerEventsUnfiltered.length > 0 ? (allPlayerEventsUnfiltered[0].class || "Unknown") : "Unknown");
      const playerSpec = primaryCharEvents.length > 0 ? (primaryCharEvents[0].spec || "Unknown") : 
                        (allPlayerEventsUnfiltered.length > 0 ? (allPlayerEventsUnfiltered[0].spec || "Unknown") : "Unknown");

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
        topAbilitiesByBoss,
        class: playerClass,
        spec: playerSpec
      });
    }

    // Filter out hidden players and players below minimum pulls
    const filteredStats = stats.filter(stat => 
      !hiddenPlayers.has(stat.player) && stat.pulls >= minPulls
    );

    return filteredStats.sort((a, b) => b.realRate - a.realRate || b.realDeaths - a.realDeaths);
  };

  const getOverviewData = () => {
    if (!data) return { bosses: [], players: [], grid: {} };

    // Filter bosses based on selection - use proper ordering
    const allBosses = sortBossesByOrder(Object.keys(data.bossParticipation), config.selectedRaid);
    const bosses = selectedBosses.size === 0 
      ? allBosses 
      : allBosses.filter(boss => selectedBosses.has(boss));
    
    // Get all base players
    const basePlayers = Object.keys(data.events).sort();
    
    // Build a map of all characters to their main (for grouped alts)
    const charToMain = {};
    Object.entries(characterGroups).forEach(([main, alts]) => {
      alts.forEach(alt => {
        charToMain[alt] = main;
      });
    });
    
    // Get unique players (mains + ungrouped characters)
    const groupedAlts = new Set(Object.keys(charToMain));
    const players = basePlayers.filter(p => !groupedAlts.has(p));
    
    const grid = {};

    const hasCheatDeaths = config.enableCheatDeath;
    const pullCutoffTimestamps = data.pullCutoffTimestamps || {};

    players.forEach(player => {
      grid[player] = {};
      
      // Get events for this player and their alts (if any)
      const alts = characterGroups[player] || [];
      const allCharacters = [player, ...alts];
      
      // Combine events from all characters in the group
      const allPlayerEvents = allCharacters.flatMap(char => data.events[char] || []);
      
      // Extract class/spec from PRIMARY character (not alts) to ensure consistent coloring
      const primaryCharEvents = data.events[player] || [];
      const playerClass = primaryCharEvents.length > 0 ? (primaryCharEvents[0].class || "Unknown") : 
                         (allPlayerEvents.length > 0 ? (allPlayerEvents[0].class || "Unknown") : "Unknown");
      const playerSpec = primaryCharEvents.length > 0 ? (primaryCharEvents[0].spec || "Unknown") : 
                        (allPlayerEvents.length > 0 ? (allPlayerEvents[0].spec || "Unknown") : "Unknown");
      
      bosses.forEach(boss => {
        // Combine boss pulls from all characters in the group
        const bossPulls = allCharacters.reduce((total, char) => {
          return total + (data.bossParticipation[boss]?.[char]?.length || 0);
        }, 0);
        
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
          hasCheatDeaths,
          class: playerClass,
          spec: playerSpec
        };
      });

      // Calculate overall for selected bosses
      let totalPulls = 0;
      let totalRealDeaths = 0;
      let totalWithCheatDeaths = 0;
      
      if (selectedBosses.size === 0) {
        // Use window-based filtering for all bosses - combine all characters in group
        totalPulls = allCharacters.reduce((total, char) => {
          return total + (data.pullParticipation[char]?.length || 0);
        }, 0);
        
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
        // For selected bosses, sum up from the grid (already combined for grouped chars)
        bosses.forEach(boss => {
          totalPulls += grid[player][boss].pulls;
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
        hasCheatDeaths,
        class: playerClass,
        spec: playerSpec
      };
    });

    // Filter out hidden players and players below minimum pulls
    const filteredPlayers = players.filter(player => 
      !hiddenPlayers.has(player) && grid[player].overall.pulls >= minPulls
    );

    return { bosses, players: filteredPlayers, grid };
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

  // Calculate median-based color with outlier handling
  const getPercentageColor = (percentage, allPercentages) => {
    if (!allPercentages || allPercentages.length === 0) {
      return '#34d399'; // default light green
    }

    // Calculate quartiles and IQR for outlier detection
    const sorted = [...allPercentages].sort((a, b) => a - b);
    const q1Index = Math.floor(sorted.length * 0.25);
    const q3Index = Math.floor(sorted.length * 0.75);
    const medianIndex = Math.floor(sorted.length * 0.5);
    
    const q1 = sorted[q1Index];
    const q3 = sorted[q3Index];
    const median = sorted[medianIndex];
    const iqr = q3 - q1;
    
    // Define outlier boundaries
    const lowerBound = q1 - 1.5 * iqr;
    const upperBound = q3 + 1.5 * iqr;
    
    // Filter out outliers for color scaling
    const filteredValues = sorted.filter(v => v >= lowerBound && v <= upperBound);
    const minVal = Math.min(...filteredValues);
    const maxVal = Math.max(...filteredValues);
    
    // Assign extreme colors to outliers
    if (percentage < lowerBound) {
      return '#166534'; // dark green for low outliers
    }
    if (percentage > upperBound) {
      return '#dc2626'; // dark red for high outliers
    }
    
    // Color scale for non-outliers
    if (percentage <= median) {
      // Below median: light green (#86efac) to darker green (#166534)
      const ratio = (median - percentage) / (median - minVal);
      const r = Math.round(134 + (22 - 134) * ratio);
      const g = Math.round(239 + (101 - 239) * ratio);
      const b = Math.round(172 + (52 - 172) * ratio);
      return `rgb(${r}, ${g}, ${b})`;
    } else {
      // Above median: light green to light yellow to red
      const ratio = (percentage - median) / (maxVal - median);
      
      if (ratio < 0.5) {
        // Light green (#86efac) to light yellow (#fef08a)
        const localRatio = ratio * 2;
        const r = Math.round(134 + (254 - 134) * localRatio);
        const g = Math.round(239 + (240 - 239) * localRatio);
        const b = Math.round(172 + (138 - 172) * localRatio);
        return `rgb(${r}, ${g}, ${b})`;
      } else {
        // Light yellow (#fef08a) to red (#dc2626)
        const localRatio = (ratio - 0.5) * 2;
        const r = Math.round(254 + (220 - 254) * localRatio);
        const g = Math.round(240 + (38 - 240) * localRatio);
        const b = Math.round(138 + (38 - 138) * localRatio);
        return `rgb(${r}, ${g}, ${b})`;
      }
    }
  };

  // Show loading while checking auth
  if (authLoading) {
    return (
      <div style={{ minHeight: '100vh', background: '#0a0e1a', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Loader2 size={48} style={{ color: '#3b82f6', animation: 'spin 1s linear infinite' }} />
      </div>
    );
  }

  // Main app (works for both logged in and anonymous users)
  return (
    <div style={{ minHeight: '100vh', background: '#0a0e1a', color: '#e2e8f0', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      <ScrollToTop />
      
      <Routes>
        <Route path="/terms" element={
          <TermsOfService 
            user={user}
            onShowAuthModal={() => setShowAuthModal(true)}
            onShowSettings={() => setShowSettings(true)}
            onLogout={handleLogout}
          />
        } />
        
        <Route path="/privacy" element={
          <PrivacyPolicy 
            user={user}
            onShowAuthModal={() => setShowAuthModal(true)}
            onShowSettings={() => setShowSettings(true)}
            onLogout={handleLogout}
          />
        } />

        {/* DISABLED - Save Reports feature
        <Route path="/saved-reports" element={
          <SavedReports 
            user={user}
            onLoadReport={handleLoadSavedReport}
          />
        } />
        */}
        
        <Route path="/*" element={
          <>
      {/* Sticky Header */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 1000,
        background: '#0f1419',
        borderBottom: '1px solid #1e293b',
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)'
      }}>
        <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div 
            onClick={() => {
              setData(null);
              setError('');
              setExpandedPlayers(new Set());
              setSortConfig({ key: null, direction: 'asc' });
              navigate('/');
            }}
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: '12px',
              cursor: 'pointer',
              transition: 'opacity 0.2s'
            }}
            onMouseOver={(e) => { e.currentTarget.style.opacity = '0.8'; }}
            onMouseOut={(e) => { e.currentTarget.style.opacity = '1'; }}
          >
            <div style={{
              width: '40px',
              height: '40px',
              background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '16px',
              fontWeight: '700',
              color: '#ffffff'
            }}>
              FP
            </div>
            <div>
              <h1 style={{ margin: 0, fontSize: '20px', fontWeight: '700', color: '#ffffff' }}>
                Floor Pov
              </h1>
              <p style={{ margin: 0, fontSize: '11px', color: '#64748b' }}>Death Analytics for World of Warcraft</p>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            {data && location.pathname === '/results' && (
              <>
                <button
                  onClick={() => { 
                    setData(null); 
                    setError(''); 
                    setExpandedPlayers(new Set()); 
                    setSortConfig({ key: null, direction: 'asc' }); 
                    navigate('/analyze');
                  }}
                  style={{ padding: '8px 16px', background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', cursor: 'pointer', fontSize: '13px', fontWeight: '600', transition: 'all 0.2s' }}
                  onMouseOver={(e) => { e.target.style.background = '#334155'; }}
                  onMouseOut={(e) => { e.target.style.background = '#1e293b'; }}
                >
                  New Analysis
                </button>
                {/* DISABLED - Save Reports feature
                {user && (
                  <button
                    onClick={() => setShowSaveDialog(true)}
                    style={{
                      padding: '8px 16px',
                      background: '#3b82f6',
                      border: 'none',
                      borderRadius: '6px',
                      color: '#fff',
                      cursor: 'pointer',
                      fontSize: '13px',
                      fontWeight: '600',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      transition: 'all 0.2s'
                    }}
                    onMouseOver={(e) => { e.target.style.background = '#2563eb'; }}
                    onMouseOut={(e) => { e.target.style.background = '#3b82f6'; }}
                  >
                    <Save size={14} />
                    Save Report
                  </button>
                )}
                */}
                <button
                  onClick={handleShare}
                  disabled={sharingData}
                  style={{ padding: '8px 16px', background: sharingData ? '#475569' : '#10b981', border: 'none', borderRadius: '6px', color: 'white', cursor: sharingData ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '6px', transition: 'all 0.2s' }}
                  onMouseOver={(e) => { if (!sharingData) e.target.style.background = '#059669'; }}
                  onMouseOut={(e) => { if (!sharingData) e.target.style.background = '#10b981'; }}
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
              </>
            )}
            {user ? (
              <div style={{ 
                display: 'flex', 
                alignItems: 'center', 
                gap: '12px',
                padding: '8px 12px',
                background: '#1e293b',
                borderRadius: '6px',
                fontSize: '13px'
              }}>
                <span style={{ color: '#94a3b8' }}>{user.email}</span>
                <button
                  onClick={() => setShowSettings(true)}
                  style={{ 
                    padding: '6px 12px', 
                    background: '#334155', 
                    border: '1px solid #475569', 
                    borderRadius: '4px', 
                    color: '#e2e8f0', 
                    cursor: 'pointer', 
                    fontSize: '12px', 
                    fontWeight: '600',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.2s'
                  }}
                  onMouseOver={(e) => { e.target.style.background = '#475569'; }}
                  onMouseOut={(e) => { e.target.style.background = '#334155'; }}
                >
                  <SettingsIcon size={14} />
                  Settings
                </button>
                <button
                  onClick={handleLogout}
                  style={{ 
                    padding: '6px 12px', 
                    background: '#334155', 
                    border: '1px solid #475569', 
                    borderRadius: '4px', 
                    color: '#e2e8f0', 
                    cursor: 'pointer', 
                    fontSize: '12px', 
                    fontWeight: '600',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.2s'
                  }}
                  onMouseOver={(e) => { e.target.style.background = '#475569'; }}
                  onMouseOut={(e) => { e.target.style.background = '#334155'; }}
                >
                  <LogOut size={14} />
                  Logout
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowAuthModal(true)}
                style={{ 
                  padding: '8px 16px', 
                  background: '#3b82f6', 
                  border: 'none', 
                  borderRadius: '6px', 
                  color: '#fff', 
                  cursor: 'pointer', 
                  fontSize: '13px', 
                  fontWeight: '600',
                  transition: 'all 0.2s'
                }}
                onMouseOver={(e) => { e.target.style.background = '#2563eb'; }}
                onMouseOut={(e) => { e.target.style.background = '#3b82f6'; }}
              >
                Sign In
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Alpha Warning Banner */}
      {showAlphaBanner && (
        <div style={{
          background: 'rgba(220, 38, 38, 0.15)',
          borderBottom: '2px solid rgba(220, 38, 38, 0.3)',
          backdropFilter: 'blur(10px)',
          padding: '12px 24px',
          position: 'relative'
        }}>
          <div style={{ maxWidth: '1400px', margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
            <AlertCircle size={20} style={{ color: '#fca5a5', flexShrink: 0 }} />
            <p style={{ 
              margin: 0, 
              color: '#fecaca', 
              fontSize: '14px', 
              fontWeight: '500',
              textAlign: 'center',
              lineHeight: '1.5'
            }}>
              ⚠️ <strong>ALPHA VERSION</strong> - This tool is in active development. Features are being added regularly and you may encounter bugs or incomplete functionality.
            </p>
            <button
              onClick={() => setShowAlphaBanner(false)}
              style={{
                background: 'rgba(252, 165, 165, 0.2)',
                border: 'none',
                borderRadius: '4px',
                padding: '4px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                color: '#fecaca',
                transition: 'background 0.2s',
                flexShrink: 0
              }}
              onMouseOver={(e) => e.target.style.background = 'rgba(252, 165, 165, 0.3)'}
              onMouseOut={(e) => e.target.style.background = 'rgba(252, 165, 165, 0.2)'}
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}
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
            background: '#1a1f2e',
            padding: '30px',
            borderRadius: '12px',
            border: '2px solid #3b82f6',
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
              <Share2 size={24} style={{ color: '#3b82f6' }} />
              Shareable Link Created!
            </h2>
            <p style={{ color: '#8b92a0', marginBottom: '15px' }}>
              Copy this link to share your analysis with others:
            </p>
            <div style={{
              background: '#0f1419',
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
                  background: copied ? '#10b981' : '#3b82f6',
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
                background: '#2d3748',
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

      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px' }}>
        {loading && (
          <div style={{ 
            position: 'fixed', 
            top: 0, 
            left: 0, 
            right: 0, 
            bottom: 0, 
            background: 'rgba(10, 14, 26, 0.98)', 
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
                border: '4px solid #1e293b', 
                borderTop: '4px solid #3b82f6',
                borderRadius: '50%',
                animation: 'spin 1s linear infinite',
                margin: '0 auto 24px'
              }} />
              <h2 style={{ margin: '0 0 16px', fontSize: '22px', fontWeight: '600', color: '#ffffff' }}>
                Analyzing Reports
              </h2>
              <div style={{ 
                padding: '14px 18px', 
                background: '#1a1f2e', 
                borderRadius: '8px',
                border: '1px solid #2d3748',
                marginBottom: '16px',
                minHeight: '60px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <p style={{ 
                  margin: 0, 
                  fontSize: '14px', 
                  color: '#60a5fa', 
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

        <Routes>
          <Route path="/" element={
            <LandingPage 
              onRunAnalysis={() => navigate('/analyze')}
              onSavedReports={null}  // DISABLED - Save Reports feature
            />
          } />
          
          <Route path="/analyze" element={
          <div style={{ background: '#1a1f2e', borderRadius: '12px', padding: '24px', marginBottom: '20px', border: '1px solid #2d3748' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '600', color: '#ffffff' }}>Configuration</h2>
              <button
                onClick={() => setShowInfoModal(true)}
                style={{
                  padding: '8px 16px',
                  background: '#1e293b',
                  border: '1px solid #3b82f6',
                  borderRadius: '6px',
                  color: '#3b82f6',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: '600',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  transition: 'all 0.2s'
                }}
                onMouseOver={(e) => { 
                  e.target.style.background = '#3b82f6'; 
                  e.target.style.color = '#ffffff';
                }}
                onMouseOut={(e) => { 
                  e.target.style.background = '#1e293b'; 
                  e.target.style.color = '#3b82f6';
                }}
              >
                <Info size={16} />
                How It Works
              </button>
            </div>
            
            <div style={{ marginBottom: '24px', padding: '14px 16px', background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.3)', borderRadius: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'start', gap: '10px' }}>
                <div style={{ fontSize: '18px' }}>🔑</div>
                <div>
                  <h3 style={{ margin: '0 0 6px', fontSize: '14px', fontWeight: '600', color: '#60a5fa' }}>
                    Need API Credentials?
                  </h3>
                  <p style={{ margin: '0 0 6px', fontSize: '12px', color: '#cbd5e1', lineHeight: '1.6' }}>
                    You need a WarcraftLogs V2 API Client ID and Secret to use this tool.
                  </p>
                  <ol style={{ margin: '6px 0 0 16px', padding: 0, fontSize: '12px', color: '#cbd5e1', lineHeight: '1.7' }}>
                    <li>Go to <a href="https://www.warcraftlogs.com/api/clients/" target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa', textDecoration: 'underline' }}>WarcraftLogs API Clients</a></li>
                    <li>Click "Create a Client"</li>
                    <li>Enter a name (e.g., "Death Tracker")</li>
                    <li>For redirect URL, enter the website URL or just use: <code style={{ background: '#0f1419', padding: '2px 6px', borderRadius: '3px', fontSize: '11px' }}>http://localhost</code></li>
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
                    style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  {user && (
                    <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#10b981', lineHeight: '1.4' }}>
                      ✓ Auto-fills from your account settings
                    </p>
                  )}
                  {!user && (
                    <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                      <a 
                        onClick={() => setShowAuthModal(true)}
                        style={{ color: '#3b82f6', cursor: 'pointer', textDecoration: 'underline' }}
                      >
                        Sign in
                      </a> to save your credentials
                    </p>
                  )}
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
                    style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  {user && (
                    <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#10b981', lineHeight: '1.4' }}>
                      ✓ Auto-fills from your account settings
                    </p>
                  )}
                  {!user && (
                    <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                      <a 
                        onClick={() => setShowAuthModal(true)}
                        style={{ color: '#3b82f6', cursor: 'pointer', textDecoration: 'underline' }}
                      >
                        Sign in
                      </a> to save your credentials
                    </p>
                  )}
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
                    style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Enter exactly as shown on WarcraftLogs - Examples: Do Over, Complexity Limit, Method
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
                    style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Enter as shown in-game (spaces OK) - Examples: Thrall, Area 52, Zirkel des Cenarius
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
                    style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
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
                    style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
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
                    Raid *
                  </label>
                  <select
                    name="selectedRaid"
                    value={config.selectedRaid}
                    onChange={handleRaidChange}
                    style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  >
                    <option value="manaforge">Manaforge Omega</option>
                    <option value="undermine">Liberation of Undermine</option>
                    <option value="nerubar">Nerub'ar Palace</option>
                  </select>
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Select which raid to analyze
                  </p>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '18px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Start Date (Optional)
                  </label>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <input
                      type="date"
                      name="startDate"
                      value={config.startDate}
                      onChange={handleInputChange}
                      style={{ flex: 1, padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                    />
                    {config.startDate && (
                      <button
                        type="button"
                        onClick={() => setConfig(prev => ({ ...prev, startDate: '' }))}
                        style={{
                          padding: '10px 14px',
                          background: '#334155',
                          border: '1px solid #475569',
                          borderRadius: '6px',
                          color: '#e2e8f0',
                          cursor: 'pointer',
                          fontSize: '12px',
                          fontWeight: '500',
                          whiteSpace: 'nowrap',
                          transition: 'all 0.2s'
                        }}
                        onMouseOver={(e) => e.target.style.background = '#475569'}
                        onMouseOut={(e) => e.target.style.background = '#334155'}
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Leave blank to include all reports from the beginning of the tier
                  </p>
                </div>

                <div>
                  <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    End Date (Optional)
                  </label>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <input
                      type="date"
                      name="endDate"
                      value={config.endDate}
                      onChange={handleInputChange}
                      style={{ flex: 1, padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                    />
                    {config.endDate && (
                      <button
                        type="button"
                        onClick={() => setConfig(prev => ({ ...prev, endDate: '' }))}
                        style={{
                          padding: '10px 14px',
                          background: '#334155',
                          border: '1px solid #475569',
                          borderRadius: '6px',
                          color: '#e2e8f0',
                          cursor: 'pointer',
                          fontSize: '12px',
                          fontWeight: '500',
                          whiteSpace: 'nowrap',
                          transition: 'all 0.2s'
                        }}
                        onMouseOver={(e) => e.target.style.background = '#475569'}
                        onMouseOut={(e) => e.target.style.background = '#334155'}
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Leave blank to include all reports up to today
                  </p>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '18px' }}>
                <div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1' }}>
                    Max Deaths to Track
                    <div 
                      style={{ 
                        position: 'relative', 
                        display: 'inline-flex',
                        cursor: 'help'
                      }}
                      title="Sets the maximum number of deaths to track per pull. For example, if set to 5, only the first 5 deaths in each pull will be analyzed. This helps focus on early mechanics failures rather than wipe cascades."
                    >
                      <Info size={14} style={{ color: '#64748b' }} />
                    </div>
                  </label>
                  <input
                    type="number"
                    name="maxCutoff"
                    value={config.maxCutoff}
                    onChange={handleInputChange}
                    min="1"
                    max="10"
                    placeholder="5"
                    style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', boxSizing: 'border-box' }}
                  />
                  <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                    Track only the first X deaths per pull (1-10). Useful for identifying early mechanics failures.
                  </p>
                </div>
              </div>

              {/* Character Groups - Hidden for now, replaced with post-analysis UI grouping */}
              {false && (
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
                  style={{ width: '100%', padding: '10px 14px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px', fontFamily: 'monospace', resize: 'vertical', boxSizing: 'border-box' }}
                />
                <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                  Merge alt characters with their mains for combined statistics
                </p>
              </div>
              )}

              {/* Cheat Death Detection - Premium Feature for Authenticated Users */}
              <div style={{ marginTop: '8px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1', cursor: user ? 'pointer' : 'not-allowed', opacity: user ? 1 : 0.6 }}>
                  <input
                    type="checkbox"
                    checked={config.enableCheatDeath}
                    onChange={(e) => user && setConfig({...config, enableCheatDeath: e.target.checked})}
                    disabled={!user}
                    style={{ cursor: user ? 'pointer' : 'not-allowed', width: '16px', height: '16px' }}
                  />
                  <span>Enable cheat death detection</span>
                  <span style={{ fontSize: '11px', color: '#f59e0b', fontWeight: '400' }}>(+20-30s slower)</span>
                  {!user && (
                    <span style={{ fontSize: '11px', color: '#3b82f6', fontWeight: '500' }}>
                      (Account required)
                    </span>
                  )}
                </label>
                <p style={{ margin: '4px 0 0 24px', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                  {user ? (
                    "Detects deaths prevented by Cauterize, Spirit of Redemption, Cheat Death, etc. Adds 1 API query per report."
                  ) : (
                    <>
                      <a 
                        onClick={() => setShowAuthModal(true)}
                        style={{ color: '#3b82f6', cursor: 'pointer', textDecoration: 'underline' }}
                      >
                        Sign in
                      </a> to enable cheat death detection. Detects deaths prevented by Cauterize, Spirit of Redemption, Cheat Death, etc.
                    </>
                  )}
                </p>
              </div>

              {/* DISABLED - Defensive Tracking Feature (Temporarily Disabled)
              <div style={{ marginTop: '8px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: '500', color: '#cbd5e1', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={config.enableDefensiveTracking}
                    onChange={(e) => setConfig({...config, enableDefensiveTracking: e.target.checked})}
                    style={{ cursor: 'pointer', width: '16px', height: '16px' }}
                  />
                  <span>Show active defensive buffs</span>
                  <span style={{ fontSize: '11px', color: '#64748b', fontWeight: '400' }}>(Beta)</span>
                </label>
                <p style={{ margin: '4px 0 0 24px', fontSize: '11px', color: '#64748b', lineHeight: '1.4' }}>
                  Shows which defensive buffs were ACTIVE when player died, plus healing received in last 5 seconds. No performance impact.
                </p>
              </div>
              */}
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
              style={{ marginTop: '24px', padding: '12px 24px', background: loading ? '#334155' : '#3b82f6', border: 'none', borderRadius: '6px', color: 'white', fontSize: '14px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1, display: 'flex', alignItems: 'center', gap: '8px' }}
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

            {/* Why Death Counts May Vary */}
            <div style={{
              background: '#1a1f2e',
              border: '1px solid #3b82f6',
              borderRadius: '12px',
              padding: '24px',
              marginTop: '32px'
            }}>
              <h3 style={{
                color: '#60a5fa',
                fontSize: '16px',
                fontWeight: '600',
                marginTop: 0,
                marginBottom: '12px'
              }}>
                Why Death Counts May Vary
              </h3>
              <p style={{
                color: '#cbd5e1',
                fontSize: '14px',
                margin: 0,
                lineHeight: '1.7'
              }}>
                You may notice slight differences (maybe a death per character) between analysis runs due to new reports being uploaded, timestamp edge cases, or WarcraftLogs API updates. These variations don't significantly impact death rate percentages—the tool prioritizes accuracy over perfect consistency.
              </p>
            </div>
          </div>
          } />
          
          <Route path="/results" element={
            <>
            {data ? (
              <div>
            {/* Analysis Title */}
            <div style={{
              background: '#1a1f2e',
              borderRadius: '12px',
              padding: '24px',
              marginBottom: '24px',
              border: '1px solid #2d3748'
            }}>
              <h1 style={{
                margin: 0,
                fontSize: '28px',
                fontWeight: '700',
                color: '#e2e8f0',
                marginBottom: '8px'
              }}>
                {config.guildName} - {config.server}
              </h1>
              <div style={{
                display: 'flex',
                gap: '16px',
                flexWrap: 'wrap',
                alignItems: 'center',
                fontSize: '14px',
                color: '#94a3b8'
              }}>
                <span>
                  {RAID_ZONES[config.selectedRaid]?.name} • {
                    config.difficulty === '3' ? 'Normal' :
                    config.difficulty === '4' ? 'Heroic' : 'Mythic'
                  }
                </span>
                <span>•</span>
                <span>
                  Analyzed on {new Date().toLocaleDateString('en-US', { 
                    month: 'short', 
                    day: 'numeric', 
                    year: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit'
                  })}
                </span>
              </div>
            </div>

            <div style={{ background: '#1a1f2e', borderRadius: '8px', padding: '14px', marginBottom: '16px', border: '1px solid #2d3748' }}>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: '#cbd5e1' }}>
                  Deaths to count:
                  <div 
                    style={{ 
                      position: 'relative', 
                      display: 'inline-flex',
                      cursor: 'help'
                    }}
                    title="Filter results to show only deaths up to this number per pull. Helps focus analysis on early deaths vs late-fight wipe cascades. Change this to see how different death thresholds affect player rankings."
                  >
                    <Info size={14} style={{ color: '#64748b' }} />
                  </div>
                </label>
                <select
                  value={cutoff}
                  onChange={(e) => setCutoff(parseInt(e.target.value))}
                  style={{ padding: '6px 10px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px' }}
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
                      <div style={{ marginLeft: '12px', fontSize: '11px', color: '#8b92a0', padding: '4px 8px', background: '#0f1419', borderRadius: '4px' }}>
                        Legend: <span style={{ color: '#cbd5e1' }}>Top</span> = Real deaths only, <span style={{ color: '#34d399' }}>Bottom (green)</span> = Including cheat deaths
                      </div>
                    </>
                  );
                })()}

                <div style={{ marginLeft: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Filter size={14} />
                  <span style={{ fontSize: '13px', color: '#cbd5e1' }}>Boss filters:</span>
                </div>
                {sortBossesByOrder(Object.keys(data.bossParticipation), config.selectedRaid).map(boss => (
                  <button
                    key={boss}
                    onClick={() => toggleBoss(boss)}
                    style={{ padding: '4px 10px', background: selectedBosses.has(boss) ? '#3b82f6' : '#2d3748', border: '1px solid ' + (selectedBosses.has(boss) ? '#3b82f6' : '#334155'), borderRadius: '14px', color: 'white', cursor: 'pointer', fontSize: '12px' }}
                  >
                    {boss}
                  </button>
                ))}
              </div>

              {/* Minimum Pulls Filter */}
              <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <label style={{ fontSize: '13px', color: '#cbd5e1' }}>Minimum pulls:</label>
                <input
                  type="text"
                  value={minPulls}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val === '' || /^\d+$/.test(val)) {
                      setMinPulls(val === '' ? 0 : parseInt(val));
                    }
                  }}
                  style={{ width: '80px', padding: '6px 10px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px' }}
                />
                <span style={{ fontSize: '11px', color: '#8b92a0' }}>
                  (Hide players with fewer than this many pulls)
                </span>
                
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search players..."
                  style={{ marginLeft: 'auto', width: '200px', padding: '6px 10px', background: '#0f1419', border: '1px solid #334155', borderRadius: '6px', color: '#e2e8f0', fontSize: '13px' }}
                />
              </div>

              {/* Hidden Players */}
              {hiddenPlayers.size > 0 && (() => {
                // Create a map of player names to their class for hidden players
                const playerClassMap = {};
                if (data && data.events) {
                  Object.keys(data.events).forEach(player => {
                    const events = data.events[player];
                    if (events.length > 0) {
                      playerClassMap[player] = events[0].class || 'Unknown';
                    }
                  });
                }
                
                return (
                <div style={{ marginTop: '12px', padding: '10px', background: '#0f1419', borderRadius: '6px', border: '1px solid #334155' }}>
                  <div style={{ fontSize: '12px', color: '#cbd5e1', marginBottom: '6px', fontWeight: '500' }}>
                    Hidden Players ({hiddenPlayers.size}):
                  </div>
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {Array.from(hiddenPlayers).map(player => {
                      const playerClass = playerClassMap[player] || 'Unknown';
                      const classColor = WOW_CLASS_COLORS[playerClass] || '#cbd5e1';
                      
                      return (
                      <button
                        key={player}
                        onClick={() => togglePlayerVisibility(player)}
                        style={{
                          padding: '4px 8px',
                          background: '#1a1f2e',
                          border: '1px solid #334155',
                          borderRadius: '4px',
                          color: classColor,
                          cursor: 'pointer',
                          fontSize: '11px',
                          fontWeight: '500',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px'
                        }}
                        title={`Show ${player}`}
                      >
                        {player} <span style={{ color: '#8b92a0' }}>✓ Show</span>
                      </button>
                    )})}
                  </div>
                </div>
                );
              })()}

              {/* Character Grouping UI */}
              <div style={{ marginTop: '12px', background: '#0f1419', borderRadius: '6px', border: '1px solid #334155', overflow: 'hidden' }}>
                <button
                  onClick={() => setShowGroupingUI(!showGroupingUI)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: '#1a1f2e',
                    border: 'none',
                    color: '#e2e8f0',
                    cursor: 'pointer',
                    fontSize: '13px',
                    fontWeight: '500',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    textAlign: 'left'
                  }}
                >
                  {showGroupingUI ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  Group Characters (Merge Alts with Mains)
                  {Object.keys(characterGroups).length > 0 && (
                    <span style={{ 
                      marginLeft: 'auto', 
                      padding: '2px 8px', 
                      background: '#3b82f6', 
                      borderRadius: '10px', 
                      fontSize: '11px',
                      fontWeight: '600'
                    }}>
                      {Object.keys(characterGroups).length} {Object.keys(characterGroups).length === 1 ? 'group' : 'groups'}
                    </span>
                  )}
                </button>

                {showGroupingUI && (() => {
                  // Get all players from the grid
                  const { players } = getOverviewData();
                  
                  // Filter out already grouped alts
                  const groupedAlts = new Set();
                  Object.values(characterGroups).forEach(alts => {
                    alts.forEach(alt => groupedAlts.add(alt));
                  });
                  
                  // Filter by search query as well
                  const availablePlayers = players
                    .filter(p => !groupedAlts.has(p))
                    .filter(p => !searchQuery || p.toLowerCase().includes(searchQuery.toLowerCase()));
                  
                  // Filter current groups by search query
                  const filteredGroups = Object.entries(characterGroups).filter(([main, alts]) => {
                    if (!searchQuery) return true;
                    const query = searchQuery.toLowerCase();
                    // Show group if main matches or any alt matches
                    return main.toLowerCase().includes(query) || 
                           alts.some(alt => alt.toLowerCase().includes(query));
                  });
                  
                  return (
                    <div style={{ padding: '12px' }}>
                      {/* Existing Groups */}
                      {filteredGroups.length > 0 && (
                        <div style={{ marginBottom: '12px' }}>
                          <div style={{ fontSize: '12px', color: '#cbd5e1', marginBottom: '8px', fontWeight: '500' }}>
                            Current Groups:
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            {filteredGroups.map(([main, alts]) => (
                              <div
                                key={main}
                                style={{
                                  padding: '8px 10px',
                                  background: '#1a1f2e',
                                  border: '1px solid #2d3748',
                                  borderRadius: '6px',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '8px'
                                }}
                              >
                                <span style={{ color: '#3b82f6', fontSize: '12px', fontWeight: '600' }}>
                                  {main}
                                </span>
                                <span style={{ color: '#64748b', fontSize: '11px' }}>+</span>
                                <span style={{ color: '#94a3b8', fontSize: '11px' }}>
                                  {alts.join(', ')}
                                </span>
                                <button
                                  onClick={() => {
                                    const newGroups = { ...characterGroups };
                                    delete newGroups[main];
                                    setCharacterGroups(newGroups);
                                  }}
                                  style={{
                                    marginLeft: 'auto',
                                    padding: '4px 8px',
                                    background: '#dc2626',
                                    border: 'none',
                                    borderRadius: '4px',
                                    color: '#fff',
                                    cursor: 'pointer',
                                    fontSize: '10px',
                                    fontWeight: '500'
                                  }}
                                >
                                  Ungroup
                                </button>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Selection Interface */}
                      <div style={{ fontSize: '12px', color: '#cbd5e1', marginBottom: '8px', fontWeight: '500' }}>
                        Select characters to merge:
                      </div>
                      
                      <div style={{ 
                        display: 'grid', 
                        gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', 
                        gap: '6px',
                        marginBottom: '12px',
                        maxHeight: '200px',
                        overflowY: 'auto'
                      }}>
                        {availablePlayers.map(player => {
                          const playerClass = data.events[player]?.[0]?.class || 'Unknown';
                          const classColor = WOW_CLASS_COLORS[playerClass] || '#cbd5e1';
                          const isSelected = selectedForGrouping.has(player);
                          
                          return (
                            <button
                              key={player}
                              onClick={() => {
                                const newSelected = new Set(selectedForGrouping);
                                if (isSelected) {
                                  newSelected.delete(player);
                                } else {
                                  newSelected.add(player);
                                }
                                setSelectedForGrouping(newSelected);
                              }}
                              style={{
                                padding: '6px 10px',
                                background: isSelected ? '#3b82f6' : '#1a1f2e',
                                border: '1px solid ' + (isSelected ? '#3b82f6' : '#2d3748'),
                                borderRadius: '4px',
                                color: isSelected ? '#fff' : classColor,
                                cursor: 'pointer',
                                fontSize: '11px',
                                fontWeight: '500',
                                textAlign: 'left',
                                transition: 'all 0.2s'
                              }}
                            >
                              {isSelected && '✓ '}{player}
                            </button>
                          );
                        })}
                      </div>

                      {/* Merge Button */}
                      {selectedForGrouping.size >= 2 && (
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                          <div style={{ flex: 1 }}>
                            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>
                              Primary character (keep this name):
                            </label>
                            <select
                              id="mainCharSelect"
                              style={{
                                width: '100%',
                                padding: '6px 10px',
                                background: '#1a1f2e',
                                border: '1px solid #334155',
                                borderRadius: '4px',
                                color: '#e2e8f0',
                                fontSize: '12px'
                              }}
                            >
                              {Array.from(selectedForGrouping).map(player => (
                                <option key={player} value={player}>{player}</option>
                              ))}
                            </select>
                          </div>
                          <button
                            onClick={() => {
                              const mainSelect = document.getElementById('mainCharSelect');
                              const mainChar = mainSelect.value;
                              const alts = Array.from(selectedForGrouping).filter(p => p !== mainChar);
                              
                              if (mainChar && alts.length > 0) {
                                setCharacterGroups({
                                  ...characterGroups,
                                  [mainChar]: alts
                                });
                                setSelectedForGrouping(new Set());
                              }
                            }}
                            style={{
                              marginTop: '20px',
                              padding: '8px 16px',
                              background: '#10b981',
                              border: 'none',
                              borderRadius: '6px',
                              color: '#fff',
                              cursor: 'pointer',
                              fontSize: '12px',
                              fontWeight: '600'
                            }}
                          >
                            Merge Selected
                          </button>
                        </div>
                      )}

                      {selectedForGrouping.size > 0 && selectedForGrouping.size < 2 && (
                        <div style={{ 
                          padding: '8px 12px', 
                          background: '#1e293b', 
                          border: '1px solid #334155', 
                          borderRadius: '4px',
                          fontSize: '11px',
                          color: '#94a3b8'
                        }}>
                          Select at least 2 characters to merge
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* Overview Section - Collapsible */}
            <div style={{ background: '#1a1f2e', borderRadius: '8px', marginBottom: '16px', border: '1px solid #2d3748', overflow: 'hidden' }}>
              <button
                onClick={() => setOverviewCollapsed(!overviewCollapsed)}
                style={{ 
                  width: '100%', 
                  padding: '12px 16px', 
                  background: '#1a1f2e', 
                  border: 'none', 
                  borderBottom: overviewCollapsed ? 'none' : '1px solid #2d3748',
                  color: '#e2e8f0', 
                  cursor: 'pointer', 
                  fontSize: '15px', 
                  fontWeight: '600',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  textAlign: 'left',
                  transition: 'background 0.2s'
                }}
                onMouseOver={(e) => { e.currentTarget.style.background = '#212736'; }}
                onMouseOut={(e) => { e.currentTarget.style.background = '#1a1f2e'; }}
              >
                {overviewCollapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
                All Bosses Overview {overviewCollapsed && '(click to expand)'}
              </button>
              
              {!overviewCollapsed && (() => {
              const { bosses, players, grid } = getOverviewData();
              
              // Filter players by search query
              const searchFilteredPlayers = players.filter(player => 
                !searchQuery || player.toLowerCase().includes(searchQuery.toLowerCase())
              );
              
              const sortedPlayers = sortConfig.key 
                ? sortOverviewData(bosses, searchFilteredPlayers, grid, sortConfig.key) 
                : searchFilteredPlayers;
              
              // Calculate all percentage values for color scaling (use all players, not just filtered)
              const allRealRates = [];
              const allTotalRates = [];
              const allBossRealRates = {};
              const allBossTotalRates = {};
              
              bosses.forEach(boss => {
                allBossRealRates[boss] = [];
                allBossTotalRates[boss] = [];
              });
              
              players.forEach(player => {
                // Collect overall rates
                if (grid[player].overall.rate !== null) {
                  allRealRates.push(grid[player].overall.rate);
                }
                if (grid[player].overall.totalRate !== null) {
                  allTotalRates.push(grid[player].overall.totalRate);
                }
                
                // Collect per-boss rates
                bosses.forEach(boss => {
                  const cellData = grid[player][boss];
                  if (cellData.rate !== null) {
                    allBossRealRates[boss].push(cellData.rate);
                  }
                  if (cellData.totalRate !== null) {
                    allBossTotalRates[boss].push(cellData.totalRate);
                  }
                });
              });
              
              return (
                <div style={{ background: '#1a1f2e', borderRadius: '12px', padding: '16px', border: '1px solid #2d3748', overflowX: 'auto' }}>
                  <h2 style={{ margin: '0 0 14px', fontSize: '16px', fontWeight: '600', color: '#ffffff' }}>Death Rate Overview</h2>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                    <thead>
                      <tr style={{ background: '#0f1419' }}>
                        <th 
                          onClick={() => handleSort('player')}
                          style={{ padding: '10px', textAlign: 'left', borderBottom: '2px solid #334155', position: 'sticky', left: 0, background: '#0f1419', zIndex: 2, cursor: 'pointer', userSelect: 'none', color: '#ffffff' }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            Player {getSortIcon('player')}
                          </div>
                        </th>
                        {bosses.map(boss => (
                          <th 
                            key={boss} 
                            onClick={() => handleSort(boss)}
                            style={{ padding: '10px', textAlign: 'center', borderBottom: '2px solid #334155', minWidth: '80px', cursor: 'pointer', userSelect: 'none', color: '#ffffff' }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                              {boss} {getSortIcon(boss)}
                            </div>
                          </th>
                        ))}
                        <th 
                          onClick={() => handleSort('overall')}
                          style={{ padding: '10px', textAlign: 'center', borderBottom: '2px solid #334155', fontWeight: '700', minWidth: '80px', cursor: 'pointer', userSelect: 'none', color: '#ffffff' }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                            Overall {getSortIcon('overall')}
                          </div>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedPlayers.map(player => (
                        <tr key={player} style={{ borderBottom: '1px solid #2d3748' }}>
                          <td style={{ padding: '10px', fontWeight: '600', position: 'sticky', left: 0, background: '#1a1f2e', zIndex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                              <div style={{ color: WOW_CLASS_COLORS[grid[player].overall?.class] || '#ffffff' }}>
                                {player}{characterGroups[player] && characterGroups[player].length > 0 && ' (grouped)'}
                              </div>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  togglePlayerVisibility(player);
                                }}
                                style={{
                                  padding: '3px 8px',
                                  background: '#2d3748',
                                  border: '1px solid #334155',
                                  borderRadius: '4px',
                                  color: '#cbd5e1',
                                  cursor: 'pointer',
                                  fontSize: '10px',
                                  fontWeight: '500',
                                  whiteSpace: 'nowrap'
                                }}
                                title="Hide this player from results"
                              >
                                Hide
                              </button>
                            </div>
                          </td>
                          {bosses.map(boss => {
                            const cellData = grid[player][boss];
                            const showBothStats = cellData.hasCheatDeaths && cellData.totalDeaths > cellData.deaths;
                            
                            return (
                              <td key={boss} style={{ padding: '10px', textAlign: 'center' }}>
                                {cellData.rate !== null ? (
                                  showBothStats ? (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                      <span style={{ color: getPercentageColor(cellData.rate, allBossRealRates[boss]), fontWeight: '600', fontSize: '11px' }}>
                                        {cellData.rate.toFixed(1)}%
                                      </span>
                                      <span style={{ color: getPercentageColor(cellData.totalRate, allBossTotalRates[boss]), fontSize: '10px', fontWeight: '500' }}>
                                        ({cellData.totalRate.toFixed(1)}%)
                                      </span>
                                    </div>
                                  ) : (
                                    <span style={{ color: getPercentageColor(cellData.rate, allBossRealRates[boss]), fontWeight: '600' }}>
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
                                    <span style={{ color: getPercentageColor(grid[player].overall.rate, allRealRates), fontSize: '11px' }}>
                                      {grid[player].overall.rate.toFixed(1)}%
                                    </span>
                                    <span style={{ color: getPercentageColor(grid[player].overall.totalRate, allTotalRates), fontSize: '10px', fontWeight: '500' }}>
                                      ({grid[player].overall.totalRate.toFixed(1)}%)
                                    </span>
                                  </div>
                                ) : (
                                  <span style={{ color: getPercentageColor(grid[player].overall.rate, allRealRates) }}>
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
            </div>

            {/* Players Section */}
            <div style={{ background: '#1a1f2e', borderRadius: '8px', padding: '14px', border: '1px solid #2d3748' }}>
              <h2 style={{ margin: '0 0 12px', fontSize: '15px', fontWeight: '600', color: '#e2e8f0' }}>
                Players
              </h2>
              {(() => {
              const filteredStats = getFilteredStats();
              // Calculate all percentage values for color scaling
              const allRealRates = filteredStats.map(s => s.realRate);
              const allTotalRates = filteredStats.map(s => s.totalRate);
              
              return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {filteredStats.map(({ player, realDeaths, totalDeaths, cheatDeaths, pulls, realRate, totalRate, hasCheatDeaths, deathsByBoss, cheatDeathsByBoss, totalDeathsByBoss, topAbilitiesByBoss, class: playerClass, spec: playerSpec }) => {
                  const isExpanded = expandedPlayers.has(player);
                  const showBothStats = hasCheatDeaths && cheatDeaths > 0;
                  
                  return (
                    <div key={player} style={{ background: '#1a1f2e', borderRadius: '6px', border: '1px solid #2d3748', overflow: 'hidden' }}>
                      <div 
                        onClick={() => togglePlayer(player)}
                        style={{ 
                          padding: '8px 12px', 
                          display: 'flex', 
                          justifyContent: 'space-between', 
                          alignItems: 'center', 
                          cursor: 'pointer',
                          background: isExpanded ? '#0f1419' : '#1a1f2e',
                          transition: 'background 0.2s'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1 }}>
                          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          <div style={{ flex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', flexWrap: 'wrap' }}>
                              <h3 style={{ margin: 0, fontSize: '14px', fontWeight: '600', color: WOW_CLASS_COLORS[playerClass] || '#ffffff' }}>
                                {player}{characterGroups[player] && characterGroups[player].length > 0 && ' (grouped)'}
                              </h3>
                              {showBothStats ? (
                                <>
                                  <span style={{ fontSize: '13px', color: '#8b92a0' }}>—</span>
                                  <span style={{ fontSize: '13px', color: '#e2e8f0' }}>
                                    {realDeaths} death{realDeaths !== 1 ? 's' : ''} / {pulls} pulls
                                  </span>
                                  <span style={{ fontSize: '13px', color: '#8b92a0' }}>·</span>
                                  <span style={{ fontSize: '14px', fontWeight: '600', color: getPercentageColor(realRate, allRealRates) }}>
                                    {realRate.toFixed(1)}%
                                  </span>
                                  <span style={{ fontSize: '11px', color: '#34d399' }}>
                                    (+{cheatDeaths} cheat)
                                  </span>
                                </>
                              ) : (
                                <>
                                  <span style={{ fontSize: '13px', color: '#8b92a0' }}>—</span>
                                  <span style={{ fontSize: '13px', color: '#e2e8f0' }}>
                                    {realDeaths} death{realDeaths !== 1 ? 's' : ''} / {pulls} pulls
                                  </span>
                                  <span style={{ fontSize: '13px', color: '#8b92a0' }}>·</span>
                                  <span style={{ fontSize: '14px', fontWeight: '600', color: getPercentageColor(realRate, allRealRates) }}>
                                    {realRate.toFixed(1)}%
                                  </span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                        
                        <div style={{ display: 'flex', alignItems: 'center', marginLeft: '12px' }}>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              togglePlayerVisibility(player);
                            }}
                            style={{
                              padding: '3px 8px',
                              background: '#2d3748',
                              border: '1px solid #334155',
                              borderRadius: '4px',
                              color: '#cbd5e1',
                              cursor: 'pointer',
                              fontSize: '10px',
                              fontWeight: '500'
                            }}
                            title="Hide this player from results"
                          >
                            Hide
                          </button>
                        </div>
                      </div>

                      {isExpanded && (
                        <div style={{ padding: '0 14px 12px', borderTop: '1px solid #2d3748' }}>
                          {sortBossesByOrder(Object.keys(deathsByBoss), config.selectedRaid).map(boss => {
                            const bossDeaths = deathsByBoss[boss];
                            const bossPulls = data.bossParticipation[boss]?.[player]?.length || 0;
                            const realDeathCount = bossDeaths.length;
                            const totalBossDeaths = totalDeathsByBoss[boss] || [];
                            const totalDeathCount = totalBossDeaths.length;
                            const cheatDeathCount = totalBossDeaths.filter(d => d.isCheatDeath).length;
                            const bossRealRate = bossPulls > 0 ? (realDeathCount / bossPulls * 100) : 0;
                            const bossTotalRate = bossPulls > 0 ? (totalDeathCount / bossPulls * 100) : 0;
                            
                            return (
                            <div key={boss} style={{ marginTop: '10px' }}>
                              <h4 style={{ margin: '0 0 8px', fontSize: '13px', fontWeight: '600', color: '#3b82f6' }}>
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
                                <div style={{ marginBottom: '8px', padding: '6px 8px', background: '#0f1419', borderRadius: '4px' }}>
                                  <div style={{ fontSize: '10px', color: '#8b92a0', marginBottom: '3px' }}>Top Abilities:</div>
                                  <div style={{ fontSize: '11px', color: '#cbd5e1' }}>
                                    {topAbilitiesByBoss[boss].map(([ability, count], idx) => (
                                      <span key={ability}>
                                        {idx + 1}. {ability} ({count}){idx < topAbilitiesByBoss[boss].length - 1 ? ' • ' : ''}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}

                              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                {(showBothStats ? totalBossDeaths : bossDeaths)
                                  .map((death, idx) => (
                                  <div key={idx} style={{ 
                                    display: 'flex', 
                                    flexDirection: 'column',
                                    gap: '6px',
                                    padding: '6px 8px',
                                    background: death.isCheatDeath ? '#2d3a2d' : '#0f1419',
                                    borderLeft: death.isCheatDeath ? '2px solid #34d399' : 'none',
                                    borderRadius: '4px',
                                    fontSize: '11px'
                                  }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
                                        <span style={{ color: '#e2e8f0' }}>
                                          {death.abilityName === 'Unknown' ? (
                                            <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>
                                              Unknown ability
                                            </span>
                                          ) : death.abilityName}
                                        </span>
                                      </div>
                                      <a 
                                        href={getWCLLink(death.reportId, death.fightId)} 
                                        target="_blank" 
                                        rel="noopener noreferrer"
                                        style={{ 
                                          display: 'flex', 
                                          alignItems: 'center', 
                                          gap: '4px', 
                                          color: '#3b82f6', 
                                          textDecoration: 'none',
                                          fontSize: '11px'
                                        }}
                                      >
                                        View Log <ExternalLink size={12} />
                                      </a>
                                    </div>

                                    {/* Defensive Abilities Display */}
                                    {config.enableDefensiveTracking && death.defensives && (
                                      <div style={{
                                        marginTop: '4px',
                                        padding: '6px 8px',
                                        background: '#1a1f2e',
                                        borderRadius: '4px',
                                        borderLeft: '2px solid #60a5fa'
                                      }}>
                                        <div style={{ 
                                          display: 'flex', 
                                          gap: '6px', 
                                          flexWrap: 'wrap',
                                          alignItems: 'center'
                                        }}>
                                          <span style={{ 
                                            color: '#60a5fa', 
                                            fontSize: '10px',
                                            fontWeight: '600',
                                            marginRight: '4px'
                                          }}>
                                            ACTIVE BUFFS:
                                          </span>
                                          {death.defensives.abilities && death.defensives.abilities.length > 0 ? (
                                            death.defensives.abilities.map((def, defIdx) => (
                                              <span 
                                                key={defIdx}
                                                style={{
                                                  color: '#cbd5e1',
                                                  fontSize: '10px',
                                                  padding: '2px 6px',
                                                  background: '#0f1419',
                                                  borderRadius: '3px',
                                                  border: '1px solid #334155'
                                                }}
                                              >
                                                {def.name} ({def.count}×)
                                              </span>
                                            ))
                                          ) : (
                                            <span style={{ 
                                              color: '#ef4444', 
                                              fontSize: '10px',
                                              fontStyle: 'italic'
                                            }}>
                                              None active
                                            </span>
                                          )}
                                        </div>
                                        {death.defensives.healing !== undefined && (
                                          <div style={{ 
                                            marginTop: '4px',
                                            fontSize: '10px',
                                            color: '#94a3b8'
                                          }}>
                                            Healing received: <span style={{ color: '#10b981', fontWeight: '500' }}>
                                              {death.defensives.healing.toLocaleString()}
                                            </span>
                                          </div>
                                        )}
                                      </div>
                                    )}
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
          </div>
            ) : (
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '400px',
                padding: '40px'
              }}>
                <p style={{ color: '#94a3b8', fontSize: '16px', marginBottom: '16px' }}>
                  {error ? error : 'No analysis data yet. Configure and run an analysis to see results.'}
                </p>
                <button
                  onClick={() => navigate('/analyze')}
                  style={{
                    padding: '10px 20px',
                    background: '#3b82f6',
                    border: 'none',
                    borderRadius: '6px',
                    color: '#fff',
                    fontSize: '14px',
                    fontWeight: '600',
                    cursor: 'pointer'
                  }}
                >
                  Run Analysis
                </button>
              </div>
            )}
            </>
          } />
          
          <Route path="/saved" element={
            <div style={{ padding: '40px 20px' }}>
              <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
                <h2 style={{ 
                  color: '#e2e8f0',
                  fontSize: '28px',
                  fontWeight: '700',
                  marginBottom: '24px'
                }}>
                  Saved Reports
                </h2>
                <div style={{
                  background: '#1a1f2e',
                  borderRadius: '12px',
                  padding: '40px',
                  border: '1px solid #2d3748',
                  textAlign: 'center'
                }}>
                  <p style={{ color: '#94a3b8', fontSize: '16px', marginBottom: '20px' }}>
                    Saved reports feature coming soon!
                  </p>
                  <button
                    onClick={() => navigate('/analyze')}
                    style={{
                      padding: '10px 20px',
                      background: '#3b82f6',
                      border: 'none',
                      borderRadius: '6px',
                      color: '#fff',
                      fontSize: '14px',
                      fontWeight: '600',
                      cursor: 'pointer'
                    }}
                  >
                    Run New Analysis
                  </button>
                </div>
              </div>
            </div>
          } />
        </Routes>
      </div>
          </>
        } />
      </Routes>

      {/* Auth Modal */}
      {showAuthModal && (
        <Auth 
          onClose={() => setShowAuthModal(false)}
          onShowTerms={() => {
            setShowAuthModal(false);
            navigate('/terms');
          }}
          onShowPrivacy={() => {
            setShowAuthModal(false);
            navigate('/privacy');
          }}
        />
      )}

      {/* Settings Modal */}
      {showSettings && user && (
        <Settings 
          user={user} 
          onClose={() => setShowSettings(false)}
          onCredentialsUpdate={loadAPICredentials}
          onShowPrivacy={() => {
            setShowSettings(false);
            navigate('/privacy');
          }}
        />
      )}

      {/* Info Modal - How It Works */}
      {showInfoModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.85)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '20px',
          overflowY: 'auto'
        }}>
          <div style={{
            maxWidth: '700px',
            width: '100%',
            background: '#1a1f2e',
            borderRadius: '12px',
            border: '2px solid #3b82f6',
            position: 'relative',
            maxHeight: '90vh',
            overflowY: 'auto'
          }}>
            <div style={{ position: 'sticky', top: 0, background: '#1a1f2e', padding: '24px 24px 16px', borderBottom: '1px solid #2d3748', zIndex: 1 }}>
              <button
                onClick={() => setShowInfoModal(false)}
                style={{
                  position: 'absolute',
                  top: '16px',
                  right: '16px',
                  background: 'transparent',
                  border: 'none',
                  color: '#94a3b8',
                  cursor: 'pointer',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center'
                }}
              >
                <X size={20} />
              </button>
              <h2 style={{ 
                color: '#3b82f6', 
                margin: 0,
                fontSize: '24px',
                fontWeight: '700',
                display: 'flex',
                alignItems: 'center',
                gap: '10px'
              }}>
                <Info size={24} />
                How Floor Pov Works
              </h2>
            </div>

            <div style={{ padding: '24px', color: '#e2e8f0', lineHeight: '1.7' }}>
              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginTop: 0, marginBottom: '12px' }}>
                Data Collection & Processing
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                Floor Pov analyzes raid death data from WarcraftLogs by:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '24px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Fetching all guild reports for your selected raid and difficulty</li>
                <li style={{ marginBottom: '8px' }}>Processing death events from each pull</li>
                <li style={{ marginBottom: '8px' }}>Tracking player participation across all fights</li>
                <li style={{ marginBottom: '8px' }}>Calculating death rates (deaths per pull) for each player and boss</li>
              </ul>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginBottom: '12px' }}>
                Data Validation & Completeness
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                Floor Pov ensures you're getting complete and accurate data through multiple verification steps:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}><strong>Comprehensive report fetching:</strong> Retrieves all available reports for your guild within the specified date range, ensuring no logs are missed</li>
                <li style={{ marginBottom: '8px' }}><strong>Participation tracking:</strong> Cross-references player presence across all fights to ensure accurate "pulls participated" counts</li>
                <li style={{ marginBottom: '8px' }}><strong>Fight boundary validation:</strong> Verifies fight start and end timestamps to ensure all deaths within valid encounters are captured</li>
                <li style={{ marginBottom: '8px' }}><strong>Missing data detection:</strong> Identifies and handles edge cases where WarcraftLogs data may be incomplete or corrupted</li>
              </ul>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginBottom: '12px' }}>
                Deduplication & Data Accuracy
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                To ensure accurate results, Floor Pov uses <strong>smart deduplication</strong>:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}><strong>Report-level deduplication:</strong> The same pull may appear in multiple reports (different log uploaders). We detect and merge these duplicates based on fight timestamps and boss encounters.</li>
                <li style={{ marginBottom: '8px' }}><strong>Character name normalization:</strong> Handles special characters and accents in player names (e.g., "Catëlynn" vs "Catelynn")</li>
                <li style={{ marginBottom: '8px' }}><strong>Death timestamp filtering:</strong> Only counts deaths within the valid fight window to ensure accuracy</li>
                <li style={{ marginBottom: '8px' }}><strong>Mass death detection:</strong> Identifies raid wipes (7+ deaths within 10 seconds) to properly track fight boundaries</li>
              </ul>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginBottom: '12px' }}>
                Why Death Counts May Vary Between Runs
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                You may notice slight differences in death counts between different analysis runs of the same guild. This is normal and can happen due to:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}><strong>New reports uploaded:</strong> Guild members may upload additional logs between runs</li>
                <li style={{ marginBottom: '8px' }}><strong>Timestamp edge cases:</strong> Deaths occurring exactly at fight end boundaries may be handled differently</li>
                <li style={{ marginBottom: '8px' }}><strong>WarcraftLogs API updates:</strong> The upstream data source occasionally corrects or updates historical data</li>
              </ul>
              <p style={{ color: '#94a3b8', fontSize: '13px', fontStyle: 'italic', background: '#0f1419', padding: '12px', borderRadius: '6px', borderLeft: '3px solid #3b82f6' }}>
                💡 <strong>Tip:</strong> These variations are maybe a death per character and don't significantly impact death rate percentages. The tool prioritizes accuracy over perfect consistency.
              </p>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginTop: '24px', marginBottom: '12px' }}>
                Cheat Death Detection (Premium)
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                For logged-in users, Floor Pov can detect "cheat deaths" - deaths that were prevented by defensive abilities:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Mage: Cauterize</li>
                <li style={{ marginBottom: '8px' }}>Priest: Spirit of Redemption</li>
                <li style={{ marginBottom: '8px' }}>Rogue: Cheat Death</li>
                <li style={{ marginBottom: '8px' }}>Death Knight: Purgatory</li>
                <li style={{ marginBottom: '8px' }}>Paladin: Divine Shield (when preventing lethal damage)</li>
                <li style={{ marginBottom: '8px' }}>And more...</li>
              </ul>
              <p style={{ color: '#94a3b8', fontSize: '13px', background: '#0f1419', padding: '12px', borderRadius: '6px' }}>
                Note: Cheat death detection requires 1 additional API call per report and adds ~20-30 seconds to analysis time.
              </p>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginTop: '24px', marginBottom: '12px' }}>
                Character Grouping (Alts)
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                You can group alternate characters with their mains to see combined statistics. This merges:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '24px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Total deaths across all characters</li>
                <li style={{ marginBottom: '8px' }}>Total pulls participated in</li>
                <li style={{ marginBottom: '8px' }}>Combined death rate calculations</li>
              </ul>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginBottom: '12px' }}>
                Questions or Issues?
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '8px' }}>
                Floor Pov is in active alpha development. If you encounter bugs or have suggestions:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', paddingLeft: '20px', marginBottom: 0 }}>
                <li style={{ marginBottom: '8px' }}>Check the site updates in the footer for recent changes</li>
                <li style={{ marginBottom: '8px' }}>Report issues or request features (contact info coming soon)</li>
                <li>Join our Discord community (link coming soon)</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Terms & Privacy Modal */}
      {showTermsModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.85)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
          padding: '20px',
          overflowY: 'auto'
        }}>
          <div style={{
            maxWidth: '700px',
            width: '100%',
            background: '#1a1f2e',
            borderRadius: '12px',
            border: '2px solid #3b82f6',
            position: 'relative',
            maxHeight: '90vh',
            overflowY: 'auto'
          }}>
            <div style={{ position: 'sticky', top: 0, background: '#1a1f2e', padding: '24px 24px 16px', borderBottom: '1px solid #2d3748', zIndex: 1 }}>
              <button
                onClick={() => setShowTermsModal(false)}
                style={{
                  position: 'absolute',
                  top: '16px',
                  right: '16px',
                  background: 'transparent',
                  border: 'none',
                  color: '#94a3b8',
                  cursor: 'pointer',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center'
                }}
              >
                <X size={20} />
              </button>
              <h2 style={{ 
                color: '#3b82f6', 
                margin: 0,
                fontSize: '24px',
                fontWeight: '700'
              }}>
                Terms of Service & Privacy Policy
              </h2>
            </div>

            <div style={{ padding: '24px', color: '#e2e8f0', lineHeight: '1.7' }}>
              <p style={{ color: '#94a3b8', fontSize: '13px', fontStyle: 'italic', marginBottom: '24px' }}>
                Last Updated: November 21, 2025
              </p>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginTop: 0, marginBottom: '12px' }}>
                1. Terms of Service
              </h3>
              
              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                1.1 Acceptance of Terms
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                By accessing or using Floor Pov ("the Service"), you agree to be bound by these Terms of Service. If you do not agree to these terms, please do not use the Service.
              </p>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                1.2 Alpha Software Disclaimer
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                Floor Pov is currently in <strong>alpha testing</strong>. The Service is provided "as is" without warranties of any kind. Features may change, be removed, or malfunction without notice. We are not liable for any data loss, errors, or issues arising from use of the Service.
              </p>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                1.3 WarcraftLogs API Usage
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                Floor Pov uses the WarcraftLogs API to retrieve publicly available raid data. You are responsible for providing your own WarcraftLogs API credentials. By using this Service, you agree to comply with WarcraftLogs' Terms of Service and API usage policies.
              </p>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                1.4 Acceptable Use
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                You agree not to:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Use the Service for any illegal or unauthorized purpose</li>
                <li style={{ marginBottom: '8px' }}>Attempt to access, modify, or interfere with the Service's infrastructure</li>
                <li style={{ marginBottom: '8px' }}>Abuse rate limits or attempt to overload the Service</li>
                <li style={{ marginBottom: '8px' }}>Use the Service to harass, bully, or harm other players</li>
                <li>Share or distribute others' API credentials without permission</li>
              </ul>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                1.5 Account Termination
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                We reserve the right to suspend or terminate accounts that violate these terms, abuse the service or API rate limits, or engage in fraudulent or malicious activity. You may delete your account at any time through your account settings.
              </p>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                1.6 Disclaimer and Limitation of Liability
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                FLOOR POV IS PROVIDED "AS IS" WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED. TO THE MAXIMUM EXTENT PERMITTED BY LAW, WE DISCLAIM ALL WARRANTIES INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.
              </p>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                IN NO EVENT SHALL FLOOR POV OR ITS OPERATORS BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF PROFITS, DATA, OR USE, ARISING OUT OF OR RELATED TO YOUR USE OF THE SERVICE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. Some jurisdictions do not allow the exclusion of certain warranties or limitation of liability, so the above limitations may not apply to you.
              </p>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                1.7 Intellectual Property
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                The Floor Pov website design, code, and branding are proprietary and protected by copyright. You may not copy, modify, distribute, or reverse engineer the Service. Analysis results you generate are yours to use and share. WarcraftLogs data remains the property of Warcraft Logs and Blizzard Entertainment.
              </p>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                1.8 Governing Law
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                These terms are governed by the laws of the State of Florida, United States. Any disputes shall be resolved in the appropriate courts of Florida.
              </p>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginTop: '24px', marginBottom: '12px' }}>
                2. Privacy Policy
              </h3>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                2.1 Data We Collect
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                When you create an account, we collect:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}><strong>Account Information:</strong> Email address and encrypted password</li>
                <li style={{ marginBottom: '8px' }}><strong>API Credentials:</strong> Your WarcraftLogs API Client ID and Secret (encrypted at rest)</li>
                <li style={{ marginBottom: '8px' }}><strong>Analysis History:</strong> Guild names, servers, and analysis configurations you've run</li>
                <li><strong>Usage Data:</strong> Basic analytics about feature usage and errors (no personal identifying information)</li>
              </ul>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                2.2 How We Use Your Data
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                We use your data to:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Provide authentication and account management</li>
                <li style={{ marginBottom: '8px' }}>Store your API credentials securely for future analyses</li>
                <li style={{ marginBottom: '8px' }}>Improve the Service and fix bugs</li>
                <li>Send important service updates (account security, major changes)</li>
              </ul>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                2.3 Data Security
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                We implement industry-standard security measures:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Passwords are hashed using bcrypt</li>
                <li style={{ marginBottom: '8px' }}>API credentials are encrypted at rest</li>
                <li style={{ marginBottom: '8px' }}>Database access is protected with Row-Level Security (RLS) policies</li>
                <li>HTTPS encryption for all data in transit</li>
              </ul>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                2.4 Data Sharing
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                We <strong>do not sell, rent, or share</strong> your personal data with third parties, except:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Service providers necessary for operation (Supabase for database, Render for hosting)</li>
                <li style={{ marginBottom: '8px' }}>When required by law or to protect our legal rights</li>
                <li>With your explicit consent</li>
              </ul>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                2.5 Third-Party Services
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                Floor Pov integrates with:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}><strong>WarcraftLogs:</strong> We access publicly available raid data on your behalf using your API credentials</li>
                <li style={{ marginBottom: '8px' }}><strong>Supabase:</strong> Our authentication and database provider</li>
                <li style={{ marginBottom: '8px' }}><strong>Resend:</strong> Email delivery service for account confirmations and notifications</li>
                <li><strong>Cloudflare:</strong> CDN and API proxy for performance</li>
              </ul>
              <p style={{ color: '#94a3b8', fontSize: '13px', marginBottom: '16px' }}>
                Each service has its own privacy policy. We recommend reviewing them.
              </p>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                2.6 Your Rights
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '12px' }}>
                You have the right to:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Access your personal data</li>
                <li style={{ marginBottom: '8px' }}>Update or correct your information</li>
                <li style={{ marginBottom: '8px' }}>Delete your account and associated data</li>
                <li>Opt out of non-essential communications</li>
              </ul>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                To exercise these rights, contact us (contact information coming soon to footer).
              </p>

              <h4 style={{ color: '#cbd5e1', fontSize: '15px', marginTop: '16px', marginBottom: '8px' }}>
                2.7 Cookies and Tracking
              </h4>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                We use essential cookies only for:
              </p>
              <ul style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px', paddingLeft: '20px' }}>
                <li style={{ marginBottom: '8px' }}>Authentication session management</li>
                <li>Remembering your preferences (e.g., dismissing the alpha banner)</li>
              </ul>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                We do not use third-party tracking or advertising cookies.
              </p>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginTop: '24px', marginBottom: '12px' }}>
                3. Changes to These Terms
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                We may update these terms as the Service evolves. Continued use of the Service after changes constitutes acceptance of the updated terms. Major changes will be announced via email and on the site.
              </p>

              <h3 style={{ color: '#60a5fa', fontSize: '18px', marginTop: '24px', marginBottom: '12px' }}>
                4. Contact
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '0' }}>
                For questions about these terms or your data, contact information will be added to the footer soon.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* DISABLED - Save Reports feature
      {showSaveDialog && user && data && (
        <SaveReportDialog
          analysisData={data}
          user={user}
          onClose={() => setShowSaveDialog(false)}
          onSaved={() => setShowSaveDialog(false)}
        />
      )}
      */}

      {/* Footer */}
      <footer style={{
        background: '#0f1419',
        borderTop: '1px solid #1e293b',
        marginTop: '60px',
        padding: '40px 24px',
        color: '#94a3b8'
      }}>
        <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
          {/* Links Section */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '32px'
          }}>
            <div>
              <h4 style={{
                color: '#e2e8f0',
                fontSize: '12px',
                fontWeight: '600',
                marginBottom: '12px',
                marginTop: 0,
                letterSpacing: '0.05em'
              }}>
                RESOURCES
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <a 
                  href="https://www.warcraftlogs.com/api/clients" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  style={{ color: '#94a3b8', fontSize: '13px', textDecoration: 'none', transition: 'color 0.2s' }}
                  onMouseOver={(e) => e.target.style.color = '#3b82f6'}
                  onMouseOut={(e) => e.target.style.color = '#94a3b8'}
                >
                  WarcraftLogs API
                </a>
                <a 
                  href="https://www.warcraftlogs.com/" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  style={{ color: '#94a3b8', fontSize: '13px', textDecoration: 'none', transition: 'color 0.2s' }}
                  onMouseOver={(e) => e.target.style.color = '#3b82f6'}
                  onMouseOut={(e) => e.target.style.color = '#94a3b8'}
                >
                  WarcraftLogs
                </a>
              </div>
            </div>

            <div>
              <h4 style={{
                color: '#e2e8f0',
                fontSize: '12px',
                fontWeight: '600',
                marginBottom: '12px',
                marginTop: 0,
                letterSpacing: '0.05em'
              }}>
                ABOUT
              </h4>
              <p style={{ color: '#64748b', fontSize: '12px', lineHeight: '1.6', margin: 0 }}>
                Floor Pov is a death analytics tool for World of Warcraft guilds using WarcraftLogs data.
              </p>
            </div>

            <div>
              <h4 style={{
                color: '#e2e8f0',
                fontSize: '12px',
                fontWeight: '600',
                marginBottom: '12px',
                marginTop: 0,
                letterSpacing: '0.05em'
              }}>
                LEGAL
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <a 
                  onClick={() => navigate('/terms')}
                  style={{ 
                    color: '#94a3b8', 
                    fontSize: '13px', 
                    textDecoration: 'none', 
                    transition: 'color 0.2s',
                    cursor: 'pointer'
                  }}
                  onMouseOver={(e) => e.target.style.color = '#3b82f6'}
                  onMouseOut={(e) => e.target.style.color = '#94a3b8'}
                >
                  Terms of Service
                </a>
                <a 
                  onClick={() => navigate('/privacy')}
                  style={{ 
                    color: '#94a3b8', 
                    fontSize: '13px', 
                    textDecoration: 'none', 
                    transition: 'color 0.2s',
                    cursor: 'pointer'
                  }}
                  onMouseOver={(e) => e.target.style.color = '#3b82f6'}
                  onMouseOut={(e) => e.target.style.color = '#94a3b8'}
                >
                  Privacy Policy
                </a>
              </div>
            </div>

            <div>
              <h4 style={{
                color: '#e2e8f0',
                fontSize: '12px',
                fontWeight: '600',
                marginBottom: '12px',
                marginTop: 0,
                letterSpacing: '0.05em'
              }}>
                CONTACT
              </h4>
              <a 
                href="mailto:support@floorpov.gg"
                style={{ 
                  color: '#94a3b8', 
                  fontSize: '13px', 
                  textDecoration: 'none', 
                  transition: 'color 0.2s'
                }}
                onMouseOver={(e) => e.target.style.color = '#3b82f6'}
                onMouseOut={(e) => e.target.style.color = '#94a3b8'}
              >
                support@floorpov.gg
              </a>
            </div>
          </div>
        </div>
      </footer>

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