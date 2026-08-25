import React from 'react';
import type { GexData, GexZone, GexSetup, MarketAlert, AlertPrefill } from '../hooks/useMarketData';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RegimePanelProps {
  metrics: GexData;
  alerts: MarketAlert[];
  onAlertClick: (prefill: AlertPrefill) => void;
  onDismissAlert: (index: number) => void;
}

// ---------------------------------------------------------------------------
// Helper constants and utilities
// ---------------------------------------------------------------------------

/** Map regime key → display color variable. */
const REGIME_COLORS: Record<string, string> = {
  LONG_GAMMA: 'var(--accent-call)',
  SHORT_GAMMA: 'var(--accent-put)',
  NEUTRAL: 'var(--text-muted)',
};

/** Map breakout risk → color. */
const RISK_COLORS: Record<string, string> = {
  HIGH: 'var(--accent-put)',
  MEDIUM: '#f59e0b',
  LOW: 'var(--accent-call)',
};

/** Map alert level → color. */
const ALERT_COLORS: Record<string, string> = {
  GAMMA_FLIP_CROSS: '#a855f7',
  APPROACHING_CALL_WALL: '#f59e0b',
  APPROACHING_PUT_WALL: '#f59e0b',
  CALL_WALL_BREAK: 'var(--accent-put)',
  PUT_WALL_BREAK: 'var(--accent-put)',
  ENTERING_BREAKOUT_ZONE: '#f97316',
  CONFLUENCE_SPIKE: 'var(--accent-put)',
};

/** Format a GEX value in Billions or Millions. */
function fmtGex(val: number): string {
  const abs = Math.abs(val);
  if (abs >= 1000) return `${(val / 1000).toFixed(2)}B`;
  return `${val.toFixed(2)}M`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Single alert row with click-to-prefill and dismiss. */
const AlertRow: React.FC<{
  alert: MarketAlert;
  index: number;
  onAlertClick: (prefill: AlertPrefill) => void;
  onDismiss: (index: number) => void;
}> = ({ alert, index, onAlertClick, onDismiss }) => {
  const color = ALERT_COLORS[alert.level] ?? '#f59e0b';
  const clickable = !!alert.prefill;

  return (
    <div
      id={`alert-row-${index}`}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '6px',
        padding: '6px 8px',
        marginBottom: '4px',
        borderRadius: '4px',
        background: `${color}18`,
        border: `1px solid ${color}44`,
        cursor: clickable ? 'pointer' : 'default',
        transition: 'background 0.15s',
      }}
      title={clickable ? 'Click to pre-fill execution form' : undefined}
      onClick={() => {
        if (clickable && alert.prefill) onAlertClick(alert.prefill);
      }}
    >
      {/* Coloured dot */}
      <span style={{
        width: '7px', height: '7px',
        borderRadius: '50%',
        background: color,
        marginTop: '5px',
        flexShrink: 0,
      }} />

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Header row: level + time */}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px' }}>
          <span style={{ color, fontWeight: 700, letterSpacing: '0.04em' }}>
            {alert.level.replace(/_/g, ' ')}
          </span>
          <span style={{ color: 'var(--text-muted)' }}>{alert.timestamp}</span>
        </div>
        {/* Suggestion */}
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px', lineHeight: 1.4 }}>
          {alert.setup_suggestion}
        </div>
        {/* Click hint */}
        {clickable && (
          <div style={{ fontSize: '10px', color, marginTop: '2px', opacity: 0.7 }}>
            ↗ Click to pre-fill form
          </div>
        )}
      </div>

      {/* Dismiss button */}
      <button
        id={`dismiss-alert-${index}`}
        onClick={e => { e.stopPropagation(); onDismiss(index); }}
        style={{
          background: 'none', border: 'none', color: 'var(--text-muted)',
          cursor: 'pointer', fontSize: '14px', lineHeight: 1, padding: '0 2px',
          flexShrink: 0,
        }}
        title="Dismiss"
      >
        ×
      </button>
    </div>
  );
};

/** A single GEX zone row. */
const ZoneRow: React.FC<{ zone: GexZone }> = ({ zone }) => {
  const color = zone.type === 'FADE' ? 'var(--accent-call)' : 'var(--accent-put)';
  const icon = zone.type === 'FADE' ? '🟢' : '🔴';
  const strikeRange =
    zone.strikes.length > 1
      ? `${zone.strikes[0]} – ${zone.strikes[zone.strikes.length - 1]}`
      : `${zone.strikes[0]}`;

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      padding: '4px 0',
      borderBottom: '1px solid var(--border-subtle)',
      fontSize: '11px',
    }}>
      <span>{icon}</span>
      <span style={{ color, fontWeight: 700, minWidth: '56px' }}>{zone.type}</span>
      <span style={{ color: 'white', flex: 1 }}>{strikeRange}</span>
      <span style={{ color: 'var(--text-muted)', minWidth: '60px', textAlign: 'right' }}>
        pk: {zone.peak_strike}
      </span>
      {zone.confluence && (
        <span title="Volume > 0.5×OI at this zone" style={{ color: '#f59e0b', fontSize: '10px' }}>
          ⚡
        </span>
      )}
    </div>
  );
};

/** A setup suggestion row. */
const SetupRow: React.FC<{
  setup: GexSetup;
  onAlertClick: (prefill: AlertPrefill) => void;
}> = ({ setup, onAlertClick }) => {
  const isBullish = setup.type === 'PCS';
  const color = isBullish ? 'var(--accent-call)' : 'var(--accent-put)';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        padding: '5px 8px',
        marginBottom: '4px',
        borderRadius: '4px',
        background: `${color}14`,
        border: `1px solid ${color}33`,
        cursor: 'pointer',
        fontSize: '11px',
      }}
      title="Click to pre-fill execution form"
      onClick={() =>
        onAlertClick({
          type: setup.type,
          target_mode: 'GEX',
          anchor: setup.anchor,
        })
      }
    >
      <span style={{ color, fontWeight: 700 }}>📍</span>
      <span style={{ color: 'var(--text-secondary)', flex: 1, lineHeight: 1.4 }}>
        {setup.label}
      </span>
      {setup.confluence && <span style={{ color: '#f59e0b', fontSize: '10px' }}>⚡</span>}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const RegimePanel: React.FC<RegimePanelProps> = ({
  metrics,
  alerts,
  onAlertClick,
  onDismissAlert,
}) => {
  const {
    regime = 'NEUTRAL',
    regime_score = 0,
    bias = 'NEUTRAL',
    net_gex_total = 0,
    pinning_candidate = null,
    expected_range = null,
    breakout_risk = 'LOW',
    gex_zones = [],
    fade_setups = [],
    breakout_setups = [],
    dark_gamma = [],
  } = metrics;

  const regimeColor = REGIME_COLORS[regime] ?? 'var(--text-muted)';
  const riskColor = RISK_COLORS[breakout_risk] ?? 'var(--text-muted)';
  const scoreLabel =
    regime_score > 0
      ? `+${regime_score.toFixed(2)}% above flip`
      : `${regime_score.toFixed(2)}% below flip`;

  // Only show the top 4 zones
  const topZones = (gex_zones ?? []).slice(0, 4);
  const allSetups = [...(fade_setups ?? []), ...(breakout_setups ?? [])];

  return (
    <div style={{ fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '14px' }}>

      {/* ── REGIME ── */}
      <section>
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '8px' }}>
          MARKET REGIME
        </div>

        {/* Regime badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
          <span style={{
            width: '8px', height: '8px', borderRadius: '50%',
            background: regimeColor, flexShrink: 0,
            boxShadow: `0 0 6px ${regimeColor}`,
          }} />
          <span style={{ color: regimeColor, fontWeight: 700, fontSize: '13px' }}>{regime.replace('_', ' ')}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>({scoreLabel})</span>
        </div>

        {/* Metric grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>

          <div style={{ padding: '6px', background: 'var(--bg-abyss)', borderRadius: '4px' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: '9px', marginBottom: '2px' }}>BIAS</div>
            <div style={{ color: bias === 'BULLISH' ? 'var(--accent-call)' : bias === 'BEARISH' ? 'var(--accent-put)' : 'var(--text-muted)', fontWeight: 700 }}>
              {bias === 'BULLISH' ? '▲ ' : bias === 'BEARISH' ? '▼ ' : ''}{bias}
            </div>
          </div>

          <div style={{ padding: '6px', background: 'var(--bg-abyss)', borderRadius: '4px' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: '9px', marginBottom: '2px' }}>NET GEX</div>
            <div style={{ color: net_gex_total > 0 ? 'var(--accent-call)' : 'var(--accent-put)', fontWeight: 700 }}>
              {net_gex_total != null ? fmtGex(net_gex_total) : '---'}
            </div>
          </div>

          <div style={{ padding: '6px', background: 'var(--bg-abyss)', borderRadius: '4px', gridColumn: '1 / -1' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: '9px', marginBottom: '6px' }}>EXPECTED RANGE (Walls)</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '10px' }}>
              <span style={{ color: 'var(--accent-call)', fontWeight: 'bold' }}>{expected_range?.[0] ?? '---'}</span>
              <div style={{
                flex: 1, position: 'relative', height: '4px',
                background: 'rgba(255,255,255,0.1)', borderRadius: '2px',
                overflow: 'hidden'
              }}>
                {expected_range && (
                  <div style={{
                    position: 'absolute',
                    left: `${Math.max(0, Math.min(100, ((metrics.spot - expected_range[0]) / (expected_range[1] - expected_range[0])) * 100))}%`,
                    top: '-3px', height: '10px', width: '2px',
                    background: 'var(--accent-spot)',
                    boxShadow: '0 0 5px var(--accent-spot)'
                  }} />
                )}
              </div>
              <span style={{ color: 'var(--accent-put)', fontWeight: 'bold' }}>{expected_range?.[1] ?? '---'}</span>
            </div>
          </div>

          <div style={{ padding: '6px', background: 'var(--bg-abyss)', borderRadius: '4px' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: '9px', marginBottom: '2px' }}>BREAK RISK</div>
            <div style={{ color: riskColor, fontWeight: 700 }}>{breakout_risk}</div>
          </div>

          {pinning_candidate != null && (
            <div style={{ padding: '6px', background: 'var(--bg-abyss)', borderRadius: '4px', gridColumn: '1 / -1' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '9px', marginBottom: '2px' }}>PINNING CANDIDATE</div>
              <div style={{ color: '#fbbf24', fontWeight: 700 }}>📌 {pinning_candidate}</div>
            </div>
          )}
        </div>
      </section>

      {/* ── GEX ZONES ── */}
      {topZones.length > 0 && (
        <section>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '8px' }}>
            GEX ZONES
          </div>
          {topZones.map((zone, i) => (
            <ZoneRow key={i} zone={zone} />
          ))}
        </section>
      )}

      {/* ── ACTIVE SETUPS ── */}
      {allSetups.length > 0 && (
        <section>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '8px' }}>
            ACTIVE SETUPS <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(click to prefill)</span>
          </div>
          {allSetups.map((setup, i) => (
            <SetupRow key={i} setup={setup} onAlertClick={onAlertClick} />
          ))}
        </section>
      )}

      {/* ── DARK GAMMA ── */}
      {dark_gamma && dark_gamma.length > 0 && (
        <section>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '8px' }}>
            DARK GAMMA
          </div>
          {dark_gamma.map((dg, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '4px 0', borderBottom: '1px solid var(--border-subtle)',
              fontSize: '11px',
            }}>
              <span>{dg.ratio > 10 ? '🔴' : '🟡'}</span>
              <span style={{ color: 'white', minWidth: '52px' }}>{dg.strike}{dg.type === 'Call' ? 'C' : 'P'}</span>
              <span style={{ color: 'var(--text-muted)', flex: 1 }}>Vol/OI: {dg.ratio}×</span>
            </div>
          ))}
        </section>
      )}

      {/* ── ALERTS ── */}
      {alerts.length > 0 && (
        <section>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '8px' }}>
            LEVEL ALERTS
          </div>
          {alerts.slice(0, 6).map((alert, i) => (
            <AlertRow
              key={i}
              alert={alert}
              index={i}
              onAlertClick={onAlertClick}
              onDismiss={onDismissAlert}
            />
          ))}
        </section>
      )}
    </div>
  );
};

export default RegimePanel;
