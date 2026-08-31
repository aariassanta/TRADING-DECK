import React, { useState } from 'react';
import type {
  Recommendation,
  ScoreBreakdown,
  Leg,
  SpreadRecommendation,
} from '../../hooks/useMarketData';

interface RecommendationBannerProps {
  recommendation: Recommendation | null;
  connected: boolean;
  liveTradingArmed: boolean;
  positionOpen: boolean;
  executeComboTrade: (params: {
    legs: Leg[];
    qty?: number;
    expiry: '0DTE' | '1DTE' | 'WEEKLY' | string;
    tp_pct?: number;
    sl_ratio?: number;
    bracket?: boolean;
    transmit: boolean;
    target_env: 'paper' | 'live';
  }) => Promise<void>;
}

const INSTRUMENT_LABELS: Record<string, string> = {
  BUY_CALL: 'BUY CALL',
  BUY_PUT: 'BUY PUT',
  CCS: 'BEAR CALL SPREAD',
  PCS: 'BULL PUT SPREAD',
  IC: 'IRON CONDOR',
  NO_TRADE: 'NO TRADE',
};

const BREAKDOWN_LABELS: Record<keyof ScoreBreakdown, string> = {
  regimeBias:            'Regime + Bias',
  wallProximity:         'Wall Proximity',
  wallProximityCall:     'Wall Proximity (Call)',
  wallProximityPut:      'Wall Proximity (Put)',
  wallBreak:             'Wall Break',
  darkGamma:             'Dark Gamma',
  volumeOiDivergence:    'Vol / OI Divergence',
  wallOiBuildup:         'Wall OI Buildup',
  wallOiBuildupCall:     'Wall OI Buildup (Call)',
  wallOiBuildupPut:      'Wall OI Buildup (Put)',
  volumeLead:            'Volume Lead',
  breakoutRisk:          'Breakout Risk',
  netGexMultiplier:      'Net GEX (×)',
  regimeMagnitude:       'Regime Magnitude (×)',
  // DEX + Greeks factors
  dexImbalance:          'DEX Imbalance',
  gammaWallStickiness:   'Gamma @ Walls',
  thetaBleed:            'Theta Bleed',
  // TIER 2 quick-win factors
  pinningCandidate:      'Pinning Candidate',
  vixContext:            'VIX Context',
  setupConfluence:       'Setup Confluence',
  gexFlip:               'GEX Flip',
  calendarWeekday:       'Calendar Weekday',
  sessionPhase:          'Session Phase',
  positionState:         'Position State',
  // TIER 3 derived factors
  maxPainPull:           'Max Pain Pull',
  spreadEfficiency:      'Spread Efficiency',
  oiDelta:               'OI Delta (Dealer Magnet)',
};

const STYLE_LABELS: Record<string, string> = {
  DIRECTIONAL: '⚡ Directional',
  WALL_PUT:    '🛡 Wall Put',
  WALL_CALL:   '🛡 Wall Call',
  PINNING:     '📌 Pinning',
  BUTTERFLY:   '🦋 Butterfly',
  WAIT:        '⏸ Wait',
};

export const RecommendationBanner: React.FC<RecommendationBannerProps> = ({
  recommendation,
  connected,
  liveTradingArmed,
  positionOpen,
  executeComboTrade,
}) => {
  const [showTooltip, setShowTooltip] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [targetEnv, setTargetEnv] = useState<'paper' | 'live'>('paper');
  const [livePhrase, setLivePhrase] = useState('');
  const [showRationale, setShowRationale] = useState(false);

  if (!recommendation) {
    return (
      <div style={{
        background: 'linear-gradient(90deg, #1a1a2e 0%, #16213e 100%)',
        border: '1px solid #334155',
        borderRadius: '10px',
        padding: '14px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        color: '#64748b',
        fontSize: '13px',
        fontStyle: 'italic',
      }}>
        <span style={{ fontSize: '18px' }}>⏳</span>
        Awaiting 10-minute recommendation...
      </div>
    );
  }

  const isBullish = recommendation.direction === 'BULLISH';
  const isBearish = recommendation.direction === 'BEARISH';

  const dirColor = isBearish ? '#ef4444' : isBullish ? '#22c55e' : '#94a3b8';
  const bgGradient = isBearish
    ? 'linear-gradient(90deg, #7f1d1d 0%, #450a0a 100%)'
    : isBullish
    ? 'linear-gradient(90deg, #14532d 0%, #052e16 100%)'
    : 'linear-gradient(90deg, #1e293b 0%, #0f172a 100%)';

  const confidenceColors: Record<string, string> = { LOW: '#94a3b8', MEDIUM: '#f59e0b', HIGH: '#22c55e' };
  const confColor = confidenceColors[recommendation.confidence] ?? '#94a3b8';
  const score = recommendation.score;
  const absScore = Math.abs(score);
  const barWidth = Math.round((absScore / 3) * 100);

  const spread = recommendation.spread ?? null;
  const canExecute = !!spread && spread.legs.length > 0 && recommendation.instrument !== 'NO_TRADE';
  const isLiveSelected = targetEnv === 'live';
  const canSubmitLive = !isLiveSelected || (liveTradingArmed && livePhrase === 'ENABLE LIVE TRADING');
  const ageSeconds = Math.max(0, Date.now() / 1000 - recommendation.timestamp);
  const isStale = ageSeconds > 600; // > 10 min

  const executeBtnLabel = (() => {
    if (!spread) return '▶ EXECUTE';
    if (spread.legs.length === 1) {
      const l = spread.legs[0];
      return `▶ ${l.action} ${l.strike}${l.right}`;
    }
    const shorts = spread.legs.filter(l => l.action === 'SELL');
    const longs = spread.legs.filter(l => l.action === 'BUY');
    if (shorts.length === 1 && longs.length >= 1) {
      return `▶ ${shorts[0].right} ${shorts[0].strike}/${longs[0].strike}`;
    }
    return `▶ ${spread.legs.length}-LEG COMBO`;
  })();

  const handleExecute = async () => {
    if (!spread || !canSubmitLive) return;
    setExecuting(true);
    try {
      await executeComboTrade({
        legs: spread.legs,
        expiry: spread.expiry_hint ?? '0DTE',
        qty: 1,
        tp_pct: spread.tp_pct,
        sl_ratio: spread.sl_ratio,
        bracket: true,
        transmit: true,
        target_env: targetEnv,
      });
      setConfirmOpen(false);
      setLivePhrase('');
    } finally {
      setExecuting(false);
    }
  };

  const btnBg = isLiveSelected && liveTradingArmed
    ? '#dc2626'
    : targetEnv === 'paper' ? '#16a34a' : '#475569';

  return (
    <div
      className="recommendation-banner"
      style={{
        background: bgGradient,
        border: `1.5px solid ${dirColor}66`,
        borderRadius: '10px',
        padding: '14px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}
    >
      {/* Top row: label + direction + instrument + confidence + levels + time */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
        {/* "10-MIN REC" label */}
        <div style={{
          background: dirColor + '22',
          border: `1px solid ${dirColor}`,
          color: dirColor,
          borderRadius: '6px',
          padding: '4px 12px',
          fontSize: '11px',
          fontWeight: 800,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}>
          10-Min Rec
        </div>

        {/* Direction arrow + word */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '22px', lineHeight: 1 }}>
            {isBearish ? '🔻' : isBullish ? '🔺' : '➖'}
          </span>
          <span style={{
            fontSize: '18px',
            fontWeight: 800,
            color: dirColor,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
          }}>
            {recommendation.direction}
          </span>
        </div>

        {/* Instrument */}
        <div style={{
          background: '#ffffff10',
          borderRadius: '6px',
          padding: '4px 14px',
          fontSize: '15px',
          fontWeight: 700,
          color: '#ffffff',
          letterSpacing: '0.03em',
        }}>
          {INSTRUMENT_LABELS[recommendation.instrument] ?? recommendation.instrument}
        </div>

        {/* Style badge */}
        {recommendation.style && recommendation.style !== 'WAIT' && (
          <div style={{
            background: '#ffffff10',
            border: '1px solid #ffffff30',
            borderRadius: '6px',
            padding: '2px 10px',
            fontSize: '11px',
            fontWeight: 600,
            color: '#cbd5e1',
            letterSpacing: '0.04em',
          }}>
            {STYLE_LABELS[recommendation.style] ?? recommendation.style}
          </div>
        )}

        {/* Confidence */}
        <div style={{
          background: confColor + '22',
          border: `1px solid ${confColor}`,
          color: confColor,
          borderRadius: '6px',
          padding: '4px 12px',
          fontSize: '11px',
          fontWeight: 700,
          letterSpacing: '0.08em',
        }}>
          {recommendation.confidence} CONFIDENCE
        </div>

        {/* Anchor strike (derived from spread's first leg) */}
        {spread && spread.legs.length > 0 && (
          <div style={{ color: '#e2e8f0', fontSize: '14px', fontWeight: 600 }}>
            @ strike <strong style={{ color: '#f8fafc' }}>{spread.legs[0].strike}</strong>
          </div>
        )}

        {/* Spread legs as pills */}
        {spread && spread.legs.length > 0 && (
          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', alignItems: 'center' }}>
            {spread.legs.map((leg, i) => {
              const isBuy = leg.action === 'BUY';
              const color = leg.right === 'C' ? 'var(--accent-call)' : 'var(--accent-put)';
              const bg = isBuy ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)';
              return (
                <span key={i} style={{
                  background: bg,
                  border: `1px solid ${color}80`,
                  color: '#f1f5f9',
                  borderRadius: '4px',
                  padding: '2px 8px',
                  fontSize: '11px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-data, monospace)',
                  letterSpacing: '0.03em',
                }}>
                  {leg.action} {leg.strike}{leg.right}
                </span>
              );
            })}
            {spread.width > 0 && (
              <span style={{ fontSize: '10px', color: '#94a3b8', marginLeft: '4px' }}>
                W{spread.width}
              </span>
            )}
          </div>
        )}

        {/* ── EXECUTE button ── */}
        {canExecute && (
          <button
            type="button"
            onClick={() => setConfirmOpen(true)}
            disabled={!connected || positionOpen || isStale || executing}
            title={
              !connected ? 'Engine not connected'
              : positionOpen ? 'A position is already open'
              : isStale ? `Recommendation is ${Math.round(ageSeconds / 60)} min old`
              : `Click to execute ${recommendation.instrument}`
            }
            style={{
              background: btnBg,
              color: '#fff',
              fontWeight: 800,
              fontSize: '12px',
              padding: '8px 14px',
              border: 'none',
              borderRadius: '6px',
              cursor: (!connected || positionOpen || isStale || executing) ? 'not-allowed' : 'pointer',
              opacity: (!connected || positionOpen || isStale || executing) ? 0.5 : 1,
              boxShadow: '0 0 8px ' + btnBg + '80',
              animation: (!connected || positionOpen || isStale || executing) ? 'none' : 'pulse 1.5s infinite',
              letterSpacing: '0.06em',
              whiteSpace: 'nowrap',
            }}
          >
            {executing ? '⏳ EXECUTING…' : positionOpen ? '🔒 POSITION OPEN' : isStale ? '⏰ STALE' : executeBtnLabel}
          </button>
        )}

        {/* Timestamp */}
        <div style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: '12px' }}>
          {new Date(recommendation.timestamp * 1000).toLocaleTimeString()}
        </div>
      </div>

      {/* Rationale (collapsible) */}
      {spread?.rationale && (
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
          <button
            type="button"
            onClick={() => setShowRationale(!showRationale)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '11px',
              padding: 0,
              letterSpacing: '0.04em',
            }}
          >
            {showRationale ? '▼' : '▶'} rationale
          </button>
          {showRationale && (
            <span style={{ marginLeft: '8px', fontStyle: 'italic' }}>
              {spread.rationale}
            </span>
          )}
        </div>
      )}

      {/* Conviction bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {/* Info icon + tooltip */}
        <div style={{ position: 'relative' }}>
          <span
            onMouseEnter={() => setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
            style={{ fontSize: '14px', cursor: 'pointer', color: '#64748b', lineHeight: 1 }}
          >
            ⓘ
          </span>
          {showTooltip && recommendation.scoreBreakdown && (
            <div style={{
              position: 'absolute',
              bottom: '110%',
              left: 0,
              zIndex: 100,
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: '8px',
              padding: '12px 14px',
              minWidth: '260px',
              boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
              maxHeight: '70vh',
              overflowY: 'auto',
            }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8 }}>
                Score Breakdown
              </div>
              {Object.entries(recommendation.scoreBreakdown).map(([key, value]) => {
                const label = BREAKDOWN_LABELS[key as keyof ScoreBreakdown] ?? key;
                const num = typeof value === 'number' ? value : 0;
                const isMultiplier = key.includes('Multiplier');
                const barFrac = isMultiplier ? Math.min(Math.abs(num - 1) / 0.4, 1) : Math.min(Math.abs(num) / 3, 1);
                const itemColor = num > 0 ? '#22c55e' : num < 0 ? '#ef4444' : '#475569';
                return (
                  <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8', width: 150, flexShrink: 0 }}>{label}</div>
                    <div style={{ flex: 1, height: 4, background: '#1e293b', borderRadius: 2 }}>
                      {num !== 0 && (
                        <div style={{
                          width: `${barFrac * 100}%`,
                          height: '100%',
                          background: itemColor,
                          borderRadius: 2,
                          marginLeft: num < 0 ? 'auto' : 0,
                        }} />
                      )}
                    </div>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: itemColor, width: 50, textAlign: 'right' }}>
                      {isMultiplier ? `${num.toFixed(2)}×` : (num > 0 ? `+${num.toFixed(1)}` : num.toFixed(1))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <span style={{ fontSize: '11px', color: '#64748b', width: 64, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Conviction</span>
        <div style={{ flex: 1, height: '8px', background: '#1e293b', borderRadius: '4px', overflow: 'hidden' }}>
          <div style={{
            width: `${barWidth}%`,
            height: '100%',
            background: `linear-gradient(90deg, ${dirColor}cc, ${dirColor})`,
            borderRadius: '4px',
            transition: 'width 0.6s ease',
          }} />
        </div>
        <span style={{ fontSize: '14px', fontWeight: 700, color: dirColor, width: 48, textAlign: 'right' }}>
          {score >= 0 ? '+' : ''}{score.toFixed(2)}
        </span>
      </div>

      {/* ── CONFIRMATION DIALOG (modal) ── */}
      {confirmOpen && spread && (
        <div
          onClick={() => !executing && setConfirmOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            className="modal-card"
            style={{
              background: '#0f172a',
              border: `1.5px solid ${dirColor}80`,
              borderRadius: '12px',
              padding: '20px 24px',
              minWidth: '480px',
              maxWidth: '560px',
              boxShadow: '0 20px 60px rgba(0,0,0,0.7)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{
                fontSize: '14px',
                fontWeight: 800,
                color: dirColor,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
              }}>
                ⚡ Confirm Trade
              </div>
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                disabled={executing}
                style={{ background: 'transparent', border: 'none', color: '#94a3b8', fontSize: '20px', cursor: 'pointer' }}
              >
                ×
              </button>
            </div>

            {/* Summary */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', marginBottom: 16, fontSize: '12px' }}>
              <div><span style={{ color: '#94a3b8' }}>Instrument:</span></div>
              <div style={{ color: '#f1f5f9', fontWeight: 700 }}>{INSTRUMENT_LABELS[recommendation.instrument]}</div>

              <div><span style={{ color: '#94a3b8' }}>Direction:</span></div>
              <div style={{ color: dirColor, fontWeight: 700 }}>{recommendation.direction}</div>

              <div><span style={{ color: '#94a3b8' }}>Qty:</span></div>
              <div style={{ color: '#f1f5f9' }}>1</div>

              {spread.width > 0 && (
                <>
                  <div><span style={{ color: '#94a3b8' }}>Width:</span></div>
                  <div style={{ color: '#f1f5f9' }}>${spread.width}</div>
                </>
              )}

              <div><span style={{ color: '#94a3b8' }}>TP / SL:</span></div>
              <div style={{ color: '#f1f5f9' }}>{spread.tp_pct}% / {spread.sl_ratio}×</div>

              <div><span style={{ color: '#94a3b8' }}>Expiry:</span></div>
              <div style={{ color: '#f1f5f9' }}>{spread.expiry_hint ?? '0DTE'}</div>

              <div><span style={{ color: '#94a3b8' }}>Style:</span></div>
              <div style={{ color: '#f1f5f9' }}>{STYLE_LABELS[recommendation.style ?? ''] ?? recommendation.style ?? '—'}</div>
            </div>

            {/* Legs */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: '11px', color: '#94a3b8', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
                Legs
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {spread.legs.map((leg, i) => (
                  <div key={i} style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    padding: '6px 10px',
                    background: '#1e293b',
                    borderRadius: '4px',
                    fontSize: '12px',
                    fontFamily: 'var(--font-data, monospace)',
                  }}>
                    <span style={{ color: leg.action === 'BUY' ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                      {leg.action}
                    </span>
                    <span style={{ color: '#f1f5f9' }}>
                      {leg.strike} {leg.right === 'C' ? 'CALL' : 'PUT'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Rationale */}
            <div style={{
              fontSize: '11px',
              color: '#cbd5e1',
              fontStyle: 'italic',
              background: '#1e293b',
              padding: '8px 10px',
              borderRadius: '4px',
              marginBottom: 16,
            }}>
              💡 {spread.rationale}
            </div>

            {/* Environment radio */}
            <div style={{ display: 'flex', gap: '12px', marginBottom: 16 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px', color: '#f1f5f9' }}>
                <input type="radio" name="execEnv" value="paper" checked={targetEnv === 'paper'} onChange={() => setTargetEnv('paper')} disabled={executing} />
                <span>PAPER</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: connected ? 'pointer' : 'not-allowed', fontSize: '13px', color: liveTradingArmed ? '#ef4444' : '#64748b' }}>
                <input type="radio" name="execEnv" value="live" checked={targetEnv === 'live'} onChange={() => setTargetEnv('live')} disabled={!liveTradingArmed || executing} />
                <span>LIVE {!liveTradingArmed && '🔒'}</span>
              </label>
            </div>

            {/* Live confirmation phrase */}
            {isLiveSelected && liveTradingArmed && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: '11px', color: '#ef4444', marginBottom: 4, fontWeight: 700 }}>
                  ⚠ LIVE = REAL MONEY. Type the phrase to confirm:
                </div>
                <input
                  type="text"
                  value={livePhrase}
                  onChange={e => setLivePhrase(e.target.value)}
                  disabled={executing}
                  placeholder="ENABLE LIVE TRADING"
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    background: '#1e293b',
                    border: livePhrase === 'ENABLE LIVE TRADING' ? '1px solid #22c55e' : '1px solid #475569',
                    borderRadius: '4px',
                    color: '#f1f5f9',
                    fontSize: '12px',
                    fontFamily: 'var(--font-data, monospace)',
                  }}
                />
              </div>
            )}

            {/* Buttons */}
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                disabled={executing}
                style={{
                  padding: '8px 16px',
                  background: '#475569',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: executing ? 'not-allowed' : 'pointer',
                  fontSize: '12px',
                  fontWeight: 600,
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleExecute}
                disabled={!canSubmitLive || executing}
                style={{
                  padding: '8px 16px',
                  background: isLiveSelected ? '#dc2626' : '#16a34a',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: (!canSubmitLive || executing) ? 'not-allowed' : 'pointer',
                  opacity: (!canSubmitLive || executing) ? 0.5 : 1,
                  fontSize: '12px',
                  fontWeight: 800,
                  letterSpacing: '0.06em',
                }}
              >
                {executing ? '⏳ EXECUTING…' : `▶ ${isLiveSelected ? 'EXECUTE LIVE' : 'EXECUTE'}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* CSS for pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 8px var(--btn-glow, rgba(34, 197, 94, 0.5)); }
          50% { box-shadow: 0 0 16px var(--btn-glow, rgba(34, 197, 94, 0.9)); }
        }
      `}</style>
    </div>
  );
};
