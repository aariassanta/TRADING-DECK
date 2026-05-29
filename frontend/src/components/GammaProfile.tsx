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

  // Build 0DTE-only GEX data - include ALL strikes between min/max level band
  const chartData = useMemo(() => {
    if (!zeroDteExpiry || !gex_by_expiry[zeroDteExpiry]) return [];
    if (!spot) return [];

    const data = gex_by_expiry[zeroDteExpiry];
    const strikes = Object.keys(data).map(Number).sort((a, b) => b - a);

    // Collect all level strikes to define the visible band
    const levelStrikes = new Set([spot]);
    if (call_wall) levelStrikes.add(call_wall);
    if (put_wall) levelStrikes.add(put_wall);
    if (typeof gamma_flip === 'number') levelStrikes.add(gamma_flip);
    const minLevel = Math.min(...levelStrikes);
    const maxLevel = Math.max(...levelStrikes);

    // Include all strikes in the band between lowest and highest level
    return strikes
      .filter(s => s >= minLevel - 100 && s <= maxLevel + 100)
      .map(strike => ({ strike, gex: data[strike] || 0 }));
  }, [gex_by_expiry, zeroDteExpiry, spot, call_wall, put_wall, gamma_flip]);

  // Bar color
  const getBarColor = (gex: number) => {
    if (Math.abs(gex) < 1e-6) return '#333';
    return gex > 0 ? '#22c55e' : '#ef4444';
  };

  // Reference lines for levels within ±5% of spot
  const wallLines = useMemo(() => {
    const lines = [];
    const threshold = spot ? spot * 0.05 : Infinity;

    // Look up GEX for a strike (nearest if exact not found)
    const gexAtStrike = (s: number): number => {
      if (!chartData.length) return 0;
      let best = chartData[0];
      let minDiff = Infinity;
      for (const d of chartData) {
        const diff = Math.abs(d.strike - s);
        if (diff < minDiff) {
          minDiff = diff;
          best = d;
        }
      }
      return best.gex || 0;
    };

    if (call_wall && Math.abs(call_wall - spot) <= threshold) {
      const gex = gexAtStrike(call_wall);
      lines.push({
        strike: call_wall,
        color: '#ef4444',
        label: `CallWall ${call_wall} ${gex >= 0 ? '+' : ''}${gex.toFixed(2)}M`,
      });
    }
    if (put_wall && Math.abs(put_wall - spot) <= threshold) {
      const gex = gexAtStrike(put_wall);
      lines.push({
        strike: put_wall,
        color: '#3b82f6',
        label: `PutWall ${put_wall} ${gex >= 0 ? '+' : ''}${gex.toFixed(2)}M`,
      });
    }
    if (typeof gamma_flip === 'number' && Math.abs(gamma_flip - spot) <= threshold) {
      const gex = gexAtStrike(gamma_flip);
      lines.push({
        strike: gamma_flip,
        color: '#f59e0b',
        label: `GammaFlip ${gamma_flip} ${gex >= 0 ? '+' : ''}${gex.toFixed(2)}M`,
      });
    }
    if (spot) {
      const gex = gexAtStrike(spot);
      lines.push({
        strike: spot,
        color: '#06b6d4',
        label: `Spot ${spot}${gex != 0 ? ` ${gex > 0 ? '+' : ''}${gex.toFixed(2)}M` : ''}`,
      });
    }
    return lines;
  }, [chartData, call_wall, put_wall, gamma_flip, spot]);

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload;
      return (
        <div style={{ background: '#1a1a2e', border: '1px solid #333', padding: '8px', borderRadius: '4px' }}>
          <div style={{ color: '#fff', fontWeight: 'bold' }}>{d.strike}</div>
          <div style={{ color: d.gex >= 0 ? '#4ade80' : '#f87171' }}>
            {d.gex >= 0 ? '+' : ''}{d.gex.toFixed(2)}M
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 120, left: 5, bottom: 5 }}>
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
            width={80}
          />
          <Tooltip content={<CustomTooltip />} />
          {wallLines.map(line => (
            <ReferenceLine
              key={line.label}
              y={line.strike}
              stroke={line.color}
              strokeDasharray="3 3"
              strokeWidth={1.5}
              label={{ value: line.label, fill: line.color, fontSize: 11, position: 'left' }}
            />
          ))}
          <Bar dataKey="gex" radius={[0, 2, 2, 0]}>
            {chartData.map((entry, index) => (
              <Cell key={index} fill={getBarColor(entry.gex)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default GammaProfile;