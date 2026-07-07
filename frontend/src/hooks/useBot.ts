import { useState, useEffect, useCallback, useRef } from 'react';

const API = '/api';

export interface BotSignal {
  strategy: 'FLIP' | 'PINNING' | 'TREND' | 'ORB';
  direction: 'BULL_PUT' | 'BEAR_CALL' | 'IC' | 'BUY_CALL' | 'BUY_PUT';
  short_strike: number;
  long_strike: number;
  width: number;
  entry_credit: number;
  tp_credit: number;
  sl_credit: number;
  confidence: number;
  reason: string;
  timestamp: number;
  entry_trigger?: number | null;
  tp_trigger?: number | null;
  sl_trigger?: number | null;
}

export interface BotStatus {
  running: boolean;
  auto_mode: boolean;
  enabled_strategies: string[];
  active_positions: Record<string, any>;
  daily_trades: BotTrade[];
  daily_pnl: number;
  current_signal: BotSignal | null;
  limits_reached: boolean;
  evaluation: Record<string, StrategyEval> | null;
  orb: OrbStatus | null;
}

export interface OrbStatus {
  high: number | null;
  low: number | null;
  mid: number | null;
  session_active: boolean;
  evaluated: boolean;
  direction: 'BULLISH' | 'BEARISH' | null;
}

export interface StrategyEval {
  enabled: boolean;
  has_position: boolean;
  prev_net_gex?: number | null;
  net_gex?: number;
  flipped?: boolean;
  abs_net_gex_ok?: boolean;
  bias?: string;
  signals?: boolean;
  regime?: string;
  regime_ok?: boolean;
  breakout_risk?: string;
  breakout_ok?: boolean;
  call_wall?: number;
  put_wall?: number;
  bias_ok?: boolean;
}

export interface BotTrade {
  strategy: string;
  direction: string;
  short_strike: number;
  long_strike?: number;
  entry_credit: number;
  timestamp: number;
}

export interface TradedTrade extends BotTrade {
  width: number;
  tp_credit: number;
  sl_credit: number;
  execution_mode: 'AUTO' | 'MANUAL';
  date: string;
}

// Module-level cache persists across component remounts (drawer close/reopen)
let _cachedStatus: BotStatus = {
  running: false,
  auto_mode: false,
  enabled_strategies: ['FLIP', 'PINNING', 'TREND', 'ORB'],
  active_positions: {},
  daily_trades: [] as BotTrade[],
  evaluation: null as Record<string, StrategyEval> | null,
  daily_pnl: 0,
  current_signal: null,
  limits_reached: false,
  orb: null,
};

let _pollInterval: ReturnType<typeof setInterval> | null = null;

export function useBot() {
  const [status, setStatus] = useState<BotStatus>({
    ..._cachedStatus,
    daily_trades: [],
    evaluation: null,
  });
  const [trades, setTrades] = useState<TradedTrade[]>([]);
  const fetchCountRef = useRef(0);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/bot/status`);
      if (res.ok) {
        const data = await res.json();
        _cachedStatus = data;
        setStatus(data);
      }
    } catch {
      // Ignore fetch errors in polling
    }
  }, []);

  const startBot = useCallback(async () => {
    const res = await fetch(`${API}/bot/start`, { method: 'POST' });
    if (res.ok) {
      _cachedStatus = { ..._cachedStatus, running: true };
      setStatus(_cachedStatus);
      _ensurePolling();
    }
  }, []);

  const stopBot = useCallback(async () => {
    const res = await fetch(`${API}/bot/stop`, { method: 'POST' });
    if (res.ok) {
      _cachedStatus = { ..._cachedStatus, running: false };
      setStatus(_cachedStatus);
    }
  }, []);

  const toggleStrategy = useCallback(async (strategy: string, enabled: boolean) => {
    await fetch(`${API}/bot/strategy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy, enabled }),
    });
    fetchStatus();
  }, [fetchStatus]);

  const toggleAutoMode = useCallback(async (enabled: boolean) => {
    await fetch(`${API}/bot/auto_mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    _cachedStatus = { ..._cachedStatus, auto_mode: enabled };
    setStatus(_cachedStatus);
  }, []);

  const executeSignal = useCallback(async (signal: BotSignal) => {
    const res = await fetch(`${API}/bot/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ signal }),
    });
    const data = await res.json();
    if (data.ok) {
      fetchStatus();
      fetchTrades();
    }
    return data;
  }, [fetchStatus]);

  const forceScan = useCallback(async () => {
    const res = await fetch(`${API}/bot/force_scan`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      _cachedStatus = data.status;
      setStatus(_cachedStatus);
      return data.signal as BotSignal | null;
    }
    return null;
  }, [fetchStatus]);

  const fetchTrades = useCallback(async () => {
    try {
      const res = await fetch(`${API}/bot/trades`);
      if (res.ok) {
        const data = await res.json();
        setTrades(data.trades as TradedTrade[]);
      }
    } catch {
      // Ignore errors
    }
  }, []);

  // Keep polling alive regardless of component mount state
  function _ensurePolling() {
    if (_pollInterval === null) {
      fetchStatus();
      _pollInterval = setInterval(fetchStatus, 30000);
    }
  }

  useEffect(() => {
    fetchCountRef.current += 1;
    const isFirstMount = fetchCountRef.current === 1;
    if (isFirstMount) {
      _ensurePolling();
    }
    return () => {
      // Don't stop polling on unmount — keep it alive so status survives drawer close/reopen
    };
  }, [fetchStatus]);

  return {
    status,
    trades,
    startBot,
    stopBot,
    toggleStrategy,
    toggleAutoMode,
    executeSignal,
    forceScan,
    fetchStatus,
    fetchTrades,
  };
}
