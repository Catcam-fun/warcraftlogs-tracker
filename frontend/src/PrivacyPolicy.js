import React, { useEffect } from 'react';
import AppHeader from './AppHeader';

export default function PrivacyPolicy({ user, onShowAuthModal, onShowSettings, onLogout }) {
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  return (
    <div className="fp-legal legal-shell" style={{ minHeight: '100vh' }}>
      <AppHeader
        user={user}
        onShowAuthModal={onShowAuthModal}
        onShowSettings={onShowSettings}
        onLogout={onLogout}
      />

      <div className="legal-content">
        <h1>Privacy Policy</h1>
        <p style={{ color: 'var(--color-muted)', fontSize: '14px', marginBottom: '40px' }}>
          Last Updated: November 21, 2024
        </p>

        <div style={{ lineHeight: '1.7', fontSize: '15px' }}>
          <section style={{ marginBottom: '32px' }}>
            <h2>1. Introduction</h2>
            <p>
              This Privacy Policy explains how Floor Pov ("we," "us," or "our") collects, uses, stores, shares, and protects your personal information when you use our website at floorpov.gg (the "Service"). We are committed to protecting your privacy and being transparent about our data practices.
            </p>
            <p>
              By using the Service, you agree to the collection and use of information in accordance with this Privacy Policy. If you do not agree with this Privacy Policy, please do not use the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>2. Information We Collect</h2>

            <h3>2.1 Information You Provide Directly</h3>
            <p>
              <strong>Account Information (Optional - Only for Registered Users):</strong>
            </p>
            <ul>
              <li><strong>Email Address:</strong> Used for account creation, authentication, and password resets</li>
              <li><strong>Password:</strong> Encrypted and never stored in plain text using bcrypt hashing</li>
              <li><strong>WarcraftLogs API Credentials:</strong> If you choose to save your Client ID and Client Secret, these are encrypted at rest and used solely to fetch data on your behalf</li>
            </ul>
            <p>
              <strong>Analysis Configurations:</strong>
            </p>
            <ul>
              <li>Guild names, server names, and regions you search for</li>
              <li>Selected raids, difficulties, boss filters, and date ranges</li>
              <li>Character grouping configurations</li>
              <li>Saved analysis results and preferences</li>
            </ul>

            <h3>2.2 Information Collected Automatically</h3>
            <p>
              <strong>Technical Information:</strong>
            </p>
            <ul>
              <li>IP Address (for security and rate limiting)</li>
              <li>Browser type and version</li>
              <li>Device type and operating system</li>
              <li>Referral source</li>
            </ul>
            <p>
              <strong>Important:</strong> We do NOT track you across other websites. We do NOT use advertising cookies or sell your data to third parties.
            </p>

            <h3>2.3 Information from Third Parties</h3>
            <p>
              <strong>WarcraftLogs Data:</strong> When you run an analysis, we retrieve publicly available combat log data from WarcraftLogs API. This data is processed in real-time and is not permanently stored except in cached analysis results.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>3. How We Use Your Information</h2>

            <h3>3.1 Core Service Functionality</h3>
            <ul>
              <li>Provide the Service: Process analysis requests and generate reports</li>
              <li>Authentication: Verify your identity when you log in</li>
              <li>Saved Credentials: Use your WarcraftLogs API credentials to fetch data</li>
              <li>Analysis History: Save your past analyses for later access</li>
            </ul>

            <h3>3.2 Service Improvement</h3>
            <ul>
              <li>Monitor system performance and identify bugs</li>
              <li>Understand feature usage to prioritize development</li>
              <li>Improve user experience and functionality</li>
            </ul>

            <h3>3.3 Legal and Security</h3>
            <ul>
              <li>Comply with legal obligations</li>
              <li>Detect and prevent fraud or abuse</li>
              <li>Enforce our Terms of Service</li>
            </ul>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>4. How We Store Your Information</h2>

            <h3>4.1 Security Measures</h3>
            <ul>
              <li>HTTPS/TLS 1.3 encryption for all connections</li>
              <li>Encrypted storage for API credentials using industry-standard encryption</li>
              <li>Secure password hashing (never stored in plain text)</li>
              <li>Row-Level Security (RLS) policies in our database</li>
            </ul>

            <h3>4.2 Data Retention</h3>
            <ul>
              <li>Account data: Retained until you delete your account</li>
              <li>Analysis history: Retained until you delete your account</li>
              <li>Logs and analytics: Retained for up to 90 days</li>
              <li>Deleted account data: Permanently deleted within 30 days</li>
            </ul>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>5. How We Share Your Information</h2>
            <p>
              <strong>We do NOT sell, rent, or trade your personal information.</strong>
            </p>

            <h3>5.1 Service Providers</h3>
            <p>We share information with trusted service providers:</p>
            <ul>
              <li>Supabase (authentication and database)</li>
              <li>WarcraftLogs (API requests using your credentials)</li>
              <li>Cloudflare (CDN and API proxying)</li>
              <li>Render.com (application hosting)</li>
            </ul>

            <h3>5.2 Public Analysis Results</h3>
            <p>
              If you share an analysis result URL, anyone with that link can view the guild and death statistics. Shared results do NOT include your email, API credentials, or other account information.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>6. Your Rights and Choices</h2>

            <h3>6.1 Account Access and Control</h3>
            <p>You can:</p>
            <ul>
              <li>View and update your information in Settings</li>
              <li>Manage your API credentials</li>
              <li>View your analysis history</li>
              <li>Delete your account and all associated data</li>
            </ul>

            <h3>6.2 California Residents (CCPA/CPRA)</h3>
            <p>California residents have the right to:</p>
            <ul>
              <li>Know what personal information we collect</li>
              <li>Access your personal information</li>
              <li>Delete your personal information</li>
              <li>Receive equal service regardless of privacy choices</li>
            </ul>
            <p>
              To exercise these rights, contact us at support@floorpov.gg. We will respond within 45 days.
            </p>

            <h3>6.3 European Union Residents (GDPR)</h3>
            <p>EU residents have the right to:</p>
            <ul>
              <li>Access your personal data</li>
              <li>Correct inaccurate personal data</li>
              <li>Request deletion ("right to be forgotten")</li>
              <li>Data portability (receive data in machine-readable format)</li>
              <li>Object to processing or withdraw consent</li>
            </ul>
            <p>
              To exercise these rights, contact us at support@floorpov.gg. We will respond within 30 days.
            </p>

            <h3>6.4 Cookies</h3>
            <p>
              We use minimal cookies for essential functionality only (authentication and preferences). We do not use advertising or tracking cookies.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>7. Children's Privacy</h2>
            <p>
              The Service is not directed to children under 13, and we do not knowingly collect information from children under 13. If we learn we have collected information from a child under 13, we will promptly delete it. Parents should supervise children between 13 and 18 who use the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>8. Data Breach Notification</h2>
            <p>
              In the unlikely event of a data breach affecting your personal information, we will notify you via email within 72 hours of discovering the breach and explain what happened and what steps we're taking.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>9. Changes to This Privacy Policy</h2>
            <p>
              We may update this Privacy Policy from time to time. When we make material changes, we will update the "Last Updated" date and notify you via email or through a prominent notice on the Service.
            </p>
          </section>

          <section style={{ marginBottom: '32px' }}>
            <h2>10. Contact Us</h2>
            <p>If you have questions or requests regarding this Privacy Policy, please contact us at:</p>
            <p>
              <strong>Email:</strong> support@floorpov.gg<br />
              <strong>Website:</strong> https://floorpov.gg
            </p>
            <p>
              For GDPR requests, include "GDPR Request" in the subject line.<br />
              For CCPA requests, include "CCPA Request" in the subject line.
            </p>
          </section>

          <div className="inset-panel" style={{ padding: '20px', marginTop: '40px', borderColor: 'var(--color-border-strong)' }}>
            <p style={{ margin: 0, textAlign: 'center', fontSize: '13px' }}>
              <strong>Floor Pov is an independent fan project and is not affiliated with, endorsed by, or sponsored by Blizzard Entertainment, Inc. or Kihra/WarcraftLogs.</strong>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
