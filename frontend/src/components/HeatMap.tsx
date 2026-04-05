import React, { useMemo } from 'react';
import type { GexData } from '../hooks/useMarketData';

interface HeatMapProps {
  metrics: GexData;
}

const HeatMap: React.FC<HeatMapProps> = ({ metrics }) => {
  const {
    gex_by_expiry,
    gex_profile,
    expiries,
    spot,
    call_wall,
    put_wall,
    pinning_candidate = null,
    oi_by_expiry = {},
    vol_by_expiry = {},
  } = metrics;

  // The 0DTE expiry is always the first in the sorted list (closest expiration).
  const zeroDteExpiry = expiries?.[0] ?? null;

  // Strike keys sorted descending (highest strike at top of table).
  // We intentionally keep the original float-string keys from JSON (e.g. "6450.0")
  // to avoid coercion issues when looking up nested dicts from Python.
  const strikeKeys = useMemo(() => {
    return Object.keys(gex_profile).sort((a, b) => Number(b) - Number(a));
  }, [gex_profile]);

  // Max absolute GEX across all cells for colour-intensity scaling.
  const maxAbsGex = useMemo(() => {
    let max = 0;
    strikeKeys.forEach(sk => {
      expiries.forEach(exp => {
        const val = Math.abs((gex_by_expiry[exp] ?? {})[sk] ?? 0);
        if (val > max) max = val;
      });
    });
    return max || 1;
  }, [gex_by_expiry, strikeKeys, expiries]);

  // Format GEX in billions or millions.
  const formatGex = (val: number) => {
    if (val === 0) return '--';
    const abs = Math.abs(val);
    if (abs >= 1000) return `${(val / 1000).toFixed(2)} B`;
    return `${val.toFixed(2)} M`;
  };

  // Format OI / Volume compactly (e.g. 12500 → "12.5k").
  const formatCount = (val: number) => {
    if (!val || val === 0) return '--';
    if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
    if (val >= 1000) return `${(val / 1000).toFixed(1)}k`;
    return `${val}`;
  };

  // Background colour for GEX cells (green = positive, red = negative).
  const getCellColor = (val: number) => {
    if (val === 0) return 'transparent';
    const intensity = Math.min(Math.max(Math.abs(val) / maxAbsGex, 0.05), 1);
    return val > 0
      ? `rgba(0, 255, 102, ${intensity * 0.4})`
      : `rgba(255, 0, 85,  ${intensity * 0.4})`;
  };

  // Text colour for GEX cells.
  const getTextColor = (val: number) => {
    if (val === 0) return 'var(--text-muted)';
    return Math.abs(val) / maxAbsGex > 0.15 ? 'white' : 'var(--text-secondary)';
  };

  // Confluence: vol > 0.5 × OI at a given 0DTE strike.
  const hasConfluence = (sk: string): boolean => {
    if (!zeroDteExpiry) return false;
    const oi = (oi_by_expiry?.[zeroDteExpiry] ?? {})[sk] ?? 0;
    const vol = (vol_by_expiry?.[zeroDteExpiry] ?? {})[sk] ?? 0;
    return oi > 0 && vol > 0.5 * oi;
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', paddingRight: '10px' }} className="font-data">
      <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'center', fontSize: '12px' }}>
        <thead style={{
          position: 'sticky', top: 0,
          background: 'var(--bg-surface-elevated)',
          zIndex: 10,
        }}>
          <tr>
            {/* Strike */}
            <th style={thStyle}>STRIKE</th>
            {/* 0DTE-only OI and VOL columns */}
            {zeroDteExpiry && (
              <>
                <th style={{ ...thStyle, color: '#f59e0b' }}>0DTE OI</th>
                <th style={{ ...thStyle, color: '#60a5fa' }}>0DTE VOL</th>
              </>
            )}
            {/* Aggregate GEX */}
            <th style={thStyle}>TOTAL GEX</th>
            {/* Per-expiry GEX columns */}
            {expiries.map(exp => (
              <th key={exp} style={thStyle}>
                {exp.length === 8 ? `${exp.slice(4, 6)}/${exp.slice(6, 8)}` : exp}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {strikeKeys.map(sk => {
            const strikeNum = Number(sk);
            const isSpotRow = Math.abs(strikeNum - spot) < 2.5;
            const isPinRow = pinning_candidate != null && Math.abs(strikeNum - pinning_candidate) < 2.5;
            const isCallWall = call_wall != null && Math.abs(strikeNum - call_wall) < 2.5;
            const isPutWall = put_wall != null && Math.abs(strikeNum - put_wall) < 2.5;
            const confluence = hasConfluence(sk);

            // Row border priority: spot > pinning > call/put wall
            const rowBorderColor = isSpotRow
              ? 'var(--accent-spot)'
              : isPinRow
              ? '#fbbf24'
              : isCallWall
              ? 'var(--accent-put)'
              : isPutWall
              ? 'var(--accent-call)'
              : undefined;

            const rowStyle: React.CSSProperties = rowBorderColor
              ? { border: `1px solid ${rowBorderColor}`, background: `${rowBorderColor}18` }
              : {};

            const profileVal = gex_profile[sk] ?? 0;

            // 0DTE-specific data (use raw float-key from JSON)
            const oi0dte = zeroDteExpiry
              ? ((oi_by_expiry?.[zeroDteExpiry] ?? {})[sk] ?? 0)
              : 0;
            const vol0dte = zeroDteExpiry
              ? ((vol_by_expiry?.[zeroDteExpiry] ?? {})[sk] ?? 0)
              : 0;

            return (
              <tr key={sk} style={rowStyle}>
                {/* Strike label */}
                <td style={{
                  padding: '5px 6px',
                  borderBottom: '1px solid var(--border-subtle)',
                  fontWeight: isSpotRow ? 'bold' : 'normal',
                  color: isSpotRow
                    ? 'var(--accent-spot)'
                    : rowBorderColor ?? 'white',
                  whiteSpace: 'nowrap',
                }}>
                  {strikeNum}
                  {isPinRow && !isSpotRow && <span title="Pinning candidate" style={{ marginLeft: '3px' }}>📌</span>}
                  {isCallWall && <span title="Call Wall" style={{ marginLeft: '3px', fontSize: '10px', color: 'var(--accent-put)' }}>CW</span>}
                  {isPutWall && <span title="Put Wall" style={{ marginLeft: '3px', fontSize: '10px', color: 'var(--accent-call)' }}>PW</span>}
                </td>

                {/* 0DTE OI */}
                {zeroDteExpiry && (
                  <td style={{
                    padding: '5px 6px',
                    borderBottom: '1px solid var(--border-subtle)',
                    color: oi0dte > 0 ? '#f59e0b' : 'var(--text-muted)',
                  }}>
                    {formatCount(oi0dte)}
                  </td>
                )}

                {/* 0DTE VOL (with confluence indicator) */}
                {zeroDteExpiry && (
                  <td style={{
                    padding: '5px 6px',
                    borderBottom: '1px solid var(--border-subtle)',
                    color: vol0dte > 0 ? '#60a5fa' : 'var(--text-muted)',
                  }}>
                    {formatCount(vol0dte)}
                    {confluence && (
                      <span title="Confluence: Vol > 0.5×OI" style={{ marginLeft: '3px', color: '#f59e0b' }}>⚡</span>
                    )}
                  </td>
                )}

                {/* Aggregate Total GEX */}
                <td style={{
                  padding: '5px 6px',
                  borderBottom: '1px solid var(--border-subtle)',
                  background: getCellColor(profileVal),
                  color: getTextColor(profileVal),
                }}>
                  {formatGex(profileVal)}
                </td>

                {/* Per-expiry GEX cells */}
                {expiries.map(exp => {
                  const val = (gex_by_expiry[exp] ?? {})[sk] ?? 0;
                  return (
                    <td key={exp} style={{
                      padding: '5px 6px',
                      borderBottom: '1px solid var(--border-subtle)',
                      background: getCellColor(val),
                      color: getTextColor(val),
                    }}>
                      {formatGex(val)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

// Shared header cell style
const thStyle: React.CSSProperties = {
  padding: '10px 8px',
  borderBottom: '1px solid var(--border-subtle)',
  color: 'var(--text-secondary)',
  fontSize: '11px',
  letterSpacing: '0.06em',
  fontWeight: 600,
};

export default HeatMap;
