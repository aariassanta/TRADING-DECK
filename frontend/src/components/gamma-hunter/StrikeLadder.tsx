import React, { useMemo, useRef, useEffect } from 'react';
import type { GexData } from '../../hooks/useMarketData';
import { getVisibleStrikes } from './utils';

interface StrikeLadderProps {
  metrics: GexData | null;
}

const formatPrice = (val?: number | null) => {
  if (val === undefined || val === null || val === 0) return '—';
  return `$${val.toFixed(2)}`;
};

const formatCount = (val: number) => {
  if (!val) return '—';
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1000) return `${(val / 1000).toFixed(1)}k`;
  return `${val}`;
};

const estimateDelta = (strike: number, spot: number, right: 'C' | 'P'): number => {
  if (!spot || strike === spot) return right === 'C' ? 0.5 : -0.5;
  const moneyness = (strike - spot) / spot;
  if (right === 'C') {
    return Math.max(0, Math.min(1, 0.5 - moneyness * 3));
  }
  return Math.max(-1, Math.min(0, -0.5 - moneyness * 3));
};

export const StrikeLadder: React.FC<StrikeLadderProps> = ({ metrics }) => {
  const spot = metrics?.spot ?? 0;
  const ladder = useMemo(() => metrics?.strike_ladder ?? [], [metrics?.strike_ladder]);
  const rowRefs = useRef<Map<number, HTMLTableRowElement | null>>(new Map());

  const { visible: rows, atmStrike } = useMemo(
    () => getVisibleStrikes(ladder, spot, metrics?.sigmas, '2'),
    [ladder, spot, metrics?.sigmas]
  );

  useEffect(() => {
    if (!atmStrike) return;
    const el = rowRefs.current.get(atmStrike.strike);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [atmStrike, rows.length]);

  if (!metrics || ladder.length === 0) {
    return (
      <div className="panel" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        Waiting for strike ladder data...
      </div>
    );
  }

  return (
    <div className="panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          SPX 0DTE · Live Strike Ladder
        </span>
        <span className="font-data" style={{ fontSize: '14px', color: 'var(--accent-spot)' }}>
          SPX {spot.toFixed(2)} ● LIVE
        </span>
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px', textAlign: 'center' }}>
          <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-surface)', zIndex: 1 }}>
            <tr>
              <th colSpan={4} style={{ color: 'var(--accent-call)', padding: '6px 4px', borderBottom: '1px solid var(--border-subtle)', fontSize: '10px' }}>CALLS</th>
              <th style={{ color: 'var(--text-muted)', padding: '6px 4px', borderBottom: '1px solid var(--border-subtle)', fontSize: '10px' }}>STRIKE</th>
              <th colSpan={4} style={{ color: 'var(--accent-put)', padding: '6px 4px', borderBottom: '1px solid var(--border-subtle)', fontSize: '10px' }}>PUTS</th>
            </tr>
            <tr>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}>Δ</th>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}>Vol</th>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}>Ask</th>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}>Bid</th>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}></th>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}>Bid</th>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}>Ask</th>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}>Vol</th>
              <th style={{ color: 'var(--text-muted)', padding: '3px 2px', fontSize: '9px' }}>Δ</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => {
              const isSpot = spot && Math.abs(row.strike - spot) < 2.5;
              const callDelta = estimateDelta(row.strike, spot, 'C');
              const putDelta = estimateDelta(row.strike, spot, 'P');
              const maxCallVol = Math.max(...rows.map(r => r.call_volume), 1);
              const maxPutVol = Math.max(...rows.map(r => r.put_volume), 1);
              const callBarWidth = row.call_volume > 0 ? (row.call_volume / maxCallVol) * 100 : 0;
              const putBarWidth = row.put_volume > 0 ? (row.put_volume / maxPutVol) * 100 : 0;

              return (
                <tr
                  key={row.strike}
                  ref={el => { rowRefs.current.set(row.strike, el); }}
                  style={{
                    background: isSpot ? 'rgba(0, 229, 255, 0.12)' : idx % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                    borderTop: isSpot ? '2px solid var(--accent-spot)' : 'none',
                    borderBottom: isSpot ? '2px solid var(--accent-spot)' : '1px solid var(--border-subtle)',
                  }}
                >
                  <td style={{ padding: '4px 2px' }}>
                    <span className="font-data" style={{ fontSize: '9px', color: callDelta > 0.3 ? 'var(--accent-call)' : callDelta < -0.3 ? 'var(--accent-put)' : 'var(--text-muted)' }}>
                      {callDelta.toFixed(2)}
                    </span>
                  </td>
                  <td style={{ padding: '4px 2px', position: 'relative' }}>
                    {row.call_volume > 0 && (
                      <div style={{
                        position: 'absolute', right: 0, top: 0, bottom: 0, width: `${callBarWidth}%`,
                        background: 'var(--accent-call-dim)', borderRadius: '2px',
                      }} />
                    )}
                    <span className="font-data" style={{ fontSize: '9px', color: 'var(--accent-call)', position: 'relative' }}>
                      {formatCount(row.call_volume)}
                    </span>
                  </td>
                  <td style={{ padding: '4px 2px', color: 'var(--text-primary)' }}>{formatPrice(row.call_ask)}</td>
                  <td style={{ padding: '4px 2px', color: 'var(--text-secondary)' }}>{formatPrice(row.call_bid)}</td>
                  <td className="font-data" style={{ padding: '4px 2px', color: isSpot ? 'var(--accent-spot)' : 'var(--text-primary)', fontWeight: isSpot ? 800 : 700, fontSize: '12px' }}>
                    {row.strike}
                  </td>
                  <td style={{ padding: '4px 2px', color: 'var(--text-secondary)' }}>{formatPrice(row.put_bid)}</td>
                  <td style={{ padding: '4px 2px', color: 'var(--text-primary)' }}>{formatPrice(row.put_ask)}</td>
                  <td style={{ padding: '4px 2px', position: 'relative' }}>
                    {row.put_volume > 0 && (
                      <div style={{
                        position: 'absolute', left: 0, top: 0, bottom: 0, width: `${putBarWidth}%`,
                        background: 'var(--accent-put-dim)', borderRadius: '2px',
                      }} />
                    )}
                    <span className="font-data" style={{ fontSize: '9px', color: 'var(--accent-put)', position: 'relative' }}>
                      {formatCount(row.put_volume)}
                    </span>
                  </td>
                  <td style={{ padding: '4px 2px' }}>
                    <span className="font-data" style={{ fontSize: '9px', color: putDelta > 0.3 ? 'var(--accent-call)' : putDelta < -0.3 ? 'var(--accent-put)' : 'var(--text-muted)' }}>
                      {putDelta.toFixed(2)}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};