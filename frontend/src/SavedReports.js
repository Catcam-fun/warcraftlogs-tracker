import React, { useState, useEffect } from 'react';
import { FolderOpen, Trash2, Download, Calendar, Clock } from 'lucide-react';

export default function SavedReports({ user, onLoadReport }) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingReport, setLoadingReport] = useState(null);

  // Automatically detect if running locally or in production
  const API_BASE = window.location.hostname === 'localhost' 
    ? 'http://localhost:5000' 
    : 'https://floorpov-backend.onrender.com';

  useEffect(() => {
    if (user) {
      fetchReports();
    }
  }, [user]);

  const fetchReports = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/user-analyses/${user.id}`);
      const data = await response.json();
      setReports(data);
    } catch (err) {
      console.error('Failed to fetch reports:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadReport = async (reportId) => {
    setLoadingReport(reportId);
    try {
      const response = await fetch(`${API_BASE}/api/load-analysis/${reportId}`);
      const data = await response.json();
      
      if (response.ok) {
        onLoadReport(data);
      } else {
        alert('Failed to load report');
      }
    } catch (err) {
      alert('Network error loading report');
    } finally {
      setLoadingReport(null);
    }
  };

  const handleDeleteReport = async (reportId, reportName) => {
    if (!window.confirm(`Delete "${reportName}"?`)) return;

    try {
      const response = await fetch(`${API_BASE}/api/delete-analysis/${reportId}`, {
        method: 'DELETE'
      });

      if (response.ok) {
        setReports(reports.filter(r => r.id !== reportId));
      } else {
        alert('Failed to delete report');
      }
    } catch (err) {
      alert('Network error deleting report');
    }
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const getDaysRemaining = (expiresAt) => {
    const now = new Date();
    const expires = new Date(expiresAt);
    const days = Math.ceil((expires - now) / (1000 * 60 * 60 * 24));
    return Math.max(0, days);
  };

  if (!user) {
    return (
      <div style={{
        minHeight: 'calc(100vh - 200px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '40px 20px'
      }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: '18px', color: '#94a3b8' }}>
            Please sign in to view saved reports
          </p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{
        minHeight: 'calc(100vh - 200px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '40px 20px'
      }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: '18px', color: '#94a3b8' }}>Loading reports...</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: 'calc(100vh - 200px)',
      padding: '40px 20px'
    }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
        <div style={{ marginBottom: '32px' }}>
          <h1 style={{
            fontSize: '32px',
            fontWeight: '700',
            color: '#e2e8f0',
            marginBottom: '8px',
            marginTop: 0
          }}>
            Saved Reports
          </h1>
          <p style={{ color: '#94a3b8', fontSize: '16px', margin: 0 }}>
            {reports.length} of 10 reports saved
          </p>
        </div>

        {reports.length === 0 ? (
          <div style={{
            textAlign: 'center',
            padding: '60px 20px',
            background: '#1a1f2e',
            borderRadius: '12px',
            border: '1px solid #2d3748'
          }}>
            <FolderOpen size={48} style={{ color: '#475569', marginBottom: '16px' }} />
            <p style={{ fontSize: '18px', color: '#94a3b8', margin: 0 }}>
              No saved reports yet
            </p>
            <p style={{ fontSize: '14px', color: '#64748b', marginTop: '8px' }}>
              Run an analysis and save it to see it here
            </p>
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: '20px'
          }}>
            {reports.map(report => (
              <div
                key={report.id}
                style={{
                  background: '#1a1f2e',
                  border: '1px solid #2d3748',
                  borderRadius: '12px',
                  padding: '20px',
                  transition: 'all 0.2s'
                }}
                onMouseOver={(e) => {
                  e.currentTarget.style.borderColor = '#3b82f6';
                  e.currentTarget.style.transform = 'translateY(-2px)';
                }}
                onMouseOut={(e) => {
                  e.currentTarget.style.borderColor = '#2d3748';
                  e.currentTarget.style.transform = 'translateY(0)';
                }}
              >
                <div style={{ marginBottom: '16px' }}>
                  <h3 style={{
                    fontSize: '16px',
                    fontWeight: '600',
                    color: '#e2e8f0',
                    marginBottom: '8px',
                    marginTop: 0,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap'
                  }}>
                    {report.analysis_name}
                  </h3>
                  <p style={{
                    fontSize: '14px',
                    color: '#3b82f6',
                    margin: 0
                  }}>
                    {report.guild_name}
                  </p>
                </div>

                <div style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                  marginBottom: '16px',
                  fontSize: '13px',
                  color: '#94a3b8'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Calendar size={14} />
                    <span>Saved {formatDate(report.created_at)}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Clock size={14} />
                    <span>Expires in {getDaysRemaining(report.expires_at)} days</span>
                  </div>
                  <div style={{ fontSize: '12px', color: '#64748b' }}>
                    Size: {formatSize(report.size_bytes)}
                  </div>
                </div>

                <div style={{
                  display: 'flex',
                  gap: '8px'
                }}>
                  <button
                    onClick={() => handleLoadReport(report.id)}
                    disabled={loadingReport === report.id}
                    style={{
                      flex: 1,
                      padding: '10px',
                      background: '#3b82f6',
                      border: 'none',
                      borderRadius: '6px',
                      color: '#fff',
                      cursor: loadingReport === report.id ? 'not-allowed' : 'pointer',
                      fontSize: '13px',
                      fontWeight: '600',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      opacity: loadingReport === report.id ? 0.7 : 1
                    }}
                    onMouseOver={(e) => {
                      if (loadingReport !== report.id) e.target.style.background = '#2563eb';
                    }}
                    onMouseOut={(e) => {
                      if (loadingReport !== report.id) e.target.style.background = '#3b82f6';
                    }}
                  >
                    <Download size={14} />
                    {loadingReport === report.id ? 'Loading...' : 'Load'}
                  </button>
                  <button
                    onClick={() => handleDeleteReport(report.id, report.analysis_name)}
                    style={{
                      padding: '10px',
                      background: '#1e293b',
                      border: '1px solid #475569',
                      borderRadius: '6px',
                      color: '#ef4444',
                      cursor: 'pointer',
                      fontSize: '13px',
                      fontWeight: '600',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}
                    onMouseOver={(e) => {
                      e.target.style.background = '#334155';
                    }}
                    onMouseOut={(e) => {
                      e.target.style.background = '#1e293b';
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}