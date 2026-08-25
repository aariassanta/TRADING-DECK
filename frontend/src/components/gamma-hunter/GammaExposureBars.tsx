import React, { useMemo, useRef, useEffect } from 'react';
import type { GexData } from '../../hooks/useMarketData';
import { getVisibleStrikes } from './utils';

interface GammaExposureBarsProps {
  metrics: GexData | null;
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

export const GammaExposureBars: React.FC<GammaExposureBarsProps> = ({ metrics }) => {
  const spot = metrics?.spot ?? 0;
  const ladder = useMemo(() => metrics?.strike_ladder ?? [], [metrics?.strike_ladder]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Map<number, HTMLDivElement | null>>(new Map());

  const { visible: rows, atmStrike } = useMemo(
    () => getVisibleStrikes(ladder, spot, metrics?.sigmas, '2'),
    [ladder, spot, metrics?.sigmas]
  );

  const maxAbs = metrics?.gex_summary?.max_abs_gex || 1;
  const summary = metrics?.gex_summary;

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
      <div className="panel" style={{ height: '250px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        Waiting for GEX data...
      </div>
    );
  }

  return (
    <div className="panel" style={{ height: '250px', display: 'flex', flexDirection: 'column' }}>
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
          MAX {fmtM(summary?.max_abs_gex ?? maxAbs)}
        </span>
      </div>

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
          const callWidth = Math.min((Math.abs(row.call_gex) / maxAbs) * 100, 100);
          const putWidth = Math.min((Math.abs(row.put_gex) / maxAbs) * 100, 100);
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
                {row.call_gex !== 0 && (
                  <>
                    <span className="font-data" style={{ fontSize: '9px', color: barColor(row.call_gex, maxAbs) }}>
                      {fmtM(row.call_gex)}
                    </span>
                    <div
                      style={{
                        width: `${callWidth}%`,
                        height: '18px',
                        background: barColor(row.call_gex, maxAbs),
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
                {row.put_gex !== 0 && (
                  <>
                    <div
                      style={{
                        width: `${putWidth}%`,
                        height: '18px',
                        background: barColor(row.put_gex, maxAbs),
                        borderRadius: '0 2px 2px 0',
                        opacity: 0.85,
                      }}
                    />
                    <span className="font-data" style={{ fontSize: '9px', color: barColor(row.put_gex, maxAbs) }}>
                      {fmtM(row.put_gex)}
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