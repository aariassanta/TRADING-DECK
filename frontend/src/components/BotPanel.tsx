import React, { useState } from 'react';
import { useBot } from '../hooks/useBot';
import type { BotSignal, BotTrade } from '../hooks/useBot';
import type { GexData } from '../hooks/useMarketData';
import { HelpTooltip } from './gamma-hunter';

interface BotPanelProps {
  metrics: GexData | null;
}

const STRATEGIES = ['FLIP', 'PINNING', 'TREND', 'ORB', 'ORB15', 'IRON_FLY', 'MILK_MAN'] as const;

const STRATEGY_COLORS: Record<string, string> = {
  FLIP: 'var(--accent-spot)',
  PINNING: 'var(--accent-call)',
  TREND: 'var(--accent-put)',
  ORB: '#f59e0b',
  ORB15: '#a78bfa',
  IRON_FLY: '#ec4899',
  MILK_MAN: '#06b6d4',
};

const STRATEGY_LABELS: Record<string, string> = {
  FLIP: '📊 Flip (GEX Cross)',
  PINNING: '📍 Pinning (Iron Condor)',
  TREND: '📈 Trend Rider',
  ORB: '🔷 ORB (Open Range)',
  ORB15: '🔶 ORB-15 (Spread)',
  IRON_FLY: '🦋 Iron Fly (0DTE 1:45PM)',
  MILK_MAN: '🥛 Milk Man (Weekly)',
};

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  FLIP: 'Activa cuando el GEX cruza cero (positivo→negativo o viceversa). Requiere |GEX| ≥ $5M y bias no neutral. Genera Bull Put o Bear Call según dirección. Credit $2.50, TP=50%, SL=2×.',
  PINNING: 'Requiere régimen LONG_GAMMA + breakout_risk ≠ HIGH + paredes (put_wall o call_wall presentes). Genera Iron Condor simétrico ancho $5. Credit $4.00, TP=50%, SL=2×.',
  TREND: 'Requiere régimen SHORT_GAMMA + bias no neutral + breakout_risk = LOW. Genera Bull Put o Bear Call en la pared correspondiente. Credit $2.50, TP=60% (más agresivo), SL=2×.',
  ORB: 'Opera entre 9:30–10:30 ET.tras definir rango de apertura, busca el primer quiebre direccional. Genera compra de call/put simple con entry en midpoint del rango, TP en high/low según dirección. Confidence 75%.',
  ORB15: 'Usa rango de las primeras 3 barras de 5min (9:30–9:45 ET). Requiere: 1) ruptura inicial del rango, 2) pullback, 3) re-ruptura con vela de cuerpo ≥2× mediana del día. Genera PCS o CCS con buffer 0.5%. Confidence 75%.',
  IRON_FLY: 'Solo opera L–J (no Miércoles). Window 13:40–13:55 ET. Requiere VIX 15–20. Strikes en delta ±0.50/0.40, alas $15 wide. Sin TP/SL, se lleva a expiry. Credit ~$4.00.',
  MILK_MAN: 'Weekly PCS ogni Lunedì 10:00 ET. Short strike = prev_week_close − ATR14×√7. Width 50pts. Filtro odds: salta se odds ≥ mediana_1Y. Hold-to-settlement. Credit ~$2.50.',
};

export const BotPanel: React.FC<BotPanelProps> = ({ metrics }) => {
  const {
    status,
    trades,
    startBot,
    stopBot,
    toggleStrategy,
    toggleAutoMode,
    executeSignal,
    forceScan,
    fetchTrades,
  } = useBot();

  const [isExecuting, setIsExecuting] = useState(false);
  const [showLog, setShowLog] = useState(false);

  const handleExecute = async (signal: BotSignal) => {
    setIsExecuting(true);
    try {
      const result = await executeSignal(signal);
      if (!result.ok) {
        window.alert(`❌ Execution failed: ${result.error}`);
      }
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

      {/* ── Bot ON/OFF ── */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px', borderRadius: '6px',
        background: status.running ? 'var(--accent-call)' : 'var(--bg-abyss)',
        color: status.running ? 'var(--text-primary)' : 'var(--text-primary)',
        border: `1px solid ${status.running ? 'var(--accent-call)' : 'var(--border-subtle)'}`,
      }}>
        <div>
          <div style={{ fontWeight: '900', fontSize: '14px' }}>🤖 0DTE GEX Bot</div>
          <div style={{ fontSize: '10px', opacity: 0.7, marginTop: '2px' }}>
            {status.running ? 'SCANNING every 5 min' : 'STOPPED'}
          </div>
        </div>
        <button
          onClick={() => status.running ? stopBot() : startBot()}
          style={{
            padding: '8px 18px',
            background: status.running ? 'var(--accent-put)' : 'var(--accent-call)',
            color: 'black', fontWeight: '900', border: 'none',
            borderRadius: '4px', cursor: 'pointer', fontSize: '12px',
          }}
        >
          {status.running ? 'STOP' : 'START'}
        </button>
      </div>

      {/* ── Auto / Manual Mode ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        padding: '8px 12px', borderRadius: '6px',
        background: status.auto_mode ? 'rgba(0,255,136,0.08)' : 'var(--bg-abyss)',
        border: `1px solid ${status.auto_mode ? 'var(--accent-call)' : 'var(--border-subtle)'}`,
      }}>
        <div style={{ fontSize: '11px', fontWeight: 'bold', color: 'var(--text-muted)' }}>
          MODE
        </div>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto' }}>
          <button
            onClick={() => toggleAutoMode(false)}
            style={{
              padding: '4px 12px',
              background: !status.auto_mode ? 'var(--accent-call)' : 'var(--bg-surface-elevated)',
              color: !status.auto_mode ? 'black' : 'var(--text-muted)',
              fontWeight: 'bold', border: 'none',
              borderRadius: '4px', cursor: 'pointer', fontSize: '11px',
            }}
          >
            MANUAL
          </button>
          <button
            onClick={() => toggleAutoMode(true)}
            style={{
              padding: '4px 12px',
              background: status.auto_mode ? 'var(--accent-call)' : 'var(--bg-surface-elevated)',
              color: status.auto_mode ? 'black' : 'var(--text-muted)',
              fontWeight: 'bold', border: 'none',
              borderRadius: '4px', cursor: 'pointer', fontSize: '11px',
            }}
          >
            AUTO
          </button>
        </div>
        {status.auto_mode && (
          <div style={{
            marginLeft: '8px', fontSize: '10px', fontWeight: 'bold',
            color: 'var(--accent-call)',
          }}>
            ⚡ NO CONFIRM
          </div>
        )}
      </div>

      {/* ── Strategy Toggles ── */}
      <div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px', fontWeight: 'bold' }}>
          STRATEGIES
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {STRATEGIES.map(strategy => (
            <label
              key={strategy}
              style={{
                display: 'flex', alignItems: 'center', gap: '8px',
                padding: '8px 10px', borderRadius: '4px',
                background: 'var(--bg-abyss)',
                border: `1px solid ${status.enabled_strategies.includes(strategy) ? STRATEGY_COLORS[strategy] : 'var(--border-subtle)'}`,
                cursor: 'pointer', fontSize: '12px',
              }}
            >
              <input
                type="checkbox"
                checked={status.enabled_strategies.includes(strategy)}
                onChange={e => toggleStrategy(strategy, e.target.checked)}
                style={{ accentColor: STRATEGY_COLORS[strategy] }}
              />
              <span style={{ color: status.enabled_strategies.includes(strategy) ? STRATEGY_COLORS[strategy] : 'var(--text-muted)' }}>
                {STRATEGY_LABELS[strategy]}
              </span>
              <HelpTooltip content={STRATEGY_DESCRIPTIONS[strategy]} mode="hover" />
              {status.active_positions[strategy] && (
                <span style={{ marginLeft: 'auto', fontSize: '10px', color: 'var(--accent-call)' }}>
                  ● OPEN
                </span>
              )}
            </label>
          ))}
        </div>
      </div>

      {/* ── Current Signal ── */}
      {status.current_signal ? (
        <div style={{
          padding: '14px', borderRadius: '6px',
          background: 'var(--bg-abyss)',
          border: `2px solid ${STRATEGY_COLORS[status.current_signal.strategy]}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{
              fontSize: '11px', fontWeight: 'bold',
              color: STRATEGY_COLORS[status.current_signal.strategy],
            }}>
              {status.current_signal.strategy}
            </span>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
              {Math.round(status.current_signal.confidence * 100)}% confidence
            </span>
          </div>

          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>
            {status.current_signal.direction === 'IC' ? 'Iron Condor' : (
              status.current_signal.direction === 'BULL_PUT' ? 'Bull Put Spread' :
              status.current_signal.direction === 'BEAR_CALL' ? 'Bear Call Spread' :
              status.current_signal.direction === 'BUY_CALL' ? 'Buy Call' :
              status.current_signal.direction === 'BUY_PUT' ? 'Buy Put' : 'Unknown'
            )}
          </div>

          <div style={{ display: 'flex', gap: '12px', fontSize: '13px', fontWeight: 'bold', marginBottom: '8px' }}>
            <span style={{ color: 'var(--accent-put)' }}>
              {status.current_signal.direction === 'IC'
                ? `${status.current_signal.short_strike} / ${status.current_signal.long_strike}`
                : `${status.current_signal.short_strike} → ${status.current_signal.long_strike}`}
            </span>
          </div>

          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
            Credit: <span style={{ color: 'var(--accent-call)' }}>${status.current_signal.entry_credit.toFixed(2)}</span>
            {' '}· TP: <span style={{ color: 'var(--accent-call)' }}>${status.current_signal.tp_credit.toFixed(2)}</span>
            {' '}· SL: <span style={{ color: 'var(--accent-put)' }}>${status.current_signal.sl_credit.toFixed(2)}</span>
          </div>

          {status.current_signal.entry_trigger && (
            <div style={{
              fontSize: '10px', color: '#f59e0b', marginBottom: '4px',
              padding: '4px 6px', background: 'rgba(245,158,11,0.1)', borderRadius: '4px',
            }}>
              ⏱ Entry: <strong>{status.current_signal.entry_trigger.toFixed(0)}</strong>
              {' '}· TP: <strong>{status.current_signal.tp_trigger?.toFixed(0)}</strong>
              {' '}· SL: <strong>{status.current_signal.sl_trigger?.toFixed(0)}</strong>
            </div>
          )}

          <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: '12px' }}>
            {status.current_signal.reason}
          </div>

          {status.auto_mode ? (
            <div style={{
              width: '100%', padding: '10px', textAlign: 'center',
              background: 'rgba(0,255,136,0.1)', border: '1px solid var(--accent-call)',
              borderRadius: '4px', fontSize: '12px', fontWeight: 'bold',
              color: 'var(--accent-call)',
            }}>
              ⚡ AUTO-EXECUTE ENABLED — Bot trades automatically
            </div>
          ) : (
            <button
              onClick={() => handleExecute(status.current_signal!)}
              disabled={isExecuting}
              style={{
                width: '100%', padding: '10px',
                background: isExecuting ? 'var(--bg-surface-elevated)' : 'var(--accent-call)',
                color: 'black', fontWeight: '900', border: 'none',
                borderRadius: '4px', cursor: isExecuting ? 'default' : 'pointer',
                fontSize: '12px',
              }}
            >
              {isExecuting ? 'EXECUTING...' : '✅ EXECUTE SIGNAL'}
            </button>
          )}
        </div>
      ) : (
        <div style={{
          padding: '20px', textAlign: 'center',
          color: 'var(--text-muted)', fontSize: '12px',
          border: '1px dashed var(--border-subtle)', borderRadius: '6px',
        }}>
          {status.running
            ? '⏳ Scanning... (next signal in up to 5 min)'
            : '🔘 Bot stopped — no signal available'}
        </div>
      )}

      {/* ── Force Scan Button ── */}
      <button
        onClick={forceScan}
        style={{
          padding: '8px',
          background: 'var(--bg-abyss)', color: 'var(--text-primary)',
          border: '1px solid var(--border-subtle)', borderRadius: '4px',
          cursor: 'pointer', fontSize: '11px',
        }}
      >
        🔄 Force Scan Now
      </button>

      {/* ── Daily Stats ── */}
      <div style={{
        padding: '12px', borderRadius: '6px',
        background: 'var(--bg-abyss)', fontSize: '11px',
      }}>
        <div style={{ color: 'var(--text-muted)', marginBottom: '6px', fontWeight: 'bold' }}>TODAY</div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
          <span>P&L</span>
          <span style={{
            color: status.daily_pnl >= 0 ? 'var(--accent-call)' : 'var(--accent-put)',
            fontWeight: 'bold',
          }}>
            {status.daily_pnl >= 0 ? '+' : ''}{status.daily_pnl.toFixed(2)}
          </span>
        </div>
        {status.limits_reached && (
          <div style={{
            marginTop: '8px', padding: '6px', borderRadius: '4px',
            background: 'rgba(255,0,85,0.15)', border: '1px solid var(--accent-put)',
            color: 'var(--accent-put)', fontSize: '10px', fontWeight: 'bold',
          }}>
            ⚠️ DAILY LIMIT REACHED — Bot stopped
          </div>
        )}
      </div>

      {/* ── Trade Log ── */}
      {status.daily_trades.length > 0 && (
        <div style={{
          padding: '12px', borderRadius: '6px',
          background: 'var(--bg-abyss)', fontSize: '11px',
        }}>
          <div style={{ color: 'var(--text-muted)', marginBottom: '8px', fontWeight: 'bold' }}>
            TRADE LOG ({status.daily_trades.length}/3)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {status.daily_trades.map((trade: BotTrade, i: number) => (
              <div key={i} style={{
                padding: '8px', borderRadius: '4px',
                background: 'var(--bg-surface-elevated)',
                border: `1px solid ${STRATEGY_COLORS[trade.strategy] || 'var(--border-subtle)'}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
                  <span style={{ fontWeight: 'bold', color: STRATEGY_COLORS[trade.strategy] || 'var(--text-primary)', fontSize: '10px' }}>
                    {trade.strategy}
                  </span>
                  <span style={{ color: 'var(--text-muted)', fontSize: '9px' }}>
                    {new Date(trade.timestamp * 1000).toLocaleTimeString()}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>
                    {trade.direction === 'IC' ? 'Iron Condor' : trade.direction === 'BULL_PUT' ? 'Bull Put' : 'Bear Call'}
                  </span>
                  <span style={{ color: 'var(--accent-call)', fontWeight: 'bold' }}>
                    ${trade.entry_credit.toFixed(2)}
                  </span>
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '10px', marginTop: '2px' }}>
                  {trade.short_strike}
                  {trade.long_strike ? ` / ${trade.long_strike}` : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Strategy Signals ── */}
      {status.evaluation && (
        <div style={{
          padding: '12px', borderRadius: '6px',
          background: 'var(--bg-abyss)', fontSize: '11px',
        }}>
          <div style={{ color: 'var(--text-muted)', marginBottom: '8px', fontWeight: 'bold' }}>
            📡 STRATEGY SIGNALS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {/* FLIP */}
            {(() => {
              const e = status.evaluation?.FLIP;
              if (!e || !e.enabled) return null;
              return (
                <div style={{
                  padding: '8px', borderRadius: '4px',
                  background: 'var(--bg-surface-elevated)',
                  border: `1px solid ${e.signals ? 'var(--accent-spot)' : 'var(--border-subtle)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                    <span style={{ fontWeight: 'bold', color: 'var(--accent-spot)', fontSize: '11px' }}>📊 FLIP</span>
                    <span style={{
                      fontWeight: 'bold', fontSize: '10px',
                      color: e.signals ? 'var(--accent-spot)' : 'var(--text-muted)',
                    }}>
                      {e.signals ? '✅ SIGNAL' : '❌ no signal'}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    <span>prev GEX: {e.prev_net_gex?.toFixed(1) ?? '---'}M → curr: {e.net_gex?.toFixed(1) ?? '---'}M</span>
                    <span>flipped: {String(!!e.flipped)} | abs&gt;5M: {String(!!e.abs_net_gex_ok)}</span>
                    <span>bias: {e.bias ?? '---'}</span>
                  </div>
                </div>
              );
            })()}

            {/* PINNING */}
            {(() => {
              const e = status.evaluation?.PINNING;
              if (!e || !e.enabled) return null;
              return (
                <div style={{
                  padding: '8px', borderRadius: '4px',
                  background: 'var(--bg-surface-elevated)',
                  border: `1px solid ${e.signals ? 'var(--accent-call)' : 'var(--border-subtle)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                    <span style={{ fontWeight: 'bold', color: 'var(--accent-call)', fontSize: '11px' }}>📍 PINNING</span>
                    <span style={{
                      fontWeight: 'bold', fontSize: '10px',
                      color: e.signals ? 'var(--accent-call)' : 'var(--text-muted)',
                    }}>
                      {e.signals ? '✅ SIGNAL' : '❌ no signal'}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    <span>regime: {e.regime ?? '---'} → {e.regime_ok ? '✅ LONG_GAMMA' : '❌'}</span>
                    <span>breakout: {e.breakout_risk ?? '---'} → {e.breakout_ok ? '✅ not HIGH' : '❌'}</span>
                    <span>call_wall: {e.call_wall} | put_wall: {e.put_wall}</span>
                  </div>
                </div>
              );
            })()}

            {/* TREND */}
            {(() => {
              const e = status.evaluation?.TREND;
              if (!e || !e.enabled) return null;
              return (
                <div style={{
                  padding: '8px', borderRadius: '4px',
                  background: 'var(--bg-surface-elevated)',
                  border: `1px solid ${e.signals ? 'var(--accent-put)' : 'var(--border-subtle)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                    <span style={{ fontWeight: 'bold', color: 'var(--accent-put)', fontSize: '11px' }}>📈 TREND</span>
                    <span style={{
                      fontWeight: 'bold', fontSize: '10px',
                      color: e.signals ? 'var(--accent-put)' : 'var(--text-muted)',
                    }}>
                      {e.signals ? '✅ SIGNAL' : '❌ no signal'}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    <span>regime: {e.regime ?? '---'} → {e.regime_ok ? '✅ SHORT_GAMMA' : '❌'}</span>
                    <span>bias: {e.bias ?? '---'} → {e.bias_ok ? '✅ directional' : '❌'}</span>
                    <span>breakout: {e.breakout_risk ?? '---'} → {e.breakout_ok ? '✅ LOW' : '❌'}</span>
                  </div>
                </div>
              );
            })()}

            {/* ORB15 */}
            {(() => {
              const e = status.evaluation?.ORB15;
              if (!e || !e.enabled) return null;
              return (
                <div style={{
                  padding: '8px', borderRadius: '4px',
                  background: 'var(--bg-surface-elevated)',
                  border: `1px solid ${e.signals ? '#a78bfa' : 'var(--border-subtle)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                    <span style={{ fontWeight: 'bold', color: '#a78bfa', fontSize: '11px' }}>🔶 ORB15</span>
                    <span style={{
                      fontWeight: 'bold', fontSize: '10px',
                      color: e.signals ? '#a78bfa' : 'var(--text-muted)',
                    }}>
                      {e.signals ? '✅ SIGNAL' : '❌ no signal'}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    <span>step: {e.step ?? '---'}</span>
                    <span>session_open: {e.session_open?.toFixed(0) ?? '---'}</span>
                    <span>breakout: {e.breakout_dir ?? '---'} | pullback: {String(!!e.pullback_seen)}</span>
                    <span>rebreakout: {e.rebreakout_dir ?? '---'} | body: {e.rebreakout_body?.toFixed(1) ?? '---'}</span>
                    <span>median_body: {e.median_body?.toFixed(1) ?? '---'} | 2×median: {((e.median_body ?? 0) * 2).toFixed(1)}</span>
                  </div>
                </div>
              );
            })()}

            {/* IRON_FLY */}
            {(() => {
              const e = status.evaluation?.IRON_FLY;
              if (!e || !e.enabled) return null;
              return (
                <div style={{
                  padding: '8px', borderRadius: '4px',
                  background: 'var(--bg-surface-elevated)',
                  border: `1px solid ${e.signals ? '#ec4899' : 'var(--border-subtle)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                    <span style={{ fontWeight: 'bold', color: '#ec4899', fontSize: '11px' }}>🦋 IRON_FLY</span>
                    <span style={{
                      fontWeight: 'bold', fontSize: '10px',
                      color: e.signals ? '#ec4899' : 'var(--text-muted)',
                    }}>
                      {e.signals ? '✅ SIGNAL' : '❌ no signal'}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    <span>now ET: {e.now_et ?? '---'} → {e.in_window ? '✅ in window' : '❌ outside 13:40-13:55'}</span>
                    <span>day: {e.is_wednesday ? '❌ Wed (skip)' : '✅ L/M/J/V'}</span>
                    <span>VIX: {e.vix?.toFixed(2) ?? '---'} → {(e.vix ?? 0) >= 15 && (e.vix ?? 0) <= 20 ? '✅ 15-20' : '❌'}</span>
                    <span>deltas: put {e.delta_put?.toFixed(2) ?? '---'} | call {e.delta_call?.toFixed(2) ?? '---'}</span>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {/* ── ORB Status ── */}
      {status.orb && (
        <div style={{
          padding: '12px', borderRadius: '6px',
          background: 'var(--bg-abyss)', fontSize: '11px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontWeight: 'bold', color: '#f59e0b' }}>🔷 ORB STATUS</span>
            <span style={{
              fontWeight: 'bold', fontSize: '10px',
              color: status.orb.session_active ? '#f59e0b'
                : status.orb.evaluated ? (status.orb.direction ? 'var(--accent-call)' : 'var(--text-muted)')
                : 'var(--text-muted)',
            }}>
              {status.orb.session_active ? '⏳ TRACKING (9:30–10:30 EST)'
                : status.orb.evaluated ? (status.orb.direction ? `📌 ${status.orb.direction}` : '— no direction')
                : '— waiting'}
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '8px' }}>
            <div style={{ textAlign: 'center', padding: '8px', background: 'var(--bg-surface-elevated)', borderRadius: '4px' }}>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '2px' }}>HIGH</div>
              <div style={{ fontWeight: 'bold', color: 'var(--accent-call)', fontSize: '13px' }}>
                {status.orb.high != null ? status.orb.high.toFixed(0) : '---'}
              </div>
            </div>
            <div style={{ textAlign: 'center', padding: '8px', background: 'var(--bg-surface-elevated)', borderRadius: '4px' }}>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '2px' }}>MID</div>
              <div style={{ fontWeight: 'bold', color: '#f59e0b', fontSize: '13px' }}>
                {status.orb.mid != null ? status.orb.mid.toFixed(0) : '---'}
              </div>
            </div>
            <div style={{ textAlign: 'center', padding: '8px', background: 'var(--bg-surface-elevated)', borderRadius: '4px' }}>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '2px' }}>LOW</div>
              <div style={{ fontWeight: 'bold', color: 'var(--accent-put)', fontSize: '13px' }}>
                {status.orb.low != null ? status.orb.low.toFixed(0) : '---'}
              </div>
            </div>
          </div>
          {status.orb.evaluated && status.orb.direction && (
            <div style={{
              padding: '6px 8px', borderRadius: '4px', fontSize: '10px',
              background: 'rgba(245,158,11,0.1)',
              border: '1px solid #f59e0b', color: '#f59e0b',
              textAlign: 'center',
            }}>
              {status.orb.direction === 'BULLISH'
                ? '📈 CALL — entry at MID, TP at HIGH, SL at LOW'
                : '📉 PUT — entry at MID, TP at LOW, SL at HIGH'}
            </div>
          )}
        </div>
      )}

      {/* ── ORB15 Status ── */}
      {status.orb15 && (
        <div style={{
          padding: '12px', borderRadius: '6px',
          background: 'var(--bg-abyss)', fontSize: '11px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontWeight: 'bold', color: '#a78bfa' }}>🔶 ORB15 STATUS</span>
            <span style={{
              fontWeight: 'bold', fontSize: '10px',
              color: status.orb15.step === 'signalled' ? '#a78bfa'
                : status.orb15.step === 'rebreakout' ? 'var(--accent-call)'
                : 'var(--text-muted)',
            }}>
              {status.orb15.step ?? '---'}
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '8px' }}>
            <div style={{ textAlign: 'center', padding: '8px', background: 'var(--bg-surface-elevated)', borderRadius: '4px' }}>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '2px' }}>HIGH</div>
              <div style={{ fontWeight: 'bold', color: 'var(--accent-call)', fontSize: '13px' }}>
                {status.orb15.high != null ? status.orb15.high.toFixed(0) : '---'}
              </div>
            </div>
            <div style={{ textAlign: 'center', padding: '8px', background: 'var(--bg-surface-elevated)', borderRadius: '4px' }}>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '2px' }}>RANGE</div>
              <div style={{ fontWeight: 'bold', color: '#a78bfa', fontSize: '13px' }}>
                {status.orb15.range != null ? status.orb15.range.toFixed(0) : '---'}
              </div>
            </div>
            <div style={{ textAlign: 'center', padding: '8px', background: 'var(--bg-surface-elevated)', borderRadius: '4px' }}>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '2px' }}>LOW</div>
              <div style={{ fontWeight: 'bold', color: 'var(--accent-put)', fontSize: '13px' }}>
                {status.orb15.low != null ? status.orb15.low.toFixed(0) : '---'}
              </div>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
            <div style={{ textAlign: 'center', padding: '6px', background: 'var(--bg-surface-elevated)', borderRadius: '4px' }}>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>SESSION OPEN</div>
              <div style={{ fontWeight: 'bold', color: '#a78bfa', fontSize: '12px' }}>
                {status.orb15.session_open != null ? status.orb15.session_open.toFixed(0) : '---'}
              </div>
            </div>
            <div style={{ textAlign: 'center', padding: '6px', background: 'var(--bg-surface-elevated)', borderRadius: '4px' }}>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>MEDIAN BODY</div>
              <div style={{ fontWeight: 'bold', color: '#a78bfa', fontSize: '12px' }}>
                {status.orb15.median_body != null ? status.orb15.median_body.toFixed(1) : '---'}
              </div>
            </div>
          </div>
          {status.orb15.rebreakout_dir && (
            <div style={{
              padding: '6px 8px', borderRadius: '4px', fontSize: '10px',
              background: 'rgba(167,139,250,0.1)',
              border: '1px solid #a78bfa', color: '#a78bfa',
              textAlign: 'center',
            }}>
              {status.orb15.rebreakout_dir === 'bull'
                ? '📈 PCS — rebreakout bullish'
                : '📉 CCS — rebreakout bearish'}
              {status.orb15.rebreakout_body != null && status.orb15.median_body != null && (
                <span> | body={status.orb15.rebreakout_body.toFixed(1)} ≥ 2×{status.orb15.median_body.toFixed(1)}={status.orb15.rebreakout_body >= 2 * status.orb15.median_body ? '✅' : '❌'}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Regime Info ── */}
      {metrics && (
        <div style={{
          padding: '12px', borderRadius: '6px',
          background: 'var(--bg-abyss)', fontSize: '11px',
        }}>
          <div style={{ color: 'var(--text-muted)', marginBottom: '6px', fontWeight: 'bold' }}>REGIME</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span>Net GEX</span>
            <span style={{ color: metrics.net_gex_total >= 0 ? 'var(--accent-call)' : 'var(--accent-put)', fontWeight: 'bold' }}>
              {metrics.net_gex_total >= 0 ? '+' : ''}{metrics.net_gex_total?.toFixed(1)}M
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span>Regime</span>
            <span style={{ fontWeight: 'bold', color: metrics.regime === 'LONG_GAMMA' ? 'var(--accent-call)' : metrics.regime === 'SHORT_GAMMA' ? 'var(--accent-put)' : 'var(--text-muted)' }}>
              {metrics.regime?.replace('_', ' ')}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span>Bias</span>
            <span style={{ fontWeight: 'bold', color: metrics.bias === 'BULLISH' ? 'var(--accent-call)' : metrics.bias === 'BEARISH' ? 'var(--accent-put)' : 'var(--text-muted)' }}>
              {metrics.bias}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>Gamma Flip</span>
            <span style={{ color: 'var(--accent-spot)', fontWeight: 'bold' }}>{metrics.gamma_flip ?? '---'}</span>
          </div>
        </div>
      )}

      {/* ── Trade Log Toggle ── */}
      <button
        onClick={() => {
          if (!showLog) fetchTrades();
          setShowLog(v => !v);
        }}
        style={{
          width: '100%', padding: '8px', borderRadius: '6px',
          background: showLog ? 'var(--accent-call)' : 'var(--bg-abyss)',
          color: showLog ? 'black' : 'var(--text-muted)',
          border: `1px solid ${showLog ? 'var(--accent-call)' : 'var(--border-subtle)'}`,
          fontSize: '11px', fontWeight: 'bold', cursor: 'pointer',
        }}
      >
        📋 TRADE LOG {trades.length > 0 ? `(${trades.length})` : ''}
      </button>

      {/* ── Trade Log Table ── */}
      {showLog && (
        <div style={{
          borderRadius: '6px', background: 'var(--bg-abyss)',
          border: '1px solid var(--border-subtle)', overflow: 'hidden',
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '10px' }}>
            <thead>
              <tr style={{ background: 'var(--bg-surface-elevated)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '6px 8px', textAlign: 'left' }}>Date</th>
                <th style={{ padding: '6px 8px', textAlign: 'left' }}>Strat</th>
                <th style={{ padding: '6px 8px', textAlign: 'left' }}>Dir</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Strike</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Credit</th>
                <th style={{ padding: '6px 8px', textAlign: 'center' }}>Mode</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ padding: '12px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    No trades yet
                  </td>
                </tr>
              )}
              {trades.slice().reverse().map((t, i) => (
                <tr key={i} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '5px 8px', color: '#a0aab2' }}>
                    {t.date ? new Date(t.date).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : new Date(t.timestamp * 1000).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </td>
                  <td style={{ padding: '5px 8px', fontWeight: 'bold', color: STRATEGY_COLORS[t.strategy] || 'var(--text-primary)' }}>
                    {t.strategy}
                  </td>
                  <td style={{ padding: '5px 8px', color: t.direction.includes('PUT') || t.direction === 'BUY_PUT' ? 'var(--accent-put)' : 'var(--accent-call)' }}>
                    {t.direction}
                  </td>
                  <td style={{ padding: '5px 8px', textAlign: 'right', color: '#e0e0e0' }}>
                    {t.short_strike > 0 ? t.short_strike : '—'}
                  </td>
                  <td style={{ padding: '5px 8px', textAlign: 'right', color: 'var(--accent-call)' }}>
                    {t.entry_credit > 0 ? `$${Number(t.entry_credit).toFixed(2)}` : '—'}
                  </td>
                  <td style={{ padding: '5px 8px', textAlign: 'center' }}>
                    <span style={{
                      padding: '1px 5px', borderRadius: '3px', fontSize: '9px', fontWeight: 'bold',
                      background: t.execution_mode === 'AUTO' ? 'rgba(0,255,65,0.15)' : 'rgba(255,170,0,0.15)',
                      color: t.execution_mode === 'AUTO' ? '#00ff41' : '#ffaa00',
                    }}>
                      {t.execution_mode}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};