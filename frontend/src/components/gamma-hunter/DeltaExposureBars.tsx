import React, { useMemo, useRef, useEffect, useState } from 'react';
import type { GexData } from '../../hooks/useMarketData';
import { getVisibleStrikes } from './utils';
import { SkeletonList } from './Skeleton';

type DexViewMode = 'call_put' | 'net';

interface DeltaExposureBarsProps {
  metrics: GexData | null;
}

/**
 * DEX Exposure — per-strike delta exposure.
 *
 * "Call Delta" = call_oi * call_delta (estimated from moneyness if not available)
 * "Put Delta"  = put_oi  * put_delta  (estimated)
 *
 * When greeks are not available we fall back to a simple approximation:
 *   call_delta ≈ N(d1) ≈ moneyness (spot/strike proximity)
 *   put_delta  ≈ N(d1) - 1
 *
 * Net DEX per strike = CallDEX - PutDEX (puts are stored negative for display).
 */
export const DeltaExposureBars: React.FC<DeltaExposureBarsProps> = ({ metrics }) => {
  const [dexViewMode, setDexViewMode] = useState<DexViewMode>('call_put');
  const spot = metrics?.spot ?? 0;
  const ladder = useMemo(() => metrics?.strike_ladder ?? [], [metrics?.strike_ladder]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Map<number, HTMLDivElement | null>>(new Map());

  const { visible: rows } = useMemo(
    () => getVisibleStrikes(ladder, spot, metrics?.sigmas, '2'),
    [ladder, spot, metrics?.sigmas]
  );

  // Estimate delta per option from moneyness (crude proxy when real greeks unavailable).
  // call_delta ≈ max(0, min(1, 0.5 + (strike - spot) / (strike * 0.02)))
  // put_delta  ≈ max(-1, min(0, call_delta - 1))
  const estimateDelta = (strike: number): { callDelta: number; putDelta: number } => {
    const dist = (strike - spot) / (spot > 0 ? spot : strike);
    const cd = Math.max(0, Math.min(1, 0.5 + dist / 0.02));
    const pd = cd - 1; // ranges from -1 to 0
    return { callDelta: cd, putDelta: pd };
  };

  // Compute per-strike DEX: OI * delta
  const rowsWithDex = useMemo(() => {
    return rows.map(row => {
      const { callDelta, putDelta } = estimateDelta(row.strike);
      const callDex = row.call_oi * callDelta;
      const putDex  = row.put_oi  * Math.abs(putDelta); // store as positive for display
      return { ...row, callDex, putDex };
    });
  }, [rows, spot]);

  const maxAbs = useMemo(() => {
    if (!rowsWithDex.length) return 1;
    let m = 1;
    for (const r of rowsWithDex) {
      if (dexViewMode === 'net') {
        m = Math.max(m, Math.abs(r.callDex - r.putDex));
      } else {
        m = Math.max(m, Math.abs(r.callDex), Math.abs(r.putDex));
      }
    }
    return m;
  }, [rowsWithDex, dexViewMode]);

  // Total summaries
  const callDexTotal = rowsWithDex.reduce((s, r) => s + r.callDex, 0);
  const putDexTotal  = rowsWithDex.reduce((s, r) => s + r.putDex, 0);
  const netDex = callDexTotal - putDexTotal;

  useEffect(() => {
    if (!rows.length) return;
    const mid = rows[Math.floor(rows.length / 2)];
    if (!mid) return;
    const el = itemRefs.current.get(mid.strike);
    if (el && scrollRef.current) {
      const container = scrollRef.current;
      container.scrollTo({ top: el.offsetTop - container.clientHeight / 2, behavior: 'smooth' });
    }
  }, [rows.length]);

  const fmtK = (val: number) => {
    const abs = Math.abs(val);
    if (abs >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000) return `${(val / 1_000).toFixed(1)}K`;
    return `${val.toFixed(0)}`;
  };

  const barColor = (val: number, maxAbs: number): string => {
    const intensity = Math.min(Math.abs(val) / maxAbs, 1);
    if (val > 0) {
      return intensity > 0.5 ? 'var(--accent-call)' : `rgba(0, 255, 102, ${0.3 + intensity * 0.5})`;
    }
    return intensity > 0.5 ? 'var(--accent-put)' : `rgba(255, 0, 85, ${0.3 + intensity * 0.5})`;
  };

  if (!metrics || rows.length === 0) {
    return (
      <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Delta Exposure
          </span>
        </div>
        <SkeletonList rows={10} rowHeight={20} rowGap={4} headerHeight={0} />
      </div>
    );
  }

  return (
    <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* Header */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '8px',
        }}
      >
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Delta Exposure
        </span>
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          <button
            type="button"
            onClick={() => setDexViewMode('call_put')}
            style={{
              padding: '3px 8px',
              fontSize: '9px',
              fontWeight: 700,
              border: 'none',
              borderRadius: '3px',
              background: dexViewMode === 'call_put' ? 'var(--accent-spot)' : 'var(--bg-abyss)',
              color: dexViewMode === 'call_put' ? 'var(--bg-base)' : 'var(--text-muted)',
              cursor: 'pointer',
            }}
          >
            CALL/PUT
          </button>
          <button
            type="button"
            onClick={() => setDexViewMode('net')}
            style={{
              padding: '3px 8px',
              fontSize: '9px',
              fontWeight: 700,
              border: 'none',
              borderRadius: '3px',
              background: dexViewMode === 'net' ? 'var(--accent-spot)' : 'var(--bg-abyss)',
              color: dexViewMode === 'net' ? 'var(--bg-base)' : 'var(--text-muted)',
              cursor: 'pointer',
            }}
          >
            NET DEX
          </button>
          <span className="font-data" style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: '8px' }}>
            MAX {fmtK(maxAbs)}
          </span>
        </div>
      </div>

      {/* Summary row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 40px 1fr',
          padding: '8px 16px',
          fontSize: '10px',
          color: 'var(--text-muted)',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        {dexViewMode === 'call_put' ? (
          <>
            <span style={{ textAlign: 'right', color: 'var(--accent-call)' }}>
              CALL DEX {fmtK(callDexTotal)}
            </span>
            <span style={{ textAlign: 'center', color: 'var(--text-primary)', fontWeight: 700 }}>
              NET {fmtK(netDex)}
            </span>
            <span style={{ textAlign: 'left', color: 'var(--accent-put)' }}>
              PUT DEX {fmtK(putDexTotal)}
            </span>
          </>
        ) : (
          <>
            <span style={{ textAlign: 'right', color: netDex >= 0 ? 'var(--accent-call)' : 'var(--text-muted)' }}>
              {netDex >= 0 ? `+${fmtK(netDex)}` : '—'}
            </span>
            <span style={{ textAlign: 'center', color: 'var(--text-primary)', fontWeight: 700 }}>
              NET DELTA
            </span>
            <span style={{ textAlign: 'left', color: netDex < 0 ? 'var(--accent-put)' : 'var(--text-muted)' }}>
              {netDex < 0 ? `${fmtK(netDex)}` : '—'}
            </span>
          </>
        )}
      </div>

      {/* Bars */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }}>
        {rowsWithDex.map(row => {
          const isSpot = spot && Math.abs(row.strike - spot) < 2.5;

          if (dexViewMode === 'call_put') {
            const callW = Math.min((Math.abs(row.callDex) / maxAbs) * 100, 100);
            const putW  = Math.min((Math.abs(row.putDex)  / maxAbs) * 100, 100);
            return (
              <div
                key={row.strike}
                ref={el => { itemRefs.current.set(row.strike, el); }}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 40px 1fr',
                  alignItems: 'center',
                  marginBottom: '3px',
                  background: isSpot ? 'rgba(0, 229, 255, 0.08)' : 'transparent',
                  borderRadius: '2px',
                  padding: '1px 0',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
                  {row.callDex > 0 && (
                    <>
                      <span className="font-data" style={{ fontSize: '9px', color: barColor(row.callDex, maxAbs) }}>
                        {fmtK(row.callDex)}
                      </span>
                      <div style={{ width: `${callW}%`, height: '18px', background: barColor(row.callDex, maxAbs), borderRadius: '2px 0 0 2px', opacity: 0.85 }} />
                    </>
                  )}
                </div>
                <div className="font-data" style={{ textAlign: 'center', fontSize: '10px', color: isSpot ? 'var(--accent-spot)' : 'var(--text-primary)', fontWeight: isSpot ? 800 : 600 }}>
                  {row.strike}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-start', gap: '6px' }}>
                  {row.putDex > 0 && (
                    <>
                      <div style={{ width: `${putW}%`, height: '18px', background: barColor(-row.putDex, maxAbs), borderRadius: '0 2px 2px 0', opacity: 0.85 }} />
                      <span className="font-data" style={{ fontSize: '9px', color: barColor(-row.putDex, maxAbs) }}>
                        {fmtK(row.putDex)}
                      </span>
                    </>
                  )}
                </div>
              </div>
            );
          } else {
            // NET DEX: callDex - putDex
            const netDex = row.callDex - row.putDex;
            const netW   = Math.min((Math.abs(netDex) / maxAbs) * 100, 100);
            const isPositive = netDex >= 0;
            const color = barColor(netDex, maxAbs);

            return (
              <div
                key={row.strike}
                ref={el => { itemRefs.current.set(row.strike, el); }}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 40px 1fr',
                  alignItems: 'center',
                  marginBottom: '3px',
                  background: isSpot ? 'rgba(0, 229, 255, 0.08)' : 'transparent',
                  borderRadius: '2px',
                  padding: '1px 0',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
                  {isPositive && netDex !== 0 && (
                    <>
                      <span className="font-data" style={{ fontSize: '9px', color }}>
                        {fmtK(netDex)}
                      </span>
                      <div style={{ width: `${netW}%`, height: '18px', background: color, borderRadius: '2px 0 0 2px', opacity: 0.85 }} />
                    </>
                  )}
                </div>
                <div className="font-data" style={{ textAlign: 'center', fontSize: '10px', color: isSpot ? 'var(--accent-spot)' : 'var(--text-primary)', fontWeight: isSpot ? 800 : 600 }}>
                  {row.strike}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-start', gap: '6px' }}>
                  {!isPositive && netDex !== 0 && (
                    <>
                      <div style={{ width: `${netW}%`, height: '18px', background: color, borderRadius: '0 2px 2px 0', opacity: 0.85 }} />
                      <span className="font-data" style={{ fontSize: '9px', color }}>
                        {fmtK(netDex)}
                      </span>
                    </>
                  )}
                </div>
              </div>
            );
          }
        })}
      </div>
    </div>
  );
};
