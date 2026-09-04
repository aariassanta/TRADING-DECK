import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';

interface HelpTooltipProps {
  children?: React.ReactNode;
  content: string;
  mode?: 'hover' | 'click';
}

export const HelpTooltip: React.FC<HelpTooltipProps> = ({ children, content, mode = 'hover' }) => {
  const [visible, setVisible] = useState(false);
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
    const rect = ref.current.getBoundingClientRect();
    console.log('HelpTooltip anchor rect:', rect);
    console.log('HelpTooltip visible at:', rect.left + rect.width / 2, rect.bottom);
  }, [visible]);

  const tooltip = (
    <div
      data-testid="help-tooltip-portal"
      style={{
        position: 'fixed',
        left: '50%',
        top: '200px',
        transform: 'translateX(-50%)',
        background: '#ff0000',
        color: '#fff',
        padding: '12px 20px',
        borderRadius: '8px',
        fontSize: '14px',
        fontFamily: 'monospace',
        zIndex: 99999,
        boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
        minWidth: '200px',
      }}
    >
      PORTAL WORKS — content below
      <br />
      {content}
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
          onClick={mode === 'click' ? () => setVisible(v => !v) : undefined}
          onMouseEnter={mode === 'hover' ? () => { console.log('mouse enter'); setVisible(true); } : undefined}
          onMouseLeave={mode === 'hover' ? () => { console.log('mouse leave'); setVisible(false); } : undefined}
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
