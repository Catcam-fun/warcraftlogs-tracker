import React from 'react';
import { useNavigate } from 'react-router-dom';
import { LogIn, LogOut, Settings as SettingsIcon } from 'lucide-react';

export default function AppHeader({ user, onShowAuthModal, onShowSettings, onLogout }) {
  const navigate = useNavigate();

  return (
    <header className="fpx-apphead">
      <div className="fpx-apphead-in">
        <div className="fpx-brand" onClick={() => navigate('/')}>
          <div className="mk">FP</div>
          <div className="wm">FLOOR&nbsp;POV<small>DEATH ANALYSIS</small></div>
        </div>

        <div className="fpx-auth">
          {user ? (
            <>
              <span className="fpx-userpill">{user.email}</span>
              <button className="fpx-btn ghost sm" onClick={onShowSettings}>
                <SettingsIcon size={15} /> Settings
              </button>
              <button className="fpx-btn ghost sm" onClick={onLogout}>
                <LogOut size={15} /> Logout
              </button>
            </>
          ) : (
            <button className="fpx-btn ghost sm" onClick={onShowAuthModal}>
              <LogIn size={15} /> Sign In
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
