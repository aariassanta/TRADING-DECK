import React, { useMemo } from 'react';
import type { GexData } from '../hooks/useMarketData';

interface HeatMapProps {
  metrics: GexData;
}

const HeatMap: React.FC<HeatMapProps> = ({ metrics }) => {
  const { gex_by_expiry, gex_profile, expiries, spot } = metrics;

  // Keep strike keys as original strings from JSON (e.g. "6450.0") and sort descending.
  // Do NOT convert to Number then back — Python floats become "6450.0" not "6450",
  // so number-to-string coercion would break the dictionary lookup.
  const strikeKeys = useMemo(() => {
    return Object.keys(gex_profile)
      .sort((a, b) => Number(b) - Number(a));
  }, [gex_profile]);

  // Find max absolute GEX for color scaling across all cells
  const maxAbsGex = useMemo(() => {
    let max = 0;
    strikeKeys.forEach(sk => {
      expiries.forEach(exp => {
        const val = Math.abs((gex_by_expiry[exp] || {})[sk] || 0);
        if (val > max) max = val;
      });
    });
    return max || 1;
  }, [gex_by_expiry, strikeKeys, expiries]);

  // Format GEX in Billions or Millions
  const formatGex = (val: number) => {
    if (val === 0) return '--';
    const absVal = Math.abs(val);
    if (absVal >= 1000) return `${(val / 1000).toFixed(2)} B`;
    return `${val.toFixed(2)} M`;
  };

  // Return a color with intensity-mapped alpha
  const getCellColor = (val: number) => {
    if (val === 0) return 'transparent';
    const intensity = Math.min(Math.max(Math.abs(val) / maxAbsGex, 0.05), 1);
    if (val > 0) return `rgba(0, 255, 102, ${intensity * 0.4})`;
    return `rgba(255, 0, 85, ${intensity * 0.4})`;
  };

  // Return readable text color based on intensity
  const getTextColor = (val: number) => {
    if (val === 0) return 'var(--text-muted)';
    return Math.abs(val) / maxAbsGex > 0.15 ? 'white' : 'var(--text-secondary)';
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', paddingRight: '10px' }} className="font-data">
      <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'center', fontSize: '13px' }}>
        <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-surface-elevated)', zIndex: 10 }}>
          <tr>
            {/* Strike column header */}
            <th style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}>
              STRIKE
            </th>
            {/* Total aggregate GEX column */}
            <th style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}>
              TOTAL GEX
            </th>
            {/* One column per expiry date, formatted as MM/DD */}
            {expiries.map(exp => (
              <th key={exp} style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}>
                {exp.length === 8 ? `${exp.slice(4, 6)}/${exp.slice(6, 8)}` : exp}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {strikeKeys.map(sk => {
            const strikeNum = Number(sk);
            const isSpotRow = Math.abs(strikeNum - spot) < 2.5;
            const rowStyle = isSpotRow
              ? { border: '1px solid var(--accent-spot)', background: 'var(--accent-spot-dim)' }
              : {};

            // Read the total GEX profile value using the original string key
            const profileVal = gex_profile[sk] || 0;

            return (
              <tr key={sk} style={rowStyle}>
                {/* Strike label */}
                <td style={{
                  padding: '6px',
                  borderBottom: '1px solid var(--border-subtle)',
                  fontWeight: isSpotRow ? 'bold' : 'normal',
                  color: isSpotRow ? 'var(--accent-spot)' : 'white'
                }}>
                  {strikeNum}
                </td>

                {/* Aggregate Total GEX */}
                <td style={{
                  padding: '6px',
                  borderBottom: '1px solid var(--border-subtle)',
                  background: getCellColor(profileVal),
                  color: getTextColor(profileVal)
                }}>
                  {formatGex(profileVal)}
                </td>

                {/* Per-expiry GEX cells: gex_by_expiry[exp] is keyed by the same float-string strike */}
                {expiries.map(exp => {
                  const val = (gex_by_expiry[exp] || {})[sk] || 0;
                  return (
                    <td key={exp} style={{
                      padding: '6px',
                      borderBottom: '1px solid var(--border-subtle)',
                      background: getCellColor(val),
                      color: getTextColor(val)
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

export default HeatMap;
