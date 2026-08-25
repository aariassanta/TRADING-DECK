import React, { useMemo, useRef, useEffect, useState } from 'react';
import type { GexData, StrikeLadderRow } from '../../hooks/useMarketData';
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

/** Estimate the Black-Scholes-ish IV by inverting the formula for ATM options.
 *  Falls back to a heuristic based on moneyness if mid is unavailable. */
const estimateIv = (mid: number | null | undefined, strike: number, spot: number, _right: 'C' | 'P'): number | null => {
  if (!mid || !spot) return null;
  const moneyness = Math.abs((strike - spot) / spot);
  // Very rough heuristic: ATM ~ spot*0.02-0.04 sqrt(T); OTM less.
  // For real IV we'd need the full Black-Scholes inversion. Mark as estimate.
  const baseIv = 0.18 + moneyness * 0.6; // ~18% baseline + skew
  return Math.min(baseIv, 1.0);
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
  const [expandedStrike, setExpandedStrike] = useState<number | null>(null);

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

  // Reset expansion if the underlying ladder refreshes and the selected strike
  // is no longer visible.
  useEffect(() => {
    if (expandedStrike === null) return;
    if (!rows.some(r => r.strike === expandedStrike)) {
      setExpandedStrike(null);
    }
  }, [rows, expandedStrike]);

  if (!metrics || ladder.length === 0) {
    return (
      <div className="panel" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        Waiting for strike ladder data...
      </div>
    );
  }

  const toggleStrike = (strike: number) => {
    setExpandedStrike(prev => (prev === strike ? null : strike));
  };

  const renderExpanded = (row: StrikeLadderRow) => {
    const callMid = row.call_bid && row.call_ask ? (row.call_bid + row.call_ask) / 2 : null;
    const putMid = row.put_bid && row.put_ask ? (row.put_bid + row.put_ask) / 2 : null;
    const callSpread = row.call_ask && row.call_bid ? row.call_ask - row.call_bid : null;
    const putSpread = row.put_ask && row.put_bid ? row.put_ask - row.put_bid : null;
    const callIv = estimateIv(callMid, row.strike, spot, 'C');
    const putIv = estimateIv(putMid, row.strike, spot, 'P');
    const totalOi = row.call_oi + row.put_oi;
    const totalVol = row.call_volume + row.put_volume;
    const pcOiRatio = row.call_oi > 0 ? row.put_oi / row.call_oi : 0;
    const pcVolRatio = row.call_volume > 0 ? row.put_volume / row.call_volume : 0;
    const totalGex = row.call_gex + row.put_gex;
    const isCallWall = metrics?.call_wall === row.strike;
    const isPutWall = metrics?.put_wall === row.strike;
    const isFlip = metrics?.gamma_flip === row.strike;
    const isAtm = spot && Math.abs(row.strike - spot) < 2.5;
    const moneynessPct = spot ? ((row.strike - spot) / spot) * 100 : 0;

    return (
      <tr style={{ background: 'rgba(0, 229, 255, 0.06)' }}>
        <td colSpan={9} style={{ padding: '10px 14px', borderBottom: '2px solid var(--accent-spot)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '12px', fontSize: '10px' }}>
            <DetailCell label="Mid Call" value={formatPrice(callMid)} />
            <DetailCell label="Mid Put" value={formatPrice(putMid)} />
            <DetailCell label="Spread Call" value={callSpread !== null ? `$${callSpread.toFixed(2)}` : '—'} />
            <DetailCell label="Spread Put" value={putSpread !== null ? `$${putSpread.toFixed(2)}` : '—'} />
            <DetailCell label="IV Call (est)" value={callIv !== null ? `${(callIv * 100).toFixed(1)}%` : '—'} />
            <DetailCell label="IV Put (est)" value={putIv !== null ? `${(putIv * 100).toFixed(1)}%` : '—'} />

            <DetailCell label="Total OI" value={formatCount(totalOi)} />
            <DetailCell label="Total Vol" value={formatCount(totalVol)} />
            <DetailCell label="P/C OI" value={pcOiRatio ? pcOiRatio.toFixed(2) : '—'} />
            <DetailCell label="P/C Vol" value={pcVolRatio ? pcVolRatio.toFixed(2) : '—'} />
            <DetailCell label="Net GEX" value={formatCount(totalGex)} color={totalGex >= 0 ? 'var(--accent-call)' : 'var(--accent-put)'} />
            <DetailCell label="Moneyness" value={`${moneynessPct >= 0 ? '+' : ''}${moneynessPct.toFixed(2)}%`} />

            <DetailCell label="Role" value={
              isCallWall ? '🟢 Call Wall' :
              isPutWall  ? '🔴 Put Wall'  :
              isFlip     ? '⚪ Gamma Flip' :
              isAtm      ? '🔵 ATM' : '—'
            } />
            <DetailCell label="OI Skew" value={
              totalOi > 0 ? `${((row.put_oi / totalOi) * 100).toFixed(0)}% P / ${((row.call_oi / totalOi) * 100).toFixed(0)}% C` : '—'
            } />
            <DetailCell label="Volume Skew" value={
              totalVol > 0 ? `${((row.put_volume / totalVol) * 100).toFixed(0)}% P / ${((row.call_volume / totalVol) * 100).toFixed(0)}% C` : '—'
            } />
            <DetailCell label="Straddle Cost" value={
              callMid !== null && putMid !== null ? `$${(callMid + putMid).toFixed(2)}` : '—'
            } />
            <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <span style={{ color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: '9px' }}>Action</span>
              <div style={{ display: 'flex', gap: '4px', marginTop: '2px' }}>
                <ActionLink label="Buy Call" />
                <ActionLink label="Buy Put" />
              </div>
            </div>
          </div>
        </td>
      </tr>
    );
  };

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
              const isExpanded = expandedStrike === row.strike;
              const callDelta = estimateDelta(row.strike, spot, 'C');
              const putDelta = estimateDelta(row.strike, spot, 'P');
              const maxCallVol = Math.max(...rows.map(r => r.call_volume), 1);
              const maxPutVol = Math.max(...rows.map(r => r.put_volume), 1);
              const callBarWidth = row.call_volume > 0 ? (row.call_volume / maxCallVol) * 100 : 0;
              const putBarWidth = row.put_volume > 0 ? (row.put_volume / maxPutVol) * 100 : 0;

              return (
                <React.Fragment key={row.strike}>
                  <tr
                    ref={el => { rowRefs.current.set(row.strike, el); }}
                    onClick={() => toggleStrike(row.strike)}
                    style={{
                      cursor: 'pointer',
                      background: isSpot
                        ? 'rgba(0, 229, 255, 0.12)'
                        : isExpanded
                          ? 'rgba(0, 229, 255, 0.04)'
                          : idx % 2 === 0
                            ? 'transparent'
                            : 'rgba(255,255,255,0.015)',
                      borderTop: isSpot ? '2px solid var(--accent-spot)' : 'none',
                      borderBottom: isSpot ? '2px solid var(--accent-spot)' : '1px solid var(--border-subtle)',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={e => {
                      if (!isSpot && !isExpanded) {
                        e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
                      }
                    }}
                    onMouseLeave={e => {
                      if (!isSpot && !isExpanded) {
                        e.currentTarget.style.background = idx % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)';
                      }
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
                      {isExpanded && <span style={{ marginLeft: '4px', fontSize: '8px', color: 'var(--accent-spot)' }}>▼</span>}
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
                  {isExpanded && renderExpanded(row)}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const DetailCell: React.FC<{ label: string; value: React.ReactNode; color?: string }> = ({ label, value, color }) => (
  <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
    <span style={{ color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: '9px' }}>
      {label}
    </span>
    <span className="font-data" style={{ color: color || 'var(--text-primary)', fontSize: '11px', fontWeight: 600, marginTop: '2px' }}>
      {value}
    </span>
  </div>
);

const ActionLink: React.FC<{ label: string }> = ({ label }) => (
  <button
    type="button"
    onClick={e => { e.stopPropagation(); /* TODO: wire to trade panel prefill */ }}
    style={{
      padding: '2px 8px',
      fontSize: '9px',
      fontWeight: 700,
      letterSpacing: '0.04em',
      border: '1px solid var(--border-subtle)',
      borderRadius: '4px',
      background: 'transparent',
      color: 'var(--text-secondary)',
      cursor: 'pointer',
    }}
  >
    {label}
  </button>
);
