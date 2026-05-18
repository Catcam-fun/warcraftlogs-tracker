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
    <div className="fpx-mov" onClick={onClose}>
      <div className="fpx-mcard" onClick={(e) => e.stopPropagation()}>
        <div className="fpx-mhead">
          <h2>{isSignUp ? 'Create account' : 'Sign in'}</h2>
          <button className="fpx-mclose" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        <div className="fpx-mbody">
          <p className="lead">
            {isSignUp
              ? 'Create an account to save your API credentials and analysis history.'
              : 'Sign in to access your saved credentials and analysis history.'}
          </p>

          <form className="fpx-mform" onSubmit={handleAuth}>
            <div className="f">
              <label>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="f">
              <label>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
              />
              {isSignUp && <p className="hint">Must be at least 6 characters</p>}
            </div>

            {/* Age Confirmation - Only for Sign Up */}
            {isSignUp && (
              <label className="fpx-mcheck">
                <input
                  type="checkbox"
                  checked={ageConfirmed}
                  onChange={(e) => setAgeConfirmed(e.target.checked)}
                />
                I confirm that I am at least 13 years old
              </label>
            )}

            {/* Terms Acceptance - Only for Sign Up */}
            {isSignUp && (
              <label className="fpx-mcheck">
                <input
                  type="checkbox"
                  checked={termsAccepted}
                  onChange={(e) => setTermsAccepted(e.target.checked)}
                />
                <span>
                  I agree to the{' '}
                  <button
                    type="button"
                    className="fpx-link"
                    onClick={() => { onClose(); navigate('/terms'); }}
                  >
                    Terms of Service
                  </button>
                  {' '}and{' '}
                  <button
                    type="button"
                    className="fpx-link"
                    onClick={() => { onClose(); navigate('/privacy'); }}
                  >
                    Privacy Policy
                  </button>
                </span>
              </label>
            )}

            {/* Turnstile CAPTCHA - For both Sign In and Sign Up */}
            <div className="turnstile">
              <div
                ref={turnstileRef}
                className="cf-turnstile"
                data-sitekey="0x4AAAAAACCS9WN5tgUaGBvQ"
                data-callback="onTurnstileSuccess"
                data-theme="dark"
              />
            </div>

            {/* Stay Logged In - Only for Sign In */}
            {!isSignUp && (
              <label className="fpx-mcheck">
                <input
                  type="checkbox"
                  checked={stayLoggedIn}
                  onChange={(e) => setStayLoggedIn(e.target.checked)}
                />
                Stay logged in
              </label>
            )}

            <button
              type="submit"
              disabled={loading}
              className="fpx-btn"
              style={{ opacity: loading ? 0.7 : 1, cursor: loading ? 'not-allowed' : 'pointer' }}
            >
              {loading ? 'Loading…' : (isSignUp ? 'Sign up' : 'Sign in')}
            </button>
          </form>

          {message && (
            <p
              className={`fpx-mmsg ${(message.includes('Success') || message.includes('successfully')) ? 'ok' : 'err'}`}
              style={{ marginTop: '16px' }}
            >
              {message}
            </p>
          )}

          <p className="fpx-mfoot">
            {isSignUp ? 'Already have an account?' : "Don't have an account?"}{' '}
            <button type="button" className="fpx-link" onClick={handleToggleMode}>
              {isSignUp ? 'Sign in' : 'Sign up'}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
