import React, { useState } from 'react';
import { X, Save } from 'lucide-react';
import { apiFetch, stripSecrets } from './api';

/* Save the current analysis to the signed-in user's account (max 5,
   enforced by the server). */
export default function SaveReportDialog({ analysisData, config, onClose, onSaved, onViewSaved }) {
  const [name, setName] = useState(
    `${analysisData.meta?.guild_name || config?.guildName || 'Report'} · ${new Date().toLocaleDateString()}`
  );
  const [retentionDays, setRetentionDays] = useState(30);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [atLimit, setAtLimit] = useState(false);

  const handleSave = async (e) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Please enter a report name');
      return;
    }
    setSaving(true);
    setError('');
    const { ok, status, body } = await apiFetch('/api/saved', {
      method: 'POST',
      auth: true,
      body: { name: name.trim(), data: analysisData, config: stripSecrets(config), retentionDays },
    });
    setSaving(false);
    if (ok) {
      onSaved?.();
      return;
    }
    setAtLimit(status === 409);
    setError(body.error || 'Failed to save report');
  };

  return (
    <div className="fpx-mov" onClick={onClose}>
      <div className="fpx-mcard" onClick={(e) => e.stopPropagation()}>
        <div className="fpx-mhead">
          <h2>Save report</h2>
          <button className="fpx-mclose" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="fpx-mbody">
          <p className="lead">Keep this analysis on your account. You can hold up to 5 saved reports at a time.</p>
          <form className="fpx-mform" onSubmit={handleSave}>
            <div className="f">
              <label htmlFor="save-name">Report name</label>
              <input id="save-name" type="text" value={name} maxLength={100}
                onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="f">
              <label htmlFor="save-keep">Keep for</label>
              <select id="save-keep" value={retentionDays} onChange={(e) => setRetentionDays(Number(e.target.value))}>
                <option value={7}>7 days</option>
                <option value={14}>14 days</option>
                <option value={30}>30 days</option>
              </select>
            </div>
            {error && (
              <p className="fpx-mmsg err">
                {error}{' '}
                {atLimit && <button type="button" className="fpx-link" onClick={onViewSaved}>Manage saved reports</button>}
              </p>
            )}
            <button type="submit" className="fpx-btn" disabled={saving} style={{ opacity: saving ? 0.7 : 1 }}>
              <Save size={16} /> {saving ? 'Saving…' : 'Save report'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
