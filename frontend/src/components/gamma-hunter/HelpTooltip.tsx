import React, { useState, useRef, useEffect } from 'react';
import { computeTooltipFlip } from '../../hooks/useTooltipFlip';

interface HelpTooltipProps {
  children?: React.ReactNode;
  content: string;
  /** 'hover' (default) | 'click' */
  mode?: 'hover' | 'click';
}

/**
 * Small `?` badge that shows `content` in a floating tooltip on hover (or click).
 * Tooltip dynamically flips downward if it would exceed the top viewport boundary.
 */
export const HelpTooltip: React.FC<HelpTooltipProps> = ({ children, content, mode = 'hover' }) => {
  const [visible, setVisible] = useState(false);
  const [tooltipStyle, setTooltipStyle] = useState<React.CSSProperties>({});
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!visible || mode !== 'click') return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setVisible(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [visible, mode]);

  useEffect(() => {
    if (!visible || !ref.current) return;
    const anchorRect = ref.current.getBoundingClientRect();
    const flip = computeTooltipFlip(anchorRect, 150);
    setTooltipStyle(flip.style);
  }, [visible]);

  return (
    <span
      ref={ref}
      style={{ display: 'inline-flex', alignItems: 'center', position: 'relative', gap: '2px' }}
    >
      {children}
      <span
        role="button"
        tabIndex={0}
        aria-label="Help"
        onClick={mode === 'click' ? () => setVisible(v => !v) : undefined}
        onMouseEnter={mode === 'hover' ? () => setVisible(true) : undefined}
        onMouseLeave={mode === 'hover' ? () => setVisible(false) : undefined}
        onKeyDown={mode === 'click' ? e => { if (e.key === 'Escape') setVisible(false); } : undefined}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '14px',
          height: '14px',
          borderRadius: '50%',
          background: 'var(--border-subtle)',
          color: 'var(--text-muted)',
          fontSize: '9px',
          fontWeight: 700,
          cursor: mode === 'click' ? 'pointer' : 'help',
          userSelect: 'none',
        }}
      >
        ?
      </span>
      {visible && (
        <div
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            ...tooltipStyle,
            background: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '6px',
            padding: '6px 10px',
            fontSize: '11px',
            color: 'var(--text-primary)',
            whiteSpace: 'pre-wrap',
            maxWidth: '260px',
            zIndex: 100,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
            lineHeight: 1.5,
          }}
        >
          {content}
          <div style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            width: 0, height: 0,
            borderLeft: '5px solid transparent',
            borderRight: '5px solid transparent',
            borderTop: '5px solid var(--bg-surface-elevated)',
            ...(tooltipStyle.bottom !== undefined
              ? { top: '100%', borderTop: '5px solid var(--border-subtle)', borderBottom: 'none' }
              : { bottom: '100%', borderBottom: '5px solid var(--border-subtle)', borderTop: 'none' }),
          }} />
        </div>
      )}
    </span>
  );
};

export default HelpTooltip;
