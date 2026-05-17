import React from 'react';
import { useNavigate } from 'react-router-dom';
import { LogIn, LogOut, Settings as SettingsIcon } from 'lucide-react';

export default function AppHeader({ user, onShowAuthModal, onShowSettings, onLogout }) {
  const navigate = useNavigate();

  return (
    <header className="fp-app-header app-header">
      <div className="app-header-inner">
        <div className="brand-lockup" onClick={() => navigate('/')}>
          <div className="brand-mark">FP</div>
          <div>
            <h1 className="brand-title">Floor Pov</h1>
            <p className="brand-subtitle">Late-night raid death analytics</p>
          </div>
        </div>

        <div className="nav-actions">
          {user ? (
            <div className="user-pill">
              <span>{user.email}</span>
              <button className="btn" onClick={onShowSettings}>
                <SettingsIcon size={14} />
                Settings
              </button>
              <button className="btn" onClick={onLogout}>
                <LogOut size={14} />
                Logout
              </button>
            </div>
          ) : (
            <button className="btn btn-primary" onClick={onShowAuthModal}>
              <LogIn size={15} />
              Sign In
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
