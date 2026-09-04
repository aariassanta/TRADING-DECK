import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { computeTooltipFlip } from '../../hooks/useTooltipFlip';

interface HelpTooltipProps {
  children?: React.ReactNode;
  content: string;
  mode?: 'hover' | 'click';
}

export const HelpTooltip: React.FC<HelpTooltipProps> = ({ children, content, mode = 'hover' }) => {
  const [visible, setVisible] = useState(false);
  const [caretUp, setCaretUp] = useState(false); // default DOWN
  const [anchorX, setAnchorX] = useState(0);
  const [anchorY, setAnchorY] = useState(0);
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

  // Always compute flip — opens downward by default
  useEffect(() => {
    if (!visible || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const flip = computeTooltipFlip(rect, 150);
    // Force downward always
    setCaretUp(false);
    setAnchorX(rect.left + rect.width / 2);
    setAnchorY(rect.bottom);
  }, [visible]);

  const tooltip = (
    <div
      style={{
        position: 'fixed',
        left: `${anchorX}px`,
        top: `${anchorY + 8}px`,
        transform: 'translateX(-50%)',
        background: 'var(--bg-surface-elevated)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '6px',
        padding: '6px 10px',
        fontSize: '11px',
        color: 'var(--text-primary)',
        whiteSpace: 'pre-wrap',
        maxWidth: '260px',
        zIndex: 9999,
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
        bottom: '100%',
        borderBottom: '5px solid var(--border-subtle)',
        borderTop: 'none',
      }} />
    </div>
  );

  return (
    <>
      <span
        ref={ref}
        style={{ display: 'inline-flex', alignItems: 'center', position: 'relative', gap: '2px' }}
      >
        {children}
        <span
          role="button"
          tabIndex={0}
          aria-label="Help"
          onClick={mode === 'click' ? () => {
            if (!visible && ref.current) {
              const rect = ref.current.getBoundingClientRect();
              const flip = computeTooltipFlip(rect, 150);
              setCaretUp(false);
              setAnchorX(rect.left + rect.width / 2);
              setAnchorY(rect.bottom);
            }
            setVisible(v => !v);
          } : undefined}
          onMouseEnter={mode === 'hover' ? () => {
            if (ref.current) {
              const rect = ref.current.getBoundingClientRect();
              setCaretUp(false);
              setAnchorX(rect.left + rect.width / 2);
              setAnchorY(rect.bottom);
            }
            setVisible(true);
          } : undefined}
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
      </span>
      {visible && createPortal(tooltip, document.body)}
    </>
  );
};

export default HelpTooltip;
