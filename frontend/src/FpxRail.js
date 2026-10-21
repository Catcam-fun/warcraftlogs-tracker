import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Home, Crosshair, BarChart3, Bookmark, ChevronsLeft, ChevronsRight } from 'lucide-react';
import FpMark from './FpMark';

/* Shared left rail — single source of truth so every surface (Analyze,
   Results, Terms, Privacy, Saved, loading) shows an identical nav.
   `active` ∈ 'home' | 'analyze' | 'results' | 'saved' | null.
   On phones the rail is hidden and the same four links show as a bottom tab bar. */
export default function FpxRail({ collapsed, onToggle, active, onHome, onAnalyze, onResults, onSaved }) {
  const navigate = useNavigate();
  const goSaved = onSaved || (() => navigate('/saved'));
  return (
    <>
    <nav className="fpx-tabbar" aria-label="Main">
      <button className={`fpx-tab${active === 'home' ? ' on' : ''}`} onClick={onHome}><Home /><span>Home</span></button>
      <button className={`fpx-tab${active === 'analyze' ? ' on' : ''}`} onClick={onAnalyze}><Crosshair /><span>Analyze</span></button>
      <button className={`fpx-tab${active === 'results' ? ' on' : ''}`} onClick={onResults}><BarChart3 /><span>Results</span></button>
      <button className={`fpx-tab${active === 'saved' ? ' on' : ''}`} onClick={goSaved}><Bookmark /><span>Saved</span></button>
    </nav>
    <aside className={`fpx-rail${collapsed ? ' collapsed' : ''}`}>
      <div className="fpx-railhead">
        <div className="fpx-brand" onClick={onHome}>
          <FpMark />
          <div className="wm">FLOOR&nbsp;POV<small>DEATH ANALYSIS</small></div>
        </div>
        <button className="fpx-railtoggle" onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
        </button>
      </div>
      <nav className="fpx-navsec">
        <h4>FLOOR POV</h4>
        <button className={`fpx-nav${active === 'home' ? ' on' : ''}`} onClick={onHome} title="Home">
          <Home /><span className="lbl">Home</span>
        </button>
        <button className={`fpx-nav${active === 'analyze' ? ' on' : ''}`} onClick={onAnalyze} title="Run Analysis">
          <Crosshair /><span className="lbl">Run Analysis</span>
        </button>
        <button className={`fpx-nav${active === 'results' ? ' on' : ''}`} onClick={onResults} title="Results">
          <BarChart3 /><span className="lbl">Results</span>
        </button>
        <button className={`fpx-nav${active === 'saved' ? ' on' : ''}`} onClick={goSaved} title="Saved Reports">
          <Bookmark /><span className="lbl">Saved</span>
        </button>
      </nav>
    </aside>
    </>
  );
}
