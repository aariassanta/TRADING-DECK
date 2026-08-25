import React, { useMemo, useState, useEffect } from 'react';
import type { GexData, EngineHealth as EngineHealthData } from '../../hooks/useMarketData';

interface EngineHealthProps {
  metrics: GexData | null;
  health: EngineHealthData | undefined;
}

export const EngineHealth: React.FC<EngineHealthProps> = ({ metrics, health }) => {
  const isHealthy = (health?.errors ?? 0) === 0 && health?.connected;
  const [now, setNow] = useState<number>(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const uptime = useMemo(() => {
    const start = health?.start_time;
    if (!start) return '—';
    const seconds = Math.floor(now / 1000 - start);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}h ${m}m`;
  }, [health?.start_time, now]);

  const lastPoll = useMemo(() => {
    const ms = health?.last_poll_ms;
    if (ms === undefined || ms === null) return '—';
    return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
  }, [health?.last_poll_ms]);

  const nextPoll = useMemo(() => {
    const ms = health?.last_poll_ms;
    if (ms === undefined || ms === null) return '—';
    const interval = 60000;
    const remaining = Math.max(0, interval - ms);
    const s = Math.ceil(remaining / 1000);
    return `${s}s`;
  }, [health?.last_poll_ms]);

  const spot = metrics?.spot ?? 0;

  return (
    <div className="panel" style={{ height: '260px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Engine Health
        </span>
      </div>

      <div style={{ flex: 1, padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span
            className="font-data"
            style={{
              fontSize: '20px',
              fontWeight: 700,
              color: isHealthy ? 'var(--accent-call)' : 'var(--accent-put)',
            }}
          >
            {isHealthy ? 'HEALTHY' : 'UNHEALTHY'}
          </span>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
            {isHealthy ? '●' : '●'}
          </span>
        </div>

        <HealthRow label="Uptime" value={uptime} />
        <HealthRow label="Last Poll" value={lastPoll} />
        <HealthRow label="Next Poll" value={nextPoll} valueColor={isHealthy ? 'var(--accent-spot)' : undefined} />
        <HealthRow label="Tracked" value={`${health?.tracked_strikes ?? 0} (${health?.calls ?? 0}C · ${health?.puts ?? 0}P)`} />
        <HealthRow label="Setups" value={`${metrics?.fade_setups?.length ?? 0}`} />
        <HealthRow label="Spot" value={spot ? spot.toFixed(2) : '—'} valueColor="var(--accent-spot)" />
      </div>
    </div>
  );
};

const HealthRow: React.FC<{ label: string; value: React.ReactNode; valueColor?: string }> = ({
  label,
  value,
  valueColor,
}) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
    <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
    <span className="font-data" style={{ color: valueColor || 'var(--text-primary)', fontWeight: 600 }}>
      {value}
    </span>
  </div>
);