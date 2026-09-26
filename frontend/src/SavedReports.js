import React, { useState, useEffect, useCallback } from 'react';
import { Bookmark, LogIn, Trash2, Loader2 } from 'lucide-react';
import { apiFetch } from './api';

const fmtDate = (d) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
const daysLeft = (d) => Math.max(0, Math.ceil((new Date(d) - Date.now()) / 86400000));
const fmtSize = (b) => (b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} KB` : `${(b / 1048576).toFixed(1)} MB`);

/* The signed-in user's saved analyses (max 5, stored server-side). */
export default function SavedReports({ user, onLoadReport, onSignIn }) {
  const [reports, setReports] = useState([]);
  const [limit, setLimit] = useState(5);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState('');

  const fetchReports = useCallback(async () => {
    setLoading(true);
    setError('');
    const { ok, body } = await apiFetch('/api/saved', { auth: true });
    setLoading(false);
    if (!ok) {
      setError(body.error || 'Could not load saved reports.');
      return;
    }
    setReports(body.analyses || []);
    if (body.limit) setLimit(body.limit);
  }, []);

  useEffect(() => {
    if (user) fetchReports();
    else setReports([]);
  }, [user, fetchReports]);

  const openReport = async (report) => {
    setBusyId(report.id);
    setError('');
    const { ok, body } = await apiFetch(`/api/saved/${report.id}`, { auth: true });
    setBusyId(null);
    if (!ok) {
      setError(body.error || 'Could not open that report.');
      return;
    }
    onLoadReport(body);
  };

  const deleteReport = async (report) => {
    if (!window.confirm(`Delete "${report.analysis_name}"?`)) return;
    setBusyId(report.id);
    const { ok, body } = await apiFetch(`/api/saved/${report.id}`, { method: 'DELETE', auth: true });
    setBusyId(null);
    if (!ok) {
      setError(body.error || 'Could not delete that report.');
      return;
    }
    setReports((rs) => rs.filter((r) => r.id !== report.id));
  };

  if (!user) {
    return (
      <div className="fpx-results-empty fpx-rv" style={{ minHeight: '64vh' }}>
        <Bookmark size={34} />
        <p>Sign in to keep up to {limit} analyses on your account and reopen them from any device.</p>
        <button className="fpx-btn" onClick={onSignIn}><LogIn size={17} /> Sign in</button>
      </div>
    );
  }

  return (
    <div className="fpx-results-empty fpx-rv" style={{ minHeight: '64vh', justifyContent: 'flex-start' }}>
      <Bookmark size={34} />
      <p>
        {loading
          ? 'Loading saved reports…'
          : reports.length
            ? `${reports.length} of ${limit} saved. Use Save on any results page to keep another.`
            : `No saved reports yet. Use Save on a results page to keep up to ${limit}.`}
      </p>
      {error && <p className="fpx-mmsg err">{error}</p>}
      {reports.length > 0 && (
        <div className="fpx-recentlist">
          <div className="fpx-recentlist-h">SAVED REPORTS · {reports.length} / {limit}</div>
          {reports.map((r) => (
            <div key={r.id} className="fpx-recent-card">
              <button className="open" onClick={() => openReport(r)} disabled={busyId === r.id}>
                <span className="t">
                  {busyId === r.id && <Loader2 size={13} className="fpx-spin" />} {r.analysis_name}
                </span>
                <span className="s">{r.guild_name}</span>
                <span className="d">
                  Saved {fmtDate(r.created_at)} · expires in {daysLeft(r.expires_at)}d · {fmtSize(r.size_bytes || 0)}
                </span>
              </button>
              <button className="rm" onClick={() => deleteReport(r)} disabled={busyId === r.id} title="Delete saved report">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
