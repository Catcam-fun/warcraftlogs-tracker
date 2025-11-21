import React from 'react';
import { Play, FolderOpen } from 'lucide-react';

export default function LandingPage({ onRunAnalysis, onSavedReports }) {
  return (
    <div style={{
      minHeight: 'calc(100vh - 200px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '40px 20px'
    }}>
      <div style={{
        maxWidth: '900px',
        width: '100%',
        textAlign: 'center'
      }}>
        {/* Hero Section */}
        <div style={{ marginBottom: '60px' }}>
          <h1 style={{
            fontSize: '48px',
            fontWeight: '700',
            color: '#e2e8f0',
            marginBottom: '16px',
            marginTop: 0,
            lineHeight: '1.2'
          }}>
            Floor Pov
          </h1>
          <p style={{
            fontSize: '18px',
            color: '#94a3b8',
            maxWidth: '600px',
            margin: '0 auto',
            lineHeight: '1.6'
          }}>
            Track and analyze raid deaths from WarcraftLogs
          </p>
        </div>

        {/* Big Buttons */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '24px',
          marginBottom: '40px'
        }}>
          {/* Run Analysis Button */}
          <button
            onClick={onRunAnalysis}
            style={{
              background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
              border: '2px solid #3b82f6',
              borderRadius: '12px',
              padding: '48px 32px',
              cursor: 'pointer',
              transition: 'all 0.3s ease',
              position: 'relative',
              overflow: 'hidden'
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.transform = 'translateY(-4px)';
              e.currentTarget.style.boxShadow = '0 12px 40px rgba(59, 130, 246, 0.4)';
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = 'none';
            }}
          >
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '16px'
            }}>
              <div style={{
                width: '64px',
                height: '64px',
                background: 'rgba(255, 255, 255, 0.15)',
                borderRadius: '16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <Play size={32} style={{ color: '#fff' }} />
              </div>
              <div>
                <h3 style={{
                  fontSize: '24px',
                  fontWeight: '700',
                  color: '#fff',
                  marginBottom: '8px',
                  marginTop: 0
                }}>
                  Run Analysis
                </h3>
                <p style={{
                  fontSize: '14px',
                  color: 'rgba(255, 255, 255, 0.9)',
                  margin: 0,
                  lineHeight: '1.5'
                }}>
                  Analyze a guild's raid deaths
                </p>
              </div>
            </div>
          </button>

          {/* Saved Reports Button */}
          <button
            onClick={onSavedReports}
            style={{
              background: '#1a1f2e',
              border: '2px solid #2d3748',
              borderRadius: '12px',
              padding: '48px 32px',
              cursor: 'pointer',
              transition: 'all 0.3s ease',
              position: 'relative',
              overflow: 'hidden'
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.transform = 'translateY(-4px)';
              e.currentTarget.style.border = '2px solid #3b82f6';
              e.currentTarget.style.boxShadow = '0 12px 40px rgba(59, 130, 246, 0.2)';
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.border = '2px solid #2d3748';
              e.currentTarget.style.boxShadow = 'none';
            }}
          >
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '16px'
            }}>
              <div style={{
                width: '64px',
                height: '64px',
                background: 'rgba(59, 130, 246, 0.15)',
                borderRadius: '16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <FolderOpen size={32} style={{ color: '#3b82f6' }} />
              </div>
              <div>
                <h3 style={{
                  fontSize: '24px',
                  fontWeight: '700',
                  color: '#e2e8f0',
                  marginBottom: '8px',
                  marginTop: 0
                }}>
                  Saved Reports
                </h3>
                <p style={{
                  fontSize: '14px',
                  color: '#94a3b8',
                  margin: 0,
                  lineHeight: '1.5'
                }}>
                  View and manage your previously analyzed reports
                </p>
              </div>
            </div>
          </button>
        </div>

        {/* Feature Highlights */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '20px',
          marginTop: '60px'
        }}>
          <div style={{
            padding: '20px',
            background: '#1a1f2e',
            borderRadius: '8px',
            border: '1px solid #2d3748'
          }}>
            <h4 style={{
              color: '#3b82f6',
              fontSize: '14px',
              fontWeight: '600',
              marginTop: 0,
              marginBottom: '8px',
              textTransform: 'uppercase',
              letterSpacing: '0.05em'
            }}>
              Real-time Tracking
            </h4>
            <p style={{
              color: '#94a3b8',
              fontSize: '13px',
              margin: 0,
              lineHeight: '1.5'
            }}>
              Live progress updates during analysis
            </p>
          </div>

          <div style={{
            padding: '20px',
            background: '#1a1f2e',
            borderRadius: '8px',
            border: '1px solid #2d3748'
          }}>
            <h4 style={{
              color: '#3b82f6',
              fontSize: '14px',
              fontWeight: '600',
              marginTop: 0,
              marginBottom: '8px',
              textTransform: 'uppercase',
              letterSpacing: '0.05em'
            }}>
              Smart Filtering
            </h4>
            <p style={{
              color: '#94a3b8',
              fontSize: '13px',
              margin: 0,
              lineHeight: '1.5'
            }}>
              Filter by boss, difficulty, and more
            </p>
          </div>

          <div style={{
            padding: '20px',
            background: '#1a1f2e',
            borderRadius: '8px',
            border: '1px solid #2d3748'
          }}>
            <h4 style={{
              color: '#3b82f6',
              fontSize: '14px',
              fontWeight: '600',
              marginTop: 0,
              marginBottom: '8px',
              textTransform: 'uppercase',
              letterSpacing: '0.05em'
            }}>
              Share Results
            </h4>
            <p style={{
              color: '#94a3b8',
              fontSize: '13px',
              margin: 0,
              lineHeight: '1.5'
            }}>
              Share analysis with your guild
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}