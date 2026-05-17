import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from './supabaseClient';
import { X } from 'lucide-react';

export default function Auth({ onClose }) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSignUp, setIsSignUp] = useState(false);
  const [message, setMessage] = useState('');
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [stayLoggedIn, setStayLoggedIn] = useState(true);
  const [captchaToken, setCaptchaToken] = useState('');
  const turnstileRef = useRef(null);

  // Load Cloudflare Turnstile script and set up callback
  useEffect(() => {
    // Set up global callback function for Turnstile
    window.onTurnstileSuccess = (token) => {
      console.log('Turnstile token received:', token ? 'YES' : 'NO');
      setCaptchaToken(token);
    };

    if (!document.getElementById('turnstile-script')) {
      const script = document.createElement('script');
      script.id = 'turnstile-script';
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
      script.async = true;
      script.defer = true;
      document.body.appendChild(script);
    }

    // Cleanup
    return () => {
      delete window.onTurnstileSuccess;
    };
  }, []);

  const handleAuth = async (e) => {
    e.preventDefault();

    console.log('handleAuth called, captchaToken:', captchaToken);

    // Validate checkboxes for sign-up
    if (isSignUp) {
      if (!ageConfirmed) {
        setMessage('You must be at least 13 years old to create an account.');
        return;
      }
      if (!termsAccepted) {
        setMessage('You must accept the Terms of Service and Privacy Policy.');
        return;
      }
    }

    // Require CAPTCHA for both sign-in and sign-up
    if (!captchaToken) {
      setMessage('Please complete the CAPTCHA verification.');
      return;
    }

    setLoading(true);
    setMessage('');

    try {
      console.log('Verifying CAPTCHA...');
      // Verify Turnstile token on backend
      const verifyResponse = await fetch('https://wcl-proxy.catcam-fun.workers.dev/verify-turnstile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: captchaToken })
      });

      const verifyData = await verifyResponse.json();
      console.log('CAPTCHA verification response:', verifyData);

      if (!verifyResponse.ok || !verifyData.success) {
        throw new Error('CAPTCHA verification failed. Please try again.');
      }

      if (isSignUp) {
        // Sign up
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
        });
        if (error) throw error;
        setMessage('Success! Check your email for confirmation link.');
      } else {
        // Sign in with session persistence based on stayLoggedIn
        const { data, error } = await supabase.auth.signInWithPassword({
          email,
          password,
          options: {
            persistSession: stayLoggedIn
          }
        });
        if (error) throw error;

        // If not staying logged in, set session to expire when browser closes
        if (!stayLoggedIn) {
          const { data: { session } } = await supabase.auth.getSession();
          if (session) {
            sessionStorage.setItem('supabase.auth.token', JSON.stringify(session));
            localStorage.removeItem('supabase.auth.token');
          }
        }

        setMessage('Logged in successfully!');
        setTimeout(() => {
          if (onClose) onClose();
        }, 1000);
      }
    } catch (error) {
      console.error('Auth error:', error);
      setMessage(error.message || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleMode = () => {
    setIsSignUp(!isSignUp);
    setMessage('');
    setAgeConfirmed(false);
    setTermsAccepted(false);
    setCaptchaToken('');
    // Reset Turnstile widget if it exists
    if (window.turnstile && turnstileRef.current) {
      window.turnstile.reset(turnstileRef.current);
    }
  };

  return (
    <div className="fp-auth auth-shell">
      <div className="auth-card surface-panel" style={{ position: 'relative' }}>
        {onClose && (
          <button
            onClick={onClose}
            style={{
              position: 'absolute',
              top: '12px',
              right: '12px',
              background: 'transparent',
              border: 'none',
              color: 'var(--color-muted)',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            <X size={20} />
          </button>
        )}

        <h2 style={{
          color: 'var(--color-gold-2)',
          textAlign: 'center',
          marginBottom: '24px',
          marginTop: 0,
          fontSize: '24px'
        }}>
          {isSignUp ? 'Create Account' : 'Sign In'}
        </h2>

        <p style={{
          color: 'var(--color-muted)',
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
              color: 'var(--color-text)',
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
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{
              display: 'block',
              marginBottom: '6px',
              color: 'var(--color-text)',
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
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
            {isSignUp && (
              <p style={{
                fontSize: '12px',
                color: 'var(--color-subtle)',
                marginTop: '4px',
                marginBottom: 0
              }}>
                Must be at least 6 characters
              </p>
            )}
          </div>

          {/* Age Confirmation Checkbox - Only for Sign Up */}
          {isSignUp && (
            <div style={{ marginBottom: '16px' }}>
              <label style={{
                display: 'flex',
                alignItems: 'center',
                cursor: 'pointer',
                fontSize: '14px',
                color: 'var(--color-text)'
              }}>
                <input
                  type="checkbox"
                  checked={ageConfirmed}
                  onChange={(e) => setAgeConfirmed(e.target.checked)}
                  style={{
                    marginRight: '8px',
                    cursor: 'pointer',
                    width: '16px',
                    height: '16px',
                    accentColor: 'var(--color-gold-2)'
                  }}
                />
                I confirm that I am at least 13 years old
              </label>
            </div>
          )}

          {/* Terms Acceptance Checkbox - Only for Sign Up */}
          {isSignUp && (
            <div style={{ marginBottom: '20px' }}>
              <label style={{
                display: 'flex',
                alignItems: 'flex-start',
                cursor: 'pointer',
                fontSize: '14px',
                color: 'var(--color-text)',
                lineHeight: '1.5'
              }}>
                <input
                  type="checkbox"
                  checked={termsAccepted}
                  onChange={(e) => setTermsAccepted(e.target.checked)}
                  style={{
                    marginRight: '8px',
                    marginTop: '4px',
                    cursor: 'pointer',
                    width: '16px',
                    height: '16px',
                    flexShrink: 0,
                    accentColor: 'var(--color-gold-2)'
                  }}
                />
                <span>
                  I agree to the{' '}
                  <a
                    onClick={(e) => {
                      e.preventDefault();
                      onClose();
                      navigate('/terms');
                    }}
                    style={{
                      color: 'var(--color-gold-2)',
                      textDecoration: 'underline',
                      cursor: 'pointer'
                    }}
                  >
                    Terms of Service
                  </a>
                  {' '}and{' '}
                  <a
                    onClick={(e) => {
                      e.preventDefault();
                      onClose();
                      navigate('/privacy');
                    }}
                    style={{
                      color: 'var(--color-gold-2)',
                      textDecoration: 'underline',
                      cursor: 'pointer'
                    }}
                  >
                    Privacy Policy
                  </a>
                </span>
              </label>
            </div>
          )}

          {/* Turnstile CAPTCHA - For both Sign In and Sign Up */}
          <div style={{ marginBottom: '20px', display: 'flex', justifyContent: 'center' }}>
            <div
              ref={turnstileRef}
              className="cf-turnstile"
              data-sitekey="0x4AAAAAACCS9WN5tgUaGBvQ"
              data-callback="onTurnstileSuccess"
              data-theme="dark"
            />
          </div>

          {/* Stay Logged In Checkbox - Only for Sign In */}
          {!isSignUp && (
            <div style={{ marginBottom: '20px' }}>
              <label style={{
                display: 'flex',
                alignItems: 'center',
                cursor: 'pointer',
                fontSize: '14px',
                color: 'var(--color-text)'
              }}>
                <input
                  type="checkbox"
                  checked={stayLoggedIn}
                  onChange={(e) => setStayLoggedIn(e.target.checked)}
                  style={{
                    marginRight: '8px',
                    cursor: 'pointer',
                    width: '16px',
                    height: '16px',
                    accentColor: 'var(--color-gold-2)'
                  }}
                />
                Stay logged in
              </label>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary"
            style={{
              width: '100%',
              opacity: loading ? 0.7 : 1,
              cursor: loading ? 'not-allowed' : 'pointer'
            }}
          >
            {loading ? 'Loading...' : (isSignUp ? 'Sign Up' : 'Sign In')}
          </button>
        </form>

        {message && (
          <p style={{
            marginTop: '16px',
            padding: '12px',
            backgroundColor: (message.includes('Success') || message.includes('successfully')) ? 'rgba(56, 217, 140, 0.1)' : 'rgba(255, 93, 102, 0.1)',
            border: `1px solid ${(message.includes('Success') || message.includes('successfully')) ? 'rgba(56, 217, 140, 0.3)' : 'rgba(255, 93, 102, 0.3)'}`,
            color: (message.includes('Success') || message.includes('successfully')) ? 'var(--color-green)' : 'var(--color-red)',
            borderRadius: 'var(--radius-md)',
            textAlign: 'center',
            fontSize: '13px'
          }}>
            {message}
          </p>
        )}

        <p style={{
          marginTop: '20px',
          textAlign: 'center',
          color: 'var(--color-muted)',
          fontSize: '14px'
        }}>
          {isSignUp ? 'Already have an account?' : "Don't have an account?"}
          {' '}
          <button
            onClick={handleToggleMode}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--color-gold-2)',
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
