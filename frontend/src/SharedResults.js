import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { AlertCircle, Loader2, ArrowLeft } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

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
      <div className="fp-shared-results shared-results-shell" style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}>
        <div style={{ textAlign: 'center' }}>
          <Loader2
            size={48}
            style={{
              color: 'var(--color-gold-2)',
              animation: 'spin 1s linear infinite',
              marginBottom: '16px'
            }}
          />
          <p style={{ color: 'var(--color-muted)', fontSize: '16px' }}>
            Loading shared analysis...
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="fp-shared-results shared-results-shell" style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px'
      }}>
        <div className="surface-panel" style={{
          maxWidth: '500px',
          width: '100%',
          borderColor: 'rgba(255, 93, 102, 0.4)',
          padding: '32px',
          textAlign: 'center'
        }}>
          <AlertCircle size={48} style={{ color: 'var(--color-red)', marginBottom: '16px' }} />
          <h2 style={{
            fontSize: '24px',
            marginBottom: '12px',
            marginTop: 0
          }}>
            Analysis Not Found
          </h2>
          <p style={{ color: 'var(--color-muted)', fontSize: '14px', marginBottom: '24px' }}>
            {error}
          </p>
          <button
            onClick={() => navigate('/')}
            className="btn btn-primary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
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

  const { data, config, timestamp } = sharedData;
  const playerCount = Object.keys(data?.events || {}).length;
  const totalDeaths = Object.values(data?.events || {}).reduce((sum, events) => sum + events.length, 0);
  const bossDeaths = Object.entries(data?.events || {}).reduce((acc, [, events]) => {
    events.forEach(event => {
      const boss = event.boss || 'Unknown';
      acc[boss] = (acc[boss] || 0) + 1;
    });
    return acc;
  }, {});
  const bossChartData = Object.entries(bossDeaths)
    .map(([boss, deaths]) => ({ boss, deaths }))
    .sort((a, b) => b.deaths - a.deaths)
    .slice(0, 8);
  const tooltipProps = {
    contentStyle: {
      background: '#090d15',
      border: '1px solid rgba(215, 180, 90, 0.32)',
      borderRadius: '8px',
      color: 'var(--color-text)'
    },
    labelStyle: { color: 'var(--color-gold-2)' }
  };

  return (
    <div className="fp-shared-results shared-results-shell" style={{
      minHeight: '100vh',
      padding: '40px 20px'
    }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
        {/* Header */}
        <div className="surface-panel" style={{ padding: '24px', marginBottom: '24px' }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: '16px'
          }}>
            <div>
              <h1 style={{
                fontSize: '28px',
                marginBottom: '8px',
                marginTop: 0
              }}>
                Shared Analysis
              </h1>
              <p style={{ color: 'var(--color-muted)', fontSize: '14px', margin: 0 }}>
                {config?.guildName || 'Unknown Guild'} — {config?.server || 'Unknown Server'} ({config?.region?.toUpperCase() || 'US'})
              </p>
            </div>
            <button
              onClick={() => navigate('/')}
              className="btn"
              style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}
            >
              <ArrowLeft size={16} />
              Back to App
            </button>
          </div>

          <div className="stat-grid" style={{ padding: '16px', background: 'rgba(9, 13, 21, 0.72)', borderRadius: 'var(--radius-md)' }}>
            <div>
              <p className="stat-label">Shared On</p>
              <p className="stat-value" style={{ fontSize: '15px' }}>
                {timestamp ? new Date(timestamp).toLocaleDateString() : 'Unknown'}
              </p>
            </div>
            <div>
              <p className="stat-label">Raid</p>
              <p className="stat-value" style={{ fontSize: '15px' }}>{config?.selectedRaid || 'Unknown'}</p>
            </div>
            <div>
              <p className="stat-label">Difficulty</p>
              <p className="stat-value" style={{ fontSize: '15px' }}>
                {config?.difficulty === '5' ? 'Mythic' :
                 config?.difficulty === '4' ? 'Heroic' :
                 config?.difficulty === '3' ? 'Normal' : 'Unknown'}
              </p>
            </div>
          </div>
        </div>

        {/* Open in app */}
        <div className="surface-panel" style={{ padding: '32px', textAlign: 'center', marginBottom: '24px' }}>
          <h2 style={{ fontSize: '20px', marginBottom: '16px', marginTop: 0 }}>
            View Full Analysis
          </h2>
          <p style={{
            color: 'var(--color-muted)',
            fontSize: '14px',
            marginBottom: '24px',
            maxWidth: '600px',
            margin: '0 auto 24px'
          }}>
            To view and interact with the full death analysis, click the button below to open the
            interactive analyzer with this shared data pre-loaded.
          </p>
          <button
            onClick={async () => {
              try {
                const saveToIndexedDB = (key, value) => {
                  return new Promise((resolve, reject) => {
                    const request = indexedDB.open('FloorPovDB', 1);

                    request.onerror = () => reject(request.error);

                    request.onupgradeneeded = (event) => {
                      const db = event.target.result;
                      if (!db.objectStoreNames.contains('analysisData')) {
                        db.createObjectStore('analysisData');
                      }
                    };

                    request.onsuccess = (event) => {
                      const db = event.target.result;
                      const transaction = db.transaction(['analysisData'], 'readwrite');
                      const store = transaction.objectStore('analysisData');
                      const putRequest = store.put(value, key);

                      putRequest.onsuccess = () => {
                        db.close();
                        resolve();
                      };

                      putRequest.onerror = () => {
                        db.close();
                        reject(putRequest.error);
                      };
                    };
                  });
                };

                await saveToIndexedDB('sharedAnalysisData', sharedData);
                navigate('/?loadShared=true');
              } catch (err) {
                console.error('Error saving to IndexedDB:', err);
                navigate('/?loadShared=true');
              }
            }}
            className="btn btn-primary"
            style={{ fontSize: '15px', padding: '12px 32px' }}
          >
            Open Interactive Analysis
          </button>
        </div>

        {/* Charts + quick stats */}
        {data && (
          <>
            <div className="chart-panel" style={{ marginBottom: '24px' }}>
              <h3 className="chart-title">Shared Death Distribution</h3>
              {bossChartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={bossChartData} margin={{ top: 8, right: 12, left: -18, bottom: 48 }}>
                    <CartesianGrid stroke="rgba(147, 165, 196, 0.14)" vertical={false} />
                    <XAxis dataKey="boss" angle={-28} textAnchor="end" interval={0} height={70} />
                    <YAxis allowDecimals={false} />
                    <Tooltip {...tooltipProps} />
                    <Bar dataKey="deaths" name="Deaths" fill="var(--chart-2)" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="chart-empty">No boss death data is available in this shared result.</div>
              )}
            </div>

            <div className="surface-panel" style={{ padding: '24px' }}>
              <h3 style={{ fontSize: '18px', marginBottom: '16px', marginTop: 0 }}>Quick Stats</h3>
              <div className="stat-grid">
                <div className="stat-tile" style={{ textAlign: 'center' }}>
                  <p className="stat-label">Total Players</p>
                  <p className="stat-value" style={{ color: 'var(--color-blue)' }}>{playerCount}</p>
                </div>
                <div className="stat-tile" style={{ textAlign: 'center' }}>
                  <p className="stat-label">Total Deaths</p>
                  <p className="stat-value" style={{ color: 'var(--color-red)' }}>{totalDeaths}</p>
                </div>
              </div>
            </div>
          </>
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
