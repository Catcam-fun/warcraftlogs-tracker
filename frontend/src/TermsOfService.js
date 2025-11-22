import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogOut, Settings as SettingsIcon } from 'lucide-react';

export default function TermsOfService({ user, onShowAuthModal, onShowSettings, onLogout }) {
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
          Terms of Service
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
              1. Acceptance of Terms
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              These Terms of Service ("Terms") constitute a legal agreement between you and Floor Pov ("we," "us," or "our") and govern your access to and use of the Floor Pov website at floorpov.gg (the "Service"). By accessing or using the Service, you agree to be bound by these Terms. If you do not agree to these Terms, you may not access or use the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              2. Description of Service
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              Floor Pov is a web-based analytical tool that processes World of Warcraft raid data from WarcraftLogs to provide death tracking and performance analysis for guilds. The Service includes:
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Analysis of guild raid performance using publicly available WarcraftLogs data</li>
              <li style={{ marginBottom: '8px' }}>Optional user accounts for saving WarcraftLogs API credentials and analysis history</li>
              <li style={{ marginBottom: '8px' }}>Shareable analysis results</li>
              <li>Features such as death rate tracking, cheat death detection, and guild roster filtering</li>
            </ul>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              The Service is provided free of charge, with certain enhanced features available to authenticated users.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              3. Eligibility
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              You must be at least 13 years of age to use the Service. If you are between 13 and 18 years old, you may only use the Service with the permission and supervision of a parent or legal guardian who agrees to be bound by these Terms. By using the Service, you represent and warrant that you meet these eligibility requirements.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              4. User Accounts
            </h2>
            
            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              4.1 Account Creation
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              You may use basic features of the Service without creating an account. To access certain features, including saved API credentials and analysis history, you must create an account by providing a valid email address and password.
            </p>

            <h3 style={{ color: '#93c5fd', fontSize: '18px', marginBottom: '12px', marginTop: '20px' }}>
              4.2 Account Security
            </h3>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              You are responsible for:
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Maintaining the confidentiality of your account credentials</li>
              <li style={{ marginBottom: '8px' }}>All activities that occur under your account</li>
              <li>Notifying us immediately of any unauthorized use of your account</li>
            </ul>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              We are not liable for any loss or damage arising from your failure to protect your account credentials.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              5. Acceptable Use
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              You agree not to:
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Use the Service for any illegal purpose or in violation of any law</li>
              <li style={{ marginBottom: '8px' }}>Violate or infringe upon the intellectual property rights of others</li>
              <li style={{ marginBottom: '8px' }}>Transmit any viruses, malware, or other malicious code</li>
              <li style={{ marginBottom: '8px' }}>Attempt to gain unauthorized access to any portion of the Service</li>
              <li style={{ marginBottom: '8px' }}>Use any automated means (including bots or scrapers) to access the Service without our express written permission</li>
              <li style={{ marginBottom: '8px' }}>Interfere with any other party's use and enjoyment of the Service</li>
              <li>Use the Service data in violation of WarcraftLogs' Terms of Service or Blizzard Entertainment's Terms of Use</li>
            </ul>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              6. Disclaimer of Warranties
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS WITHOUT WARRANTIES OF ANY KIND. To the fullest extent permitted by law, we disclaim all warranties, including but not limited to implied warranties of merchantability, fitness for a particular purpose, and non-infringement.
            </p>
            <p style={{ color: '#cbd5e1', marginBottom: '8px' }}>
              You acknowledge that:
            </p>
            <ul style={{ color: '#cbd5e1', paddingLeft: '24px', marginBottom: '16px' }}>
              <li style={{ marginBottom: '8px' }}>Analysis results may contain inaccuracies due to data processing or API limitations</li>
              <li style={{ marginBottom: '8px' }}>Death counts may vary slightly between analysis runs</li>
              <li style={{ marginBottom: '8px' }}>The Service is for informational purposes only</li>
              <li>You should not rely solely on the Service for critical raid management decisions</li>
            </ul>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              7. Limitation of Liability
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL FLOOR POV BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING WITHOUT LIMITATION LOSS OF PROFITS, DATA, OR USE.
            </p>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              TO THE EXTENT PERMITTED BY LAW, OUR TOTAL LIABILITY FOR ANY CLAIMS SHALL NOT EXCEED $100 USD.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              8. Changes to the Service
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              We reserve the right to modify, suspend, or discontinue the Service (or any part thereof) at any time with or without notice. We will not be liable to you or any third party for any modification, suspension, or discontinuance of the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              9. Governing Law
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              These Terms shall be governed by and construed in accordance with the laws of the State of Florida, United States, without regard to its conflict of law provisions. Any disputes shall be resolved through binding arbitration, except that you may assert claims in small claims court if your claims qualify.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              10. Intellectual Property
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              World of Warcraft, Warcraft, and Blizzard Entertainment are trademarks or registered trademarks of Blizzard Entertainment, Inc. WarcraftLogs is a trademark of Kihra. Floor Pov is not affiliated with, endorsed by, or sponsored by Blizzard Entertainment or WarcraftLogs.
            </p>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              Analysis results you generate through the Service are yours to use and share. The Service itself, including its design, code, logos, and graphics, is owned by Floor Pov and protected by copyright and trademark laws.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              11. Contact Information
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              If you have questions about these Terms, please contact us at:
            </p>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              <strong>Email:</strong> support@floorpov.gg<br />
              <strong>Website:</strong> https://floorpov.gg
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2 style={{ color: '#60a5fa', fontSize: '24px', marginBottom: '16px' }}>
              12. Acknowledgment
            </h2>
            <p style={{ color: '#cbd5e1', marginBottom: '16px' }}>
              BY USING THE SERVICE, YOU ACKNOWLEDGE THAT YOU HAVE READ THESE TERMS, UNDERSTAND THEM, AND AGREE TO BE BOUND BY THEM.
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