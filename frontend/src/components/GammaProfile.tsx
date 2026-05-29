import React, { useMemo } from 'react';
import type { GexData } from '../hooks/useMarketData';

interface GammaProfileProps {
  metrics: GexData;
}

const GammaProfile: React.FC<GammaProfileProps> = ({ metrics }) => {
  const {
    gex_by_expiry = {},
    expiries = [],
    spot,
    call_wall,
    put_wall,
    gamma_flip,
  } = metrics;

  const zeroDteExpiry = expiries[0] ?? null;

  // Build 0DTE-only GEX data, sorted descending
  const chartData = useMemo(() => {
    if (!zeroDteExpiry || !gex_by_expiry[zeroDteExpiry]) return [];

    const data = gex_by_expiry[zeroDteExpiry];
    const strikes = Object.keys(data).map(Number).sort((a, b) => b - a);

    // Filter to ±5% around spot
    let filtered = strikes;
    if (spot) {
      filtered = strikes.filter(s => Math.abs(s - spot) / spot <= 0.05);
    }

    return filtered.map(strike => ({
      strike,
      gex: data[strike] || 0,
    }));
  }, [gex_by_expiry, zeroDteExpiry, spot]);

  // Wall/level data
  const levels = useMemo(() => {
    const result = [];
    const threshold = spot ? spot * 0.05 : Infinity;

    if (call_wall && spot && Math.abs(call_wall - spot) <= threshold) {
      result.push({ strike: call_wall, color: '#ef4444', label: 'CallWall', gex: 0 });
    }
    if (put_wall && spot && Math.abs(put_wall - spot) <= threshold) {
      result.push({ strike: put_wall, color: '#3b82f6', label: 'PutWall', gex: 0 });
    }
    if (gamma_flip && typeof gamma_flip === 'number' && spot && Math.abs(gamma_flip - spot) <= threshold) {
      result.push({ strike: gamma_flip, color: '#f59e0b', label: 'GammaFlip', gex: 0 });
    }
    if (spot) {
      result.push({ strike: spot, color: '#06b6d4', label: 'Spot', gex: 0 });
    }
    return result;
  }, [call_wall, put_wall, gamma_flip, spot]);

  // Max absolute GEX for scaling bars
  const maxGex = useMemo(() => {
    if (chartData.length === 0) return 1;
    return Math.max(...chartData.map(d => Math.abs(d.gex)), 0.01);
  }, [chartData]);

  const rowHeight = 32;
  const labelWidth = 90;
  const barMaxWidth = 200;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontFamily: 'var(--font-data, monospace)', fontSize: '12px' }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid #222', color: '#666', fontSize: '11px' }}>
        <div style={{ width: labelWidth, color: '#666' }}>STRIKE</div>
        <div style={{ color: '#666', paddingLeft: '12px' }}>GAMMA EXPOSURE</div>
      </div>

      {/* Scrollable table of strikes */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {chartData.map(({ strike, gex }) => {
          const isWall = levels.some(l => l.strike === strike);
          const barWidth = barMaxWidth * (Math.abs(gex) / maxGex);

          return (
            <div
              key={strike}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '0 12px',
                borderBottom: '1px solid #1a1a1a',
                background: isWall ? '#1a1a2e' : 'transparent',
                height: `${rowHeight}px`,
              }}
            >
              {/* Strike label */}
              <div style={{ width: labelWidth, color: isWall ? '#fff' : '#888', fontWeight: isWall ? 'bold' : 'normal' }}>
                {strike}
              </div>

              {/* Bar area */}
              <div style={{ display: 'flex', alignItems: 'center', flex: 1, paddingLeft: '12px', gap: '8px' }}>
                {gex !== 0 && (
                  <>
                    <div
                      style={{
                        height: '8px',
                        width: `${barWidth}px`,
                        background: gex > 0 ? '#22c55e' : '#ef4444',
                        borderRadius: '2px',
                        flexShrink: 0,
                      }}
                    />
                    <div
                      style={{
                        color: gex > 0 ? '#4ade80' : '#f87171',
                        fontSize: '11px',
                        minWidth: '50px',
                      }}
                    >
                      {gex > 0 ? '+' : ''}{gex.toFixed(2)}M
                    </div>
                  </>
                )}
                {gex === 0 && (
                  <div style={{ color: '#333', fontSize: '11px' }}>—</div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Level legend at bottom */}
      {levels.length > 0 && (
        <div style={{ borderTop: '1px solid #222', padding: '10px 12px', display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {levels.map(level => {
            const levelGex = chartData.find(d => d.strike === level.strike)?.gex || 0;
            return (
              <div key={level.label} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: level.color }} />
                <span style={{ color: '#666', fontSize: '11px' }}>{level.label}:</span>
                <span style={{ color: level.color, fontWeight: 'bold' }}>{level.strike}</span>
                {levelGex !== 0 && (
                  <span style={{ color: levelGex > 0 ? '#4ade80' : '#f87171', fontSize: '11px' }}>
                    ({levelGex > 0 ? '+' : ''}{levelGex.toFixed(2)}M)
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default GammaProfile;