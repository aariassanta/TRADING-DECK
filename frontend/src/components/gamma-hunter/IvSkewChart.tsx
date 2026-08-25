import React, { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Line,
} from 'recharts';
import type { GexData } from '../../hooks/useMarketData';

interface IvSkewChartProps {
  metrics: GexData | null;
}

export const IvSkewChart: React.FC<IvSkewChartProps> = ({ metrics }) => {
  const data = useMemo(() => {
    const raw = metrics?.iv_skew ?? [];
    // Find ATM point (moneyness closest to 1)
    const atmPoint = raw.find(p => Math.abs(p.moneyness - 1) < 0.02) ?? raw[0];
    const atmCallIv = atmPoint?.call_iv ?? 0;
    const atmPutIv = atmPoint?.put_iv ?? 0;
    const atmSkew = atmPoint ? (atmPutIv - atmCallIv) * 100 : 0;
    return { data: raw, atmSkew };
  }, [metrics?.iv_skew]);

  const pcRatio = metrics?.put_call_ratio?.volume ?? null;

  if (!metrics || data.data.length === 0) {
    return (
      <div className="panel" style={{ height: '250px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        Waiting for IV skew data...
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
          IV Skew · Put/Call Ratio
        </span>
        <span className="font-data" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          {data.data.length} strikes · Skew ATM {data.atmSkew >= 0 ? '+' : ''}{data.atmSkew.toFixed(1)}%
        </span>
      </div>

      <div style={{ flex: 1, padding: '8px' }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data.data} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
            <defs>
              <linearGradient id="ivSkewFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent-put)" stopOpacity={0.15} />
                <stop offset="100%" stopColor="var(--accent-call)" stopOpacity={0.15} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
            <XAxis
              dataKey="moneyness"
              tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
              tickFormatter={(v: number) => v.toFixed(2)}
              stroke="var(--border-subtle)"
            />
            <YAxis
              tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
              stroke="var(--border-subtle)"
            />
            <Tooltip
              contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)' }}
              itemStyle={{ color: 'var(--text-primary)', fontSize: '11px' }}
              formatter={(value: unknown) => {
                const n = Number(value);
                return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : String(value);
              }}
            />
            <ReferenceLine x={1} stroke="var(--accent-spot)" strokeDasharray="3 3" />
            <Area
              type="monotone"
              dataKey="put_iv"
              stroke="var(--accent-put)"
              fill="url(#ivSkewFill)"
              fillOpacity={0}
              strokeWidth={0}
              name="Put IV"
            />
            <Area
              type="monotone"
              dataKey="call_iv"
              stroke="var(--accent-call)"
              fill="url(#ivSkewFill)"
              fillOpacity={0}
              strokeWidth={0}
              name="Call IV"
            />
            <Line type="monotone" dataKey="call_iv" stroke="var(--accent-call)" dot={false} strokeWidth={2} name="Call IV" />
            <Line type="monotone" dataKey="put_iv" stroke="var(--accent-put)" dot={false} strokeWidth={2} name="Put IV" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {pcRatio !== null && (
        <div
          style={{
            padding: '8px 16px',
            borderTop: '1px solid var(--border-subtle)',
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: '11px',
            color: 'var(--text-secondary)',
          }}
        >
          <span>Session P/C Ratio</span>
          <span className="font-data">{pcRatio.toFixed(2)}</span>
        </div>
      )}
    </div>
  );
};