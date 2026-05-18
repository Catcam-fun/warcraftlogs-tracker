import React from 'react';
import { Home, Crosshair, BarChart3, ChevronsLeft, ChevronsRight } from 'lucide-react';

/* Shared left rail — single source of truth so every surface (Analyze,
   Results, Terms, Privacy, Saved, loading) shows an identical nav.
   `active` ∈ 'home' | 'analyze' | 'results' | null. */
export default function FpxRail({ collapsed, onToggle, active, onHome, onAnalyze, onResults }) {
  return (
    <aside className={`fpx-rail${collapsed ? ' collapsed' : ''}`}>
      <div className="fpx-railhead">
        <div className="fpx-brand" onClick={onHome}>
          <div className="mk">FP</div>
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
      </nav>
    </aside>
  );
}
