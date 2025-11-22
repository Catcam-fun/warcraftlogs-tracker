import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogOut, Settings as SettingsIcon } from 'lucide-react';

export default function PrivacyPolicy({ user, onShowAuthModal, onShowSettings, onLogout }) {
  const navigate = useNavigate();

  // Scroll to top when component mounts
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  return (
    <div style={{ minHeight: '100vh', background: '#0a0e1a', color: '#e2e8f0', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      {/* Sticky Header - Same as main app */}
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
            onClick={() => navigate('/')}
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

      {/* Content */}
      <div style={{
        padding: '40px 20px'
      }}>
        <div style={{
          maxWidth: '900px',
          margin: '0 auto'
        }}>
        {/* Header */}
        <h1 style={{
          color: '#3b82f6',
          fontSize: '36px',
          fontWeight: '700',
          marginBottom: '8px',
          marginTop: 0
        }}>
          Privacy Policy
        </h1>
        <p style={{
          color: '#94a3b8',
          fontSize: '14px',
          marginBottom: '40px'
        }}>
          Last Updated: November 21, 2024
        </p>

        {/* Content */}
        <div style={{
          lineHeight: '1.7',
          fontSize: '15px'
        }}>
          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              1. Introduction
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              This Privacy Policy explains how Floor Pov ("we," "us," or "our") collects, uses, stores, shares, and protects your personal information when you use our website at floorpov.gg (the "Service"). We are committed to protecting your privacy and being transparent about our data practices.
            </p>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              By using the Service, you agree to the collection and use of information in accordance with this Privacy Policy. If you do not agree with this Privacy Policy, please do not use the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              2. Information We Collect
            </h2>
            
            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              2.1 Information You Provide Directly
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              <strong>Account Information (Optional - Only for Registered Users):</strong>
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}><strong>Email Address:</strong> Used for account creation, authentication, and password resets</li>
              <li style={{ marginBottom: '8px' }}><strong>Password:</strong> Encrypted and never stored in plain text using bcrypt hashing</li>
              <li><strong>WarcraftLogs API Credentials:</strong> If you choose to save your Client ID and Client Secret, these are encrypted at rest and used solely to fetch data on your behalf</li>
            </ul>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              <strong>Analysis Configurations:</strong>
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Guild names, server names, and regions you search for</li>
              <li style={{ marginBottom: '8px' }}>Selected raids, difficulties, boss filters, and date ranges</li>
              <li style={{ marginBottom: '8px' }}>Character grouping configurations</li>
              <li>Saved analysis results and preferences</li>
            </ul>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              2.2 Information Collected Automatically
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              <strong>Technical Information:</strong>
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>IP Address (for security and rate limiting)</li>
              <li style={{ marginBottom: '8px' }}>Browser type and version</li>
              <li style={{ marginBottom: '8px' }}>Device type and operating system</li>
              <li>Referral source</li>
            </ul>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              <strong>Important:</strong> We do NOT track you across other websites. We do NOT use advertising cookies or sell your data to third parties.
            </p>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              2.3 Information from Third Parties
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              <strong>WarcraftLogs Data:</strong> When you run an analysis, we retrieve publicly available combat log data from WarcraftLogs API. This data is processed in real-time and is not permanently stored except in cached analysis results.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              3. How We Use Your Information
            </h2>
            
            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              3.1 Core Service Functionality
            </h3>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Provide the Service: Process analysis requests and generate reports</li>
              <li style={{ marginBottom: '8px' }}>Authentication: Verify your identity when you log in</li>
              <li style={{ marginBottom: '8px' }}>Saved Credentials: Use your WarcraftLogs API credentials to fetch data</li>
              <li>Analysis History: Save your past analyses for later access</li>
            </ul>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              3.2 Service Improvement
            </h3>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Monitor system performance and identify bugs</li>
              <li style={{ marginBottom: '8px' }}>Understand feature usage to prioritize development</li>
              <li>Improve user experience and functionality</li>
            </ul>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              3.3 Legal and Security
            </h3>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Comply with legal obligations</li>
              <li style={{ marginBottom: '8px' }}>Detect and prevent fraud or abuse</li>
              <li>Enforce our Terms of Service</li>
            </ul>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              4. How We Store Your Information
            </h2>
            
            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              4.1 Security Measures
            </h3>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>HTTPS/TLS 1.3 encryption for all connections</li>
              <li style={{ marginBottom: '8px' }}>Encrypted storage for API credentials using industry-standard encryption</li>
              <li style={{ marginBottom: '8px' }}>Secure password hashing (never stored in plain text)</li>
              <li>Row-Level Security (RLS) policies in our database</li>
            </ul>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              4.2 Data Retention
            </h3>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Account data: Retained until you delete your account</li>
              <li style={{ marginBottom: '8px' }}>Analysis history: Retained until you delete your account</li>
              <li style={{ marginBottom: '8px' }}>Logs and analytics: Retained for up to 90 days</li>
              <li>Deleted account data: Permanently deleted within 30 days</li>
            </ul>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              5. How We Share Your Information
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              <strong>We do NOT sell, rent, or trade your personal information.</strong>
            </p>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              5.1 Service Providers
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              We share information with trusted service providers:
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Supabase (authentication and database)</li>
              <li style={{ marginBottom: '8px' }}>WarcraftLogs (API requests using your credentials)</li>
              <li style={{ marginBottom: '8px' }}>Cloudflare (CDN and API proxying)</li>
              <li>Render.com (application hosting)</li>
            </ul>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              5.2 Public Analysis Results
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              If you share an analysis result URL, anyone with that link can view the guild and death statistics. Shared results do NOT include your email, API credentials, or other account information.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              6. Your Rights and Choices
            </h2>
            
            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              6.1 Account Access and Control
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              You can:
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>View and update your information in Settings</li>
              <li style={{ marginBottom: '8px' }}>Manage your API credentials</li>
              <li style={{ marginBottom: '8px' }}>View your analysis history</li>
              <li>Delete your account and all associated data</li>
            </ul>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              6.2 California Residents (CCPA/CPRA)
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              California residents have the right to:
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Know what personal information we collect</li>
              <li style={{ marginBottom: '8px' }}>Access your personal information</li>
              <li style={{ marginBottom: '8px' }}>Delete your personal information</li>
              <li>Receive equal service regardless of privacy choices</li>
            </ul>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              To exercise these rights, contact us at support@floorpov.gg. We will respond within 45 days.
            </p>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              6.3 European Union Residents (GDPR)
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              EU residents have the right to:
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Access your personal data</li>
              <li style={{ marginBottom: '8px' }}>Correct inaccurate personal data</li>
              <li style={{ marginBottom: '8px' }}>Request deletion ("right to be forgotten")</li>
              <li style={{ marginBottom: '8px' }}>Data portability (receive data in machine-readable format)</li>
              <li>Object to processing or withdraw consent</li>
            </ul>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              To exercise these rights, contact us at support@floorpov.gg. We will respond within 30 days.
            </p>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              6.4 Cookies
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              We use minimal cookies for essential functionality only (authentication and preferences). We do not use advertising or tracking cookies.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              7. Children's Privacy
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              The Service is not directed to children under 13, and we do not knowingly collect information from children under 13. If we learn we have collected information from a child under 13, we will promptly delete it. Parents should supervise children between 13 and 18 who use the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              8. Data Breach Notification
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              In the unlikely event of a data breach affecting your personal information, we will notify you via email within 72 hours of discovering the breach and explain what happened and what steps we're taking.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              9. Changes to This Privacy Policy
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              We may update this Privacy Policy from time to time. When we make material changes, we will update the "Last Updated" date and notify you via email or through a prominent notice on the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              10. Contact Us
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              If you have questions or requests regarding this Privacy Policy, please contact us at:
            </p>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              <strong>Email:</strong> support@floorpov.gg<br />
              <strong>Website:</strong> https://floorpov.gg
            </p>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              For GDPR requests, include "GDPR Request" in the subject line.<br />
              For CCPA requests, include "CCPA Request" in the subject line.
            </p>
          </section>

          {/* Disclaimer */}
          <div style={{
            background: '#1a1f2e',
            border: '1px solid #3b82f6',
            borderRadius: '8px',
            padding: '20px',
            marginTop: '40px'
          }}>
            <p style={{ color: '#cbd5e1', fontSize: '13px', margin: 0, textAlign: 'center' }}>
              <strong>Floor Pov is an independent fan project and is not affiliated with, endorsed by, or sponsored by Blizzard Entertainment, Inc. or Kihra/WarcraftLogs.</strong>
            </p>
          </div>
        </div>
        </div>
      </div>
    </div>
  );
}