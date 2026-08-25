import React, { useMemo } from 'react';
import type { GexData, BotTapeSignal, PositionData } from '../../hooks/useMarketData';

interface HeaderStatsProps {
  metrics: GexData | null;
  position: PositionData;
  tapeSignals: BotTapeSignal[];
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

export const HeaderStats: React.FC<HeaderStatsProps> = ({ metrics, position, tapeSignals }) => {
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

  const regimeLabel = regime === 'LONG_GAMMA' ? '+ Long Gamma' : regime === 'SHORT_GAMMA' ? '- Short Gamma' : 'Neutral';
  const regimeColor = regime === 'LONG_GAMMA' ? 'var(--accent-call)' : regime === 'SHORT_GAMMA' ? 'var(--accent-put)' : 'var(--text-muted)';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {/* Top row: P&L grande + spot + regime */}
      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr 1fr', gap: '12px', alignItems: 'stretch' }}>
        {/* P&L grande */}
        <div className="panel" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
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

        {/* Spot + Gamma Flip */}
        <div className="panel" style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-around', alignItems: 'center' }}>
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

      {/* Bottom row: signals, hit rate, P/C, next window */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
        <StatCard
          label="Signals Fired"
          value={tapeSignals.length}
          sub={`${executedCount} executed`}
        />
        <StatCard
          label="Hit Rate"
          value="—"
          sub="no closes"
        />
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