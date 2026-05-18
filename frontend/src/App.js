import React, { useState, useEffect } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Search, AlertCircle, Loader2, Filter, ChevronDown, ChevronRight, ExternalLink, ArrowUpDown, ArrowUp, ArrowDown, Share2, Copy, Check, LogOut, Settings as SettingsIcon, Info, X, Crosshair, BarChart3, LogIn } from 'lucide-react';
import { supabase } from './supabaseClient';
import Auth from './Auth';
import Settings from './Settings';
import LandingPage from './LandingPage';
import AnalyzeConfig from './AnalyzeConfig';
import InfoModal from './InfoModal';
import FpxRail from './FpxRail';
import TermsOfService from './TermsOfService';
import PrivacyPolicy from './PrivacyPolicy';
import { MOCK_RESULTS, MOCK_CONFIG } from './mockResults';

// Automatically detect if running locally or in production
const API_URL = window.location.hostname === 'localhost' 
  ? 'http://localhost:5000' 
  : 'https://deathwarcraftlogs-api.onrender.com';


// Raid Zone Definitions
const RAID_ZONES = {
  // === MIDNIGHT SEASON 1 ===
  'voidspire': {
    name: 'The Voidspire',
    reportZone: '46',
    fightZone: '2912'
  },
  'dreamrift': {
    name: 'The Dreamrift',
    reportZone: '46',
    fightZone: '2939'
  },
  'queldanas': {
    name: "March on Quel'Danas",
    reportZone: '46',
    fightZone: '0'   // Opens March 31 — update fightZone then
  },
  'midnight-all': {
    name: 'Midnight S1 Raids',
    reportZone: '46',
    fightZone: '0'   // 0 = match all fights across all 3 raids
  },
  // === THE WAR WITHIN ===
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
  // === MIDNIGHT SEASON 1 ===
  'voidspire': [
    'Imperator Averzian',
    'Vorasius',
    'Fallen-King Salhadaar',
    'Vaelgor & Ezzorak',
    'Lightblinded Vanguard',
    'Crown of the Cosmos'
  ],
  'dreamrift': [
    'Chimaerus, the Undreamt God'
  ],
  'queldanas': [
    "Belo'ren",
    "L'ura"
  ],
  'midnight-all': [
    'Imperator Averzian',
    'Vorasius',
    'Fallen-King Salhadaar',
    'Vaelgor & Ezzorak',
    'Lightblinded Vanguard',
    'Crown of the Cosmos',
    'Chimaerus, the Undreamt God',
    "Belo'ren",
    "L'ura"
  ],
  // === THE WAR WITHIN ===
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
  const fullBleed = location.pathname === '/' || location.pathname === '/analyze' || location.pathname === '/results' || location.pathname === '/saved';
  const [resultsRailCollapsed, setResultsRailCollapsed] = useState(false);
  
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
  const [recentRuns, setRecentRuns] = useState([]);
  const [showRecentMenu, setShowRecentMenu] = useState(false);
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

  // Dev-only: ?mock=1 seeds the Results surface with a fixture so the
  // redesign can be iterated without a live WarcraftLogs run. Gated to
  // localhost (dev server + locally-served prod build) so it can never
  // fire on the deployed site, same idiom as API_URL above.
  useEffect(() => {
    const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
    if (!isLocal) return;
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('mock') === '1' && !data && !loading) {
      setConfig((prev) => ({ ...prev, ...MOCK_CONFIG }));
      setData(MOCK_RESULTS);
      if (location.pathname !== '/results') navigate('/results');
    }
    // ?loader=1 forces the analysis loader overlay so it can be previewed
    // without a live run (Cancel dismisses it).
    if (urlParams.get('loader') === '1' && !loading) {
      setLoadingStage('Fetching guild reports from WarcraftLogs…');
      setLoading(true);
    }
  }, [location.search, location.pathname, data, loading, navigate]);

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

  // ---- Recent runs (last 5, browser-local; no account needed) ----
  const RECENT_KEY = 'recentRuns';
  const MAX_RECENT = 5;

  const runLabel = (cfg) => ({
    title: `${cfg.guildName || 'Unknown guild'} · ${cfg.server || ''}`.trim().replace(/·\s*$/, '').trim(),
    sub: `${RAID_ZONES[cfg.selectedRaid]?.name || cfg.selectedRaid} · ${
      cfg.difficulty === '3' ? 'Normal' : cfg.difficulty === '4' ? 'Heroic' : 'Mythic'
    }`,
  });

  const loadRecentRuns = async () => {
    try {
      const arr = await loadFromIndexedDB(RECENT_KEY);
      return Array.isArray(arr) ? arr : [];
    } catch {
      return [];
    }
  };

  const saveRecentRun = async (resultData, cfg) => {
    try {
      const { title, sub } = runLabel(cfg);
      const record = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        savedAt: new Date().toISOString(),
        title,
        sub,
        config: { ...cfg },
        data: resultData,
      };
      const existing = await loadRecentRuns();
      const next = [record, ...existing].slice(0, MAX_RECENT);
      await saveToIndexedDB(RECENT_KEY, next);
      setRecentRuns(next);
    } catch (err) {
      console.error('[RecentRuns] save failed (non-fatal):', err);
    }
  };

  const removeRecentRun = async (id) => {
    try {
      const next = (await loadRecentRuns()).filter((r) => r.id !== id);
      await saveToIndexedDB(RECENT_KEY, next);
      setRecentRuns(next);
    } catch (err) {
      console.error('[RecentRuns] remove failed (non-fatal):', err);
    }
  };

  const openRecentRun = (record) => {
    setShowRecentMenu(false);
    setError('');
    setExpandedPlayers(new Set());
    setSortConfig({ key: null, direction: 'asc' });
    setConfig((prev) => ({ ...prev, ...record.config }));
    setData(record.data);
    if (location.pathname !== '/results') navigate('/results');
  };

  // hydrate the recent-runs list once on mount
  useEffect(() => {
    loadRecentRuns().then(setRecentRuns);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    setLoading(false);
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

        // CRITICAL FIX: Process remaining buffer before breaking on stream end
        if (done) {
          buffer += decoder.decode(); // Flush decoder
        } else {
          buffer += decoder.decode(value, { stream: true });
        }
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

              // Persist this completed run to the browser-local recent list
              saveRecentRun(data.result, config);

              // Navigate to results page after analysis completes
              navigate('/results');
            }
          }
        }
        if (done) break;
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
    
    // Assign extreme colors to outliers — endpoints clamped to stay
    // legible on the near-black fpx panels (dark green / dark red read
    // at ~3:1 on #0d111c; these floors keep severity meaning at ~5.5:1+)
    if (percentage < lowerBound) {
      return '#34aa5c'; // deep green for low outliers (good)
    }
    if (percentage > upperBound) {
      return '#f05248'; // red for high outliers (bad)
    }

    // Color scale for non-outliers
    if (percentage <= median) {
      // Below median: light green (#86efac) to deep green (#34aa5c)
      const ratio = (median - percentage) / (median - minVal);
      const r = Math.round(134 + (52 - 134) * ratio);
      const g = Math.round(239 + (170 - 239) * ratio);
      const b = Math.round(172 + (92 - 172) * ratio);
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
        // Light yellow (#fef08a) to red (#f05248)
        const localRatio = (ratio - 0.5) * 2;
        const r = Math.round(254 + (240 - 254) * localRatio);
        const g = Math.round(240 + (82 - 240) * localRatio);
        const b = Math.round(138 + (72 - 138) * localRatio);
        return `rgb(${r}, ${g}, ${b})`;
      }
    }
  };

  // Show loading while checking auth
  if (authLoading) {
    return (
      <div className="fp-analysis analysis-shell" style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Loader2 size={48} style={{ color: 'var(--color-gold-2)', animation: 'spin 1s linear infinite' }} />
      </div>
    );
  }

  // Main app (works for both logged in and anonymous users)
  return (
    <div className="fp-analysis analysis-shell app-shell" style={{ minHeight: '100vh' }}>
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
          <div className="surface-panel" style={{
            padding: '30px',
            border: '1px solid var(--color-border-strong)',
            maxWidth: '500px',
            width: '90%'
          }}>
            <h2 style={{
              marginTop: 0,
              marginBottom: '20px',
              fontSize: '24px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px'
            }}>
              <Share2 size={24} style={{ color: 'var(--color-gold-2)' }} />
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
                className={copied ? 'btn btn-success' : 'btn btn-primary'}
                style={{ flexShrink: 0 }}
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

      <div
        className={fullBleed ? 'fpx-landing-wrap' : 'analysis-content'}
        style={fullBleed ? undefined : { maxWidth: '1400px', margin: '0 auto', padding: '24px' }}
      >
        {loading && (
          <div className="fpx-loadov">
            <div className={`fpx-shell${resultsRailCollapsed ? ' collapsed' : ''}`}>
              <FpxRail
                collapsed={resultsRailCollapsed}
                onToggle={() => setResultsRailCollapsed((v) => !v)}
                active={null}
                onHome={() => { handleCancel(); navigate('/'); }}
                onAnalyze={() => { handleCancel(); navigate('/analyze'); }}
                onResults={() => { handleCancel(); navigate('/results'); }}
              />
              <div className="fpx-main fpx-loadmain">
                <div className="fpx-load">
                  <div className="fpx-load-orb">
                    <video
                      src={`${process.env.PUBLIC_URL}/art/lura-loader.webm`}
                      poster={`${process.env.PUBLIC_URL}/art/lura-loader.jpg`}
                      autoPlay loop muted playsInline aria-hidden="true"
                    />
                  </div>
                  <h2>ANALYZING REPORTS</h2>
                  <div className="stage">{loadingStage || 'Starting analysis…'}</div>
                  <p className="sub">Pulling data from WarcraftLogs — this can take a while.</p>
                  <button className="cancel" onClick={handleCancel}>Cancel analysis</button>
                </div>
              </div>
            </div>
          </div>
        )}

        <Routes>
          <Route path="/" element={
            <LandingPage
              onRunAnalysis={() => navigate('/analyze')}
              onSavedReports={null}  // DISABLED - Save Reports feature
              user={user}
              onShowAuthModal={() => setShowAuthModal(true)}
              onShowSettings={() => setShowSettings(true)}
              onLogout={handleLogout}
            />
          } />
          
          <Route path="/analyze" element={
            <AnalyzeConfig
              config={config}
              onChange={handleInputChange}
              onRaidChange={handleRaidChange}
              onSubmit={handleSubmit}
              setConfig={setConfig}
              loading={loading}
              error={error}
              user={user}
              onShowAuth={() => setShowAuthModal(true)}
              onShowSettings={() => setShowSettings(true)}
              onLogout={handleLogout}
              onShowInfo={() => setShowInfoModal(true)}
              onHome={() => { setData(null); setError(''); navigate('/'); }}
            />
          } />

          <Route path="/results" element={
            <>
            <div className="fpx-atmos base" />
            <div className="fpx-atmos vignette" />
            <div className="fpx-atmos grain" />
            <main className="fpx-land">
              <div className={`fpx-shell${resultsRailCollapsed ? ' collapsed' : ''}`}>
                <FpxRail
                  collapsed={resultsRailCollapsed}
                  onToggle={() => setResultsRailCollapsed((v) => !v)}
                  active="results"
                  onHome={() => { setData(null); setError(''); setExpandedPlayers(new Set()); setSortConfig({ key: null, direction: 'asc' }); navigate('/'); }}
                  onAnalyze={() => { setData(null); setError(''); setExpandedPlayers(new Set()); setSortConfig({ key: null, direction: 'asc' }); navigate('/analyze'); }}
                  onResults={() => {}}
                />

                <div className="fpx-main">
                  <div className="fpx-top fpx-rv">
                    <div className="fpx-crumbs">ANALYSIS&nbsp; /&nbsp; <b>RESULTS</b></div>
                    <div className="fpx-auth">
                      {data && (
                        <>
                          {recentRuns.length > 0 && (
                            <div className="fpx-recent">
                              <button className="fpx-btn ghost sm" onClick={() => setShowRecentMenu((v) => !v)}>
                                Recent <ChevronDown size={13} />
                              </button>
                              {showRecentMenu && (
                                <div className="fpx-recent-menu">
                                  {recentRuns.map((r) => (
                                    <div key={r.id} className="fpx-recent-item">
                                      <button className="open" onClick={() => openRecentRun(r)}>
                                        <span className="t">{r.title}</span>
                                        <span className="s">{r.sub} · {new Date(r.savedAt).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span>
                                      </button>
                                      <button className="rm" onClick={() => removeRecentRun(r.id)} title="Remove run">
                                        <X size={13} />
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                          <button className="fpx-btn ghost sm" onClick={() => { setData(null); setError(''); setExpandedPlayers(new Set()); setSortConfig({ key: null, direction: 'asc' }); navigate('/analyze'); }}>
                            <Crosshair size={15} /> New Analysis
                          </button>
                          <button className="fpx-btn sm" onClick={handleShare} disabled={sharingData}
                            style={{ opacity: sharingData ? 0.7 : 1, cursor: sharingData ? 'not-allowed' : 'pointer' }}>
                            {sharingData ? <><Loader2 size={15} className="fpx-spin" /> Sharing…</> : <><Share2 size={15} /> Share</>}
                          </button>
                        </>
                      )}
                      {user ? (
                        <>
                          <button className="fpx-btn ghost sm" onClick={() => setShowSettings(true)}><SettingsIcon size={15} /> Settings</button>
                          <button className="fpx-btn ghost sm" onClick={handleLogout}><LogOut size={15} /> Logout</button>
                        </>
                      ) : (
                        <button className="fpx-btn ghost sm" onClick={() => setShowAuthModal(true)}><LogIn size={15} /> Sign In</button>
                      )}
                    </div>
                  </div>

                  {data ? (
                    <>
                    <div className="fpx-pagehead fpx-rv">
                      <div>
                        <h2>{config.guildName} — {config.server}</h2>
                        <p>{RAID_ZONES[config.selectedRaid]?.name} · {
                          config.difficulty === '3' ? 'Normal' :
                          config.difficulty === '4' ? 'Heroic' : 'Mythic'
                        } · Analyzed {new Date().toLocaleDateString('en-US', {
                          month: 'short', day: 'numeric', year: 'numeric',
                          hour: 'numeric', minute: '2-digit'
                        })}</p>
                      </div>
                    </div>

                    <div className="fpx-results">

            <div className="fpx-rsec fpx-rv"><h3>FILTERS</h3><span className="sub">scope the death review</span><div className="rule" /></div>
            <div className="fpx-filters fpx-rv">
              <div className="fpx-frow">
                <label className="fpx-flabel">
                  Deaths to count
                  <span
                    title="Filter results to show only deaths up to this number per pull. Helps focus analysis on early deaths vs late-fight wipe cascades. Change this to see how different death thresholds affect player rankings."
                    style={{ display: 'inline-flex' }}
                  >
                    <Info size={14} />
                  </span>
                </label>
                <select value={cutoff} onChange={(e) => setCutoff(parseInt(e.target.value))}>
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
                      <span className="fpx-tag ok">✓ {cheatDeathCount} cheat deaths detected</span>
                      <span className="fpx-tag muted">
                        Legend: <b>Top</b> real only · <b style={{ color: 'var(--fpx-best)' }}>Bottom</b> incl. cheat
                      </span>
                    </>
                  );
                })()}

                <div className="fpx-flabel" style={{ marginLeft: '4px' }}>
                  <Filter size={14} /> Boss filters
                </div>
                {sortBossesByOrder(Object.keys(data.bossParticipation), config.selectedRaid).map(boss => (
                  <button
                    key={boss}
                    onClick={() => toggleBoss(boss)}
                    className={`fpx-chip${selectedBosses.has(boss) ? ' on' : ''}`}
                  >
                    {boss}
                  </button>
                ))}
              </div>

              {/* Minimum Pulls Filter */}
              <div className="fpx-frow">
                <label className="fpx-flabel">Minimum pulls</label>
                <input
                  type="text"
                  value={minPulls}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val === '' || /^\d+$/.test(val)) {
                      setMinPulls(val === '' ? 0 : parseInt(val));
                    }
                  }}
                  style={{ width: '88px' }}
                />
                <span style={{ fontSize: '11px', color: 'var(--fpx-ink-faint)' }}>
                  hide players below this pull count
                </span>

                <input
                  type="text"
                  className="fpx-search"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search players…"
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
                <div className="fpx-subpanel">
                  <div className="fpx-subpanel-t">Hidden players ({hiddenPlayers.size})</div>
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {Array.from(hiddenPlayers).map(player => {
                      const playerClass = playerClassMap[player] || 'Unknown';
                      const classColor = WOW_CLASS_COLORS[playerClass] || 'var(--fpx-ink)';

                      return (
                      <button
                        key={player}
                        onClick={() => togglePlayerVisibility(player)}
                        className="fpx-pill"
                        style={{ color: classColor }}
                        title={`Show ${player}`}
                      >
                        {player} <span style={{ color: 'var(--fpx-ink-faint)' }}>✓ show</span>
                      </button>
                    )})}
                  </div>
                </div>
                );
              })()}

              {/* Character Grouping UI */}
              <div className="fpx-acc">
                <button
                  onClick={() => setShowGroupingUI(!showGroupingUI)}
                  className="fpx-acc-head"
                >
                  {showGroupingUI ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  Group characters — merge alts with mains
                  {Object.keys(characterGroups).length > 0 && (
                    <span className="count">
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
                    <div className="fpx-acc-body">
                      {/* Existing Groups */}
                      {filteredGroups.length > 0 && (
                        <div>
                          <div className="fpx-subpanel-t">Current groups</div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            {filteredGroups.map(([main, alts]) => (
                              <div key={main} className="fpx-grouprow">
                                <span className="main">{main}</span>
                                <span className="plus">+</span>
                                <span className="alts">{alts.join(', ')}</span>
                                <button
                                  onClick={() => {
                                    const newGroups = { ...characterGroups };
                                    delete newGroups[main];
                                    setCharacterGroups(newGroups);
                                  }}
                                  className="fpx-ungroup"
                                >
                                  Ungroup
                                </button>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Selection Interface */}
                      <div>
                        <div className="fpx-subpanel-t">Select characters to merge</div>
                        <div className="fpx-pillgrid">
                          {availablePlayers.map(player => {
                            const playerClass = data.events[player]?.[0]?.class || 'Unknown';
                            const classColor = WOW_CLASS_COLORS[playerClass] || 'var(--fpx-ink)';
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
                                className={`fpx-pill${isSelected ? ' on' : ''}`}
                                style={{ color: isSelected ? undefined : classColor, textAlign: 'left' }}
                              >
                                {isSelected && '✓ '}{player}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* Merge Button */}
                      {selectedForGrouping.size >= 2 && (
                        <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end' }}>
                          <div style={{ flex: 1 }}>
                            <label style={{ display: 'block', fontSize: '11px', color: 'var(--fpx-ink-faint)', marginBottom: '5px', fontWeight: 600 }}>
                              Primary character (keep this name)
                            </label>
                            <select id="mainCharSelect" style={{ width: '100%' }}>
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
                            className="fpx-merge"
                          >
                            Merge selected
                          </button>
                        </div>
                      )}

                      {selectedForGrouping.size > 0 && selectedForGrouping.size < 2 && (
                        <div style={{ fontSize: '11px', color: 'var(--fpx-ink-faint)' }}>
                          Select at least 2 characters to merge
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            </div>

            {/* Overview Section - Collapsible */}
            <div className="fpx-rsec fpx-rv"><h3>DEATH-RATE MATRIX</h3><span className="sub">player × boss</span><div className="rule" /></div>
            <div className="fpx-matrix fpx-rv">
              <button
                onClick={() => setOverviewCollapsed(!overviewCollapsed)}
                className="fpx-matrix-head"
              >
                {overviewCollapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
                ALL BOSSES OVERVIEW
                <span className="hint">{overviewCollapsed ? 'click to expand' : 'sortable — click any column'}</span>
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
                <div className="fpx-mtx-wrap">
                  <table className="fpx-mtx">
                    <thead>
                      <tr>
                        <th onClick={() => handleSort('player')}>
                          <span className="sortc">Player {getSortIcon('player')}</span>
                        </th>
                        {bosses.map(boss => (
                          <th key={boss} onClick={() => handleSort(boss)}>
                            <span className="sortc">{boss} {getSortIcon(boss)}</span>
                          </th>
                        ))}
                        <th onClick={() => handleSort('overall')}>
                          <span className="sortc">Overall {getSortIcon('overall')}</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedPlayers.map(player => (
                        <tr key={player}>
                          <td>
                            <div className="fpx-cellname">
                              <span style={{ color: WOW_CLASS_COLORS[grid[player].overall?.class] || 'var(--fpx-ink)' }}>
                                {player}{characterGroups[player] && characterGroups[player].length > 0 && ' (grouped)'}
                              </span>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  togglePlayerVisibility(player);
                                }}
                                className="fpx-rowhide"
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
                              <td key={boss} className={cellData.rate !== null ? 'val' : undefined}>
                                {cellData.rate !== null ? (
                                  showBothStats ? (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                                      <span style={{ color: getPercentageColor(cellData.rate, allBossRealRates[boss]) }}>
                                        {cellData.rate.toFixed(1)}%
                                      </span>
                                      <span className="mini" style={{ color: getPercentageColor(cellData.totalRate, allBossTotalRates[boss]) }}>
                                        ({cellData.totalRate.toFixed(1)}%)
                                      </span>
                                    </div>
                                  ) : (
                                    <span style={{ color: getPercentageColor(cellData.rate, allBossRealRates[boss]) }}>
                                      {cellData.rate.toFixed(1)}%
                                    </span>
                                  )
                                ) : (
                                  <span>—</span>
                                )}
                              </td>
                            );
                          })}
                          <td className="ov">
                            {grid[player].overall.rate !== null ? (
                              (() => {
                                const showBothStats = grid[player].overall.hasCheatDeaths && grid[player].overall.totalDeaths > grid[player].overall.deaths;
                                return showBothStats ? (
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', alignItems: 'center' }}>
                                    <span style={{ color: getPercentageColor(grid[player].overall.rate, allRealRates) }}>
                                      {grid[player].overall.rate.toFixed(1)}%
                                    </span>
                                    <span className="mini" style={{ color: getPercentageColor(grid[player].overall.totalRate, allTotalRates) }}>
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
                              <span>—</span>
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
            <div className="fpx-rsec fpx-rv"><h3>PLAYERS</h3><span className="sub">expand for the per-boss death log</span><div className="rule" /></div>
            {(() => {
              const filteredStats = getFilteredStats();
              // Calculate all percentage values for color scaling
              const allRealRates = filteredStats.map(s => s.realRate);
              const allTotalRates = filteredStats.map(s => s.totalRate);

              return (
              <div className="fpx-plist fpx-rv">
                {filteredStats.map(({ player, realDeaths, totalDeaths, cheatDeaths, pulls, realRate, totalRate, hasCheatDeaths, deathsByBoss, cheatDeathsByBoss, totalDeathsByBoss, topAbilitiesByBoss, class: playerClass, spec: playerSpec }) => {
                  const isExpanded = expandedPlayers.has(player);
                  const showBothStats = hasCheatDeaths && cheatDeaths > 0;

                  return (
                    <div key={player} className={`fpx-prow${isExpanded ? ' open' : ''}`}>
                      <div onClick={() => togglePlayer(player)} className="fpx-prow-h">
                        {isExpanded ? <ChevronDown size={14} className="chev" /> : <ChevronRight size={14} className="chev" />}
                        <div style={{ flex: 1, display: 'flex', alignItems: 'baseline', gap: '7px', flexWrap: 'wrap' }}>
                          <span className="fpx-pname" style={{ color: WOW_CLASS_COLORS[playerClass] || 'var(--fpx-ink)' }}>
                            {player}{characterGroups[player] && characterGroups[player].length > 0 && ' (grouped)'}
                          </span>
                          <span className="fpx-pdot">—</span>
                          <span className="fpx-pmeta">{realDeaths} death{realDeaths !== 1 ? 's' : ''} / {pulls} pulls</span>
                          <span className="fpx-pdot">·</span>
                          <span className="fpx-prate" style={{ color: getPercentageColor(realRate, allRealRates) }}>
                            {realRate.toFixed(1)}%
                          </span>
                          {showBothStats && <span className="fpx-pcheat">(+{cheatDeaths} cheat)</span>}
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            togglePlayerVisibility(player);
                          }}
                          className="fpx-hide"
                          title="Hide this player from results"
                        >
                          Hide
                        </button>
                      </div>

                      {isExpanded && (
                        <div className="fpx-pbody">
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
                            <div key={boss} className="fpx-pboss">
                              <h4 className="fpx-pboss-h">
                                {boss}
                                {showBothStats && cheatDeathCount > 0 ? (
                                  <>
                                    <span className="r">Real {realDeathCount}/{bossPulls} pulls · {bossRealRate.toFixed(1)}%</span>
                                    <span className="c">+cheat {totalDeathCount}/{bossPulls} pulls · {bossTotalRate.toFixed(1)}%</span>
                                  </>
                                ) : (
                                  <span className="r">{realDeathCount}/{bossPulls} pulls · {bossRealRate.toFixed(1)}%</span>
                                )}
                              </h4>

                              {topAbilitiesByBoss[boss] && topAbilitiesByBoss[boss].length > 0 && (
                                <div className="fpx-abil">
                                  <span className="lbl">Top abilities</span>
                                  {topAbilitiesByBoss[boss].map(([ability, count], idx) => (
                                    <span key={ability}>
                                      {idx + 1}. {ability} ({count}){idx < topAbilitiesByBoss[boss].length - 1 ? '   ·   ' : ''}
                                    </span>
                                  ))}
                                </div>
                              )}

                              <div className="fpx-dlist">
                                {(showBothStats ? totalBossDeaths : bossDeaths)
                                  .map((death, idx) => (
                                  <div key={idx} className={`fpx-death${death.isCheatDeath ? ' cheat' : ''}`}>
                                    <div className="fpx-death-top">
                                      <div className="fpx-death-meta">
                                        <span className="pn">Pull #{death.pullNo}</span>
                                        <span>{formatTimestamp(death.absTs)}</span>
                                        {death.isCheatDeath && (
                                          <span className="fpx-cheatbadge">CHEAT</span>
                                        )}
                                        <span className="ab">
                                          {death.abilityName === 'Unknown' ? (
                                            <span className="un">Unknown ability</span>
                                          ) : death.abilityName}
                                        </span>
                                      </div>
                                      <a
                                        href={getWCLLink(death.reportId, death.fightId)}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="fpx-wcl"
                                      >
                                        View log <ExternalLink size={12} />
                                      </a>
                                    </div>

                                    {/* Defensive Abilities Display */}
                                    {config.enableDefensiveTracking && death.defensives && (
                                      <div className="fpx-defs">
                                        <div className="fpx-defs-row">
                                          <span className="lbl">ACTIVE BUFFS</span>
                                          {death.defensives.abilities && death.defensives.abilities.length > 0 ? (
                                            death.defensives.abilities.map((def, defIdx) => (
                                              <span key={defIdx} className="d">
                                                {def.name} ({def.count}×)
                                              </span>
                                            ))
                                          ) : (
                                            <span className="none">None active</span>
                                          )}
                                        </div>
                                        {death.defensives.healing !== undefined && (
                                          <div className="heal">
                                            Healing received: <b>{death.defensives.healing.toLocaleString()}</b>
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
          </>
                  ) : (
                    <div className="fpx-results-empty fpx-rv">
                      <AlertCircle size={34} />
                      <p>{error
                        ? error
                        : recentRuns.length > 0
                          ? 'No analysis loaded — open a recent run below or start a new one.'
                          : 'No analysis yet. Configure and run a death review to see results here.'}</p>
                      <button className="fpx-btn" onClick={() => navigate('/analyze')}>
                        <Crosshair size={17} /> Run Analysis <ChevronRight size={15} />
                      </button>
                      {recentRuns.length > 0 && (
                        <div className="fpx-recentlist">
                          <div className="fpx-recentlist-h">RECENT RUNS · LAST {recentRuns.length}</div>
                          {recentRuns.map((r) => (
                            <div key={r.id} className="fpx-recent-card">
                              <button className="open" onClick={() => openRecentRun(r)}>
                                <span className="t">{r.title}</span>
                                <span className="s">{r.sub}</span>
                                <span className="d">{new Date(r.savedAt).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span>
                              </button>
                              <button className="rm" onClick={() => removeRecentRun(r.id)} title="Remove run">
                                <X size={14} />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </main>
            </>
          } />
          
          <Route path="/saved" element={
            <>
            <div className="fpx-atmos base" />
            <div className="fpx-atmos vignette" />
            <div className="fpx-atmos grain" />
            <main className="fpx-land">
              <div className={`fpx-shell${resultsRailCollapsed ? ' collapsed' : ''}`}>
                <FpxRail
                  collapsed={resultsRailCollapsed}
                  onToggle={() => setResultsRailCollapsed((v) => !v)}
                  active={null}
                  onHome={() => navigate('/')}
                  onAnalyze={() => navigate('/analyze')}
                  onResults={() => navigate('/results')}
                />
                <div className="fpx-main">
                  <div className="fpx-top fpx-rv">
                    <div className="fpx-crumbs">ANALYSIS&nbsp; /&nbsp; <b>SAVED</b></div>
                    <div className="fpx-auth">
                      {user ? (
                        <>
                          <button className="fpx-btn ghost sm" onClick={() => setShowSettings(true)}><SettingsIcon size={15} /> Settings</button>
                          <button className="fpx-btn ghost sm" onClick={handleLogout}><LogOut size={15} /> Logout</button>
                        </>
                      ) : (
                        <button className="fpx-btn ghost sm" onClick={() => setShowAuthModal(true)}><LogIn size={15} /> Sign In</button>
                      )}
                    </div>
                  </div>
                  <div className="fpx-results-empty fpx-rv" style={{ minHeight: '64vh' }}>
                    <BarChart3 size={34} />
                    <p>Saved reports are coming soon — you'll be able to revisit past death reviews here.</p>
                    <button className="fpx-btn" onClick={() => navigate('/analyze')}>
                      <Crosshair size={17} /> Run an analysis <ChevronRight size={15} />
                    </button>
                  </div>
                </div>
              </div>
            </main>
            </>
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
      {showInfoModal && <InfoModal onClose={() => setShowInfoModal(false)} />}

      {/* Terms & Privacy Modal */}
      {showTermsModal && (
        <div className="fpx-mov" onClick={() => setShowTermsModal(false)}>
          <div className="fpx-mcard" onClick={(e) => e.stopPropagation()}>
            <div className="fpx-mhead">
              <h2>Terms of Service &amp; Privacy Policy</h2>
              <button className="fpx-mclose" onClick={() => setShowTermsModal(false)} aria-label="Close">
                <X size={18} />
              </button>
            </div>

            <div className="fpx-mbody fpx-legalbody">
              <p style={{ color: '#94a3b8', fontSize: '13px', fontStyle: 'italic', marginBottom: '24px' }}>
                Last Updated: November 21, 2025
              </p>

              <h3 style={{ color: 'var(--color-info)', fontSize: '18px', marginTop: 0, marginBottom: '12px' }}>
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

              <h3 style={{ color: 'var(--color-info)', fontSize: '18px', marginTop: '24px', marginBottom: '12px' }}>
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

              <h3 style={{ color: 'var(--color-info)', fontSize: '18px', marginTop: '24px', marginBottom: '12px' }}>
                3. Changes to These Terms
              </h3>
              <p style={{ color: '#cbd5e1', fontSize: '14px', marginBottom: '16px' }}>
                We may update these terms as the Service evolves. Continued use of the Service after changes constitutes acceptance of the updated terms. Major changes will be announced via email and on the site.
              </p>

              <h3 style={{ color: 'var(--color-info)', fontSize: '18px', marginTop: '24px', marginBottom: '12px' }}>
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
