import React from 'react';

interface ErrorStateProps {
  /** Short headline describing what failed (e.g. "Failed to fetch metrics"). */
  title?: string;
  /** Optional detail / suggestion (e.g. "Check TWS connection"). */
  detail?: React.ReactNode;
  /** Optional retry handler — when provided, renders a Retry button. */
  onRetry?: () => void;
  /** Small icon or emoji to show above the title. Defaults to a warning glyph. */
  glyph?: React.ReactNode;
}

/**
 * Consistent error placeholder for panels that couldn't load.
 * Use as a replacement for "no data" empty states when the failure cause is known.
 */
export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Something went wrong',
  detail,
  onRetry,
  glyph = '⚠️',
}) => (
  <div
    className="panel"
    style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '10px',
      color: 'var(--text-muted)',
      padding: '32px 16px',
      textAlign: 'center',
      minHeight: '160px',
    }}
  >
    <div style={{ fontSize: '28px', lineHeight: 1 }} aria-hidden="true">
      {glyph}
    </div>
    <div style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: '13px' }}>
      {title}
    </div>
    {detail && (
      <div style={{ fontSize: '11px', maxWidth: '320px', lineHeight: 1.5 }}>
        {detail}
      </div>
    )}
    {onRetry && (
      <button
        type="button"
        onClick={onRetry}
        style={{
          marginTop: '6px',
          padding: '6px 14px',
          borderRadius: '4px',
          fontSize: '11px',
          fontWeight: 700,
          letterSpacing: '0.04em',
          border: '1px solid var(--accent-spot)',
          background: 'transparent',
          color: 'var(--accent-spot)',
          cursor: 'pointer',
        }}
      >
        ↻ Retry
      </button>
    )}
  </div>
);
