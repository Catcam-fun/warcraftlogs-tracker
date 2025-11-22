import React, { useState } from 'react';
import { X, Save } from 'lucide-react';

export default function SaveReportDialog({ analysisData, user, onClose, onSaved }) {
  const [name, setName] = useState(`${analysisData.meta?.guild_name || 'Report'} - ${new Date().toLocaleDateString()}`);
  const [retentionDays, setRetentionDays] = useState(7);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Automatically detect if running locally or in production
  const API_BASE = window.location.hostname === 'localhost' 
    ? 'http://localhost:5000' 
    : 'https://floorpov-backend.onrender.com';

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Please enter a report name');
      return;
    }

    setSaving(true);
    setError('');

    try {
      const response = await fetch(`${API_BASE}/api/save-analysis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: user.id,
          analysis_name: name.trim(),
          analysis_data: analysisData,
          retention_days: retentionDays
        })
      });

      const data = await response.json();

      if (response.ok) {
        const compressionRatio = ((1 - data.compressed_size / data.original_size) * 100).toFixed(1);
        alert(`Report saved! Compressed to ${compressionRatio}% of original size.`);
        if (onSaved) onSaved();
        onClose();
      } else {
        setError(data.error || 'Failed to save report');
      }
    } catch (err) {
      setError('Network error. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.85)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999
    }}>
      <div style={{
        maxWidth: '480px',
        width: '90%',
        padding: '32px',
        border: '1px solid #3b82f6',
        borderRadius: '12px',
        backgroundColor: '#1a1a2e',
        position: 'relative'
      }}>
        <button
          onClick={onClose}
          style={{
            position: 'absolute',
            top: '12px',
            right: '12px',
            background: 'transparent',
            border: 'none',
            color: '#94a3b8',
            cursor: 'pointer',
            padding: '4px'
          }}
        >
          <X size={20} />
        </button>

        <h2 style={{
          color: '#3b82f6',
          textAlign: 'center',
          marginBottom: '24px',
          marginTop: 0,
          fontSize: '24px'
        }}>
          Save Report
        </h2>

        <div style={{ marginBottom: '20px' }}>
          <label style={{
            display: 'block',
            marginBottom: '8px',
            color: '#e2e8f0',
            fontSize: '14px',
            fontWeight: '500'
          }}>
            Report Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: '6px',
              border: '1px solid #475569',
              backgroundColor: '#0f1419',
              color: '#fff',
              fontSize: '14px',
              boxSizing: 'border-box'
            }}
          />
        </div>

        <div style={{ marginBottom: '20px' }}>
          <label style={{
            display: 'block',
            marginBottom: '8px',
            color: '#e2e8f0',
            fontSize: '14px',
            fontWeight: '500'
          }}>
            Keep for
          </label>
          <select
            value={retentionDays}
            onChange={(e) => setRetentionDays(Number(e.target.value))}
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: '6px',
              border: '1px solid #475569',
              backgroundColor: '#0f1419',
              color: '#fff',
              fontSize: '14px',
              boxSizing: 'border-box',
              cursor: 'pointer'
            }}
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
        </div>

        {error && (
          <div style={{
            padding: '12px',
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#ef4444',
            borderRadius: '6px',
            marginBottom: '20px',
            fontSize: '13px'
          }}>
            {error}
          </div>
        )}

        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            width: '100%',
            padding: '12px',
            backgroundColor: saving ? '#1e40af' : '#3b82f6',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: saving ? 'not-allowed' : 'pointer',
            fontSize: '15px',
            fontWeight: '600',
            opacity: saving ? 0.7 : 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            boxSizing: 'border-box'
          }}
        >
          <Save size={16} />
          {saving ? 'Saving...' : 'Save Report'}
        </button>

        <p style={{
          marginTop: '16px',
          fontSize: '12px',
          color: '#64748b',
          textAlign: 'center',
          margin: '16px 0 0 0'
        }}>
          You can save up to 10 reports. Older reports will expire after the selected time period.
        </p>
      </div>
    </div>
  );
}