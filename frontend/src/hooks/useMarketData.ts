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

// ---------------------------------------------------------------------------
// Alert rule types and helpers (module-scope)
// ---------------------------------------------------------------------------
export type AlertRuleType =
  | 'SPOT_BREAKS_PUT_WALL'
  | 'SPOT_BREAKS_CALL_WALL'
  | 'SPOT_CROSSES_GAMMA_FLIP'
  | 'NET_GEX_CHANGES_SIGN'
  | 'NET_GEX_ABOVE'
  | 'NET_GEX_BELOW';

export interface AlertRule {
  id: string;
  type: AlertRuleType;
  enabled: boolean;
  /** Threshold (used by NET_GEX_ABOVE / NET_GEX_BELOW). */
  threshold?: number;
  /** Minimum seconds between re-firing of the same rule (default 300). */
  cooldownSec?: number;
}

const ALERT_RULES_KEY = 'gh.alertRules.v1';
const SOUND_SETTINGS_KEY = 'gh.soundSettings.v1';

export interface SoundSettings {
  enabled: boolean;
  /** 0.0 - 1.0; applied as gain.gain.setValueAtTime. */
  volume: number;
}

const defaultSoundSettings = (): SoundSettings => ({ enabled: true, volume: 0.2 });

const defaultAlertRules = (): AlertRule[] => [
  { id: 'r1', type: 'SPOT_BREAKS_PUT_WALL', enabled: true, cooldownSec: 300 },
  { id: 'r2', type: 'SPOT_BREAKS_CALL_WALL', enabled: true, cooldownSec: 300 },
  { id: 'r3', type: 'SPOT_CROSSES_GAMMA_FLIP', enabled: false, cooldownSec: 600 },
  { id: 'r4', type: 'NET_GEX_CHANGES_SIGN', enabled: true, cooldownSec: 900 },
  { id: 'r5', type: 'NET_GEX_ABOVE', enabled: false, threshold: 50, cooldownSec: 600 },
  { id: 'r6', type: 'NET_GEX_BELOW', enabled: false, threshold: -50, cooldownSec: 600 },
];

const ruleLabel = (type: AlertRuleType): string => {
  switch (type) {
    case 'SPOT_BREAKS_PUT_WALL':  return 'Spot breaks Put Wall';
    case 'SPOT_BREAKS_CALL_WALL': return 'Spot breaks Call Wall';
    case 'SPOT_CROSSES_GAMMA_FLIP': return 'Spot crosses Gamma Flip';
    case 'NET_GEX_CHANGES_SIGN':  return 'Net GEX flips sign';
    case 'NET_GEX_ABOVE':         return 'Net GEX above threshold';
    case 'NET_GEX_BELOW':         return 'Net GEX below threshold';
  }
};

/**
 * Returns a human-readable message if the rule should fire given the new
 * metrics and the previous snapshot, else null.
 */
const evaluateRule = (
  rule: AlertRule,
  curr: GexData,
  prev: GexData | null
): string | null => {
  switch (rule.type) {
    case 'SPOT_BREAKS_PUT_WALL': {
      if (!curr.spot || !curr.put_wall || !prev?.spot || !prev.put_wall) return null;
      if (prev.spot >= prev.put_wall && curr.spot < curr.put_wall) {
        return `Spot ${curr.spot.toFixed(2)} broke put wall ${curr.put_wall.toFixed(2)}`;
      }
      return null;
    }
    case 'SPOT_BREAKS_CALL_WALL': {
      if (!curr.spot || !curr.call_wall || !prev?.spot || !prev.call_wall) return null;
      if (prev.spot <= prev.call_wall && curr.spot > curr.call_wall) {
        return `Spot ${curr.spot.toFixed(2)} broke call wall ${curr.call_wall.toFixed(2)}`;
      }
      return null;
    }
    case 'SPOT_CROSSES_GAMMA_FLIP': {
      const cf = curr.gamma_flip;
      const pf = prev?.gamma_flip;
      if (typeof cf !== 'number' || !curr.spot || typeof pf !== 'number' || !prev?.spot) return null;
      const crossed = (prev.spot - pf) * (curr.spot - cf) < 0;
      return crossed ? `Spot ${curr.spot.toFixed(2)} crossed gamma flip ${cf.toFixed(2)}` : null;
    }
    case 'NET_GEX_CHANGES_SIGN': {
      const c = curr.net_gex_total;
      const p = prev?.net_gex_total;
      if (typeof c !== 'number' || typeof p !== 'number') return null;
      if ((p > 0 && c <= 0) || (p < 0 && c >= 0)) {
        return `Net GEX flipped to ${c >= 0 ? '+' : ''}${c.toFixed(1)}M`;
      }
      return null;
    }
    case 'NET_GEX_ABOVE': {
      const c = curr.net_gex_total;
      if (typeof c !== 'number' || rule.threshold === undefined) return null;
      return c > rule.threshold ? `Net GEX ${c.toFixed(1)}M > ${rule.threshold}M` : null;
    }
    case 'NET_GEX_BELOW': {
      const c = curr.net_gex_total;
      if (typeof c !== 'number' || rule.threshold === undefined) return null;
      return c < rule.threshold ? `Net GEX ${c.toFixed(1)}M < ${rule.threshold}M` : null;
    }
  }
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
  // Browser Notification permission state — 'unsupported' on browsers without the API
  const [notificationPermission, setNotificationPermission] = useState<
    NotificationPermission | 'unsupported'
  >(typeof Notification === 'undefined' ? 'unsupported' : Notification.permission);
  // Pause flag — when true, new WS metrics are kept but a separate
  // 'frozenMetrics' snapshot is exposed for rendering. Useful for visual
  // inspection of state without being thrown off by live updates.
  const [isPaused, setIsPaused] = useState(false);
  const [frozenMetrics, setFrozenMetrics] = useState<GexData | null>(null);
  const metricsRef = useRef<GexData | null>(null);
  const wasPausedRef = useRef(false);

  // Keep a ref to the latest metrics so togglePause can snapshot it
  useEffect(() => {
    metricsRef.current = metrics;
  }, [metrics]);

  // When transitioning paused → running, clear the frozen snapshot.
  // When transitioning running → paused, snapshot the current metrics.
  useEffect(() => {
    if (isPaused && !wasPausedRef.current) {
      setFrozenMetrics(metricsRef.current);
    } else if (!isPaused && wasPausedRef.current) {
      setFrozenMetrics(null);
    }
    wasPausedRef.current = isPaused;
  }, [isPaused]);
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
   * Honors the current sound settings (enabled + volume) via soundSettingsRef.
   */
  const playBeep = () => {
    try {
      const { enabled, volume } = soundSettingsRef.current;
      if (!enabled) return;
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      osc.type = 'sine';
      const peak = Math.max(0.001, volume);
      gain.gain.setValueAtTime(peak, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.2);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.2);
      // Close context after beep finishes
      setTimeout(() => ctx.close(), 300);
    } catch (e) {
      // Silent fail — autoplay policy may block
    }
  };

  /**
   * Show a browser notification if permission is granted. No-op otherwise.
   * Auto-closes after 6s.
   */
  const showBrowserNotification = (title: string, body: string) => {
    try {
      if (typeof Notification === 'undefined') return;
      if (Notification.permission !== 'granted') return;
      const n = new Notification(title, {
        body,
        icon: '/favicon.ico',
        tag: 'trading-deck-signal',
      });
      setTimeout(() => n.close(), 6000);
    } catch (e) {
      console.error('Notification failed', e);
    }
  };

  /**
   * Request browser notification permission. Must be called from a user
   * gesture (e.g. button click) — browsers will silently reject otherwise.
   */
  const requestNotificationPermission = async (): Promise<NotificationPermission | 'unsupported'> => {
    if (typeof Notification === 'undefined') return 'unsupported';
    try {
      const result = await Notification.requestPermission();
      setNotificationPermission(result);
      addLog(result === 'granted' ? '🔔 Browser notifications enabled' : `Notifications: ${result}`);
      return result;
    } catch (e: any) {
      addLog(`Notification permission request failed: ${e.message}`);
      return notificationPermission;
    }
  };

  /**
   * Toggle the pause state. When paused, the most recent metrics snapshot is
   * frozen and returned via `metrics` so the UI stops refreshing while the
   * underlying WS keeps streaming (and the live snapshot updates on resume).
   */
  const togglePause = () => {
    setIsPaused(prev => {
      const next = !prev;
      addLog(next ? '⏸  Paused — UI frozen on last snapshot' : '▶  Resumed — UI now live');
      return next;
    });
  };

  /**
   * Force a manual refresh — calls getMetrics() and logs the action.
   */
  const refreshNow = () => {
    addLog('⟳ Manual refresh triggered (kbd "r")');
    void getMetrics();
  };

  // ---------------------------------------------------------------------------
  // Configurable alert rules (user-defined thresholds)
  // ---------------------------------------------------------------------------
  const [alertRules, setAlertRules] = useState<AlertRule[]>(() => {
    try {
      const raw = localStorage.getItem(ALERT_RULES_KEY);
      if (!raw) return defaultAlertRules();
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    } catch {
      // Ignore — fall through to defaults
    }
    return defaultAlertRules();
  });

  // Persist rule changes
  useEffect(() => {
    try {
      localStorage.setItem(ALERT_RULES_KEY, JSON.stringify(alertRules));
    } catch {
      // Silent fail
    }
  }, [alertRules]);

  // ---------------------------------------------------------------------------
  // Sound settings (enabled + volume)
  // ---------------------------------------------------------------------------
  const [soundSettings, setSoundSettings] = useState<SoundSettings>(() => {
    try {
      const raw = localStorage.getItem(SOUND_SETTINGS_KEY);
      if (!raw) return defaultSoundSettings();
      const parsed = JSON.parse(raw);
      if (typeof parsed?.enabled === 'boolean' && typeof parsed?.volume === 'number') {
        return { enabled: parsed.enabled, volume: Math.max(0, Math.min(1, parsed.volume)) };
      }
    } catch {
      // Ignore
    }
    return defaultSoundSettings();
  });
  useEffect(() => {
    try {
      localStorage.setItem(SOUND_SETTINGS_KEY, JSON.stringify(soundSettings));
    } catch {
      // Silent fail
    }
  }, [soundSettings]);
  // Ref so playBeep can read the latest settings without re-binding the effect.
  const soundSettingsRef = useRef<SoundSettings>(soundSettings);
  useEffect(() => { soundSettingsRef.current = soundSettings; }, [soundSettings]);

  // Track last-fired time per rule ID for cooldown enforcement
  const lastFiredRef = useRef<Map<string, number>>(new Map());
  // Track previous metrics for transition detection (sign change, level cross)
  const prevMetricsRef = useRef<GexData | null>(null);

  // Watch for rule firings on every metrics update
  useEffect(() => {
    if (!metrics) return;
    const now = Date.now();
    for (const rule of alertRules) {
      if (!rule.enabled) continue;
      const cooldownMs = (rule.cooldownSec ?? 300) * 1000;
      const last = lastFiredRef.current.get(rule.id) ?? 0;
      if (now - last < cooldownMs) continue;

      const fired = evaluateRule(rule, metrics, prevMetricsRef.current);
      if (fired) {
        lastFiredRef.current.set(rule.id, now);
        playBeep();
        showBrowserNotification(`⚡ ${ruleLabel(rule.type)}`, fired);
        addLog(`⚡ Alert fired: ${ruleLabel(rule.type)} — ${fired}`);
      }
    }
    prevMetricsRef.current = metrics;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metrics, alertRules]);

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
            // Merge partial updates (monitor_levels sends {spot} only) without wiping full state.
            // When paused, we still update `metrics` but also snapshot into
            // `frozenMetrics` so consumers can choose what to display.
            setMetrics(prev => {
              const merged = { ...prev, ...payload.data };
              // Push to sparkline buffers (cap at SPARK_BUFFER_SIZE)
              if (typeof merged.spot === 'number' && merged.spot > 0) {
                setSpotHistory(h => appendSample(h, merged.spot));
              }
              if (typeof merged.net_gex_total === 'number') {
                setNetGexHistory(h => appendSample(h, merged.net_gex_total));
              }
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

  // ---------------------------------------------------------------------------
  // Signal alerts: beep + browser notification on new EXECUTED signals
  // ---------------------------------------------------------------------------
  // Track the count we've already seen so we only fire on new additions
  // (and not on initial load or refetch replacement).
  const seenSignalCountRef = useRef<number>(0);
  // Track a set of "keys" (timestamp-strike-side) we've already alerted on,
  // so that re-sorts or duplicate signals don't re-fire the beep.
  const alertedKeysRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (tapeSignals.length === 0) {
      seenSignalCountRef.current = 0;
      alertedKeysRef.current.clear();
      return;
    }
    // First observation — just seed; don't alert on existing signals.
    if (seenSignalCountRef.current === 0 && alertedKeysRef.current.size === 0) {
      seenSignalCountRef.current = tapeSignals.length;
      for (const s of tapeSignals) {
        alertedKeysRef.current.add(`${s.timestamp}-${s.strike}-${s.side}`);
      }
      return;
    }
    // Only consider signals added since last observation.
    const newOnes = tapeSignals.slice(seenSignalCountRef.current);
    seenSignalCountRef.current = tapeSignals.length;
    for (const s of newOnes) {
      const key = `${s.timestamp}-${s.strike}-${s.side}`;
      if (alertedKeysRef.current.has(key)) continue;
      alertedKeysRef.current.add(key);
      if (s.status === 'EXECUTED') {
        playBeep();
        showBrowserNotification(
          `Signal Executed · ${s.side === 'C' ? 'Call' : 'Put'} ${s.strike}`,
          `Z=${s.z_score.toFixed(2)} · ratio ${s.ratio.toFixed(1)} · ask $${s.ask.toFixed(2)}`
        );
        addLog(`🔔 New EXECUTED signal: ${s.side === 'C' ? 'C' : 'P'} ${s.strike} @ $${s.ask.toFixed(2)}`);
      }
    }
    // Cap the alerted set size to avoid unbounded growth on long sessions.
    if (alertedKeysRef.current.size > 500) {
      const arr = Array.from(alertedKeysRef.current);
      alertedKeysRef.current = new Set(arr.slice(arr.length - 300));
    }
  }, [tapeSignals]);

  return {
    connected,
    connectedLive,
    connecting,
    liveTradingArmed,
    wsConnected,
    notificationPermission,
    isPaused,
    metrics,
    displayMetrics: isPaused ? (frozenMetrics ?? metrics) : metrics,
    logs,
    alerts,
    position,
    tapeSignals,
    recommendation,
    spotHistory,
    netGexHistory,
    pnlHistory,
    alertRules,
    setAlertRules,
    soundSettings,
    setSoundSettings,
    /** Probe beep — used by the sound settings test button. */
    testBeep: playBeep,
    connectToIBKR,
    connectLive,
    getMetrics,
    executeTrade,
    refreshNow,
    togglePause,
    fetchHistory,
    dismissAlert,
    armLiveTrading,
    disarmLiveTrading,
    requestNotificationPermission,
  };
}
