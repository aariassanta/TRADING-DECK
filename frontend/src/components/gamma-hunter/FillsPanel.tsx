import React, { useState, useMemo } from 'react';
import type { FillRecord } from '../../hooks/useMarketData';
import { downloadCsv, timestampedFilename, toCsv } from './csv';

interface FillsPanelProps {
  fills: FillRecord[];
  strategyPnl: Record<string, number>;
}

const STRATEGY_COLORS: Record<string, string> = {
  FLIP: '#00ff41',
  PINNING: '#3b82f6',
  TREND: '#f59e0b',
  ORB: '#a855f7',
  ORB15: '#ec4899',
  IRON_FLY: '#06b6d4',
  MILK_MAN: '#84cc16',
  MANUAL: '#889890',
};

const formatPrice = (v: number) => {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${v < 0 ? '-' : ''}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${v < 0 ? '-' : ''}$${(abs / 1_000).toFixed(1)}K`;
  return `${v < 0 ? '-' : ''}$${abs.toFixed(2)}`;
};

export const FillsPanel: React.FC<FillsPanelProps> = ({ fills, strategyPnl }) => {
  const [filter, setFilter] = useState<string>('ALL');
  const [sideFilter, setSideFilter] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');

  const strategies = useMemo(() => {
    const s = new Set(fills.map(f => f.strategy));
    return ['ALL', ...Array.from(s).sort()];
  }, [fills]);

  const filtered = useMemo(() => {
    return fills.filter(f => {
      if (filter !== 'ALL' && f.strategy !== filter) return false;
      if (sideFilter !== 'ALL' && f.side !== sideFilter) return false;
      return true;
    });
  }, [fills, filter, sideFilter]);

  const totalPnl = useMemo(() => {
    return Object.values(strategyPnl).reduce((s, v) => s + v, 0);
  }, [strategyPnl]);

  const handleExport = () => {
    if (!filtered.length) return;
    const columns = [
      { key: 'time', header: 'Time' },
      { key: 'strategy', header: 'Strategy' },
      { key: 'contract', header: 'Contract' },
      { key: 'side', header: 'Side' },
      { key: 'qty', header: 'Qty' },
      { key: 'price', header: 'Fill Price' },
    ];
    const csv = toCsv(filtered, columns);
    downloadCsv(csv, timestampedFilename('fills'));
  };

  return (
    <div
      style={{
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '8px',
        padding: '10px 12px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.06em' }}>FILLS</span>
          {/* Strategy filter */}
          {strategies.map(s => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              style={{
                padding: '2px 7px',
                fontSize: '9px',
                fontWeight: 700,
                background: filter === s ? (STRATEGY_COLORS[s] ?? '#889890') : 'var(--bg-surface-elevated)',
                color: filter === s ? '#000' : (STRATEGY_COLORS[s] ?? 'var(--text-muted)'),
                border: `1px solid ${STRATEGY_COLORS[s] ?? 'var(--border-subtle)'}`,
                borderRadius: '3px',
                cursor: 'pointer',
              }}
            >
              {s}
            </button>
          ))}
          {/* Side filter */}
          <div style={{ display: 'flex', gap: '2px', marginLeft: '4px' }}>
            {(['ALL', 'BUY', 'SELL'] as const).map(s => (
              <button
                key={s}
                onClick={() => setSideFilter(s)}
                style={{
                  padding: '2px 6px',
                  fontSize: '9px',
                  fontWeight: 700,
                  background: sideFilter === s ? 'var(--accent-spot)' : 'var(--bg-surface-elevated)',
                  color: sideFilter === s ? '#000' : 'var(--text-muted)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '3px',
                  cursor: 'pointer',
                }}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {/* P&L summary */}
          {Object.entries(strategyPnl).map(([str, pnl]) => (
            <span key={str} style={{ fontSize: '9px', color: pnl >= 0 ? 'var(--accent-call)' : 'var(--accent-put)', fontWeight: 700 }}>
              {str} {pnl >= 0 ? '+' : ''}{formatPrice(pnl)}
            </span>
          ))}
          {Object.keys(strategyPnl).length > 0 && (
            <span style={{ fontSize: '10px', color: totalPnl >= 0 ? 'var(--accent-call)' : 'var(--accent-put)', fontWeight: 800, borderLeft: '1px solid var(--border-subtle)', paddingLeft: '8px' }}>
              Total {totalPnl >= 0 ? '+' : ''}{formatPrice(totalPnl)}
            </span>
          )}
          <button
            onClick={handleExport}
            style={{
              padding: '2px 8px',
              fontSize: '9px',
              fontWeight: 700,
              background: 'var(--bg-surface-elevated)',
              color: 'var(--text-muted)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '3px',
              cursor: 'pointer',
            }}
          >
            CSV
          </button>
        </div>
      </div>

      {/* Table */}
      <div style={{ overflowY: 'auto', flex: 1 }}>
        {filtered.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '11px', textAlign: 'center', padding: '20px' }}>
            No fills yet today.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '10px' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                {['Time', 'Strategy', 'Contract', 'Side', 'Qty', 'Price'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '3px 6px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.06em', fontSize: '9px' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((fill, i) => {
                const color = STRATEGY_COLORS[fill.strategy] ?? '#889890';
                return (
                  <tr
                    key={`${fill.order_id}-${fill.time}-${i}`}
                    style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  >
                    <td style={{ padding: '3px 6px', color: 'var(--text-secondary)', fontFamily: 'var(--font-data, monospace)' }}>
                      {fill.time.split(' ')[1] ?? fill.time}
                    </td>
                    <td style={{ padding: '3px 6px' }}>
                      <span style={{ color, fontWeight: 700 }}>{fill.strategy}</span>
                    </td>
                    <td style={{ padding: '3px 6px', color: 'var(--text-primary)', fontFamily: 'var(--font-data, monospace)' }}>
                      {fill.contract}
                    </td>
                    <td style={{ padding: '3px 6px', color: fill.side === 'BUY' ? 'var(--accent-call)' : 'var(--accent-put)', fontWeight: 700 }}>
                      {fill.side}
                    </td>
                    <td style={{ padding: '3px 6px', color: 'var(--text-primary)', fontFamily: 'var(--font-data, monospace)', textAlign: 'right' }}>
                      {fill.qty}
                    </td>
                    <td style={{ padding: '3px 6px', color: 'var(--text-primary)', fontFamily: 'var(--font-data, monospace)', textAlign: 'right' }}>
                      {fill.price.toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
