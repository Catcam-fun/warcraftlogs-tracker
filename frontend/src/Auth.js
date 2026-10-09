import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase, setSessionOnly } from './supabaseClient';
import { X } from 'lucide-react';

const TURNSTILE_SITE_KEY = process.env.REACT_APP_TURNSTILE_SITE_KEY || '';

export default function Auth({ onClose }) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSignUp, setIsSignUp] = useState(false);
  const [isReset, setIsReset] = useState(false);
  const [message, setMessage] = useState('');
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [stayLoggedIn, setStayLoggedIn] = useState(true);
  const [captchaToken, setCaptchaToken] = useState('');
  const turnstileRef = useRef(null);

  // Cloudflare Turnstile, rendered explicitly into our container. The
  // implicit auto-render only scans the page once when the script first
  // loads, so reopening this modal used to show no CAPTCHA at all.
  const widgetIdRef = useRef(null);
  useEffect(() => {
    let cancelled = false;

    const render = () => {
      if (cancelled || !window.turnstile || !turnstileRef.current || widgetIdRef.current !== null) return;
      widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
        sitekey: TURNSTILE_SITE_KEY,
        theme: 'dark',
        callback: (token) => setCaptchaToken(token),
        'expired-callback': () => setCaptchaToken(''),
        'error-callback': () => setCaptchaToken(''),
      });
    };

    if (window.turnstile) {
      render();
    } else {
      let script = document.getElementById('turnstile-script');
      if (!script) {
        script = document.createElement('script');
        script.id = 'turnstile-script';
        script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
        script.async = true;
        document.body.appendChild(script);
      }
      script.addEventListener('load', render);
    }

    return () => {
      cancelled = true;
      document.getElementById('turnstile-script')?.removeEventListener('load', render);
      if (widgetIdRef.current !== null && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
      }
      widgetIdRef.current = null;
    };
  }, []);

  // A Turnstile token is single-use: get a fresh one after every attempt.
  const resetCaptcha = () => {
    setCaptchaToken('');
    if (window.turnstile && widgetIdRef.current !== null) {
      window.turnstile.reset(widgetIdRef.current);
    }
  };

  const handleReset = async (e) => {
    e.preventDefault();
    if (!captchaToken) {
      setMessage('Please complete the CAPTCHA verification.');
      return;
    }
    setLoading(true);
    setMessage('');
    try {
      // Supabase checks the CAPTCHA token itself (Attack Protection), so a
      // bot calling Supabase directly can't skip it.
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: window.location.origin,
        captchaToken,
      });
      if (error) throw error;
      setMessage('Success! If that email has an account, a reset link is on its way.');
    } catch (error) {
      setMessage(error.message || 'An error occurred');
    } finally {
      setLoading(false);
      resetCaptcha();
    }
  };

  const handleAuth = async (e) => {
    e.preventDefault();

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
      if (isSignUp) {
        const { error } = await supabase.auth.signUp({ email, password, options: { captchaToken } });
        if (error) throw error;
        setMessage('Success! Check your email for confirmation link.');
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password, options: { captchaToken } });
        if (error) throw error;
        setSessionOnly(!stayLoggedIn);

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
      resetCaptcha();
    }
  };

  const handleToggleMode = () => {
    setIsSignUp(!isSignUp);
    setMessage('');
    setAgeConfirmed(false);
    setTermsAccepted(false);
    setIsReset(false);
    resetCaptcha();
  };

  return (
    <div className="fpx-mov" onClick={onClose}>
      <div className="fpx-mcard" onClick={(e) => e.stopPropagation()}>
        <div className="fpx-mhead">
          <h2>{isReset ? 'Reset password' : isSignUp ? 'Create account' : 'Sign in'}</h2>
          <button className="fpx-mclose" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        <div className="fpx-mbody">
          <p className="lead">
            {isReset
              ? "Enter your account email and we'll send you a link to choose a new password."
              : isSignUp
                ? 'Create an account to save your API credentials and analysis history.'
                : 'Sign in to access your saved credentials and analysis history.'}
          </p>

          <form className="fpx-mform" onSubmit={isReset ? handleReset : handleAuth}>
            <div className="f">
              <label>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {!isReset && (
              <div className="f">
                <label>Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={6}
                />
                {isSignUp
                  ? <p className="hint">Must be at least 6 characters</p>
                  : (
                    <p className="hint">
                      <button type="button" className="fpx-link" onClick={() => { setIsReset(true); setMessage(''); }}>
                        Forgot password?
                      </button>
                    </p>
                  )}
              </div>
            )}

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
              <div ref={turnstileRef} />
            </div>

            {/* Stay Logged In - Only for Sign In */}
            {!isSignUp && !isReset && (
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
              {loading ? 'Loading…' : isReset ? 'Send reset link' : (isSignUp ? 'Sign up' : 'Sign in')}
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
            {isReset ? (
              <button type="button" className="fpx-link" onClick={() => { setIsReset(false); setMessage(''); }}>
                Back to sign in
              </button>
            ) : (
              <>
                {isSignUp ? 'Already have an account?' : "Don't have an account?"}{' '}
                <button type="button" className="fpx-link" onClick={handleToggleMode}>
                  {isSignUp ? 'Sign in' : 'Sign up'}
                </button>
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
