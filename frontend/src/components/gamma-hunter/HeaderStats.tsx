import React, { useEffect, useMemo, useState } from 'react';
import type { GexData, BotTapeSignal, PositionData } from '../../hooks/useMarketData';
import { ThemeToggle } from './ThemeToggle';

interface HeaderStatsProps {
  metrics: GexData | null;
  position: PositionData;
  tapeSignals: BotTapeSignal[];
  wsConnected: boolean;
  spotHistory: number[];
  netGexHistory: number[];
  pnlHistory: number[];
  isPaused: boolean;
}

interface StatCardProps {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  color?: string;
}

const StatCard: React.FC<StatCardProps> = ({ label, value, sub, color }) => (
  <div
    className="panel"
    style={{
      padding: '8px 14px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      minWidth: '100px',
      flex: 1,
    }}
  >
    <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
      {label}
    </div>
    <div
      className="font-data"
      style={{
        fontSize: '20px',
        fontWeight: 700,
        color: color || 'var(--text-primary)',
        marginTop: '2px',
      }}
    >
      {value}
    </div>
    {sub && (
      <div style={{ fontSize: '9px', color: 'var(--text-secondary)', marginTop: '2px' }}>
        {sub}
      </div>
    )}
  </div>
);

/**
 * Inline SVG sparkline. Renders an empty placeholder if buffer has < 2 points.
 * `color` overrides the stroke color (default: var(--accent-spot)).
 * `width`/`height` are pixel sizes for the SVG viewport.
 */
interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
}

const Sparkline: React.FC<SparklineProps> = ({ data, width = 80, height = 22, color = 'var(--accent-spot)' }) => {
  if (data.length < 2) {
    return <div style={{ width, height, opacity: 0.3, fontSize: '9px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}>—</div>;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  const points = data
    .map((v, i) => `${(i * step).toFixed(2)},${(height - ((v - min) / range) * height).toFixed(2)}`)
    .join(' ');
  // Last point for the trailing dot
  const lastY = height - ((data[data.length - 1] - min) / range) * height;
  const lastX = (data.length - 1) * step;
  return (
    <svg width={width} height={height} style={{ display: 'block' }} aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={lastX} cy={lastY} r={2} fill={color} />
    </svg>
  );
};

/**
 * Compact WS connection indicator: pulsing dot + label.
 * Green when connected, amber pulsing when reconnecting.
 */
const WSIndicator: React.FC<{ connected: boolean }> = ({ connected }) => {
  const color = connected ? 'var(--accent-call)' : '#f59e0b';
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '4px 10px',
        borderRadius: '12px',
        background: 'rgba(255,255,255,0.04)',
        border: `1px solid ${color}55`,
        fontSize: '10px',
        fontWeight: 700,
        letterSpacing: '0.06em',
        color,
      }}
      title={connected ? 'WebSocket connected — live updates streaming' : 'WebSocket disconnected — reconnecting with exponential backoff'}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: color,
          boxShadow: `0 0 6px ${color}`,
          animation: connected ? 'none' : 'wsPulse 1.2s ease-in-out infinite',
        }}
      />
      WS · {connected ? 'LIVE' : 'RECONNECT'}
      <style>{`@keyframes wsPulse { 0%,100% { opacity: 1 } 50% { opacity: 0.35 } }`}</style>
    </div>
  );
};

/**
 * Wall-clock in America/New_York (handles EST/EDT automatically via Intl).
 * Updates every second; the colon blinks to signal a live clock.
 */
const useEtClock = (): string => {
  const [now, setNow] = useState(() => formatEt(new Date()));
  useEffect(() => {
    // Align next tick to the top of the next second for smooth display
    const msToNextSecond = 1000 - (Date.now() % 1000);
    let intervalId: ReturnType<typeof setInterval> | undefined;
    const timeoutId = setTimeout(() => {
      setNow(formatEt(new Date()));
      intervalId = setInterval(() => setNow(formatEt(new Date())), 1000);
    }, msToNextSecond);
    return () => {
      clearTimeout(timeoutId);
      if (intervalId) clearInterval(intervalId);
    };
  }, []);
  return now;
};

const formatEt = (d: Date): string => {
  try {
    return d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return '--:--:--';
  }
};

const ETClock: React.FC = () => {
  const time = useEtClock();
  // Blink the colons every second
  const blinkOn = time.endsWith(':00') ? '0.4' : '1';
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '4px 10px',
        borderRadius: '12px',
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid var(--border-subtle)',
        fontSize: '11px',
        fontWeight: 700,
        letterSpacing: '0.08em',
        color: 'var(--accent-spot)',
        fontFamily: 'var(--font-data, monospace)',
      }}
      title="Current time in US/Eastern (auto-handles EST/EDT)"
    >
      <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>ET</span>
      <span style={{ opacity: blinkOn, fontVariantNumeric: 'tabular-nums' }}>{time}</span>
    </div>
  );
};

export const HeaderStats: React.FC<HeaderStatsProps> = ({
  metrics,
  position,
  tapeSignals,
  wsConnected,
  spotHistory,
  netGexHistory,
  pnlHistory,
  isPaused,
}) => {
  const executedCount = useMemo(
    () => tapeSignals.filter(s => s.status === 'EXECUTED').length,
    [tapeSignals]
  );

  const strikesTracked = metrics?.strike_ladder?.length ?? 0;
  const callStrikes = metrics?.strike_ladder?.filter(r => r.call_volume > 0 || r.call_oi > 0).length ?? 0;
  const putStrikes = metrics?.strike_ladder?.filter(r => r.put_volume > 0 || r.put_oi > 0).length ?? 0;

  const pnl = position.active ? (position.unrealized_pnl ?? 0) : 0;
  const pnlPct = position.active ? (position.unrealized_pct ?? 0) : 0;
  const isProfit = pnl >= 0;
  const spot = metrics?.spot ?? 0;
  const gammaFlip = metrics?.gamma_flip;
  const regime = metrics?.regime;
  const netGex = metrics?.net_gex_total ?? 0;
  const netGexColor = netGex > 0 ? 'var(--accent-call)' : netGex < 0 ? 'var(--accent-put)' : 'var(--text-muted)';

  const regimeLabel = regime === 'LONG_GAMMA' ? '+ Long Gamma' : regime === 'SHORT_GAMMA' ? '- Short Gamma' : 'Neutral';
  const regimeColor = regime === 'LONG_GAMMA' ? 'var(--accent-call)' : regime === 'SHORT_GAMMA' ? 'var(--accent-put)' : 'var(--text-muted)';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {/* Top row: P&L grande + spot + regime */}
      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr 1fr', gap: '12px', alignItems: 'stretch' }}>
        {/* P&L grande with WS indicator overlay */}
        <div className="panel" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', justifyContent: 'center', position: 'relative' }}>
          {/* WS indicator + ET clock + theme toggle pinned to top-right */}
          <div style={{ position: 'absolute', top: '8px', right: '8px', display: 'flex', gap: '6px' }}>
            <ThemeToggle />
            <WSIndicator connected={wsConnected && !isPaused} />
            <ETClock />
          </div>
          {/* Optional P&L sparkline (only when position is active) */}
          {position.active && pnlHistory.length > 1 && (
            <div style={{ position: 'absolute', bottom: '6px', right: '10px', opacity: 0.85 }}>
              <Sparkline data={pnlHistory} width={70} height={18} color={isProfit ? 'var(--accent-call)' : 'var(--accent-put)'} />
            </div>
          )}
          <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Session P&L
          </div>
          <div
            className="font-data"
            style={{
              fontSize: '36px',
              fontWeight: 800,
              color: isProfit ? 'var(--accent-call)' : 'var(--accent-put)',
              lineHeight: 1,
            }}
          >
            {isProfit ? '+' : ''}${pnl.toFixed(2)}
          </div>
          <div
            className="font-data"
            style={{
              fontSize: '14px',
              fontWeight: 600,
              color: isProfit ? 'var(--accent-call)' : 'var(--accent-put)',
              marginTop: '4px',
            }}
          >
            {isProfit ? '+' : ''}{pnlPct.toFixed(1)}%
          </div>
        </div>

        {/* Spot + Gamma Flip with sparkline */}
        <div className="panel" style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-around', alignItems: 'center', position: 'relative' }}>
          <div style={{ textAlign: 'center', flex: 1 }}>
            <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>SPX Spot</div>
            <div className="font-data" style={{ fontSize: '24px', fontWeight: 700, color: 'var(--accent-spot)', marginTop: '2px' }}>
              {spot ? spot.toFixed(2) : '-----'}
            </div>
          </div>
          <div style={{ width: '1px', height: '40px', background: 'var(--border-subtle)' }} />
          <div style={{ textAlign: 'center', flex: 1 }}>
            <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Gamma Flip</div>
            <div className="font-data" style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
              {gammaFlip ?? '---'}
            </div>
          </div>
          {/* Spot sparkline bottom-right */}
          <div style={{ position: 'absolute', bottom: '4px', right: '8px' }}>
            <Sparkline data={spotHistory} width={90} height={20} />
          </div>
        </div>

        {/* Regime badge + Strikes */}
        <div className="panel" style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-around', alignItems: 'center' }}>
          <div style={{ textAlign: 'center', flex: 1 }}>
            <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Regime</div>
            <div className="font-data" style={{ fontSize: '14px', fontWeight: 700, color: regimeColor, marginTop: '4px' }}>
              {regimeLabel}
            </div>
          </div>
          <div style={{ width: '1px', height: '40px', background: 'var(--border-subtle)' }} />
          <div style={{ textAlign: 'center', flex: 1 }}>
            <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Strikes</div>
            <div className="font-data" style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
              {strikesTracked}
            </div>
            <div style={{ fontSize: '9px', color: 'var(--text-secondary)' }}>{callStrikes}C · {putStrikes}P</div>
          </div>
        </div>
      </div>

      {/* Bottom row: signals, net gex + sparkline, P/C, next window */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
        <StatCard
          label="Signals Fired"
          value={tapeSignals.length}
          sub={`${executedCount} executed`}
        />
        {/* Net GEX with embedded sparkline (replaces Hit Rate placeholder) */}
        <div
          className="panel"
          style={{
            padding: '8px 14px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            minWidth: '100px',
            flex: 1,
            position: 'relative',
          }}
        >
          <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Net GEX (M)
          </div>
          <div
            className="font-data"
            style={{
              fontSize: '20px',
              fontWeight: 700,
              color: netGexColor,
              marginTop: '2px',
            }}
          >
            {netGex > 0 ? '+' : ''}{netGex.toFixed(1)}
          </div>
          <div style={{ position: 'absolute', bottom: '4px', right: '8px' }}>
            <Sparkline data={netGexHistory} width={70} height={16} color={netGexColor} />
          </div>
        </div>
        <StatCard
          label="Put/Call"
          value={metrics?.put_call_ratio?.volume?.toFixed(2) ?? '—'}
          sub={`OI ${metrics?.put_call_ratio?.oi?.toFixed(2) ?? '—'}`}
        />
        <StatCard
          label="Next Window"
          value="M1 LIVE"
          color="var(--accent-spot)"
        />
      </div>
    </div>
  );
};
