import React, { useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from 'recharts';
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

  // Build 0DTE-only GEX data
  const chartData = useMemo(() => {
    if (!zeroDteExpiry || !gex_by_expiry[zeroDteExpiry]) return [];

    const data = gex_by_expiry[zeroDteExpiry];
    const strikes = Object.keys(data).map(Number).sort((a, b) => b - a);

    // Filter to ±15 strikes around spot
    let filtered = strikes;
    if (spot) {
      filtered = strikes.filter(s => Math.abs(s - spot) / spot <= 0.025);
    }

    return filtered.map(strike => ({
      strike,
      gex: data[strike] || 0,
    }));
  }, [gex_by_expiry, zeroDteExpiry, spot]);

  // Determine bar color based on GEX sign and proximity to walls/flip
  const getBarColor = (gex: number, strike: number) => {
    if (Math.abs(gex) < 1e-6) return '#333';
    if (gex > 0) {
      if (call_wall && Math.abs(strike - call_wall) < 5) return '#22c55e';
      return '#4ade80';
    } else {
      if (put_wall && Math.abs(strike - put_wall) < 5) return '#ef4444';
      return '#f87171';
    }
  };

  const wallLines = useMemo(() => {
    const lines = [];
    const threshold = spot ? spot * 0.05 : Infinity;

    if (call_wall && spot && Math.abs(call_wall - spot) <= threshold) {
      lines.push({ strike: call_wall, color: '#ef4444', label: 'Call Wall' });
    }
    if (put_wall && spot && Math.abs(put_wall - spot) <= threshold) {
      lines.push({ strike: put_wall, color: '#3b82f6', label: 'Put Wall' });
    }
    if (gamma_flip && typeof gamma_flip === 'number' && spot && Math.abs(gamma_flip - spot) <= threshold) {
      lines.push({ strike: gamma_flip, color: '#f59e0b', label: 'Gamma Flip' });
    }
    return lines;
  }, [call_wall, put_wall, gamma_flip, spot]);

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload;
      return (
        <div style={{ background: '#1a1a2e', border: '1px solid #333', padding: '8px', borderRadius: '4px' }}>
          <div style={{ color: '#fff', fontWeight: 'bold' }}>Strike {d.strike}</div>
          <div style={{ color: d.gex >= 0 ? '#4ade80' : '#f87171' }}>
            GEX: {d.gex >= 0 ? '+' : ''}{d.gex.toFixed(2)}M
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', gap: '16px', fontSize: '12px' }}>
        {wallLines.map(line => (
          <div key={line.label} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div style={{ width: '12px', height: '12px', background: line.color, borderRadius: '2px' }} />
            <span style={{ color: '#888' }}>{line.label}:</span>
            <span className="font-data" style={{ color: line.color }}>{line.strike}</span>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: 'auto' }}>
          <div style={{ width: '12px', height: '12px', background: '#4ade80', borderRadius: '2px' }} />
          <span style={{ color: '#888' }}>+GEX (FADE)</span>
          <div style={{ width: '12px', height: '12px', background: '#f87171', borderRadius: '2px', marginLeft: '8px' }} />
          <span style={{ color: '#888' }}>-GEX (BREAKOUT)</span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height="85%">
        <BarChart data={chartData} layout="vertical" margin={{ top: 10, right: 30, left: 10, bottom: 20 }}>
          <XAxis
            type="number"
            tick={{ fill: '#888', fontSize: 11 }}
            tickLine={{ stroke: '#333' }}
            axisLine={{ stroke: '#333' }}
            tickFormatter={v => `${v}M`}
          />
          <YAxis
            type="category"
            dataKey="strike"
            tick={{ fill: '#888', fontSize: 11 }}
            tickLine={{ stroke: '#333' }}
            axisLine={{ stroke: '#333' }}
            width={70}
            tickFormatter={v => v.toString()}
          />
          <Tooltip content={<CustomTooltip />} />
          {wallLines.map(line => (
            <ReferenceLine
              key={line.label}
              y={line.strike}
              stroke={line.color}
              strokeDasharray="4 4"
              strokeWidth={2}
              label={{ value: line.label, fill: line.color, fontSize: 10, position: 'right' }}
            />
          ))}
          <Bar dataKey="gex" radius={[0, 2, 2, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={index} fill={getBarColor(entry.gex, entry.strike)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default GammaProfile;