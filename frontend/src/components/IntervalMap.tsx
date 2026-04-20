import React, { useEffect, useState, useMemo } from 'react';
import {
  ComposedChart,
  Scatter,
  Line,
  XAxis,
  YAxis,
  ZAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface IntervalMapProps {
  fetchHistory: () => Promise<{ data: any[], date: string }>;
  metrics: any;
}

// Visible window = 1 hour in milliseconds
const WINDOW_MS = 60 * 60 * 1000;

const IntervalMap: React.FC<IntervalMapProps> = ({ fetchHistory, metrics }) => {
  const [data, setData] = useState<any[]>([]);
  const [dateStr, setDateStr] = useState<string>('');
  // windowEnd tracks the right edge of the visible 1-hour slice.
  // Starts at null → auto-pins to the latest tick.
  const [windowEnd, setWindowEnd] = useState<number | null>(null);

  useEffect(() => {
    const load = () => {
      fetchHistory().then(payload => {
        setData(payload.data || []);
        setDateStr(payload.date || '');
        setWindowEnd(null); // Reset to latest on data refresh
      });
    };

    // Load on mount and when metrics update
    load();

    // Also load immediately when the user returns to the tab.
    // This fixes the issue where browsers throttle background Javascript
    // and the chart looks "stuck" even though the backend kept saving data.
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        load();
      }
    };
    
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [fetchHistory, metrics]);

  // Parse all CSV rows into chart-ready objects
  const chartData = useMemo(() => {
    return data.map(d => {
      const [h, m, s] = d.Timestamp.split(':').map(Number);
      const timeMs = (h * 3600 + m * 60 + s) * 1000;
      return {
        timeMs,
        timeLabel: `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`,
        strike: d.Strike,
        gex: d.NetGEX,
        volume: d.Volume,
        spot: d.Spot,
        isPositive: d.NetGEX > 0,
        absGex: Math.abs(d.NetGEX),
      };
    });
  }, [data]);

  if (!chartData.length) {
    return (
      <div style={{ color: 'var(--text-muted)', padding: '40px', textAlign: 'center' }}>
        No intraday interval data available yet. Waiting for market ticks...
      </div>
    );
  }

  const globalMaxMs = Math.max(...chartData.map(d => d.timeMs));
  const globalMinMs = Math.min(...chartData.map(d => d.timeMs));

  // Window right-edge: default to latest tick
  const effectiveEnd = windowEnd ?? globalMaxMs;
  const effectiveStart = effectiveEnd - WINDOW_MS;

  // Clamp so we don't go past the edges
  const clampedEnd = Math.min(effectiveEnd, globalMaxMs);
  const clampedStart = Math.max(effectiveStart, globalMinMs);

  // Filter data to the visible 1-hour slice
  const slicedData = chartData.filter(
    d => d.timeMs >= clampedStart && d.timeMs <= clampedEnd
  );

  // Build spot line from sliced data
  const seen = new Set<number>();
  const spotLineData: { timeMs: number; spot: number }[] = [];
  slicedData.forEach(d => {
    if (!seen.has(d.timeMs) && d.spot > 0) {
      seen.add(d.timeMs);
      spotLineData.push({ timeMs: d.timeMs, spot: d.spot });
    }
  });
  spotLineData.sort((a, b) => a.timeMs - b.timeMs);

  const currentSpot = spotLineData[spotLineData.length - 1]?.spot ?? 0;
  // SPX strikes are generally 5 points wide. 15 strikes = 75 points span.
  const yMin = Math.floor(currentSpot - 75);
  const yMax = Math.ceil(currentSpot + 75);

  const calls = slicedData.filter(d => d.isPositive && d.strike >= yMin && d.strike <= yMax);
  const puts = slicedData.filter(d => !d.isPositive && d.strike >= yMin && d.strike <= yMax);

  const tickFormatter = (ms: number) => {
    const totalSec = ms / 1000;
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
  };

  // Navigate backwards or forwards by 30 minutes
  const stepMs = 30 * 60 * 1000;
  const canGoBack = effectiveEnd - stepMs - WINDOW_MS >= globalMinMs;

  const goBack = () => setWindowEnd(prev => (prev ?? globalMaxMs) - stepMs);
  const goForward = () => {
    const next = (windowEnd ?? globalMaxMs) + stepMs;
    // If we'd go past the latest, snap back to live
    if (next >= globalMaxMs) setWindowEnd(null);
    else setWindowEnd(next);
  };

  const isLive = windowEnd === null || windowEnd >= globalMaxMs;

  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload || !payload.length) return null;
    
    // Find the first payload item that has scatter bubble data (has 'gex' field)
    const scatterEntry = payload.find((p: any) => p.payload && p.payload.gex !== undefined);
    if (!scatterEntry) return null;
    
    const d = scatterEntry.payload;
    return (
      <div style={{
        background: 'var(--bg-surface-elevated)',
        border: '1px solid var(--border-subtle)',
        padding: '10px', borderRadius: '4px', fontSize: '12px'
      }}>
        <div style={{ color: 'var(--text-secondary)' }}>{d.timeLabel}</div>
        <div style={{ fontWeight: 'bold', color: 'white', marginTop: '4px' }}>Strike: {d.strike}</div>
        <div style={{ color: d.isPositive ? 'var(--accent-call)' : 'var(--accent-put)' }}>
          NetGEX: {(d.gex as number).toFixed(2)} M
        </div>
        <div style={{ color: 'var(--accent-spot)', marginTop: '2px' }}>Spot: {d.spot}</div>
        <div style={{ color: 'var(--text-muted)' }}>Vol: {d.volume?.toLocaleString()}</div>
      </div>
    );
  };

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', gap: '8px' }}>

      {/* Top bar: legend + navigation controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: '14px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <span><span style={{ color: 'var(--accent-call)' }}>●</span> +GEX</span>
          <span><span style={{ color: 'var(--accent-put)' }}>●</span> -GEX</span>
          <span><span style={{ color: 'var(--accent-spot)' }}>—</span> SPX Spot</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
          {dateStr && !isLive && (
            <span style={{ color: 'var(--text-secondary)' }}>
              {dateStr.substring(0, 4)}-{dateStr.substring(4, 6)}-{dateStr.substring(6, 8)}
            </span>
          )}
          <span style={{ color: 'var(--text-secondary)' }}>
            {tickFormatter(clampedStart)} – {tickFormatter(clampedEnd)}
          </span>
          <button
            onClick={goBack}
            disabled={!canGoBack}
            style={{
              padding: '3px 10px', fontSize: '13px',
              background: 'var(--bg-abyss)', color: canGoBack ? 'white' : 'var(--text-muted)',
              border: '1px solid var(--border-subtle)', borderRadius: '4px', cursor: canGoBack ? 'pointer' : 'default'
            }}
          >◀</button>
          <button
            onClick={goForward}
            disabled={isLive}
            style={{
              padding: '3px 10px', fontSize: '13px',
              background: isLive ? 'var(--bg-surface-elevated)' : 'var(--bg-abyss)',
              color: isLive ? 'var(--accent-spot)' : 'white',
              border: `1px solid ${isLive ? 'var(--accent-spot)' : 'var(--border-subtle)'}`,
              borderRadius: '4px', cursor: isLive ? 'default' : 'pointer'
            }}
          >{isLive ? '● LIVE' : '▶'}</button>
        </div>
      </div>

      {/* Chart — uses ResponsiveContainer so it fills the panel width correctly */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
            <XAxis
              type="number"
              dataKey="timeMs"
              domain={[clampedStart, clampedEnd]}
              tickFormatter={tickFormatter}
              stroke="var(--border-subtle)"
              tick={{ fill: 'var(--text-secondary)', fontSize: 11, fontFamily: 'JetBrains Mono' }}
              scale="linear"
              tickCount={7}
            />
            <YAxis
              type="number"
              dataKey="strike"
              domain={[yMin, yMax]}
              stroke="var(--border-subtle)"
              tick={{ fill: 'var(--text-secondary)', fontSize: 11, fontFamily: 'JetBrains Mono' }}
              width={52}
            />
            <ZAxis type="number" dataKey="absGex" range={[12, 600]} />
            <Tooltip cursor={{ strokeDasharray: '3 3' }} content={<CustomTooltip />} />

            {/* Spot price line */}
            <Line
              data={spotLineData}
              dataKey="spot"
              type="monotone"
              stroke="var(--accent-spot)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />

            {/* GEX bubbles */}
            <Scatter name="Calls (+GEX)" data={calls} fill="var(--accent-call)" fillOpacity={0.65} />
            <Scatter name="Puts  (-GEX)" data={puts} fill="var(--accent-put)" fillOpacity={0.65} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default IntervalMap;
