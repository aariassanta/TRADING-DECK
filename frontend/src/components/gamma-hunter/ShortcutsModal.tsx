import React, { useEffect, useState } from 'react';

interface ShortcutEntry {
  key: string;
  description: string;
}

const SHORTCUTS: ShortcutEntry[] = [
  { key: 'Space', description: 'Pause / Resume live feed' },
  { key: 'R', description: 'Refresh data immediately' },
  { key: '1', description: 'Switch to NetDrift tab' },
  { key: '2', description: 'Switch to GammaHunter tab' },
  { key: '3', description: 'Switch to BotPanel tab' },
  { key: '4', description: 'Switch to Signals tab' },
  { key: '↑ / K', description: 'Navigate to previous strike (Strike Ladder)' },
  { key: '↓ / J', description: 'Navigate to next strike (Strike Ladder)' },
  { key: 'Enter', description: 'Expand / collapse focused strike (Strike Ladder)' },
  { key: 'Esc', description: 'Close expanded strike row (Strike Ladder)' },
  { key: '?', description: 'Open / close this shortcuts cheatsheet' },
];

interface ShortcutsModalProps {
  /** Controls visibility from the parent (for the `?` key handler in App). */
  initialVisible?: boolean;
}

/**
 * Full shortcuts cheatsheet. Also subscribes to `?` key for self-toggle.
 */
export const ShortcutsModal: React.FC<ShortcutsModalProps> = ({ initialVisible = false }) => {
  const [visible, setVisible] = useState(initialVisible);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
      }
      if (e.key === '?') {
        setVisible(v => !v);
      } else if (e.key === 'Escape') {
        setVisible(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  if (!visible) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 200,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0,0,0,0.55)',
        backdropFilter: 'blur(4px)',
      }}
      onClick={e => { if (e.target === e.currentTarget) setVisible(false); }}
    >
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: '12px',
          padding: '24px 28px',
          minWidth: '340px',
          maxWidth: '460px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ margin: 0, fontSize: '14px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            ⌨ Keyboard Shortcuts
          </h2>
          <button
            type="button"
            onClick={() => setVisible(false)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              fontSize: '16px',
              padding: '2px 6px',
            }}
          >
            ✕
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {SHORTCUTS.map(({ key, description }) => (
            <div key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)', flex: 1 }}>{description}</span>
              <kbd style={{
                padding: '2px 8px',
                borderRadius: '4px',
                background: 'var(--bg-abyss)',
                border: '1px solid var(--border-subtle)',
                fontSize: '11px',
                fontFamily: 'var(--font-data, monospace)',
                color: 'var(--accent-spot)',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}>
                {key}
              </kbd>
            </div>
          ))}
        </div>
        <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--border-subtle)', fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center' }}>
          Press <kbd style={{ padding: '1px 5px', borderRadius: '3px', background: 'var(--bg-abyss)', border: '1px solid var(--border-subtle)', fontSize: '10px', fontFamily: 'var(--font-data, monospace)', color: 'var(--accent-spot)' }}>?</kbd> or <kbd style={{ padding: '1px 5px', borderRadius: '3px', background: 'var(--bg-abyss)', border: '1px solid var(--border-subtle)', fontSize: '10px', fontFamily: 'var(--font-data, monospace)', color: 'var(--accent-spot)' }}>Esc</kbd> to close
        </div>
      </div>
    </div>
  );
};

export default ShortcutsModal;
