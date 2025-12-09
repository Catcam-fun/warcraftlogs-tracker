import React from 'react';
import { Play, FolderOpen, CheckCircle, BarChart3, Shield } from 'lucide-react';

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
          gridTemplateColumns: onSavedReports ? 'repeat(auto-fit, minmax(280px, 1fr))' : '1fr',
          gap: '24px',
          marginBottom: '40px',
          maxWidth: onSavedReports ? '800px' : '400px',
          margin: '0 auto'
        }}>
          <button
            onClick={onRunAnalysis}
            style={{
              padding: '24px 32px',
              background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
              color: '#ffffff',
              border: 'none',
              borderRadius: '12px',
              cursor: 'pointer',
              fontSize: '16px',
              fontWeight: '600',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '12px',
              transition: 'all 0.2s',
              boxShadow: '0 4px 12px rgba(59, 130, 246, 0.3)'
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.boxShadow = '0 6px 16px rgba(59, 130, 246, 0.4)';
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 4px 12px rgba(59, 130, 246, 0.3)';
            }}
          >
            <Play size={28} />
            <div>
              <div style={{ fontSize: '18px', marginBottom: '4px' }}>Run Analysis</div>
              <div style={{ fontSize: '13px', opacity: 0.9, fontWeight: '400' }}>Analyze your guild's deaths</div>
            </div>
          </button>

          {onSavedReports && (
            <button
              onClick={onSavedReports}
              style={{
                padding: '24px 32px',
                background: '#1e293b',
                color: '#e2e8f0',
                border: '1px solid #334155',
                borderRadius: '12px',
                cursor: 'pointer',
                fontSize: '16px',
                fontWeight: '600',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12px',
                transition: 'all 0.2s'
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.background = '#2d3748';
                e.currentTarget.style.transform = 'translateY(-2px)';
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.background = '#1e293b';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
            >
              <FolderOpen size={28} />
              <div>
                <div style={{ fontSize: '18px', marginBottom: '4px' }}>Saved Reports</div>
                <div style={{ fontSize: '13px', opacity: 0.7, fontWeight: '400' }}>View saved analyses</div>
              </div>
            </button>
          )}
        </div>

        {/* Features Grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
          gap: '24px',
          marginTop: '60px',
          textAlign: 'left'
        }}>
          <div style={{
            padding: '24px',
            background: '#1a1f2e',
            borderRadius: '12px',
            border: '1px solid #2d3748'
          }}>
            <CheckCircle size={32} style={{ color: '#10b981', marginBottom: '12px' }} />
            <h3 style={{
              color: '#e2e8f0',
              fontSize: '16px',
              fontWeight: '600',
              margin: '0 0 8px 0'
            }}>
              Smart Filtering
            </h3>
            <p style={{
              color: '#94a3b8',
              fontSize: '14px',
              margin: 0,
              lineHeight: '1.5'
            }}>
              Track first X deaths per pull, excluding wipe cascades
            </p>
          </div>

          <div style={{
            padding: '24px',
            background: '#1a1f2e',
            borderRadius: '12px',
            border: '1px solid #2d3748'
          }}>
            <BarChart3 size={32} style={{ color: '#f59e0b', marginBottom: '12px' }} />
            <h3 style={{
              color: '#e2e8f0',
              fontSize: '16px',
              fontWeight: '600',
              margin: '0 0 8px 0'
            }}>
              Detailed Metrics
            </h3>
            <p style={{
              color: '#94a3b8',
              fontSize: '14px',
              margin: 0,
              lineHeight: '1.5'
            }}>
              Per-player, per-boss, and overall statistics
            </p>
          </div>

          <div style={{
            padding: '24px',
            background: '#1a1f2e',
            borderRadius: '12px',
            border: '1px solid #2d3748'
          }}>
            <Shield size={32} style={{ color: '#8b5cf6', marginBottom: '12px' }} />
            <h3 style={{
              color: '#e2e8f0',
              fontSize: '16px',
              fontWeight: '600',
              margin: '0 0 8px 0'
            }}>
              Shareable Results
            </h3>
            <p style={{
              color: '#94a3b8',
              fontSize: '14px',
              margin: 0,
              lineHeight: '1.5'
            }}>
              Share analysis with your guild
            </p>
          </div>
        </div>


        {/* Recent Updates Section */}
        <div style={{
          marginTop: '80px',
          paddingTop: '60px',
          borderTop: '1px solid #2d3748'
        }}>
          <h2 style={{
            fontSize: '32px',
            fontWeight: '700',
            color: '#e2e8f0',
            marginBottom: '16px',
            marginTop: 0
          }}>
            Recent Updates
          </h2>
          <p style={{
            fontSize: '16px',
            color: '#94a3b8',
            marginBottom: '32px'
          }}>
            Latest improvements to Floor Pov
          </p>

          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
            maxWidth: '700px',
            margin: '0 auto',
            textAlign: 'left'
          }}>
            {/* Update Item - Cheat Death Optimization */}
            <div style={{
              padding: '20px',
              background: '#1a1f2e',
              borderRadius: '8px',
              border: '1px solid #2d3748',
              borderLeft: '4px solid #10b981'
            }}>
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                marginBottom: '8px'
              }}>
                <h3 style={{
                  color: '#e2e8f0',
                  fontSize: '16px',
                  fontWeight: '600',
                  margin: 0
                }}>
                  Optimized Cheat Death Detection
                </h3>
                <span style={{
                  fontSize: '13px',
                  color: '#64748b',
                  whiteSpace: 'nowrap',
                  marginLeft: '16px'
                }}>
                  Dec 8
                </span>
              </div>
              <p style={{
                color: '#94a3b8',
                fontSize: '14px',
                margin: 0,
                lineHeight: '1.6'
              }}>
                Cheat death detection now available for logged-in users with improved deduplication logic.
              </p>
            </div>

            {/* Update Item - Additional Raids */}
            <div style={{
              padding: '20px',
              background: '#1a1f2e',
              borderRadius: '8px',
              border: '1px solid #2d3748',
              borderLeft: '4px solid #3b82f6'
            }}>
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                marginBottom: '8px'
              }}>
                <h3 style={{
                  color: '#e2e8f0',
                  fontSize: '16px',
                  fontWeight: '600',
                  margin: 0
                }}>
                  Added Support for Additional Raids
                </h3>
                <span style={{
                  fontSize: '13px',
                  color: '#64748b',
                  whiteSpace: 'nowrap',
                  marginLeft: '16px'
                }}>
                  Nov 20
                </span>
              </div>
              <p style={{
                color: '#94a3b8',
                fontSize: '14px',
                margin: 0,
                lineHeight: '1.6'
              }}>
                Floor Pov now supports death tracking across all The War Within raids.
              </p>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}