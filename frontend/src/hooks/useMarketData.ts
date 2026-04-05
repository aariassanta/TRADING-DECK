import { useState, useEffect } from 'react';

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
  const [connecting, setConnecting] = useState(false);
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
  };

  useEffect(() => {
    // Check initial connection status on mount
    fetch(`${ApiUrl}/status`)
      .then(res => res.json())
      .then(data => setConnected(data.connected))
      .catch(() => setConnected(false));

    let ws: WebSocket;
    let reconnectTimeout: ReturnType<typeof setTimeout>;

    const connectWS = () => {
      ws = new WebSocket(WsUrl);

      ws.onopen = () => {
        addLog('WebSocket Connected.');
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'log') {
            addLog(payload.message);
          } else if (payload.type === 'metrics') {
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
        addLog('WebSocket disconnected. Reconnecting in 5s...');
        reconnectTimeout = setTimeout(connectWS, 5000);
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
      };
    };

    connectWS();

    return () => {
      clearTimeout(reconnectTimeout);
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

  const executeTrade = async (
    type: string,
    qty: number,
    target_mode: string,
    target_value: number,
    width: number,
    tp_pct: number,
    sl_ratio: number,
    transmit: boolean,
  ) => {
    addLog(`Transmitting [${type}] Order to Backend... (Live: ${transmit})`);
    try {
      await fetch(`${ApiUrl}/trade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trade_type: type,
          qty,
          target_mode,
          target_value,
          width,
          tp_pct,
          sl_ratio,
          transmit,
        }),
      });
    } catch (e: any) {
      addLog(`Trade payload failed: ${e.message}`);
    }
  };

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${ApiUrl}/history`);
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

  return {
    connected,
    connecting,
    metrics,
    logs,
    alerts,
    connectToIBKR,
    getMetrics,
    executeTrade,
    fetchHistory,
    dismissAlert,
  };
}
