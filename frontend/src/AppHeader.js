import React from 'react';
import { useNavigate } from 'react-router-dom';
import { LogOut, Settings as SettingsIcon } from 'lucide-react';

export default function AppHeader({ user, onShowAuthModal, onShowSettings, onLogout }) {
  const navigate = useNavigate();
  
  return (
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
                onClick={onShowSettings}
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
                onClick={onLogout}
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
              onClick={onShowAuthModal}
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
  );
}