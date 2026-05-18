import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogIn, LogOut, Settings as SettingsIcon } from 'lucide-react';
import FpxRail from './FpxRail';

export default function TermsOfService({ user, onShowAuthModal, onShowSettings, onLogout }) {
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  return (
    <>
    <div className="fpx-atmos base" />
    <div className="fpx-atmos vignette" />
    <div className="fpx-atmos grain" />
    <main className="fpx-land">
      <div className={`fpx-shell${collapsed ? ' collapsed' : ''}`}>
        <FpxRail
          collapsed={collapsed}
          onToggle={() => setCollapsed((v) => !v)}
          active={null}
          onHome={() => navigate('/')}
          onAnalyze={() => navigate('/analyze')}
          onResults={() => navigate('/results')}
        />
        <div className="fpx-main">
          <div className="fpx-top fpx-rv">
            <div className="fpx-crumbs">LEGAL&nbsp; /&nbsp; <b>TERMS</b></div>
            <div className="fpx-auth">
              {user ? (
                <>
                  <button className="fpx-btn ghost sm" onClick={onShowSettings}><SettingsIcon size={15} /> Settings</button>
                  <button className="fpx-btn ghost sm" onClick={onLogout}><LogOut size={15} /> Logout</button>
                </>
              ) : (
                <button className="fpx-btn ghost sm" onClick={onShowAuthModal}><LogIn size={15} /> Sign In</button>
              )}
            </div>
          </div>

      <div className="fpx-legal">
        <h1>Terms of Service</h1>
        <p style={{ color: 'var(--color-muted)', fontSize: '14px', marginBottom: '40px' }}>
          Last Updated: November 21, 2024
        </p>

        <div style={{ lineHeight: '1.7', fontSize: '15px' }}>
          <section style={{ marginBottom: '32px' }}>
            <h2>1. Acceptance of Terms</h2>
            <p>
              These Terms of Service ("Terms") constitute a legal agreement between you and Floor Pov ("we," "us," or "our") and govern your access to and use of the Floor Pov website at floorpov.gg (the "Service"). By accessing or using the Service, you agree to be bound by these Terms. If you do not agree to these Terms, you may not access or use the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>2. Description of Service</h2>
            <p>Floor Pov is a web-based analytical tool that processes World of Warcraft raid data from WarcraftLogs to provide death tracking and performance analysis for guilds. The Service includes:</p>
            <ul>
              <li>Analysis of guild raid performance using publicly available WarcraftLogs data</li>
              <li>Optional user accounts for saving WarcraftLogs API credentials and analysis history</li>
              <li>Shareable analysis results</li>
              <li>Features such as death rate tracking, cheat death detection, and guild roster filtering</li>
            </ul>
            <p>The Service is provided free of charge, with certain enhanced features available to authenticated users.</p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>3. Eligibility</h2>
            <p>
              You must be at least 13 years of age to use the Service. If you are between 13 and 18 years old, you may only use the Service with the permission and supervision of a parent or legal guardian who agrees to be bound by these Terms. By using the Service, you represent and warrant that you meet these eligibility requirements.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>4. User Accounts</h2>

            <h3>4.1 Account Creation</h3>
            <p>
              You may use basic features of the Service without creating an account. To access certain features, including saved API credentials and analysis history, you must create an account by providing a valid email address and password.
            </p>

            <h3>4.2 Account Security</h3>
            <p>You are responsible for:</p>
            <ul>
              <li>Maintaining the confidentiality of your account credentials</li>
              <li>All activities that occur under your account</li>
              <li>Notifying us immediately of any unauthorized use of your account</li>
            </ul>
            <p>We are not liable for any loss or damage arising from your failure to protect your account credentials.</p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>5. Acceptable Use</h2>
            <p>You agree not to:</p>
            <ul>
              <li>Use the Service for any illegal purpose or in violation of any law</li>
              <li>Violate or infringe upon the intellectual property rights of others</li>
              <li>Transmit any viruses, malware, or other malicious code</li>
              <li>Attempt to gain unauthorized access to any portion of the Service</li>
              <li>Use any automated means (including bots or scrapers) to access the Service without our express written permission</li>
              <li>Interfere with any other party's use and enjoyment of the Service</li>
              <li>Use the Service data in violation of WarcraftLogs' Terms of Service or Blizzard Entertainment's Terms of Use</li>
            </ul>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>6. Disclaimer of Warranties</h2>
            <p>
              THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS WITHOUT WARRANTIES OF ANY KIND. To the fullest extent permitted by law, we disclaim all warranties, including but not limited to implied warranties of merchantability, fitness for a particular purpose, and non-infringement.
            </p>
            <p>You acknowledge that:</p>
            <ul>
              <li>Analysis results may contain inaccuracies due to data processing or API limitations</li>
              <li>Death counts may vary slightly between analysis runs</li>
              <li>The Service is for informational purposes only</li>
              <li>You should not rely solely on the Service for critical raid management decisions</li>
            </ul>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>7. Limitation of Liability</h2>
            <p>
              TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL FLOOR POV BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING WITHOUT LIMITATION LOSS OF PROFITS, DATA, OR USE.
            </p>
            <p>TO THE EXTENT PERMITTED BY LAW, OUR TOTAL LIABILITY FOR ANY CLAIMS SHALL NOT EXCEED $100 USD.</p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>8. Changes to the Service</h2>
            <p>
              We reserve the right to modify, suspend, or discontinue the Service (or any part thereof) at any time with or without notice. We will not be liable to you or any third party for any modification, suspension, or discontinuance of the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>9. Governing Law</h2>
            <p>
              These Terms shall be governed by and construed in accordance with the laws of the State of Florida, United States, without regard to its conflict of law provisions. Any disputes shall be resolved through binding arbitration, except that you may assert claims in small claims court if your claims qualify.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>10. Intellectual Property</h2>
            <p>
              World of Warcraft, Warcraft, and Blizzard Entertainment are trademarks or registered trademarks of Blizzard Entertainment, Inc. WarcraftLogs is a trademark of Kihra. Floor Pov is not affiliated with, endorsed by, or sponsored by Blizzard Entertainment or WarcraftLogs.
            </p>
            <p>
              Analysis results you generate through the Service are yours to use and share. The Service itself, including its design, code, logos, and graphics, is owned by Floor Pov and protected by copyright and trademark laws.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>11. Contact Information</h2>
            <p>If you have questions about these Terms, please contact us at:</p>
            <p>
              <strong>Email:</strong> support@floorpov.gg<br />
              <strong>Website:</strong> https://floorpov.gg
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>12. Acknowledgment</h2>
            <p>
              BY USING THE SERVICE, YOU ACKNOWLEDGE THAT YOU HAVE READ THESE TERMS, UNDERSTAND THEM, AND AGREE TO BE BOUND BY THEM.
            </p>
          </section>

          <div className="disclaimer">
            <p>
              <strong>Floor Pov is an independent fan project and is not affiliated with, endorsed by, or sponsored by Blizzard Entertainment, Inc. or Kihra/WarcraftLogs.</strong>
            </p>
          </div>
        </div>
          </div>
        </div>
      </div>
    </main>
    </>
  );
}
