import { useState, useEffect, useRef } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A single contiguous GEX zone (cluster of strikes with the same GEX sign). */
export interface GexZone {
  strikes: number[];
  sign: 'POSITIVE' | 'NEGATIVE';
  type: 'FADE' | 'BREAKOUT';
  peak_strike: number;
  peak_gex: number;
  avg_oi: number;
  confluence: boolean;
}

/** An actionable setup derived from proximity to a GEX zone. */
export interface GexSetup {
  type: 'CCS' | 'PCS';
  anchor: number;
  tp: number | null;
  label: string;
  confluence: boolean;
  approach?: string;
}

/** Single row in the Gamma Hunter live strike ladder. */
export interface StrikeLadderRow {
  strike: number;
  call_bid?: number | null;
  call_ask?: number | null;
  call_last?: number | null;
  call_volume: number;
  call_oi: number;
  call_gex: number;
  put_bid?: number | null;
  put_ask?: number | null;
  put_last?: number | null;
  put_volume: number;
  put_oi: number;
  put_gex: number;
}

/** Aggregated Gamma Exposure summary for the Gamma Hunter header. */
export interface GexSummary {
  call_gex_total: number;
  put_gex_total: number;
  net_gex: number;
  max_abs_gex: number;
}

/** Single point in the IV skew curve. */
export interface IvSkewPoint {
  strike: number;
  moneyness: number;
  call_iv?: number | null;
  put_iv?: number | null;
}

/** Engine health payload broadcast with metrics and via WebSocket. */
export interface EngineHealth {
  start_time: number;
  last_poll_ms: number | null;
  polls: number;
  tracked_strikes: number;
  calls: number;
  puts: number;
  errors: number;
  connected: boolean;
  connected_live: boolean;
}

/** Active option position for the Gamma Hunter panel. */
export interface PositionData {
  active: boolean;
  symbol?: string;
  right?: 'C' | 'P';
  strike?: number;
  expiry?: string;
  qty?: number;
  entry_price?: number | null;
  current_price?: number | null;
  unrealized_pnl?: number;
  unrealized_pct?: number;
  opened_at?: string | null;
}

/** Single tape signal formatted for the Gamma Hunter signal feed. */
export interface BotTapeSignal {
  timestamp: string;
  side: 'C' | 'P';
  strike: number;
  z_score: number;
  ratio: number;
  volume: number | null;
  ask: number;
  status: 'EXECUTED' | 'PENDING' | 'OUT WINDOW';
  _raw?: any;
}

/** Full market metrics payload returned by fetch_market_metrics(). */
export interface GexData {
  // --- Existing fields (unchanged) ---
  gex_by_expiry: { [expiry: string]: { [strike: string]: number } };
  gex_profile: { [strike: string]: number };
  expiries: string[];
  spot: number;
  call_wall: number | null;
  put_wall: number | null;
  gamma_flip: number | null;
  sigmas: { [key: string]: number };
  dark_gamma: { strike: number; type: string; volume: number; oi: number; ratio: number }[];
  atm_iv: number | null;

  // --- NEW fields ---
  oi_profile: { [strike: string]: number };
  vol_profile: { [strike: string]: number };
  oi_by_expiry: { [expiry: string]: { [strike: string]: number } };
  vol_by_expiry: { [expiry: string]: { [strike: string]: number } };
  max_change_gamma: number | null;
  regime: 'LONG_GAMMA' | 'SHORT_GAMMA' | 'NEUTRAL';
  regime_score: number;        // % distance from gamma flip (positive = above)
  bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  net_gex_total: number;       // Sum of all GEX in millions
  pinning_candidate: number | null;
  expected_range: [number, number];
  breakout_risk: 'HIGH' | 'MEDIUM' | 'LOW';
  gex_zones: GexZone[];
  fade_setups: GexSetup[];
  breakout_setups: GexSetup[];
  // --- Gamma Hunter fields ---
  strike_ladder: StrikeLadderRow[];
  gex_summary: GexSummary;
  iv_skew: IvSkewPoint[];
  put_call_ratio: { volume: number; oi: number };
  engine_health: EngineHealth;
}

/** Alert prefill payload for one-click form population. */
export interface AlertPrefill {
  type: 'CCS' | 'PCS';
  target_mode: 'GEX' | 'Delta' | 'R:R';
  anchor: number;
}

/** Parameters for placing a spread order. */
export interface SpreadParams {
  trade_type: 'CCS' | 'PCS';
  qty: number;
  target_mode: 'Delta' | 'R:R' | 'GEX';
  target_value: number;
  width: number;
  tp_pct: number;
  sl_ratio: number;
  transmit: boolean;
  target_env: 'paper' | 'live';
}

/** A level-breach alert emitted by the server's monitor_levels() loop. */
export interface MarketAlert {
  type: 'alert';
  level: string;
  value: number;
  spot: number;
  distance_pct: number;
  setup_suggestion: string;
  prefill?: AlertPrefill;
  timestamp: string;         // Added client-side on receipt
}

/** 10-minute trading recommendation from the recommendation engine. */
export interface Recommendation {
  score: number;
  direction: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  instrument: 'BUY_CALL' | 'BUY_PUT' | 'CCS' | 'PCS' | 'NO_TRADE';
  regime: string;
  bias: string;
  breakout_risk: string;
  spot: number | null;
  call_wall: number | null;
  put_wall: number | null;
  gamma_flip: number | string | null;
  net_gex_total: number;
  regime_score: number;
  anchor_strike: number | null;
  confidence: 'LOW' | 'MEDIUM' | 'HIGH';
  reason: string;
  timestamp: number;
  scoreBreakdown?: ScoreBreakdown;
}

export interface ScoreBreakdown {
  regimeBias: number;
  wallProximity: number;
  wallBreak: number;
  darkGamma: number;
  volumeOiDivergence: number;
  wallOiBuildup: number;
  volumeLead: number;
  breakoutRisk: number;
  netGexMultiplier: number;
  regimeMagnitude: number;
}

export interface MetricPayload {
  data: GexData;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/** Append a sample to a ring buffer, capped at SPARK_BUFFER_SIZE. */
const SPARK_BUFFER_SIZE = 60;
const appendSample = (buf: number[], sample: number): number[] => {
  const next = [...buf, sample];
  return next.length > SPARK_BUFFER_SIZE ? next.slice(next.length - SPARK_BUFFER_SIZE) : next;
};

export function useMarketData() {
  const [connected, setConnected] = useState(false);
  const [connectedLive, setConnectedLive] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [liveTradingArmed, setLiveTradingArmed] = useState(false);
  const [metrics, setMetrics] = useState<GexData | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<MarketAlert[]>([]);
  const [position, setPosition] = useState<PositionData>({ active: false });
  const [tapeSignals, setTapeSignals] = useState<BotTapeSignal[]>([]);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  // WebSocket lifecycle (separate from IBKR connection state above)
  const [wsConnected, setWsConnected] = useState(false);
  // Rolling history buffers (last SPARK_BUFFER_SIZE samples) for sparkline widgets
  const [spotHistory, setSpotHistory] = useState<number[]>([]);
  const [netGexHistory, setNetGexHistory] = useState<number[]>([]);
  const [pnlHistory, setPnlHistory] = useState<number[]>([]);

  const WsUrl = 'ws://localhost:8000/ws/market_data';
  const ApiUrl = 'http://localhost:8000/api';

  /** Append a message to the log panel (capped at 50 lines). */
  const addLog = (msg: string) => {
    setLogs(prev => {
      const newLogs = [...prev, `> ${msg}`];
      return newLogs.length > 50 ? newLogs.slice(newLogs.length - 50) : newLogs;
    });
  };

  /**
   * Push a new alert to the alerts list (capped at 30).
   * Adds a local timestamp so the UI can display it.
   */
  const addAlert = (raw: Omit<MarketAlert, 'timestamp'>) => {
    const withTs: MarketAlert = {
      ...raw,
      timestamp: new Date().toLocaleTimeString('en-US', { hour12: false }),
    };
    setAlerts(prev => {
      const next = [withTs, ...prev];
      return next.length > 30 ? next.slice(0, 30) : next;
    });
    // Mirror alert to logs as well so nothing is missed
    addLog(`⚠️ ${raw.level} @ ${raw.value} — ${raw.setup_suggestion}`);

    // Play a short beep for critical alerts (wall breaks, gamma flip cross)
    const CRITICAL = new Set([
      'CALL_WALL_BREAK',
      'PUT_WALL_BREAK',
      'GAMMA_FLIP_CROSS',
      'CONFLUENCE_SPIKE',
    ]);
    if (CRITICAL.has(raw.level)) {
      playBeep();
    }
  };

  /**
   * Play a short oscillator beep (no external asset required).
   * Wrapped in try/catch — autoplay policies may block on some browsers.
   */
  const playBeep = () => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.2);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.2);
      // Close context after beep finishes
      setTimeout(() => ctx.close(), 300);
    } catch (e) {
      // Silent fail — autoplay policy may block
    }
  };

  // Reconnect attempt counter for exponential backoff
  const reconnectAttemptRef = useRef<number>(0);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimeout: ReturnType<typeof setTimeout>;

    const connectWS = () => {
      ws = new WebSocket(WsUrl);

      ws.onopen = () => {
        reconnectAttemptRef.current = 0;  // Reset backoff on successful connect
        setWsConnected(true);
        addLog('WebSocket Connected.');
        // Fetch latest metrics and tape on reconnect so UI updates immediately
        getMetrics();
        fetchTapeSignals();
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'log') {
            addLog(payload.message);
          } else if (payload.type === 'status') {
            // Initial status from WebSocket open replaces /api/status fetch
            setConnected(!!payload.connected);
            setConnectedLive(!!payload.connected_live);
          } else if (payload.type === 'metrics') {
            // Merge partial updates (monitor_levels sends {spot} only) without wiping full state
            setMetrics(prev => {
              const merged = { ...prev, ...payload.data };
              // Push to sparkline buffers (cap at SPARK_BUFFER_SIZE)
              const ts = Date.now();
              if (typeof merged.spot === 'number' && merged.spot > 0) {
                setSpotHistory(h => appendSample(h, merged.spot));
              }
              if (typeof merged.net_gex_total === 'number') {
                setNetGexHistory(h => appendSample(h, merged.net_gex_total));
              }
              void ts; // reserved for future timestamped buffers
              return merged;
            });
          } else if (payload.type === 'alert') {
            // Incoming level-breach alert from monitor_levels()
            addAlert(payload as Omit<MarketAlert, 'timestamp'>);
          } else if (payload.type === 'position') {
            // Active SPX/SPXW position update for Gamma Hunter
            const pos = payload.data || { active: false };
            setPosition(pos);
            if (pos.active && typeof pos.unrealized_pnl === 'number') {
              setPnlHistory(h => appendSample(h, pos.unrealized_pnl as number));
            }
          } else if (payload.type === 'recommendation') {
            // 10-minute trading recommendation
            console.log('[WS] recommendation received', payload);
            setRecommendation(payload as Recommendation);
          }
        } catch (e) {
          console.error('WS Parse Error', e);
        }
      };

      ws.onclose = () => {
        setWsConnected(false);
        // Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
        const attempt = reconnectAttemptRef.current++;
        const delay = Math.min(30000, 1000 * Math.pow(2, attempt)) + Math.random() * 1000;
        addLog(`WebSocket disconnected. Reconnecting in ${Math.round(delay / 1000)}s...`);
        reconnectTimeout = setTimeout(connectWS, delay);
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
      };
    };

    connectWS();

    const handleFocus = () => {
      // Re-connect instantly if tab gains focus and WS is disconnected or connecting
      if (document.visibilityState === 'visible') {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          addLog('Tab focused, forcing fast reconnect...');
          clearTimeout(reconnectTimeout);
          reconnectAttemptRef.current = 0;  // Reset backoff for manual retry
          connectWS();
        }
      }
    };
    document.addEventListener('visibilitychange', handleFocus);

    return () => {
      clearTimeout(reconnectTimeout);
      document.removeEventListener('visibilitychange', handleFocus);
      if (ws) {
        ws.onclose = null; // Prevent reconnect on unmount
        ws.close();
      }
    };
  }, []);

  // ---------------------------------------------------------------------------
  // API helpers
  // ---------------------------------------------------------------------------

  const connectToIBKR = async (port: number = 4002) => {
    setConnecting(true);
    addLog(`Connecting to IBKR on port ${port}...`);
    try {
      const res = await fetch(`${ApiUrl}/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        setConnected(true);
        addLog(data.message);
      } else {
        addLog(`Error: ${data.message}`);
      }
    } catch (e: any) {
      addLog(`Failed to connect: ${e.message}`);
    } finally {
      setConnecting(false);
    }
  };

  const connectLive = async () => {
    addLog(`Initiating connection to LIVE engine on port 4001...`);
    try {
      const res = await fetch(`${ApiUrl}/connect_live`, { method: 'POST' });
      const payload = await res.json();
      if (payload.status === 'success') {
        setConnectedLive(true);
        addLog('Successfully mapped LIVE engine on port 4001.');
      } else {
        addLog(`Failed to connect LIVE: ${payload.message || payload.detail}`);
      }
    } catch (e: any) {
      addLog(`Failed to connect LIVE: ${e.message}`);
    }
  };

  const getMetrics = async () => {
    addLog('Requesting manual GEX Scrape...');
    try {
      const res = await fetch(`${ApiUrl}/metrics`);
      const payload = await res.json();
      if (payload.status === 'success' && payload.data) {
        const data = payload.data as GexData;
        setMetrics(data);
        // Push to sparkline buffers on manual fetch too
        if (typeof data.spot === 'number' && data.spot > 0) {
          setSpotHistory(h => appendSample(h, data.spot));
        }
        if (typeof data.net_gex_total === 'number') {
          setNetGexHistory(h => appendSample(h, data.net_gex_total));
        }
        fetchTapeSignals();
      }
    } catch (e: any) {
      addLog(`Metrics fetch failed: ${e.message}`);
    }
  };

  const fetchTapeSignals = async () => {
    try {
      const res = await fetch(`${ApiUrl}/bot/signals`);
      const payload = await res.json();
      if (payload.signals && Array.isArray(payload.signals)) {
        setTapeSignals(payload.signals);
      }
    } catch (e) {
      console.error('Tape signals fetch failed:', e);
    }
  };

  const executeTrade = async (params: SpreadParams) => {
    addLog(`Transmitting [${params.trade_type}] Order to Backend... (Live: ${params.transmit})`);
    try {
      await fetch(`${ApiUrl}/trade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
    } catch (e: any) {
      addLog(`Trade payload failed: ${e.message}`);
    }
  };

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${ApiUrl}/history?t=${Date.now()}`, { cache: 'no-store' });
      const payload = await res.json();
      return payload; // Returns { data: [], date: "..." }
    } catch (e) {
      console.error(e);
      return { data: [], date: '' };
    }
  };

  /** Dismiss (remove) an alert by its index in the alerts array. */
  const dismissAlert = (index: number) => {
    setAlerts(prev => prev.filter((_, i) => i !== index));
  };

  /** Arm the live trading safety gate. Requires exact phrase confirmation. */
  const armLiveTrading = async () => {
    addLog('⚠️ Requesting LIVE TRADING arming — confirmation required');
    const confirmed = window.confirm(
      '🚨 CRITICAL: Arming live trading will allow REAL orders to transmit.\n\n' +
      'Type "ENABLE LIVE TRADING" in the next prompt to confirm.'
    );
    if (!confirmed) {
      addLog('Live trading arming cancelled by user.');
      return;
    }
    const phrase = window.prompt('Type exactly: ENABLE LIVE TRADING');
    if (phrase !== 'ENABLE LIVE TRADING') {
      addLog(`Live trading arming failed: phrase mismatch (got "${phrase}")`);
      return;
    }
    try {
      const res = await fetch(`${ApiUrl}/arm_live_trading`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: phrase }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        setLiveTradingArmed(true);
        addLog('⚠️ LIVE TRADING ARMED. Real orders will now transmit.');
      } else {
        addLog(`Failed to arm live trading: ${data.detail || 'unknown error'}`);
      }
    } catch (e: any) {
      addLog(`Arm request failed: ${e.message}`);
    }
  };

  /** Disarm the live trading safety gate. */
  const disarmLiveTrading = async () => {
    try {
      const res = await fetch(`${ApiUrl}/disarm_live_trading`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        setLiveTradingArmed(false);
        addLog('Live trading disarmed.');
      }
    } catch (e: any) {
      addLog(`Disarm request failed: ${e.message}`);
    }
  };

  return {
    connected,
    connectedLive,
    connecting,
    liveTradingArmed,
    wsConnected,
    metrics,
    logs,
    alerts,
    position,
    tapeSignals,
    recommendation,
    spotHistory,
    netGexHistory,
    pnlHistory,
    connectToIBKR,
    connectLive,
    getMetrics,
    executeTrade,
    fetchHistory,
    dismissAlert,
    armLiveTrading,
    disarmLiveTrading,
  };
}
