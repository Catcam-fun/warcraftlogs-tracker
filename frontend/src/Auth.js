import React, { useState } from 'react';
import { supabase } from './supabaseClient';
import { X } from 'lucide-react';

export default function Auth({ onClose }) {
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSignUp, setIsSignUp] = useState(false);
  const [message, setMessage] = useState('');

  const handleAuth = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage('');

    try {
      if (isSignUp) {
        // Sign up
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
        });
        if (error) throw error;
        setMessage('Success! Check your email for confirmation link.');
      } else {
        // Sign in
        const { data, error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (error) throw error;
        setMessage('Logged in successfully!');
        // Close modal after successful login
        setTimeout(() => {
          if (onClose) onClose();
        }, 1000);
      }
    } catch (error) {
      setMessage(error.message || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  return (
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
      zIndex: 9999
    }}>
      <div style={{
        maxWidth: '420px',
        width: '90%',
        margin: '0 auto',
        padding: '32px',
        border: '1px solid #3b82f6',
        borderRadius: '12px',
        backgroundColor: '#1a1a2e',
        position: 'relative'
      }}>
        {onClose && (
          <button
            onClick={onClose}
            style={{
              position: 'absolute',
              top: '12px',
              right: '12px',
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            <X size={20} />
          </button>
        )}

        <h2 style={{ 
          color: '#3b82f6', 
          textAlign: 'center', 
          marginBottom: '24px',
          marginTop: 0,
          fontSize: '24px'
        }}>
          {isSignUp ? 'Create Account' : 'Sign In'}
        </h2>

        <p style={{
          color: '#94a3b8',
          textAlign: 'center',
          fontSize: '14px',
          marginBottom: '24px',
          lineHeight: '1.5'
        }}>
          {isSignUp 
            ? 'Create an account to save your API credentials and analysis history' 
            : 'Sign in to access your saved credentials and analysis history'
          }
        </p>
        
        <form onSubmit={handleAuth}>
          <div style={{ marginBottom: '16px' }}>
            <label style={{ 
              display: 'block', 
              marginBottom: '6px', 
              color: '#e2e8f0',
              fontSize: '14px',
              fontWeight: '500'
            }}>
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #475569',
                backgroundColor: '#0f1419',
                color: '#fff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ 
              display: 'block', 
              marginBottom: '6px', 
              color: '#e2e8f0',
              fontSize: '14px',
              fontWeight: '500'
            }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #475569',
                backgroundColor: '#0f1419',
                color: '#fff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
            {isSignUp && (
              <p style={{
                fontSize: '12px',
                color: '#64748b',
                marginTop: '4px',
                marginBottom: 0
              }}>
                Must be at least 6 characters
              </p>
            )}
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '12px',
              backgroundColor: loading ? '#1e40af' : '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '15px',
              fontWeight: '600',
              opacity: loading ? 0.7 : 1,
              transition: 'all 0.2s',
              boxSizing: 'border-box'
            }}
            onMouseOver={(e) => { if (!loading) e.target.style.backgroundColor = '#2563eb'; }}
            onMouseOut={(e) => { if (!loading) e.target.style.backgroundColor = '#3b82f6'; }}
          >
            {loading ? 'Loading...' : (isSignUp ? 'Sign Up' : 'Sign In')}
          </button>
        </form>

        {message && (
          <p style={{
            marginTop: '16px',
            padding: '12px',
            backgroundColor: message.includes('Success') ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            border: `1px solid ${message.includes('Success') ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
            color: message.includes('Success') ? '#10b981' : '#ef4444',
            borderRadius: '6px',
            textAlign: 'center',
            fontSize: '13px'
          }}>
            {message}
          </p>
        )}

        <p style={{ 
          marginTop: '20px', 
          textAlign: 'center', 
          color: '#94a3b8',
          fontSize: '14px'
        }}>
          {isSignUp ? 'Already have an account?' : "Don't have an account?"}
          {' '}
          <button
            onClick={() => {
              setIsSignUp(!isSignUp);
              setMessage('');
            }}
            style={{
              background: 'none',
              border: 'none',
              color: '#3b82f6',
              cursor: 'pointer',
              textDecoration: 'underline',
              fontSize: '14px',
              fontWeight: '500'
            }}
          >
            {isSignUp ? 'Sign In' : 'Sign Up'}
          </button>
        </p>
      </div>
    </div>
  );
}