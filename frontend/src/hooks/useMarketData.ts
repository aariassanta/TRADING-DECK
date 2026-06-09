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

export interface MetricPayload {
  data: GexData;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useMarketData() {
  const [connected, setConnected] = useState(false);
  const [connectedLive, setConnectedLive] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [liveTradingArmed, setLiveTradingArmed] = useState(false);
  const [metrics, setMetrics] = useState<GexData | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<MarketAlert[]>([]);

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
        addLog('WebSocket Connected.');
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
            // Always apply latest metrics update (timestamp tracking was over-engineering)
            setMetrics(payload.data);
          } else if (payload.type === 'alert') {
            // Incoming level-breach alert from monitor_levels()
            addAlert(payload as Omit<MarketAlert, 'timestamp'>);
          }
        } catch (e) {
          console.error('WS Parse Error', e);
        }
      };

      ws.onclose = () => {
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
        setMetrics(payload.data);
      }
    } catch (e: any) {
      addLog(`Metrics fetch failed: ${e.message}`);
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
    metrics,
    logs,
    alerts,
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
