import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { AlertCircle, Loader2, ArrowLeft } from 'lucide-react';

// Automatically detect if running locally or in production
const API_URL = window.location.hostname === 'localhost' 
  ? 'http://localhost:5000' 
  : 'https://deathwarcraftlogs-api.onrender.com';

export default function SharedResults() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const shareId = searchParams.get('share');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sharedData, setSharedData] = useState(null);

  useEffect(() => {
    if (!shareId) {
      setError('No share ID provided');
      setLoading(false);
      return;
    }

    loadSharedResults();
  }, [shareId]);

  const loadSharedResults = async () => {
    try {
      setLoading(true);
      setError('');

      const response = await fetch(`${API_URL}/api/shared/${shareId}`);
      const result = await response.json();

      if (!result.success) {
        throw new Error(result.error || 'Failed to load shared results');
      }

      setSharedData(result);
      setLoading(false);
    } catch (err) {
      console.error('Error loading shared results:', err);
      setError(err.message);
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{
        minHeight: '100vh',
        background: '#0f1419',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}>
        <div style={{ textAlign: 'center' }}>
          <Loader2 
            size={48} 
            style={{ 
              color: '#3b82f6', 
              animation: 'spin 1s linear infinite',
              marginBottom: '16px'
            }} 
          />
          <p style={{ color: '#94a3b8', fontSize: '16px' }}>
            Loading shared analysis...
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        minHeight: '100vh',
        background: '#0f1419',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px'
      }}>
        <div style={{
          maxWidth: '500px',
          width: '100%',
          background: '#1a1f2e',
          border: '1px solid #dc2626',
          borderRadius: '12px',
          padding: '32px',
          textAlign: 'center'
        }}>
          <AlertCircle size={48} style={{ color: '#dc2626', marginBottom: '16px' }} />
          <h2 style={{ 
            color: '#e2e8f0', 
            fontSize: '24px', 
            marginBottom: '12px',
            marginTop: 0
          }}>
            Analysis Not Found
          </h2>
          <p style={{ color: '#94a3b8', fontSize: '14px', marginBottom: '24px' }}>
            {error}
          </p>
          <button
            onClick={() => navigate('/')}
            style={{
              padding: '12px 24px',
              background: '#3b82f6',
              border: 'none',
              borderRadius: '6px',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '600',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <ArrowLeft size={16} />
            Go Home
          </button>
        </div>
      </div>
    );
  }

  if (!sharedData) {
    return null;
  }

  // Extract data and config from shared results
  const { data, config, timestamp } = sharedData;

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0f1419',
      padding: '40px 20px'
    }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
        {/* Header */}
        <div style={{
          background: '#1a1f2e',
          border: '1px solid #2d3748',
          borderRadius: '12px',
          padding: '24px',
          marginBottom: '24px'
        }}>
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'flex-start',
            marginBottom: '16px'
          }}>
            <div>
              <h1 style={{ 
                color: '#e2e8f0', 
                fontSize: '28px', 
                marginBottom: '8px',
                marginTop: 0
              }}>
                Shared Analysis
              </h1>
              <p style={{ 
                color: '#94a3b8', 
                fontSize: '14px', 
                margin: 0 
              }}>
                {config?.guildName || 'Unknown Guild'} - {config?.server || 'Unknown Server'} ({config?.region?.toUpperCase() || 'US'})
              </p>
            </div>
            <button
              onClick={() => navigate('/')}
              style={{
                padding: '8px 16px',
                background: '#334155',
                border: '1px solid #475569',
                borderRadius: '6px',
                color: '#e2e8f0',
                cursor: 'pointer',
                fontSize: '13px',
                fontWeight: '600',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <ArrowLeft size={16} />
              Back to App
            </button>
          </div>
          
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '16px',
            padding: '16px',
            background: '#0f1419',
            borderRadius: '8px'
          }}>
            <div>
              <p style={{ 
                color: '#64748b', 
                fontSize: '12px', 
                marginBottom: '4px',
                marginTop: 0
              }}>
                Shared On
              </p>
              <p style={{ 
                color: '#e2e8f0', 
                fontSize: '14px', 
                fontWeight: '600',
                margin: 0
              }}>
                {timestamp ? new Date(timestamp).toLocaleDateString() : 'Unknown'}
              </p>
            </div>
            <div>
              <p style={{ 
                color: '#64748b', 
                fontSize: '12px', 
                marginBottom: '4px',
                marginTop: 0
              }}>
                Raid
              </p>
              <p style={{ 
                color: '#e2e8f0', 
                fontSize: '14px', 
                fontWeight: '600',
                margin: 0
              }}>
                {config?.selectedRaid || 'Unknown'}
              </p>
            </div>
            <div>
              <p style={{ 
                color: '#64748b', 
                fontSize: '12px', 
                marginBottom: '4px',
                marginTop: 0
              }}>
                Difficulty
              </p>
              <p style={{ 
                color: '#e2e8f0', 
                fontSize: '14px', 
                fontWeight: '600',
                margin: 0
              }}>
                {config?.difficulty === '5' ? 'Mythic' : 
                 config?.difficulty === '4' ? 'Heroic' : 
                 config?.difficulty === '3' ? 'Normal' : 'Unknown'}
              </p>
            </div>
          </div>
        </div>

        {/* Analysis Results Info */}
        <div style={{
          background: '#1a1f2e',
          border: '1px solid #2d3748',
          borderRadius: '12px',
          padding: '32px',
          textAlign: 'center'
        }}>
          <h2 style={{ 
            color: '#3b82f6', 
            fontSize: '20px', 
            marginBottom: '16px',
            marginTop: 0
          }}>
            View Full Analysis
          </h2>
          <p style={{ 
            color: '#94a3b8', 
            fontSize: '14px', 
            marginBottom: '24px',
            maxWidth: '600px',
            margin: '0 auto 24px'
          }}>
            To view and interact with the full death analysis, click the button below to open the 
            interactive analyzer with this shared data pre-loaded.
          </p>
          <button
            onClick={() => {
              // Store the shared data in sessionStorage and navigate to main app
              sessionStorage.setItem('sharedAnalysisData', JSON.stringify(sharedData));
              navigate('/?loadShared=true');
            }}
            style={{
              padding: '12px 32px',
              background: '#3b82f6',
              border: 'none',
              borderRadius: '6px',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '15px',
              fontWeight: '600',
              transition: 'background 0.2s'
            }}
            onMouseOver={(e) => e.target.style.background = '#2563eb'}
            onMouseOut={(e) => e.target.style.background = '#3b82f6'}
          >
            Open Interactive Analysis
          </button>
        </div>

        {/* Basic Stats Preview */}
        {data && (
          <div style={{
            marginTop: '24px',
            background: '#1a1f2e',
            border: '1px solid #2d3748',
            borderRadius: '12px',
            padding: '24px'
          }}>
            <h3 style={{ 
              color: '#e2e8f0', 
              fontSize: '18px', 
              marginBottom: '16px',
              marginTop: 0
            }}>
              Quick Stats
            </h3>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: '16px'
            }}>
              <div style={{
                background: '#0f1419',
                padding: '16px',
                borderRadius: '8px',
                textAlign: 'center'
              }}>
                <p style={{ 
                  color: '#64748b', 
                  fontSize: '12px', 
                  marginBottom: '4px',
                  marginTop: 0
                }}>
                  Total Players
                </p>
                <p style={{ 
                  color: '#3b82f6', 
                  fontSize: '24px', 
                  fontWeight: '700',
                  margin: 0
                }}>
                  {Object.keys(data.events || {}).length}
                </p>
              </div>
              <div style={{
                background: '#0f1419',
                padding: '16px',
                borderRadius: '8px',
                textAlign: 'center'
              }}>
                <p style={{ 
                  color: '#64748b', 
                  fontSize: '12px', 
                  marginBottom: '4px',
                  marginTop: 0
                }}>
                  Total Deaths
                </p>
                <p style={{ 
                  color: '#dc2626', 
                  fontSize: '24px', 
                  fontWeight: '700',
                  margin: 0
                }}>
                  {Object.values(data.events || {}).reduce((sum, events) => sum + events.length, 0)}
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}