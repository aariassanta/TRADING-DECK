import React from 'react';
import type { PositionData } from '../../hooks/useMarketData';

interface ActivePositionProps {
  position: PositionData;
}

const StatRow: React.FC<{ label: string; value: string; valueColor?: string }> = ({ label, value, valueColor }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
    <span style={{ color: 'var(--text-muted)' }}>{label}</span>
    <span className="font-data" style={{ color: valueColor || 'var(--text-primary)', fontWeight: 600 }}>{value}</span>
  </div>
);

export const ActivePosition: React.FC<ActivePositionProps> = ({ position }) => {
  if (!position.active) {
    return (
      <div className="panel" style={{ height: '260px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Active Position
          </span>
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
          No active position
        </div>
      </div>
    );
  }

  const pnl = position.unrealized_pnl ?? 0;
  const pnlPct = position.unrealized_pct ?? 0;
  const isProfit = pnl >= 0;
  const rightLabel = position.right === 'C' ? 'CALL' : 'PUT';

  return (
    <div className="panel" style={{ height: '260px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Active Position
        </span>
        <span style={{ fontSize: '10px', color: isProfit ? 'var(--accent-call)' : 'var(--accent-put)' }}>● LIVE</span>
      </div>

      <div style={{ flex: 1, padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px' }}>
          <span
            className="font-data"
            style={{ fontSize: '36px', fontWeight: 800, color: isProfit ? 'var(--accent-call)' : 'var(--accent-put)' }}
          >
            {isProfit ? '+' : ''}${pnl.toFixed(2)}
          </span>
          <span
            className="font-data"
            style={{ fontSize: '16px', fontWeight: 600, color: isProfit ? 'var(--accent-call)' : 'var(--accent-put)' }}
          >
            ({isProfit ? '+' : ''}{pnlPct.toFixed(1)}%)
          </span>
        </div>

        <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>
          {position.symbol} · {position.strike} {rightLabel}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
          {position.qty} contracts · Entry ${(position.entry_price ?? 0).toFixed(2)} · Current ${(position.current_price ?? 0).toFixed(2)}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '4px' }}>
          <StatRow label="Entry Price" value={position.entry_price ? `$${position.entry_price.toFixed(2)}` : '—'} />
          <StatRow label="Current Price" value={position.current_price ? `$${position.current_price.toFixed(2)}` : '—'} />
          <StatRow label="Max Favorable" value="—" />
          <StatRow label="Max Adverse" value="—" />
        </div>
      </div>
    </div>
  );
};