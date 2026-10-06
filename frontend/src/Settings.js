import React, { useState, useEffect } from 'react';
import { supabase } from './supabaseClient';
import { apiFetch, saveLocalCredentials } from './api';
import { X, Save, Eye, EyeOff, Key, Mail, Trash2 } from 'lucide-react';

export default function Settings({ user, onClose, onCredentialsUpdate, onShowPrivacy }) {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [showSecret, setShowSecret] = useState(false);

  // Password change state
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState('');
  const [passwordLoading, setPasswordLoading] = useState(false);

  // Email change state
  const [newEmail, setNewEmail] = useState('');
  const [emailMessage, setEmailMessage] = useState('');
  const [emailLoading, setEmailLoading] = useState(false);

  // Delete account state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteMessage, setDeleteMessage] = useState('');

  // Load existing credentials
  useEffect(() => {
    loadCredentials();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadCredentials = async () => {
    try {
      const { data, error } = await supabase
        .from('api_credentials')
        .select('client_id, client_secret')
        .eq('user_id', user.id)
        .maybeSingle();

      if (error) {
        console.error('Error loading credentials:', error);
        return;
      }

      if (data) {
        setClientId(data.client_id || '');
        setClientSecret(data.client_secret || '');
      }
    } catch (err) {
      console.error('Error loading credentials:', err);
    }
  };

  const handleSave = async () => {
    if (!clientId || !clientSecret) {
      setMessage('Please fill in both Client ID and Client Secret');
      return;
    }

    setLoading(true);
    setMessage('');

    try {
      // Check if credentials already exist
      const { data: existing } = await supabase
        .from('api_credentials')
        .select('id')
        .eq('user_id', user.id)
        .maybeSingle();

      if (existing) {
        // Update existing
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
        // Insert new
        const { error } = await supabase
          .from('api_credentials')
          .insert({
            user_id: user.id,
            client_id: clientId,
            client_secret: clientSecret
          });

        if (error) throw error;
      }

      setMessage('Credentials saved successfully!');
      
      // Notify parent component to refresh credentials
      if (onCredentialsUpdate) {
        onCredentialsUpdate();
      }

      setTimeout(() => {
        setMessage('');
      }, 3000);
    } catch (err) {
      setMessage(err.message || 'Error saving credentials');
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    setPasswordMessage('');

    if (newPassword.length < 6) {
      setPasswordMessage('Password must be at least 6 characters');
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordMessage('Passwords do not match');
      return;
    }

    setPasswordLoading(true);

    try {
      const { error } = await supabase.auth.updateUser({
        password: newPassword
      });

      if (error) throw error;

      setPasswordMessage('Password updated successfully!');
      setNewPassword('');
      setConfirmPassword('');

      setTimeout(() => {
        setPasswordMessage('');
      }, 3000);
    } catch (err) {
      setPasswordMessage(err.message || 'Error updating password');
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleEmailChange = async (e) => {
    e.preventDefault();
    setEmailMessage('');

    if (!newEmail || !newEmail.includes('@')) {
      setEmailMessage('Please enter a valid email address');
      return;
    }

    setEmailLoading(true);

    try {
      const { error } = await supabase.auth.updateUser({
        email: newEmail
      });

      if (error) throw error;

      setEmailMessage('Confirmation email sent! Check your inbox to confirm the change.');
      setNewEmail('');

      setTimeout(() => {
        setEmailMessage('');
      }, 5000);
    } catch (err) {
      setEmailMessage(err.message || 'Error updating email');
    } finally {
      setEmailLoading(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirmText !== 'DELETE') {
      setDeleteMessage('Please type DELETE to confirm');
      return;
    }

    setDeleteLoading(true);
    setDeleteMessage('');

    try {
      // The server identifies the account from the session token, deletes
      // its saved reports, shares, stored credentials, and the login itself.
      const { ok, body } = await apiFetch('/api/account', { method: 'DELETE', auth: true });
      if (!ok) {
        throw new Error(body.error || 'Failed to delete account');
      }

      await supabase.auth.signOut({ scope: 'local' });
      // The WarcraftLogs key this browser remembers goes with the account.
      saveLocalCredentials('', '');
      setDeleteMessage('Account deleted successfully');
      setTimeout(() => {
        onClose();
        window.location.assign('/');
      }, 1000);
    } catch (err) {
      console.error('[Delete Account] Error:', err);
      setDeleteMessage(err.message || 'Error deleting account. Please contact support.');
    } finally {
      setDeleteLoading(false);
    }
  };

  const msgClass = (m, okWord) => `fpx-mmsg ${m.includes(okWord) ? 'ok' : 'err'}`;

  return (
    <div className="fpx-mov" onClick={onClose}>
      <div className="fpx-mcard" onClick={(e) => e.stopPropagation()}>
        <div className="fpx-mhead">
          <h2>Account settings</h2>
          <button className="fpx-mclose" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        <div className="fpx-mbody">
          <p className="lead">Logged in as <strong style={{ color: 'var(--fpx-ink)' }}>{user.email}</strong></p>

          {/* WarcraftLogs API Credentials */}
          <section className="fpx-msec">
            <h3><Key size={16} /> WarcraftLogs API credentials</h3>
            <p>Save your WarcraftLogs API credentials here — they auto-fill when you analyze reports.</p>

            <p className="fpx-mnote">
              <strong style={{ color: 'var(--fpx-ink)' }}>How they're stored.</strong>{' '}
              Saved to your account in our database, which is encrypted at rest; no other account can read them.
              We only use them to fetch raid data on your behalf. See our{' '}
              <button type="button" className="fpx-link" onClick={() => { if (onShowPrivacy) onShowPrivacy(); }}>
                Privacy Policy
              </button>.
            </p>

            <div className="fpx-mform">
              <div className="f">
                <label>Client ID</label>
                <input
                  type="text"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="Your WarcraftLogs Client ID"
                />
              </div>

              <div className="f">
                <label>Client Secret</label>
                <div className="pw">
                  <input
                    type={showSecret ? 'text' : 'password'}
                    value={clientSecret}
                    onChange={(e) => setClientSecret(e.target.value)}
                    placeholder="Your WarcraftLogs Client Secret"
                  />
                  <button type="button" className="eye" onClick={() => setShowSecret(!showSecret)} aria-label="Toggle visibility">
                    {showSecret ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                <p className="hint">
                  Get your API credentials from{' '}
                  <a href="https://www.warcraftlogs.com/api/clients" target="_blank" rel="noopener noreferrer" className="fpx-link">
                    WarcraftLogs API Clients
                  </a>
                </p>
              </div>

              {message && <p className={msgClass(message, 'successfully')}>{message}</p>}

              <button
                onClick={handleSave}
                disabled={loading}
                className="fpx-btn"
                style={{ opacity: loading ? 0.7 : 1, cursor: loading ? 'not-allowed' : 'pointer' }}
              >
                <Save size={16} /> {loading ? 'Saving…' : 'Save credentials'}
              </button>
            </div>
          </section>

          {/* Change Password */}
          <section className="fpx-msec">
            <h3><Key size={16} /> Change password</h3>
            <p>Update your account password. Changes take effect immediately.</p>

            <form className="fpx-mform" onSubmit={handlePasswordChange}>
              <div className="f">
                <label>New password</label>
                <div className="pw">
                  <input
                    type={showNewPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Enter new password"
                    minLength={6}
                  />
                  <button type="button" className="eye" onClick={() => setShowNewPassword(!showNewPassword)} aria-label="Toggle visibility">
                    {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              <div className="f">
                <label>Confirm new password</label>
                <div className="pw">
                  <input
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm new password"
                    minLength={6}
                  />
                  <button type="button" className="eye" onClick={() => setShowConfirmPassword(!showConfirmPassword)} aria-label="Toggle visibility">
                    {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {passwordMessage && <p className={msgClass(passwordMessage, 'successfully')}>{passwordMessage}</p>}

              <button
                type="submit"
                disabled={passwordLoading}
                className="fpx-btn"
                style={{ opacity: passwordLoading ? 0.7 : 1, cursor: passwordLoading ? 'not-allowed' : 'pointer' }}
              >
                {passwordLoading ? 'Updating…' : 'Update password'}
              </button>
            </form>
          </section>

          {/* Change Email */}
          <section className="fpx-msec">
            <h3><Mail size={16} /> Change email</h3>
            <p>Update your account email address. You'll confirm the change via email.</p>

            <form className="fpx-mform" onSubmit={handleEmailChange}>
              <div className="f">
                <label>New email address</label>
                <input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="Enter new email address"
                />
              </div>

              {emailMessage && <p className={msgClass(emailMessage, 'sent')}>{emailMessage}</p>}

              <button
                type="submit"
                disabled={emailLoading}
                className="fpx-btn"
                style={{ opacity: emailLoading ? 0.7 : 1, cursor: emailLoading ? 'not-allowed' : 'pointer' }}
              >
                {emailLoading ? 'Sending…' : 'Update email'}
              </button>
            </form>
          </section>

          {/* Delete Account */}
          <section className="fpx-msec danger">
            <h3><Trash2 size={16} /> Delete account</h3>
            <p>Permanently delete your account and all associated data. This cannot be undone.</p>

            {!showDeleteConfirm ? (
              <button className="fpx-btn danger" onClick={() => setShowDeleteConfirm(true)}>
                <Trash2 size={14} /> Delete my account
              </button>
            ) : (
              <div className="fpx-mform">
                <p className="fpx-mmsg warn">
                  <strong>Warning:</strong> this permanently deletes your account, API credentials,
                  and analysis history. Type <strong>DELETE</strong> to confirm.
                </p>

                <div className="f">
                  <input
                    type="text"
                    value={deleteConfirmText}
                    onChange={(e) => setDeleteConfirmText(e.target.value)}
                    placeholder="Type DELETE to confirm"
                  />
                </div>

                {deleteMessage && <p className={msgClass(deleteMessage, 'successfully')}>{deleteMessage}</p>}

                <div className="fpx-mrow">
                  <button
                    className="fpx-btn ghost"
                    onClick={() => {
                      setShowDeleteConfirm(false);
                      setDeleteConfirmText('');
                      setDeleteMessage('');
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    className="fpx-btn danger"
                    onClick={handleDeleteAccount}
                    disabled={deleteLoading || deleteConfirmText !== 'DELETE'}
                    style={{
                      opacity: (deleteLoading || deleteConfirmText !== 'DELETE') ? 0.6 : 1,
                      cursor: (deleteLoading || deleteConfirmText !== 'DELETE') ? 'not-allowed' : 'pointer'
                    }}
                  >
                    <Trash2 size={14} /> {deleteLoading ? 'Deleting…' : 'Confirm delete'}
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
