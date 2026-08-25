import { useState, useEffect, lazy, Suspense } from 'react';
import { useMarketData } from './hooks/useMarketData';
import type { AlertPrefill } from './hooks/useMarketData';
import { Activity, BarChart3, Crosshair, PanelRight, RotateCcw, Terminal, X } from 'lucide-react';
import { useNetDriftData } from './hooks/useNetDriftData';
import RegimePanel from './components/RegimePanel';
import { ConnectionWidget } from './components/ConnectionWidget';
import { BotPanel } from './components/BotPanel';
import { RecommendationBanner } from './components/gamma-hunter/RecommendationBanner';

// Lazy-load charts so recharts (~365KB) is only fetched when the user opens those tabs.
// Initial bundle keeps only HeatMap (always visible).
const HeatMap = lazy(() => import('./components/HeatMap'));
const IntervalMap = lazy(() => import('./components/IntervalMap'));
const NetDriftChart = lazy(() => import('./components/NetDriftChart').then(m => ({ default: m.NetDriftChart })));
const GammaHunter = lazy(() => import('./components/gamma-hunter/GammaHunter'));

// ---------------------------------------------------------------------------
// Default trade form values (used on first load / after reset)
// ---------------------------------------------------------------------------

const LS_KEY = 'tradingDeck.tradeDefaults';

const DEFAULT_TRADE_FORM: TradeForm = {
  type: 'CCS',
  qty: 1,
  target_mode: 'Delta',
  target_value: 50,
  width: 10,
  tp_pct: 50,
  sl_ratio: 2.5,
  transmit: false,
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** State for the trade execution form. */
interface TradeForm {
  type: string;
  qty: number | string;
  target_mode: string;
  target_value: number | string;
  width: number | string;
  tp_pct: number | string;
  sl_ratio: number | string;
  transmit: boolean;
}

// ---------------------------------------------------------------------------
// Trade Execution Panel — used both inline and in slide-over drawer
// ---------------------------------------------------------------------------
interface TradeExecutionPanelProps {
  tradeForm: TradeForm;
  setTradeForm: React.Dispatch<React.SetStateAction<TradeForm>>;
  targetEnv: 'paper' | 'live';
  setTargetEnv: (env: 'paper' | 'live') => void;
  liveTradingArmed: boolean;
  connectedLive: boolean;
  metrics: any;
  onExecuteTrade: (params: any) => void;
  onResetDefaults: () => void;
}

function TradeExecutionPanel({
  tradeForm, setTradeForm, targetEnv, setTargetEnv,
  liveTradingArmed, connectedLive, metrics,
  onExecuteTrade, onResetDefaults,
}: TradeExecutionPanelProps) {
  return (
    <>
      <h3 style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'space-between' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Crosshair size={16} /> EXECUTION ENGINE
        </span>
        <button
          id="reset-defaults-btn"
          onClick={onResetDefaults}
          title="Reset to factory defaults"
          style={{
            display: 'flex', alignItems: 'center', gap: '4px',
            background: 'none', border: '1px solid var(--border-subtle)',
            color: 'var(--text-muted)', borderRadius: '4px',
            padding: '3px 7px', cursor: 'pointer', fontSize: '10px',
          }}
        >
          <RotateCcw size={10} /> RESET
        </button>
      </h3>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <label>Quantity</label>
          <input id="qty-input" type="number" value={tradeForm.qty}
            onChange={e => setTradeForm({ ...tradeForm, qty: e.target.value })}
            style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <label>Target By</label>
          <select
            id="target-mode-select"
            value={tradeForm.target_mode}
            onChange={e => {
              const mode = e.target.value;
              setTradeForm({ ...tradeForm, target_mode: mode, target_value: mode === 'Delta' ? 50 : mode === 'R:R' ? 1.75 : tradeForm.target_value });
            }}
            style={{ background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }}
          >
            <option value="Delta">Delta (Δ)</option>
            <option value="R:R">Risk:Reward</option>
            <option value="GEX">GEX Wall 🎯</option>
          </select>
        </div>

        {tradeForm.target_mode !== 'GEX' ? (
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <label>{tradeForm.target_mode === 'Delta' ? 'Target Delta' : 'Min R:R'}</label>
            <input id="target-value-input" type="number" step={tradeForm.target_mode === 'Delta' ? "1" : "0.1"} value={tradeForm.target_value}
              onChange={e => setTradeForm({ ...tradeForm, target_value: e.target.value })}
              style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
          </div>
        ) : (
          <div style={{ padding: '8px', background: 'var(--bg-abyss)', borderRadius: '4px', border: '1px solid var(--border-subtle)', fontSize: '11px' }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>Anchors (from last scan)</div>
            <div style={{ color: 'var(--accent-put)' }}>📍 Short Call → {metrics?.call_wall ?? '---'} (Call Wall)</div>
            <div style={{ color: 'var(--accent-call)' }}>📍 Short Put → {metrics?.put_wall ?? '---'} (Put Wall)</div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <label>Spread Width</label>
          <input id="width-input" type="number" step="5" value={tradeForm.width}
            onChange={e => setTradeForm({ ...tradeForm, width: e.target.value })}
            style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <label>Take Profit %</label>
          <input id="tp-pct-input" type="number" step="1" value={tradeForm.tp_pct}
            onChange={e => setTradeForm({ ...tradeForm, tp_pct: e.target.value })}
            style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <label>Stop Loss Mult.</label>
          <input id="sl-ratio-input" type="number" step="0.1" value={tradeForm.sl_ratio}
            onChange={e => setTradeForm({ ...tradeForm, sl_ratio: e.target.value })}
            style={{ width: '60px', background: 'var(--bg-abyss)', color: 'white', border: '1px solid var(--border-subtle)' }} />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
          <label style={{ color: tradeForm.transmit ? 'var(--accent-call)' : 'var(--text-secondary)' }}>
            {tradeForm.transmit ? 'LIVE TRANSMIT' : 'STAGE (Pendiente)'}
          </label>
          <input id="transmit-toggle" type="checkbox" checked={tradeForm.transmit}
            onChange={e => setTradeForm({ ...tradeForm, transmit: e.target.checked })}
            style={{ width: '18px', height: '18px', cursor: 'pointer', accentColor: 'var(--accent-call)' }} />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px', background: 'var(--bg-abyss)', borderRadius: '4px' }}>
          <span style={{ fontSize: '12px', fontWeight: 'bold' }}>TARGET ENGINE</span>
          <div style={{ display: 'flex', gap: '16px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer', fontSize: '11px' }}>
              <input type="radio" name="targetEnvSlide" value="paper" checked={targetEnv === 'paper'} onChange={() => setTargetEnv('paper')} />
              PAPER (DEMO)
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: connectedLive ? 'pointer' : 'not-allowed', fontSize: '11px', color: connectedLive ? 'inherit' : 'var(--text-muted)' }}>
              <input type="radio" name="targetEnvSlide" value="live" checked={targetEnv === 'live'} onChange={() => setTargetEnv('live')} disabled={!connectedLive} />
              REAL (LIVE)
            </label>
          </div>
        </div>

        {/* Execution buttons */}
        <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
          <button
            id="launch-ccs-btn"
            onClick={() => {
              if (targetEnv === 'live') {
                if (!liveTradingArmed) { window.alert("🚫 Live trading is not armed. Arm it from the connection panel first."); return; }
                if (!window.confirm("🚨 ALERTA CRÍTICA: Estás a punto de enviar una órden simultánea a tu CUENTA REAL. ¿Estás absolutamente seguro de querer proceder?")) return;
              }
              onExecuteTrade({ trade_type: 'CCS', qty: Number(tradeForm.qty), target_mode: tradeForm.target_mode as any, target_value: Number(tradeForm.target_value), width: Number(tradeForm.width), tp_pct: Number(tradeForm.tp_pct), sl_ratio: Number(tradeForm.sl_ratio), transmit: tradeForm.transmit, target_env: targetEnv });
            }}
            style={{ flex: 1, padding: '12px', background: 'var(--accent-put)', color: 'black', fontWeight: '900', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
          >
            Launch CCS
          </button>
          <button
            id="launch-pcs-btn"
            onClick={() => {
              if (targetEnv === 'live') {
                if (!liveTradingArmed) { window.alert("🚫 Live trading is not armed. Arm it from the connection panel first."); return; }
                if (!window.confirm("🚨 ALERTA CRÍTICA: Estás a punto de enviar una órden simultánea a tu CUENTA REAL. ¿Estás absolutamente seguro de querer proceder?")) return;
              }
              onExecuteTrade({ trade_type: 'PCS', qty: Number(tradeForm.qty), target_mode: tradeForm.target_mode as any, target_value: Number(tradeForm.target_value), width: Number(tradeForm.width), tp_pct: Number(tradeForm.tp_pct), sl_ratio: Number(tradeForm.sl_ratio), transmit: tradeForm.transmit, target_env: targetEnv });
            }}
            style={{ flex: 1, padding: '12px', background: 'var(--accent-call)', color: 'black', fontWeight: '900', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
          >
            Launch PCS
          </button>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

function App() {
  const { metrics, connected, connectedLive, connecting, liveTradingArmed, connectToIBKR, connectLive, getMetrics, alerts, dismissAlert, executeTrade, fetchHistory, armLiveTrading, disarmLiveTrading, logs, position, tapeSignals, recommendation, wsConnected, spotHistory, netGexHistory, pnlHistory } = useMarketData();
  const { driftData, dateStr: driftDateStr } = useNetDriftData();

  // "activeTab" handles which main view is rendered: heatmap | interval | netdrift | gamma-hunter
  const [activeTab, setActiveTab] = useState<'heatmap' | 'interval' | 'netdrift' | 'gamma-hunter'>('heatmap');

  // Fetch metrics when user switches to heatmap tab so data is fresh
  useEffect(() => {
    if (activeTab === 'heatmap') {
      getMetrics();
    }
  }, [activeTab]);
  const [port, setPort] = useState('4002');
  const [targetEnv, setTargetEnv] = useState<'paper' | 'live'>('paper');
  // Slide-over panel for trading strategies — hidden by default, toggled via button
  const [showTradePanel, setShowTradePanel] = useState(false);
  const [activeTradeTab, setActiveTradeTab] = useState<'manual' | 'bot'>('manual');

  // Load form defaults from localStorage (persists between sessions).
  // Falls back to hardcoded defaults if nothing is stored yet.
  const loadDefaults = (): TradeForm => {
    try {
      const saved = localStorage.getItem('tradingDeck.tradeDefaults');
      if (saved) return { ...DEFAULT_TRADE_FORM, ...JSON.parse(saved) };
    } catch {
      // Corrupt storage — ignore and use defaults
    }
    return { ...DEFAULT_TRADE_FORM };
  };

  const [tradeForm, setTradeForm] = useState<TradeForm>(loadDefaults);

  // Auto-save form values to localStorage on every change.
  // The transmit toggle is intentionally NOT persisted (safety: always starts false).
  useEffect(() => {
    const { transmit: _t, ...toSave } = tradeForm;
    localStorage.setItem(LS_KEY, JSON.stringify(toSave));
  }, [tradeForm]);

  /** Reset form to factory defaults and clear localStorage. */
  const resetDefaults = () => {
    localStorage.removeItem(LS_KEY);
    setTradeForm({ ...DEFAULT_TRADE_FORM });
  };

  /**
   * Pre-fill the execution form from a clicked alert or setup suggestion.
   * Called by RegimePanel when the user clicks an alert or a setup row.
   */
  const handleAlertPrefill = (prefill: AlertPrefill) => {
    setTradeForm(prev => ({
      ...prev,
      type: prefill.type,
      target_mode: prefill.target_mode,
      // When GEX mode is selected a numeric target is not needed, but we
      // store the anchor so the user can see what level was suggested.
      target_value: prefill.anchor,
    }));
  };

  // Sigma levels from last metrics (already calculated by backend).
  const sigmas = metrics?.sigmas ?? {};
  const atmIv = metrics?.atm_iv;
  const regime = metrics?.regime ?? null;

  // Regime dot colour for the header badge.
  const regimeDotColor =
    regime === 'LONG_GAMMA'
      ? 'var(--accent-call)'
      : regime === 'SHORT_GAMMA'
      ? 'var(--accent-put)'
      : 'var(--text-muted)';

  return (
    <div className="layout-container" style={{ display: 'flex', height: '100vh', width: '100vw' }}>

      {/* ──────────────────────────────────────────────────────────── SIDEBAR */}
      <aside className="sidebar panel" style={{ width: '300px', margin: '12px', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
          {/* Connection Widget */}
          <ConnectionWidget
            port={port}
            setPort={setPort}
            connected={connected}
            connectedLive={connectedLive}
            connecting={connecting}
            liveTradingArmed={liveTradingArmed}
            connectToIBKR={connectToIBKR}
            connectLive={connectLive}
            armLiveTrading={armLiveTrading}
            disarmLiveTrading={disarmLiveTrading}
          />

        {/* ── REGIME PANEL (only when new strategy fields are available) ── */}
        {metrics && 'gex_zones' in metrics && (
          <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)', flexShrink: 0 }}>
            <RegimePanel
              metrics={metrics}
              alerts={alerts}
              onAlertClick={handleAlertPrefill}
              onDismissAlert={dismissAlert}
            />
          </div>
        )}
        </div> {/* End of top scrollable area */}

        {/* ── BOTTOM DOCKED ZONE ── */}
        <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', borderTop: '1px solid var(--border-subtle)' }}>

        {/* Terminal Logs */}
        <div style={{
          padding: '12px', height: '180px',
          background: 'var(--bg-abyss)', overflowY: 'auto',
          fontSize: '11px', flexShrink: 0,
        }} className="font-data text-secondary">
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', color: 'var(--text-muted)' }}>
            <Terminal size={14} /> SYSTEM LOGS
          </div>
          {logs.map((log, i) => (
            <div
              key={i}
              style={{
                marginBottom: '3px',
                color: log.includes('⚠️') ? '#f59e0b' : 'inherit',
              }}
            >
              {log}
            </div>
          ))}
        </div>

        </div>

      </aside>

      {/* ───────────────────────────────────────────────────── MAIN DASHBOARD */}
      <main style={{ flex: 1, padding: '12px', paddingLeft: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}>

        {/* ── HEADER ── */}
        <header className="panel" style={{ padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>

            {/* Spot price */}
            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>SPX SPOT PRICE</div>
              <div className="font-data text-glow-spot" style={{ fontSize: '32px', color: 'var(--text-primary)', fontWeight: '800' }}>
                {metrics?.spot ? metrics.spot.toFixed(2) : '-----'}
              </div>
            </div>

            {/* Key GEX levels + regime badge */}
            <div style={{ display: 'flex', gap: '16px', borderLeft: '1px solid var(--border-subtle)', paddingLeft: '20px', alignItems: 'center', flexWrap: 'wrap' }}>

              {/* GEX Levels & Regime Block */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                <div style={{ display: 'flex', gap: '16px' }}>
                  {/* Call Wall */}
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '10px', color: 'var(--accent-put)' }}>Call Wall</div>
                    <div className="font-data text-glow-put" style={{ fontWeight: 'bold' }}>{metrics?.call_wall ?? '---'}</div>
                  </div>

                  {/* Gamma Flip */}
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '10px', color: 'var(--accent-spot)' }}>Gamma Flip</div>
                    <div className="font-data text-glow-spot" style={{ fontWeight: 'bold' }}>{metrics?.gamma_flip ?? '---'}</div>
                  </div>

                  {/* Put Wall */}
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '10px', color: 'var(--accent-call)' }}>Put Wall</div>
                    <div className="font-data text-glow-call" style={{ fontWeight: 'bold' }}>{metrics?.put_wall ?? '---'}</div>
                  </div>
                </div>

                {/* Regime badge */}
                {regime && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '5px',
                    padding: '2px 10px', borderRadius: '12px',
                    background: `${regimeDotColor}22`,
                    border: `1px solid ${regimeDotColor}55`,
                  }}>
                    <span style={{
                      width: '6px', height: '6px', borderRadius: '50%',
                      background: regimeDotColor,
                      boxShadow: `0 0 5px ${regimeDotColor}`,
                    }} />
                    <span style={{ color: regimeDotColor, fontSize: '10px', fontWeight: 700 }}>
                      {regime.replace('_', ' ')}
                    </span>
                  </div>
                )}
              </div>

              {/* Data Modifiers Column: Sigmas & ATM IV */}
              {((sigmas['+1'] || sigmas['+2']) || atmIv) && (
                <div style={{ paddingLeft: '12px', borderLeft: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: '2px', justifyContent: 'center' }}>
                  {sigmas['+1'] && (
                    <div className="font-data" style={{ fontSize: '11px', color: 'var(--text-secondary)', display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                      <span style={{ color: 'var(--text-muted)', fontSize: '9px' }}>±1σ</span>
                      <span>{Number(sigmas['+1']).toFixed(0)} / {Number(sigmas['-1']).toFixed(0)}</span>
                    </div>
                  )}
                  {sigmas['+2'] && (
                    <div className="font-data" style={{ fontSize: '11px', color: 'var(--text-secondary)', display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                      <span style={{ color: 'var(--text-muted)', fontSize: '9px' }}>±2σ</span>
                      <span>{Number(sigmas['+2']).toFixed(0)} / {Number(sigmas['-2']).toFixed(0)}</span>
                    </div>
                  )}
                  {atmIv && (
                    <div className="font-data" style={{ fontSize: '11px', color: 'var(--text-secondary)', display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                      <span style={{ color: 'var(--text-muted)', fontSize: '9px' }}>ATM IV</span>
                      <span>{(atmIv * 100).toFixed(1)}%</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Controls */}
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              id="force-refresh-btn"
              onClick={getMetrics}
              style={{
                padding: '8px 16px', background: 'transparent',
                border: '1px solid var(--border-subtle)', color: 'white',
                borderRadius: '4px', cursor: 'pointer',
              }}
            >
              <Activity size={16} style={{ verticalAlign: 'middle', marginRight: '6px' }} />
              FORCE REFRESH
            </button>

            {/* Tab switcher */}
            <div style={{ display: 'flex', background: 'var(--bg-abyss)', padding: '4px', borderRadius: '6px', border: '1px solid var(--border-subtle)' }}>
              <button
                id="tab-heatmap"
                onClick={() => setActiveTab('heatmap')}
                style={{
                  padding: '6px 16px',
                  background: activeTab === 'heatmap' ? 'var(--bg-surface-elevated)' : 'transparent',
                  color: activeTab === 'heatmap' ? 'white' : 'var(--text-muted)',
                  border: 'none', borderRadius: '4px', cursor: 'pointer',
                }}
              >
                GEX HEATMAP
              </button>
              <button
                id="tab-interval"
                onClick={() => setActiveTab('interval')}
                style={{
                  padding: '6px 16px',
                  background: activeTab === 'interval' ? 'var(--bg-surface-elevated)' : 'transparent',
                  color: activeTab === 'interval' ? 'white' : 'var(--text-muted)',
                  border: 'none', borderRadius: '4px', cursor: 'pointer',
                }}
              >
                <BarChart3 size={14} style={{ verticalAlign: 'middle', marginRight: '6px' }} />
                INTERVAL MAP
              </button>
              <button
                id="tab-netdrift"
                onClick={() => setActiveTab('netdrift')}
                style={{
                  padding: '6px 16px',
                  background: activeTab === 'netdrift' ? 'var(--bg-surface-elevated)' : 'transparent',
                  color: activeTab === 'netdrift' ? 'white' : 'var(--text-muted)',
                  border: 'none', borderRadius: '4px', cursor: 'pointer',
                }}
              >
                NET DRIFT (PRM)
              </button>
              <button
                id="tab-gamma-hunter"
                onClick={() => setActiveTab('gamma-hunter')}
                style={{
                  padding: '6px 16px',
                  background: activeTab === 'gamma-hunter' ? 'var(--bg-surface-elevated)' : 'transparent',
                  color: activeTab === 'gamma-hunter' ? 'white' : 'var(--text-muted)',
                  border: 'none', borderRadius: '4px', cursor: 'pointer',
                }}
              >
                GAMMA HUNTER
              </button>
            </div>

            {/* Floating toggle for trade panel */}
            <button
              id="toggle-trade-panel-btn"
              onClick={() => setShowTradePanel(v => !v)}
              title={showTradePanel ? 'Close trade panel' : 'Open trade panel'}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '8px 14px',
                background: showTradePanel ? 'var(--accent-call)' : 'var(--bg-abyss)',
                color: showTradePanel ? 'black' : 'white',
                border: `1px solid ${showTradePanel ? 'var(--accent-call)' : 'var(--border-subtle)'}`,
                borderRadius: '6px', cursor: 'pointer', fontWeight: '700', fontSize: '12px',
              }}
            >
              <PanelRight size={16} />
              {showTradePanel ? 'CLOSE' : 'TRADE'}
            </button>
          </div>
        </header>

        {/* ── RECOMMENDATION BANNER (sticky, always visible) ── */}
        <div style={{ position: 'sticky', top: 0, zIndex: 50, padding: '0 20px', background: 'var(--bg-base)' }}>
          <RecommendationBanner recommendation={recommendation} />
        </div>

        {/* ── CONTENT AREA ── */}
        <section className="panel" style={{ flex: 1, padding: '20px', position: 'relative', overflowY: 'auto' }}>
          {!metrics ? (
            <div style={{
              position: 'absolute', top: '50%', left: '50%',
              transform: 'translate(-50%, -50%)',
              color: 'var(--text-muted)', textAlign: 'center',
            }}>
              <Activity size={48} className="animate-pulse-glow" style={{ marginBottom: '16px' }} />
              <p>AWAITING MARKET DATA</p>
            </div>
          ) : (
            <Suspense fallback={<div style={{ padding: '40px', textAlign: 'center', color: '#888' }}>Loading chart...</div>}>
              {activeTab === 'heatmap' ? (
                <HeatMap metrics={metrics} />
              ) : activeTab === 'interval' ? (
                <IntervalMap metrics={metrics} fetchHistory={fetchHistory} />
              ) : activeTab === 'netdrift' ? (
                <NetDriftChart data={driftData} dateStr={driftDateStr} />
              ) : (
                <GammaHunter
                  metrics={metrics}
                  position={position}
                  tapeSignals={tapeSignals}
                  wsConnected={wsConnected}
                  spotHistory={spotHistory}
                  netGexHistory={netGexHistory}
                  pnlHistory={pnlHistory}
                />
              )}
            </Suspense>
          )}
        </section>

      </main>

      {/* ── SLIDE-OVER TRADE PANEL ── */}
      {showTradePanel && (
        <>
          {/* Backdrop */}
          <div
            onClick={() => setShowTradePanel(false)}
            style={{ position: 'fixed', inset: 0, zIndex: 998, background: 'rgba(0,0,0,0.5)' }}
          />
          {/* Drawer */}
          <aside style={{
            position: 'fixed', top: 0, right: 0, bottom: 0, zIndex: 999,
            width: '380px', background: 'var(--bg-surface)',
            borderLeft: '1px solid var(--border-subtle)',
            display: 'flex', flexDirection: 'column',
            boxShadow: '-4px 0 20px rgba(0,0,0,0.4)',
          }}>
            {/* Close button */}
            <button
              onClick={() => setShowTradePanel(false)}
              style={{
                position: 'absolute', top: '12px', right: '12px', zIndex: 1000,
                background: 'var(--bg-abyss)', border: '1px solid var(--border-subtle)',
                color: 'var(--text-secondary)', borderRadius: '4px',
                padding: '4px 8px', cursor: 'pointer', display: 'flex', alignItems: 'center',
              }}
            >
              <X size={14} />
            </button>

            {/* Tab bar */}
            <div style={{
              display: 'flex', borderBottom: '1px solid var(--border-subtle)',
              flexShrink: 0, paddingTop: '12px',
            }}>
              <button
                onClick={() => setActiveTradeTab('manual')}
                style={{
                  flex: 1, padding: '10px',
                  background: activeTradeTab === 'manual' ? 'var(--bg-surface-elevated)' : 'transparent',
                  color: activeTradeTab === 'manual' ? 'white' : 'var(--text-muted)',
                  border: 'none', borderBottom: activeTradeTab === 'manual' ? '2px solid var(--accent-call)' : '2px solid transparent',
                  cursor: 'pointer', fontSize: '12px', fontWeight: '700',
                }}
              >
                Manual
              </button>
              <button
                onClick={() => setActiveTradeTab('bot')}
                style={{
                  flex: 1, padding: '10px',
                  background: activeTradeTab === 'bot' ? 'var(--bg-surface-elevated)' : 'transparent',
                  color: activeTradeTab === 'bot' ? 'white' : 'var(--text-muted)',
                  border: 'none', borderBottom: activeTradeTab === 'bot' ? '2px solid var(--accent-call)' : '2px solid transparent',
                  cursor: 'pointer', fontSize: '12px', fontWeight: '700',
                }}
              >
                🤖 Bot
              </button>
            </div>

            {/* Tab content */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
              {activeTradeTab === 'manual' ? (
                <TradeExecutionPanel
                  tradeForm={tradeForm}
                  setTradeForm={setTradeForm}
                  targetEnv={targetEnv}
                  setTargetEnv={setTargetEnv}
                  liveTradingArmed={liveTradingArmed}
                  connectedLive={connectedLive}
                  metrics={metrics}
                  onExecuteTrade={executeTrade}
                  onResetDefaults={resetDefaults}
                />
              ) : (
                <BotPanel metrics={metrics} />
              )}
            </div>
          </aside>
        </>
      )}
    </div>
  );
}

export default App;
