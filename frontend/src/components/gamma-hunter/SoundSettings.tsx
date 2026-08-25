import React, { useState } from 'react';
import type { SoundSettings as SoundSettingsType } from '../../hooks/useMarketData';

interface SoundSettingsProps {
  settings: SoundSettingsType;
  onChange: (s: SoundSettingsType) => void;
  /** Probe the current beep implementation (reads live from the hook). */
  onTest: () => void;
}

/**
 * Inline sound settings panel: on/off toggle, volume slider, test button.
 * Persists via the parent hook's localStorage.
 */
export const SoundSettingsPanel: React.FC<SoundSettingsProps> = ({ settings, onChange, onTest }) => {
  const [testing, setTesting] = useState(false);

  const handleTest = () => {
    setTesting(true);
    onTest();
    setTimeout(() => setTesting(false), 500);
  };

  return (
    <div
      className="panel"
      style={{ display: 'flex', flexDirection: 'column' }}
    >
      <button
        type="button"
        onClick={() => onChange({ ...settings, enabled: !settings.enabled })}
        style={{
          padding: '10px 16px',
          background: 'transparent',
          border: 'none',
          borderBottom: '1px solid var(--border-subtle)',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          width: '100%',
        }}
      >
        <span style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          🔊 Sound · {settings.enabled ? 'ON' : 'OFF'}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* Volume slider — only interactive when enabled */}
          <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: settings.enabled ? 'pointer' : 'not-allowed', opacity: settings.enabled ? 1 : 0.4 }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>🔈</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={settings.volume}
              disabled={!settings.enabled}
              onChange={e => onChange({ ...settings, volume: Number(e.target.value) })}
              onClick={e => e.stopPropagation()}
              style={{ width: '80px', accentColor: 'var(--accent-spot)' }}
            />
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>🔊</span>
          </label>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
            {testing ? '🔊 playing…' : '▶ test'}
          </span>
          <button
            type="button"
            onClick={e => { e.stopPropagation(); handleTest(); }}
            disabled={!settings.enabled}
            title="Play a test beep"
            style={{
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '10px',
              fontWeight: 700,
              border: '1px solid var(--border-subtle)',
              background: 'transparent',
              color: settings.enabled ? 'var(--text-secondary)' : 'var(--text-muted)',
              cursor: settings.enabled ? 'pointer' : 'not-allowed',
            }}
          >
            ▶
          </button>
        </div>
      </button>
    </div>
  );
};

export default SoundSettingsPanel;
