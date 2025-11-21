import React, { useState, useEffect } from 'react';
import { supabase } from './supabaseClient';
import { X, Save, Eye, EyeOff, Key, Mail } from 'lucide-react';

export default function Settings({ user, onClose, onCredentialsUpdate }) {
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

  // Load existing credentials
  useEffect(() => {
    loadCredentials();
  }, []);

  const loadCredentials = async () => {
    try {
      const { data, error } = await supabase
        .from('api_credentials')
        .select('client_id, client_secret')
        .eq('user_id', user.id)
        .single();

      if (error && error.code !== 'PGRST116') {
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
        .single();

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
        maxWidth: '600px',
        width: '90%',
        margin: '0 auto',
        padding: '32px',
        border: '1px solid #3b82f6',
        borderRadius: '12px',
        backgroundColor: '#1a1a2e',
        position: 'relative',
        maxHeight: '90vh',
        overflowY: 'auto'
      }}>
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

        <h2 style={{ 
          color: '#3b82f6', 
          marginBottom: '8px',
          marginTop: 0,
          fontSize: '24px'
        }}>
          Account Settings
        </h2>

        <p style={{
          color: '#64748b',
          fontSize: '13px',
          marginBottom: '24px'
        }}>
          Logged in as: <span style={{ color: '#e2e8f0', fontWeight: '500' }}>{user.email}</span>
        </p>

        {/* WarcraftLogs API Credentials Section */}
        <div style={{
          background: '#0f1419',
          borderRadius: '8px',
          padding: '20px',
          marginBottom: '20px',
          border: '1px solid #2d3748'
        }}>
          <h3 style={{
            color: '#e2e8f0',
            fontSize: '16px',
            marginTop: 0,
            marginBottom: '8px',
            fontWeight: '600'
          }}>
            WarcraftLogs API Credentials
          </h3>
          
          <p style={{
            color: '#94a3b8',
            fontSize: '13px',
            marginBottom: '20px',
            lineHeight: '1.5'
          }}>
            Save your WarcraftLogs API credentials here. They'll automatically fill when you analyze reports.
          </p>

          <div style={{ marginBottom: '16px' }}>
            <label style={{ 
              display: 'block', 
              marginBottom: '6px', 
              color: '#e2e8f0',
              fontSize: '14px',
              fontWeight: '500'
            }}>
              Client ID
            </label>
            <input
              type="text"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="Your WarcraftLogs Client ID"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #475569',
                backgroundColor: '#0a0e1a',
                color: '#fff',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div style={{ marginBottom: '8px' }}>
            <label style={{ 
              display: 'block', 
              marginBottom: '6px', 
              color: '#e2e8f0',
              fontSize: '14px',
              fontWeight: '500'
            }}>
              Client Secret
            </label>
            <div style={{ position: 'relative' }}>
              <input
                type={showSecret ? 'text' : 'password'}
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder="Your WarcraftLogs Client Secret"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  paddingRight: '45px',
                  borderRadius: '6px',
                  border: '1px solid #475569',
                  backgroundColor: '#0a0e1a',
                  color: '#fff',
                  fontSize: '14px',
                  boxSizing: 'border-box'
                }}
              />
              <button
                type="button"
                onClick={() => setShowSecret(!showSecret)}
                style={{
                  position: 'absolute',
                  right: '8px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'transparent',
                  border: 'none',
                  color: '#94a3b8',
                  cursor: 'pointer',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center'
                }}
              >
                {showSecret ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          <p style={{
            color: '#64748b',
            fontSize: '12px',
            marginTop: '8px',
            marginBottom: '16px'
          }}>
            Get your API credentials from{' '}
            <a 
              href="https://www.warcraftlogs.com/api/clients" 
              target="_blank" 
              rel="noopener noreferrer"
              style={{ color: '#3b82f6', textDecoration: 'underline' }}
            >
              WarcraftLogs API Clients
            </a>
          </p>

          {message && (
            <p style={{
              marginBottom: '16px',
              padding: '12px',
              backgroundColor: message.includes('successfully') ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
              border: `1px solid ${message.includes('successfully') ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
              color: message.includes('successfully') ? '#10b981' : '#ef4444',
              borderRadius: '6px',
              textAlign: 'center',
              fontSize: '13px'
            }}>
              {message}
            </p>
          )}

          <button
            onClick={handleSave}
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
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px'
            }}
            onMouseOver={(e) => { if (!loading) e.target.style.backgroundColor = '#2563eb'; }}
            onMouseOut={(e) => { if (!loading) e.target.style.backgroundColor = '#3b82f6'; }}
          >
            <Save size={16} />
            {loading ? 'Saving...' : 'Save Credentials'}
          </button>
        </div>

        {/* Change Password Section */}
        <div style={{
          background: '#0f1419',
          borderRadius: '8px',
          padding: '20px',
          marginBottom: '20px',
          border: '1px solid #2d3748'
        }}>
          <h3 style={{
            color: '#e2e8f0',
            fontSize: '16px',
            marginTop: 0,
            marginBottom: '8px',
            fontWeight: '600',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <Key size={18} />
            Change Password
          </h3>
          
          <p style={{
            color: '#94a3b8',
            fontSize: '13px',
            marginBottom: '20px',
            lineHeight: '1.5'
          }}>
            Update your account password. Changes take effect immediately.
          </p>

          <form onSubmit={handlePasswordChange}>
            <div style={{ marginBottom: '16px' }}>
              <label style={{ 
                display: 'block', 
                marginBottom: '6px', 
                color: '#e2e8f0',
                fontSize: '14px',
                fontWeight: '500'
              }}>
                New Password
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type={showNewPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Enter new password"
                  minLength={6}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    paddingRight: '45px',
                    borderRadius: '6px',
                    border: '1px solid #475569',
                    backgroundColor: '#0a0e1a',
                    color: '#fff',
                    fontSize: '14px',
                    boxSizing: 'border-box'
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowNewPassword(!showNewPassword)}
                  style={{
                    position: 'absolute',
                    right: '8px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'transparent',
                    border: 'none',
                    color: '#94a3b8',
                    cursor: 'pointer',
                    padding: '4px',
                    display: 'flex',
                    alignItems: 'center'
                  }}
                >
                  {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ 
                display: 'block', 
                marginBottom: '6px', 
                color: '#e2e8f0',
                fontSize: '14px',
                fontWeight: '500'
              }}>
                Confirm New Password
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Confirm new password"
                  minLength={6}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    paddingRight: '45px',
                    borderRadius: '6px',
                    border: '1px solid #475569',
                    backgroundColor: '#0a0e1a',
                    color: '#fff',
                    fontSize: '14px',
                    boxSizing: 'border-box'
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  style={{
                    position: 'absolute',
                    right: '8px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'transparent',
                    border: 'none',
                    color: '#94a3b8',
                    cursor: 'pointer',
                    padding: '4px',
                    display: 'flex',
                    alignItems: 'center'
                  }}
                >
                  {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {passwordMessage && (
              <p style={{
                marginBottom: '16px',
                padding: '12px',
                backgroundColor: passwordMessage.includes('successfully') ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                border: `1px solid ${passwordMessage.includes('successfully') ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                color: passwordMessage.includes('successfully') ? '#10b981' : '#ef4444',
                borderRadius: '6px',
                textAlign: 'center',
                fontSize: '13px'
              }}>
                {passwordMessage}
              </p>
            )}

            <button
              type="submit"
              disabled={passwordLoading || !newPassword || !confirmPassword}
              style={{
                width: '100%',
                padding: '12px',
                backgroundColor: (passwordLoading || !newPassword || !confirmPassword) ? '#1e40af' : '#3b82f6',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                cursor: (passwordLoading || !newPassword || !confirmPassword) ? 'not-allowed' : 'pointer',
                fontSize: '15px',
                fontWeight: '600',
                opacity: (passwordLoading || !newPassword || !confirmPassword) ? 0.7 : 1,
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px'
              }}
              onMouseOver={(e) => { 
                if (!passwordLoading && newPassword && confirmPassword) 
                  e.target.style.backgroundColor = '#2563eb'; 
              }}
              onMouseOut={(e) => { 
                if (!passwordLoading && newPassword && confirmPassword) 
                  e.target.style.backgroundColor = '#3b82f6'; 
              }}
            >
              <Key size={16} />
              {passwordLoading ? 'Updating...' : 'Update Password'}
            </button>
          </form>
        </div>

        {/* Change Email Section */}
        <div style={{
          background: '#0f1419',
          borderRadius: '8px',
          padding: '20px',
          border: '1px solid #2d3748'
        }}>
          <h3 style={{
            color: '#e2e8f0',
            fontSize: '16px',
            marginTop: 0,
            marginBottom: '8px',
            fontWeight: '600',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <Mail size={18} />
            Change Email
          </h3>
          
          <p style={{
            color: '#94a3b8',
            fontSize: '13px',
            marginBottom: '20px',
            lineHeight: '1.5'
          }}>
            Update your account email address. A confirmation link will be sent to your new email.
          </p>

          <form onSubmit={handleEmailChange}>
            <div style={{ marginBottom: '16px' }}>
              <label style={{ 
                display: 'block', 
                marginBottom: '6px', 
                color: '#e2e8f0',
                fontSize: '14px',
                fontWeight: '500'
              }}>
                New Email Address
              </label>
              <input
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                placeholder="Enter new email address"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: '6px',
                  border: '1px solid #475569',
                  backgroundColor: '#0a0e1a',
                  color: '#fff',
                  fontSize: '14px',
                  boxSizing: 'border-box'
                }}
              />
            </div>

            {emailMessage && (
              <p style={{
                marginBottom: '16px',
                padding: '12px',
                backgroundColor: emailMessage.includes('sent') ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                border: `1px solid ${emailMessage.includes('sent') ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                color: emailMessage.includes('sent') ? '#10b981' : '#ef4444',
                borderRadius: '6px',
                textAlign: 'center',
                fontSize: '13px'
              }}>
                {emailMessage}
              </p>
            )}

            <button
              type="submit"
              disabled={emailLoading || !newEmail}
              style={{
                width: '100%',
                padding: '12px',
                backgroundColor: (emailLoading || !newEmail) ? '#1e40af' : '#3b82f6',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                cursor: (emailLoading || !newEmail) ? 'not-allowed' : 'pointer',
                fontSize: '15px',
                fontWeight: '600',
                opacity: (emailLoading || !newEmail) ? 0.7 : 1,
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px'
              }}
              onMouseOver={(e) => { 
                if (!emailLoading && newEmail) 
                  e.target.style.backgroundColor = '#2563eb'; 
              }}
              onMouseOut={(e) => { 
                if (!emailLoading && newEmail) 
                  e.target.style.backgroundColor = '#3b82f6'; 
              }}
            >
              <Mail size={16} />
              {emailLoading ? 'Sending...' : 'Update Email'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}