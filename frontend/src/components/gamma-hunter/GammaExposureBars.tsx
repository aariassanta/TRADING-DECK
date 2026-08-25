import React, { useMemo, useRef, useEffect } from 'react';
import type { GexData } from '../../hooks/useMarketData';
import { getVisibleStrikes } from './utils';
import { SkeletonList } from './Skeleton';

interface GammaExposureBarsProps {
  metrics: GexData | null;
  selectedExpiry?: string;
  onSelectExpiry?: (expiry: string) => void;
}

const fmtM = (val: number) => {
  const abs = Math.abs(val);
  if (abs >= 1000) return `${(val / 1000).toFixed(2)}B`;
  return `${val.toFixed(2)}M`;
};

const barColor = (val: number, maxAbs: number): string => {
  const intensity = Math.min(Math.abs(val) / maxAbs, 1);
  if (val > 0) {
    return intensity > 0.5 ? 'var(--accent-call)' : `rgba(0, 255, 102, ${0.3 + intensity * 0.5})`;
  }
  return intensity > 0.5 ? 'var(--accent-put)' : `rgba(255, 0, 85, ${0.3 + intensity * 0.5})`;
};

export const GammaExposureBars: React.FC<GammaExposureBarsProps> = ({
  metrics,
  selectedExpiry,
  onSelectExpiry,
}) => {
  const spot = metrics?.spot ?? 0;
  const ladder = useMemo(() => metrics?.strike_ladder ?? [], [metrics?.strike_ladder]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Map<number, HTMLDivElement | null>>(new Map());

  const { visible: rows, atmStrike } = useMemo(
    () => getVisibleStrikes(ladder, spot, metrics?.sigmas, '2'),
    [ladder, spot, metrics?.sigmas]
  );

  // When an expiry is selected, augment each row with that expiry's GEX values
  // (otherwise fall back to the strike_ladder's own call_gex/put_gex).
  const expiryProfile = selectedExpiry ? metrics?.gex_by_expiry?.[selectedExpiry] : undefined;

  const maxAbs = useMemo(() => {
    if (!rows.length) return 1;
    let m = 1;
    for (const r of rows) {
      const callG = expiryProfile?.[String(r.strike)] ?? r.call_gex;
      const putG = expiryProfile?.[String(r.strike)] ?? r.put_gex;
      m = Math.max(m, Math.abs(callG), Math.abs(putG));
    }
    return m;
  }, [rows, expiryProfile]);
  const summary = metrics?.gex_summary;

  const expiries = metrics?.expiries ?? [];
  const activeExpiry = selectedExpiry ?? expiries[0] ?? '0DTE';
  const showTabs = expiries.length > 1 && onSelectExpiry;

  useEffect(() => {
    if (!atmStrike) return;
    const el = itemRefs.current.get(atmStrike.strike);
    if (el && scrollRef.current) {
      const container = scrollRef.current;
      const elTop = el.offsetTop;
      const containerHeight = container.clientHeight;
      container.scrollTo({ top: elTop - containerHeight / 2 + el.clientHeight / 2, behavior: 'smooth' });
    }
  }, [atmStrike, rows.length]);

  if (!metrics || rows.length === 0) {
    return (
      <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
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
            Gamma Exposure · $/1pt Move
          </span>
          <span className="font-data" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            LOADING…
          </span>
        </div>
        <SkeletonList rows={10} rowHeight={20} rowGap={4} headerHeight={0} />
      </div>
    );
  }

  return (
    <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
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
          Gamma Exposure · $/1pt Move
        </span>
        <span className="font-data" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          MAX {fmtM(summary?.max_abs_gex ?? maxAbs)}
        </span>
      </div>

      {/* Expiry tabs — only shown when multiple expiries are available */}
      {showTabs && (
        <div
          role="tablist"
          aria-label="Select expiry"
          style={{
            display: 'flex',
            gap: '2px',
            padding: '8px 16px 0',
            borderBottom: '1px solid var(--border-subtle)',
            flexWrap: 'wrap',
          }}
        >
          {expiries.map(exp => {
            const active = exp === activeExpiry;
            return (
              <button
                key={exp}
                role="tab"
                aria-selected={active}
                type="button"
                onClick={() => onSelectExpiry?.(exp)}
                title={exp}
                style={{
                  padding: '4px 12px',
                  fontSize: '10px',
                  fontWeight: 700,
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                  border: 'none',
                  borderRadius: '4px 4px 0 0',
                  background: active ? 'var(--bg-surface-elevated)' : 'transparent',
                  color: active ? 'var(--accent-spot)' : 'var(--text-muted)',
                  borderBottom: active ? '2px solid var(--accent-spot)' : '2px solid transparent',
                  cursor: 'pointer',
                  transition: 'color 0.15s',
                }}
              >
                {expiryLabel(exp)}
              </button>
            );
          })}
        </div>
      )}

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
        <span style={{ textAlign: 'right', color: 'var(--accent-call)' }}>CALL GEX {fmtM(summary?.call_gex_total ?? 0)}</span>
        <span style={{ textAlign: 'center', color: 'var(--text-primary)', fontWeight: 700 }}>
          NET {fmtM(summary?.net_gex ?? 0)}
        </span>
        <span style={{ textAlign: 'left', color: 'var(--accent-put)' }}>PUT GEX {fmtM(summary?.put_gex_total ?? 0)}</span>
      </div>

      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }}>
        {rows.map(row => {
          // Pull GEX values from the selected expiry profile if available
          const callGex = expiryProfile?.[String(row.strike)] ?? row.call_gex;
          const putGex = expiryProfile?.[String(row.strike)] ?? row.put_gex;
          const callWidth = Math.min((Math.abs(callGex) / maxAbs) * 100, 100);
          const putWidth = Math.min((Math.abs(putGex) / maxAbs) * 100, 100);
          const isSpot = spot && Math.abs(row.strike - spot) < 2.5;

          return (
            <div key={row.strike} ref={el => { itemRefs.current.set(row.strike, el); }} style={{
              display: 'grid',
              gridTemplateColumns: '1fr 40px 1fr',
              alignItems: 'center',
              marginBottom: '3px',
              background: isSpot ? 'rgba(0, 229, 255, 0.08)' : 'transparent',
              borderRadius: '2px',
              padding: '1px 0',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
                {callGex !== 0 && (
                  <>
                    <span className="font-data" style={{ fontSize: '9px', color: barColor(callGex, maxAbs) }}>
                      {fmtM(callGex)}
                    </span>
                    <div
                      style={{
                        width: `${callWidth}%`,
                        height: '18px',
                        background: barColor(callGex, maxAbs),
                        borderRadius: '2px 0 0 2px',
                        opacity: 0.85,
                      }}
                    />
                  </>
                )}
              </div>
              <div className="font-data" style={{
                textAlign: 'center',
                fontSize: '10px',
                color: isSpot ? 'var(--accent-spot)' : 'var(--text-primary)',
                fontWeight: isSpot ? 800 : 600,
              }}>
                {row.strike}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-start', gap: '6px' }}>
                {putGex !== 0 && (
                  <>
                    <div
                      style={{
                        width: `${putWidth}%`,
                        height: '18px',
                        background: barColor(putGex, maxAbs),
                        borderRadius: '0 2px 2px 0',
                        opacity: 0.85,
                      }}
                    />
                    <span className="font-data" style={{ fontSize: '9px', color: barColor(putGex, maxAbs) }}>
                      {fmtM(putGex)}
                    </span>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/** Convert an ISO date (YYYY-MM-DD) into a friendly label like "0DTE" / "1DTE" / "W". */
const expiryLabel = (exp: string): string => {
  if (!exp) return '—';
  // Backend may emit either ISO date or already-labeled strings
  if (!/^\d{4}-\d{2}-\d{2}/.test(exp)) return exp.toUpperCase();
  const expDate = new Date(exp + 'T00:00:00');
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.round((expDate.getTime() - today.getTime()) / 86400000);
  if (diffDays === 0) return '0DTE';
  if (diffDays === 1) return '1DTE';
  if (diffDays >= 2 && diffDays <= 6) return `${exp.slice(5).replace('-', '/')} W`;
  return exp.slice(5).replace('-', '/');
};