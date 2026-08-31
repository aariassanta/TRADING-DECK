# -*- coding: utf-8 -*-
"""
0DTE GEX Trading Bot Engine
=================================
Semi-automatic bot that evaluates GEX regime and suggests trades.
Human-in-the-loop: user decides whether to execute each signal.

Strategies: FLIP, PINNING (Iron Condor), TREND
Max 3 trades/day, paper trading only.
"""

import asyncio
import csv
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, NamedTuple


def _to_native(obj):
    """Recursively convert numpy / pandas types to native Python for JSON serialization."""
    import numpy as np
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(x) for x in obj]
    return obj

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class BotSignal(NamedTuple):
    strategy: Literal['FLIP', 'PINNING', 'TREND', 'ORB', 'ORB15', 'IRON_FLY', 'MILK_MAN']
    direction: Literal['BULL_PUT', 'BEAR_CALL', 'IC', 'BUY_CALL', 'BUY_PUT']
    short_strike: float
    long_strike: float
    width: int
    entry_credit: float
    tp_credit: float
    sl_credit: float
    confidence: float  # 0-1
    reason: str
    timestamp: float = None
    # ORB-based price triggers
    entry_trigger: float | None = None   # price of underlying to trigger entry
    tp_trigger: float | None = None      # price of underlying for take-profit
    sl_trigger: float | None = None      # price of underlying for stop-loss
    # Iron Fly: per-side delta targets (engine resolves to strikes via _find_strike_by_delta)
    delta_target_put: float | None = None   # e.g. -0.50 → short put at -0.50 delta
    delta_target_call: float | None = None  # e.g. +0.40 → short call at +0.40 delta


# ---------------------------------------------------------------------------
# BotEngine
# ---------------------------------------------------------------------------

class BotEngine:
    """
    Evaluates GEX regime every SCAN_INTERVAL seconds and emits trade signals.
    All trades go to paper engine only. Human approves each execution.
    """

    SCAN_INTERVAL = 300       # 5 minutes
    MAX_DAILY_TRADES = 3
    MAX_DAILY_LOSS_PCT = 0.05  # 5% of capital
    ENTRY_DEADLINE_HOUR = 13   # 13:00 EST — no new positions after
    TIME_EXIT_HOUR = 15.5      # 15:30 EST — force close all

    def __init__(self, paper_engine, metrics_cache, capital: float = 25000):
        self.engine = paper_engine
        self.get_metrics = metrics_cache          # () -> GexData dict
        self.capital = capital

        # State
        self.enabled_strategies: set[str] = {'FLIP', 'PINNING', 'TREND', 'ORB', 'ORB15', 'IRON_FLY', 'MILK_MAN'}
        self.bot_running: bool = False
        self.auto_mode: bool = False   # if True, auto-execute signals without human approval
        self._scan_task: asyncio.Task | None = None

        # Previous tick data for flip detection
        self._prev_net_gex: float | None = None

        # Active positions: strategy name -> {open: bool, entry_credit: float, ...}
        self.active_positions: dict[str, dict] = {}

        # Daily stats (reset each day)
        self.daily_trades: list[dict] = []
        self.daily_pnl: float = 0.0
        self._last_reset_date: str = self._est_date()

        # Signal history
        self.signal_history: list[BotSignal] = []
        self.current_signal: BotSignal | None = None

        # Last evaluation: raw conditions per strategy (for debug panel)
        self._last_evaluation: dict = {}

        # ORB state
        self.orb_high: float | None = None
        self.orb_low: float | None = None
        self.orb_mid: float | None = None
        self.orb_session_active: bool = False      # 9:30-10:30 EST tracking in progress
        self.orb_evaluated: bool = False         # ORB session closed and signal emitted (or not)
        self.orb_direction: Literal['BULLISH', 'BEARISH'] | None = None  # direction after ORB close
        self.orb_arb_low_broken: bool = False    # was low broken first (bullish signal)
        self.orb_arb_high_broken: bool = False   # was high broken first (bearish signal)
        self._orb_tick_task: asyncio.Task | None = None

        # ORB15 state — 4-step ORB with displacement filter, spreads execution
        self.orb15_session_open: float | None = None   # open of 9:30 first candle
        self.orb15_high: float | None = None
        self.orb15_low: float | None = None
        self.orb15_range: float | None = None
        self.orb15_body_list: list[float] = []         # bodies of all 5-min candles for median
        self.orb15_step: Literal['idle', 'forming', 'breakout', 'pullback', 'rebreakout', 'signalled'] = 'idle'
        self.orb15_breakout_dir: Literal['bull', 'bear'] | None = None
        self.orb15_breakout_time: datetime | None = None
        self.orb15_pullback_seen: bool = False
        self.orb15_rebreakout_dir: Literal['bull', 'bear'] | None = None
        self.orb15_rebreakout_time: datetime | None = None
        self.orb15_rebreakout_body: float | None = None
        self.orb15_evaluated: bool = False
        self._orb15_tick_task: asyncio.Task | None = None
        self._orb15_last_5min_bar_open: float | None = None
        self._orb15_bar_period: int | None = None  # stored bar period to detect new 5-min bar

        # Milk Man state — weekly PCS, survives _reset_daily
        self.milk_strike: float | None = None       # short strike chosen this week
        self.milk_atr: float | None = None         # ATR_semanal(14) at entry
        self.milk_odds: float | None = None       # odds at entry (put_price / payout)
        self.milk_odds_history: list[float] = []  # accumulated for 1Y median
        self._milk_man_loop_task: asyncio.Task | None = None
        self._milk_week_active: bool = False        # True Mon-Fri while position or setup is live

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def start(self):
        """Start the background scan loop and ORB tracking."""
        if self.bot_running:
            return
        self.bot_running = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._orb_tick_task = asyncio.create_task(self._orb_loop())
        self._orb15_tick_task = asyncio.create_task(self._orb15_loop())
        self._milk_man_loop_task = asyncio.create_task(self._milk_man_loop())
        print("[Bot] Started")

    async def stop(self):
        """Stop the background scan loop and ORB tracking."""
        self.bot_running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None
        if self._orb_tick_task:
            self._orb_tick_task.cancel()
            try:
                await self._orb_tick_task
            except asyncio.CancelledError:
                pass
            self._orb_tick_task = None
        if self._orb15_tick_task:
            self._orb15_tick_task.cancel()
            try:
                await self._orb15_tick_task
            except asyncio.CancelledError:
                pass
            self._orb15_tick_task = None
        if self._milk_man_loop_task:
            self._milk_man_loop_task.cancel()
            try:
                await self._milk_man_loop_task
            except asyncio.CancelledError:
                pass
            self._milk_man_loop_task = None
        print("[Bot] Stopped")

    def get_status(self) -> dict:
        """Return current bot status for API endpoint."""
        return {
            "running": self.bot_running,
            "auto_mode": self.auto_mode,
            "enabled_strategies": list(self.enabled_strategies),
            "active_positions": self.active_positions,
            "daily_trades": self.daily_trades,
            "daily_pnl": round(self.daily_pnl, 2),
            "current_signal": self._signal_to_dict(self.current_signal),
            "limits_reached": bool(self._limits_reached()),
            "evaluation": _to_native(self._last_evaluation),
            "orb": _to_native({
                "high": self.orb_high,
                "low": self.orb_low,
                "mid": self.orb_mid,
                "session_active": self.orb_session_active,
                "evaluated": self.orb_evaluated,
                "direction": self.orb_direction,
            }),
            "orb15": {
                "session_open": self.orb15_session_open,
                "high": self.orb15_high,
                "low": self.orb15_low,
                "range": self.orb15_range,
                "step": self.orb15_step,
                "breakout_dir": self.orb15_breakout_dir,
                "pullback_seen": self.orb15_pullback_seen,
                "rebreakout_dir": self.orb15_rebreakout_dir,
                "rebreakout_body": self.orb15_rebreakout_body,
                "evaluated": self.orb15_evaluated,
                "median_body": float(sorted(self.orb15_body_list)[len(self.orb15_body_list)//2]) if self.orb15_body_list else None,
            },
            "milk_man": {
                "short_strike": self.milk_strike,
                "atr": self.milk_atr,
                "odds": self.milk_odds,
                "odds_history_len": len(self.milk_odds_history),
            },
        }

    def toggle_strategy(self, strategy: str, enabled: bool):
        """Enable or disable a strategy."""
        if enabled:
            self.enabled_strategies.add(strategy)
        else:
            self.enabled_strategies.discard(strategy)

    def set_auto_mode(self, enabled: bool):
        """Enable or disable auto-execution mode."""
        self.auto_mode = enabled
        print(f"[Bot] Auto mode {'enabled' if enabled else 'disabled'}")

    async def execute_signal(self, signal: BotSignal, execution_mode: Literal['AUTO', 'MANUAL'] = 'MANUAL', transmit: bool = True, bracket: bool = True) -> dict:
        """Execute a signal (human-approved). Returns result dict.

        Args:
            transmit: If False, the bracket order is staged in TWS but NOT sent
                to the exchange. Use for dry-runs / smoke tests.
            bracket: If False, only the entry combo is placed (no TP/SL children).
                Useful when the operator manages exits manually.
        """
        # ORB strategy uses single-leg call/put purchase
        if signal.strategy == 'ORB':
            right = 'CALL' if signal.direction == 'BUY_CALL' else 'PUT'
            try:
                await self.engine.execute_single_leg(
                    right=right,
                    qty=1,
                    strike=None,
                    orb_mid=signal.entry_trigger,
                    limit_price=None,
                    transmit=True,
                    entry_trigger_price=signal.entry_trigger,
                    tp_trigger_price=signal.tp_trigger,
                    sl_trigger_price=signal.sl_trigger,
                )
                trade = {
                    "strategy": signal.strategy,
                    "direction": signal.direction,
                    "short_strike": 0,
                    "long_strike": 0,
                    "width": 0,
                    "entry_credit": 0,
                    "tp_credit": 0,
                    "sl_credit": 0,
                    "timestamp": signal.timestamp,
                }
                self.daily_trades.append(trade)
                self._log_trade_to_csv(trade, execution_mode)
                self.active_positions[signal.strategy] = {"open": True}
                self.current_signal = None
                return {"ok": True, "trade": trade}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # GEX strategies use credit spreads
        spread_type = 'IC' if signal.direction == 'IC' else (
            'PCS' if 'PUT' in signal.direction else 'CCS'
        )

        # ORB15 anchors to ORB levels (pre-computed); IRON_FLY uses per-side delta targets;
# FLIP/PINNING/TREND anchor to GEX walls.
        if signal.strategy == 'ORB15':
            target_mode = 'orb15'
            target_value = signal.short_strike
        elif signal.strategy == 'IRON_FLY':
            target_mode = 'iron_fly'
            target_value = 0   # ignored by iron_fly branch (uses delta_target_put/call kwargs)
            bracket = False    # hold-to-expiry: never use TP/SL bracket
        elif signal.strategy == 'MILK_MAN':
            target_mode = 'milk_man'
            target_value = signal.short_strike
            bracket = False    # hold-to-settlement: no TP/SL bracket
        else:
            target_mode = 'GEX'
            target_value = 0

        try:
            await self.engine.execute_spread(
                spread_type=spread_type,
                qty=1,
                target_mode=target_mode,
                target_value=target_value,
                width=signal.width,
                tp_pct=50 if signal.strategy != 'TREND' else 60,
                sl_ratio=2.0,
                transmit=transmit,
                entry_trigger_price=signal.entry_trigger,
                tp_trigger_price=signal.tp_trigger,
                sl_trigger_price=signal.sl_trigger,
                bracket=bracket,
                delta_target_put=signal.delta_target_put,
                delta_target_call=signal.delta_target_call,
            )

            # Record the trade
            trade = {
                "strategy": signal.strategy,
                "direction": signal.direction,
                "short_strike": signal.short_strike,
                "long_strike": signal.long_strike,
                "width": signal.width,
                "entry_credit": signal.entry_credit,
                "tp_credit": signal.tp_credit,
                "sl_credit": signal.sl_credit,
                "timestamp": signal.timestamp,
            }
            self.daily_trades.append(trade)
            self._log_trade_to_csv(trade, execution_mode)

            # Track active position
            self.active_positions[signal.strategy] = {
                "open": True,
                "entry_credit": signal.entry_credit,
                "short_strike": signal.short_strike,
            }

            # Clear current signal
            self.current_signal = None

            return {"ok": True, "trade": trade}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Scan loop
    # -------------------------------------------------------------------------

    async def _scan_loop(self):
        """Background loop: runs every SCAN_INTERVAL seconds."""
        while self.bot_running:
            # Reset daily stats at market open (EST midnight → new day)
            current_date = self._est_date()
            if current_date != self._last_reset_date:
                self._reset_daily()
                self._last_reset_date = current_date

            # Skip if outside market hours (approx)
            if self._past_deadline():
                await asyncio.sleep(self.SCAN_INTERVAL)
                continue

            signal = await self.scan_and_signal()
            if signal:
                self.current_signal = signal
                self.signal_history.append(signal)
                # Keep last 20 signals
                if len(self.signal_history) > 20:
                    self.signal_history = self.signal_history[-20:]

                # Auto-execute if auto_mode is enabled
                if self.auto_mode:
                    result = await self.execute_signal(signal, execution_mode='AUTO')
                    print(f"[Bot] Auto-executed {signal.strategy}: {result} [AUTO]")

            await asyncio.sleep(self.SCAN_INTERVAL)

    async def scan_and_signal(self) -> BotSignal | None:
        """
        Evaluate all enabled strategies and return the first valid signal.
        Priority: FLIP → PINNING → TREND
        """
        metrics = self.get_metrics()
        if not metrics:
            return None

        # Check hard limits
        if self._limits_reached():
            return None

        net_gex = metrics.get('net_gex_total', 0)
        regime = metrics.get('regime', 'NEUTRAL')
        bias = metrics.get('bias', 'NEUTRAL')
        breakout_risk = metrics.get('breakout_risk', 'MEDIUM')
        call_wall = metrics.get('call_wall') or metrics.get('spot', 5000)
        put_wall = metrics.get('put_wall') or metrics.get('spot', 5000)

        prev_net_gex = self._prev_net_gex
        flipped = (prev_net_gex is not None and
                   ((prev_net_gex > 0 and net_gex < 0) or (prev_net_gex < 0 and net_gex > 0)))

        # Update live evaluation state for debug panel
        self._last_evaluation = {
            "FLIP": {
                "enabled": 'FLIP' in self.enabled_strategies,
                "has_position": 'FLIP' in self.active_positions,
                "prev_net_gex": prev_net_gex,
                "net_gex": net_gex,
                "flipped": flipped,
                "abs_net_gex_ok": abs(net_gex) >= 5,
                "bias": bias,
                "signals": flipped and abs(net_gex) >= 5 and bias != 'NEUTRAL',
            },
            "PINNING": {
                "enabled": 'PINNING' in self.enabled_strategies,
                "has_position": 'PINNING' in self.active_positions,
                "regime": regime,
                "regime_ok": regime == 'LONG_GAMMA',
                "breakout_risk": breakout_risk,
                "breakout_ok": breakout_risk != 'HIGH',
                "call_wall": call_wall,
                "put_wall": put_wall,
                "signals": regime == 'LONG_GAMMA' and breakout_risk != 'HIGH',
            },
            "TREND": {
                "enabled": 'TREND' in self.enabled_strategies,
                "has_position": 'TREND' in self.active_positions,
                "regime": regime,
                "regime_ok": regime == 'SHORT_GAMMA',
                "bias": bias,
                "bias_ok": bias != 'NEUTRAL',
                "breakout_risk": breakout_risk,
                "breakout_ok": breakout_risk == 'LOW',
                "signals": regime == 'SHORT_GAMMA' and bias != 'NEUTRAL' and breakout_risk == 'LOW',
            },
            "ORB15": {
                "enabled": 'ORB15' in self.enabled_strategies,
                "has_position": 'ORB15' in self.active_positions,
                "step": self.orb15_step,
                "session_open": self.orb15_session_open,
                "high": self.orb15_high,
                "low": self.orb15_low,
                "range": self.orb15_range,
                "breakout_dir": self.orb15_breakout_dir,
                "pullback_seen": self.orb15_pullback_seen,
                "rebreakout_dir": self.orb15_rebreakout_dir,
                "rebreakout_body": self.orb15_rebreakout_body,
                "median_body": float(sorted(self.orb15_body_list)[len(self.orb15_body_list)//2]) if self.orb15_body_list else None,
                "signals": self.orb15_step == 'signalled' and self.orb15_rebreakout_body is not None,
            },
            "IRON_FLY": {
                "enabled": 'IRON_FLY' in self.enabled_strategies,
                "has_position": 'IRON_FLY' in self.active_positions,
                "now_et": self._est_time().strftime('%H:%M'),
                "is_wednesday": self._est_time().weekday() == 2,
                "in_window": (
                    13 * 60 + 40 <= self._est_time().hour * 60 + self._est_time().minute
                    <= 13 * 60 + 55
                ),
                "vix": metrics.get('vix'),  # current VIX from live metrics
                "delta_put": -0.50,
                "delta_call": +0.40,
            },
            "MILK_MAN": {
                "enabled": 'MILK_MAN' in self.enabled_strategies,
                "has_position": 'MILK_MAN' in self.active_positions,
                "short_strike": self.milk_strike,
                "atr": self.milk_atr,
                "odds": self.milk_odds,
                "odds_history_len": len(self.milk_odds_history),
                "median_1y": float(sorted(self.milk_odds_history)[len(self.milk_odds_history)//2]) if len(self.milk_odds_history) >= 12 else None,
                "week_active": self._milk_week_active,
                "signals": self.milk_strike is not None and 'MILK_MAN' not in self.active_positions,
            },
        }

        # Check for FLIP
        if 'FLIP' in self.enabled_strategies and 'FLIP' not in self.active_positions:
            signal = await self._evaluate_flip(metrics, net_gex)
            if signal:
                return signal

        # Check for PINNING
        if 'PINNING' in self.enabled_strategies and 'PINNING' not in self.active_positions:
            signal = await self._evaluate_pinning(metrics)
            if signal:
                return signal

        # Check for TREND
        if 'TREND' in self.enabled_strategies and 'TREND' not in self.active_positions:
            signal = await self._evaluate_trend(metrics)
            if signal:
                return signal

        # Check for ORB (after ORB session closes)
        if 'ORB' in self.enabled_strategies and 'ORB' not in self.active_positions:
            signal = await self._evaluate_orb(metrics)
            if signal:
                return signal

        # Check for ORB15 (4-step ORB → credit spread)
        if 'ORB15' in self.enabled_strategies and 'ORB15' not in self.active_positions:
            signal = await self._evaluate_orb15(metrics)
            if signal:
                return signal

        # Check for IRON_FLY (0DTE Iron Butterfly on SPXW, 1:40-1:55 PM ET)
        if 'IRON_FLY' in self.enabled_strategies and 'IRON_FLY' not in self.active_positions:
            signal = await self._evaluate_iron_fly(metrics)
            if signal:
                return signal

        # Check for MILK_MAN (weekly PCS, Mon 10:00 ET)
        if 'MILK_MAN' in self.enabled_strategies and 'MILK_MAN' not in self.active_positions:
            signal = await self._evaluate_milk_man(metrics)
            if signal:
                return signal

        return None

    # -------------------------------------------------------------------------
    # Strategy evaluators
    # -------------------------------------------------------------------------

    async def _evaluate_flip(self, metrics: dict, net_gex: float) -> BotSignal | None:
        """
        FLIP: GEX crosses from positive to negative (or vice versa).
        Requires previous net_gex value to detect the crossing.
        """
        if self._prev_net_gex is None:
            self._prev_net_gex = net_gex
            return None

        prev = self._prev_net_gex
        curr = net_gex

        # Detect flip: sign changed AND not near zero
        flipped = (prev > 0 and curr < 0) or (prev < 0 and curr > 0)
        if not flipped:
            self._prev_net_gex = net_gex
            return None

        # Only trade if flip is significant (not marginal crossing near zero)
        if abs(curr) < 5:  # less than $5M net GEX — too thin
            self._prev_net_gex = net_gex
            return None

        self._prev_net_gex = net_gex

        bias = metrics.get('bias', 'NEUTRAL')
        call_wall = metrics.get('call_wall') or metrics.get('spot', 5000)
        put_wall = metrics.get('put_wall') or metrics.get('spot', 5000)

        if bias == 'BULLISH':
            # Bull Put Spread: short put at put_wall, long put lower
            short_strike = put_wall
            long_strike = short_strike - 5
            direction = 'BULL_PUT'
            reason = f"GEX flipped to {curr:+.1f}M, bias BULLISH → Bull Put"
        elif bias == 'BEARISH':
            # Bear Call Spread: short call at call_wall, long call higher
            short_strike = call_wall
            long_strike = short_strike + 5
            direction = 'BEAR_CALL'
            reason = f"GEX flipped to {curr:+.1f}M, bias BEARISH → Bear Call"
        else:
            return None

        width = 5
        entry_credit = 2.50
        tp = entry_credit * 0.50
        sl = entry_credit * 2.0
        confidence = 0.70

        return BotSignal(
            strategy='FLIP',
            direction=direction,
            short_strike=short_strike,
            long_strike=long_strike,
            width=width,
            entry_credit=entry_credit,
            tp_credit=tp,
            sl_credit=sl,
            confidence=confidence,
            reason=reason,
        )

    async def _evaluate_pinning(self, metrics: dict) -> BotSignal | None:
        """
        PINNING: LONG_GAMMA regime with pinning candidate.
        Suggests Iron Condor anchored at call_wall / put_wall.
        """
        regime = metrics.get('regime', 'NEUTRAL')
        breakout_risk = metrics.get('breakout_risk', 'MEDIUM')
        pinning_candidate = metrics.get('pinning_candidate')

        if regime != 'LONG_GAMMA':
            return None
        if breakout_risk == 'HIGH':
            return None
        if not pinning_candidate and not metrics.get('put_wall') or not metrics.get('call_wall'):
            return None

        call_wall = metrics.get('call_wall') or metrics.get('spot', 5000)
        put_wall = metrics.get('put_wall') or metrics.get('spot', 5000)

        # Iron Condor: short put at put_wall, long put 5pt lower
        #              short call at call_wall, long call 5pt higher
        short_put = put_wall
        long_put = short_put - 5
        short_call = call_wall
        long_call = short_call + 5

        width = 5
        entry_credit = 4.00   # total credit for both spreads
        tp = entry_credit * 0.50
        sl = entry_credit * 2.0
        confidence = 0.65

        reason = (f"LONG_GAMMA regime (pinning candidate {pinning_candidate}), "
                  f"breakout_risk {breakout_risk} → Iron Condor")

        return BotSignal(
            strategy='PINNING',
            direction='IC',
            short_strike=short_put,   # IC uses short_put as reference
            long_strike=long_call,    # and long_call as far wing
            width=width,
            entry_credit=entry_credit,
            tp_credit=tp,
            sl_credit=sl,
            confidence=confidence,
            reason=reason,
        )

    async def _evaluate_trend(self, metrics: dict) -> BotSignal | None:
        """
        TREND: SHORT_GAMMA regime with directional bias and low breakout risk.
        """
        regime = metrics.get('regime', 'NEUTRAL')
        bias = metrics.get('bias', 'NEUTRAL')
        breakout_risk = metrics.get('breakout_risk', 'MEDIUM')

        if regime != 'SHORT_GAMMA':
            return None
        if bias == 'NEUTRAL':
            return None
        if breakout_risk != 'LOW':
            return None

        call_wall = metrics.get('call_wall') or metrics.get('spot', 5000)
        put_wall = metrics.get('put_wall') or metrics.get('spot', 5000)

        if bias == 'BULLISH':
            # Bull Put Spread at put_wall support
            short_strike = put_wall
            long_strike = short_strike - 5
            direction = 'BULL_PUT'
            reason = f"SHORT_GAMMA + BULLISH bias, breakout_risk LOW → Bull Put"
        elif bias == 'BEARISH':
            # Bear Call Spread at call_wall resistance
            short_strike = call_wall
            long_strike = short_strike + 5
            direction = 'BEAR_CALL'
            reason = f"SHORT_GAMMA + BEARISH bias, breakout_risk LOW → Bear Call"
        else:
            return None

        width = 5
        entry_credit = 2.50
        tp = entry_credit * 0.60   # Trend gets 60% TP (higher R:R)
        sl = entry_credit * 2.0
        confidence = 0.60

        return BotSignal(
            strategy='TREND',
            direction=direction,
            short_strike=short_strike,
            long_strike=long_strike,
            width=width,
            entry_credit=entry_credit,
            tp_credit=tp,
            sl_credit=sl,
            confidence=confidence,
            reason=reason,
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _limits_reached(self) -> bool:
        """Check if any risk limit has been hit."""
        if len(self.daily_trades) >= self.MAX_DAILY_TRADES:
            return True
        if self.daily_pnl <= -(self.capital * self.MAX_DAILY_LOSS_PCT):
            return True
        return False

    def _past_deadline(self) -> bool:
        """Check if current EST time is past the entry deadline."""
        now_utc = datetime.now(timezone.utc)
        # EST = UTC - 5 (or UTC - 4 during DST — simplified)
        now_est_hour = (now_utc.hour - 5) % 24
        return now_est_hour >= self.ENTRY_DEADLINE_HOUR

    def _log_trade_to_csv(self, trade: dict, execution_mode: Literal['AUTO', 'MANUAL']):
        """Append executed trade to CSV log file."""
        log_dir = os.path.join(os.path.dirname(__file__), 'history')
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'trades_log.csv')
        # Use `or` so a None timestamp (BotSignal default) falls back to time.time()
        # instead of being written as an empty cell by csv.DictWriter.
        row = {
            'timestamp': trade.get('timestamp') or time.time(),
            'date': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'strategy': trade.get('strategy', ''),
            'direction': trade.get('direction', ''),
            'short_strike': trade.get('short_strike', 0),
            'long_strike': trade.get('long_strike', 0),
            'width': trade.get('width', 0),
            'entry_credit': trade.get('entry_credit', 0),
            'tp_credit': trade.get('tp_credit', 0),
            'sl_credit': trade.get('sl_credit', 0),
            'execution_mode': execution_mode,
        }
        file_exists = os.path.exists(log_path)
        with open(log_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        print(f"[Bot] Trade logged: {row['strategy']} {row['direction']} ({execution_mode}) → {log_path}")

    def _est_date(self) -> str:
        """Return current EST date string YYYYMMDD."""
        now_utc = datetime.now(timezone.utc)
        est_hour = (now_utc.hour - 5) % 24
        # If hour rolled negative, we're past midnight EST but same UTC day
        if now_utc.hour < 5:
            # Still previous day in EST
            yesterday = now_utc.replace(hour=now_utc.hour + 19)  # subtract 5, wrap
            return yesterday.strftime('%Y%m%d')
        return now_utc.strftime('%Y%m%d')

    def _reset_daily(self):
        """Reset daily counters."""
        self.daily_trades = []
        self.daily_pnl = 0.0
        self.active_positions = {}
        self.current_signal = None
        self._prev_net_gex = None
        # Reset ORB state for new day
        self.orb_high = None
        self.orb_low = None
        self.orb_mid = None
        self.orb_session_active = False
        self.orb_evaluated = False
        self.orb_direction = None
        self.orb_arb_low_broken = False
        self.orb_arb_high_broken = False
        # Reset ORB15 state
        self._orb15_reset()
        print("[Bot] Daily stats reset")

    def _signal_to_dict(self, signal: BotSignal | None) -> dict | None:
        if signal is None:
            return None
        return {
            "strategy": signal.strategy,
            "direction": signal.direction,
            "short_strike": signal.short_strike,
            "long_strike": signal.long_strike,
            "width": signal.width,
            "entry_credit": signal.entry_credit,
            "tp_credit": signal.tp_credit,
            "sl_credit": signal.sl_credit,
            "confidence": signal.confidence,
            "reason": signal.reason,
            "timestamp": signal.timestamp,
            "entry_trigger": signal.entry_trigger,
            "tp_trigger": signal.tp_trigger,
            "sl_trigger": signal.sl_trigger,
        }

    # -------------------------------------------------------------------------
    # ORB (Opening Range Breakout) tracking
    # -------------------------------------------------------------------------

    async def _orb_loop(self):
        """
        Continuously track SPX price during the ORB window (9:30-10:30 EST).
        Updates orb_high, orb_low in real time.
        After 10:30 EST, evaluates direction and locks in the signal.
        """
        while self.bot_running:
            now_est = self._est_time()
            est_hour = now_est.hour
            est_min = now_est.minute
            est_total_min = est_hour * 60 + est_min

            # ORB window: 9:30 (570) to 10:30 (630) EST
            orb_start = 9 * 60 + 30   # 570
            orb_end = 10 * 60 + 30    # 630

            if orb_start <= est_total_min < orb_end:
                self.orb_session_active = True
                metrics = self.get_metrics()
                spot = metrics.get('spot')
                if spot:
                    if self.orb_high is None or spot > self.orb_high:
                        self.orb_high = spot
                    if self.orb_low is None or spot < self.orb_low:
                        self.orb_low = spot
            else:
                if self.orb_session_active and not self.orb_evaluated:
                    # ORB session just closed — compute mid and direction
                    if self.orb_high is not None and self.orb_low is not None:
                        self.orb_mid = (self.orb_high + self.orb_low) / 2
                        # Direction: first break determines bias
                        if self.orb_arb_low_broken and not self.orb_arb_high_broken:
                            self.orb_direction = 'BULLISH'
                        elif self.orb_arb_high_broken and not self.orb_arb_low_broken:
                            self.orb_direction = 'BEARISH'
                        # If neither was broken, bias stays None (no signal)
                    self.orb_session_active = False
                    self.orb_evaluated = True
                    print(f"[Bot] ORB closed — H:{self.orb_high} L:{self.orb_low} M:{self.orb_mid} Dir:{self.orb_direction}")

            await asyncio.sleep(15)  # check every 15 seconds

    def _est_time(self) -> datetime:
        """Return current ET (EST/EDT) datetime using zoneinfo (handles DST automatically)."""
        from zoneinfo import ZoneInfo
        return datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York'))

    async def _evaluate_orb(self, metrics: dict) -> BotSignal | None:
        """
        ORB strategy: after the ORB session closes (10:30 EST),
        if a direction was established (first break of high or low),
        generate a signal with entry at orb_mid, TP/SL at ORB boundaries.
        """
        if not self.orb_evaluated:
            return None
        if self.orb_direction is None:
            return None
        if 'ORB' in self.active_positions:
            return None

        spot = metrics.get('spot', 0)
        call_wall = metrics.get('call_wall') or spot
        put_wall = metrics.get('put_wall') or spot

        # Entry trigger at orb_mid
        entry_trigger = self.orb_mid
        if self.orb_direction == 'BULLISH':
            # CALL: buy call at orb_mid, TP at orb_high, SL at orb_low
            direction = 'BUY_CALL'
            tp_trigger = self.orb_high
            sl_trigger = self.orb_low
            reason = f"ORB bullish — buy call @ {entry_trigger:.0f}, TP {tp_trigger:.0f}, SL {sl_trigger:.0f}"
        else:
            # PUT: buy put at orb_mid, TP at orb_low, SL at orb_high
            direction = 'BUY_PUT'
            tp_trigger = self.orb_low
            sl_trigger = self.orb_high
            reason = f"ORB bearish — buy put @ {entry_trigger:.0f}, TP {tp_trigger:.0f}, SL {sl_trigger:.0f}"

        confidence = 0.75

        return BotSignal(
            strategy='ORB',
            direction=direction,
            short_strike=0,
            long_strike=0,
            width=0,
            entry_credit=0,
            tp_credit=0,
            sl_credit=0,
            confidence=confidence,
            reason=reason,
            entry_trigger=entry_trigger,
            tp_trigger=tp_trigger,
            sl_trigger=sl_trigger,
        )

    # -------------------------------------------------------------------------
    # ORB15 — 4-step ORB with displacement filter → credit spreads
    # -------------------------------------------------------------------------

    ORB15_WIDTH = 20       # pts, spread width
    ORB15_BUFFER_PCT = 0.005  # 0.5% × session_open
    ORB15_DISP_MIN = 2.0  # body must be ≥ 2× median body to signal

    async def _orb15_loop(self):
        """
        Track 5-min candles from 9:30 ET.
        State machine: idle → forming → breakout → pullback → rebreakout → signalled/done.

        On first entry (idle), fetches historical 5-min bars from IBKR for the ORB range.
        Then tracks live spot each tick for breakout/pullback/rebreakout detection.
        """
        print(f"[Bot] _orb15_loop started, step={self.orb15_step}")

        while self.bot_running:
            now_est = self._est_time()
            est_total_min = now_est.hour * 60 + now_est.minute
            session_open_min = 9 * 60 + 30   # 570
            session_close_min = 15 * 60 + 30 # 930 (15:30 ET)

            # Before market open — reset and wait
            if est_total_min < session_open_min:
                if self.orb15_step not in ('idle', 'signalled'):
                    self._orb15_reset()
                await asyncio.sleep(60)
                continue

            # After market close — reset and wait
            if est_total_min >= session_close_min:
                if self.orb15_step not in ('idle', 'signalled'):
                    self._orb15_reset()
                await asyncio.sleep(60)
                continue

            # ── On first tick: load historical bars from IBKR ──
            if self.orb15_step == 'idle' and self.orb15_session_open is None:
                print(f"[Bot] _orb15_loop: idle state, fetching bars, est_total_min={est_total_min}")
                bars = []
                try:
                    bars = await self.engine.fetch_5min_bars()
                except Exception as e:
                    print(f"[Bot] _orb15_loop: fetch_5min_bars failed: {e}")

                # Filter bars from 9:30–9:45 (first 3 bars: 9:30, 9:35, 9:40)
                orb_bars = [b for b in bars if 570 <= b['total_min'] < 600][:3]
                print(f"[Bot] _orb15_loop: fetched {len(bars)} total bars, {len(orb_bars)} in ORB window, est_total_min={est_total_min}")

                if orb_bars:
                    self.orb15_session_open = orb_bars[0]['open']
                    self.orb15_high = max(b['high'] for b in orb_bars)
                    self.orb15_low = min(b['low'] for b in orb_bars)
                    self.orb15_range = self.orb15_high - self.orb15_low
                    # Backfill body list with bars AFTER the ORB window only
                    # (ORB bars 9:30-9:40 are excluded from median so they don't inflate the threshold)
                    orb_max_total = 600  # 9:40 = 10:00 in total minutes
                    self.orb15_body_list = [
                        abs(b['close'] - b['open'])
                        for b in bars
                        if b['total_min'] >= orb_max_total
                        and abs(b['close'] - b['open']) > 0
                    ]
                    self.orb15_step = 'breakout'
                    print(f"[Bot] _orb15_loop: loaded {len(orb_bars)} ORB bars, "
                          f"H={self.orb15_high} L={self.orb15_low} R={self.orb15_range:.2f}")
                else:
                    await asyncio.sleep(30)
                    continue

            # ── Get live spot ──
            metrics = self.get_metrics()
            spot = metrics.get('spot') if metrics else None
            if spot is None:
                await asyncio.sleep(15)
                continue

            # ── Detect new 5-min bar (previous bar just closed) ──
            current_bar_period = est_total_min // 5
            stored_bar_period = getattr(self, '_orb15_bar_period', None)

            # First iteration after ORB load: seed bar tracking
            if stored_bar_period is None:
                self._orb15_bar_period = current_bar_period
                self._orb15_last_5min_bar_open = spot
                self._orb15_last_spot = spot
                await asyncio.sleep(15)
                continue

            # Has a new bar just started? (integer-period differs)
            new_bar = current_bar_period != stored_bar_period

            if new_bar:
                # Capture the just-closed bar's open / close / body using the
                # last seen spot as the bar's close.
                prev_close = self._orb15_last_spot
                prev_open = self._orb15_last_5min_bar_open
                prev_body = abs(prev_close - prev_open) if (prev_close is not None and prev_open is not None) else 0

                if prev_body > 0:
                    self.orb15_body_list.append(prev_body)

                # Stash for the rebreakout evaluation (only valid on this iteration)
                self._orb15_prev_bar_close = prev_close
                self._orb15_prev_bar_open = prev_open
                self._orb15_prev_bar_body = prev_body

                # Start tracking the new bar
                self._orb15_last_5min_bar_open = spot
                self._orb15_bar_period = current_bar_period

            # Remember this spot so it becomes the previous bar's close next time
            self._orb15_last_spot = spot

            # ── State machine ──
            if self.orb15_step == 'breakout':
                # B2: breakout detection — spot crosses actual ORB level
                if self.orb15_high is not None and self.orb15_low is not None:
                    if spot > self.orb15_high:
                        self.orb15_breakout_dir = 'bull'
                        self.orb15_breakout_time = now_est
                        self.orb15_step = 'pullback'
                    elif spot < self.orb15_low:
                        self.orb15_breakout_dir = 'bear'
                        self.orb15_breakout_time = now_est
                        self.orb15_step = 'pullback'

            elif self.orb15_step == 'pullback':
                # B3: pullback — price crosses to the opposite side of the ORB range
                # Bull: price came from above, now back below ORB_low
                # Bear: price came from below, now back above ORB_high
                if self.orb15_breakout_dir == 'bull' and self.orb15_low is not None and spot < self.orb15_low:
                    self.orb15_pullback_seen = True
                    self.orb15_step = 'rebreakout'
                elif self.orb15_breakout_dir == 'bear' and self.orb15_high is not None and spot > self.orb15_high:
                    self.orb15_pullback_seen = True
                    self.orb15_step = 'rebreakout'

            elif self.orb15_step == 'rebreakout':
                median_body = (
                    float(sorted(self.orb15_body_list)[len(self.orb15_body_list) // 2])
                    if self.orb15_body_list else 0
                )
                body = self._orb15_prev_bar_body or 0
                prev_close = self._orb15_prev_bar_close

                # B4: re-breakout on bar close — prev_close (pullback bar) closes beyond
                # ORB level in the same direction AND body >= 2 × median_body_session.
                # If body is too small the bar is discarded; engine stays in 'rebreakout'
                # and evaluates the next bar when it closes.
                if (self.orb15_breakout_dir == 'bull'
                        and self.orb15_high is not None
                        and prev_close is not None
                        and prev_close > self.orb15_high
                        and body > 0
                        and median_body > 0
                        and body >= self.ORB15_DISP_MIN * median_body):
                    self.orb15_rebreakout_dir = 'bull'
                    self.orb15_rebreakout_time = now_est
                    self.orb15_rebreakout_body = body
                    self.orb15_step = 'signalled'
                    print(f"[Bot] ORB15 bullish signal — bar close={prev_close} > high={self.orb15_high}, "
                          f"body={body:.2f} >= {self.ORB15_DISP_MIN}×median={self.ORB15_DISP_MIN * median_body:.2f}")

                elif (self.orb15_breakout_dir == 'bear'
                      and self.orb15_low is not None
                      and prev_close is not None
                      and prev_close < self.orb15_low
                      and body > 0
                      and median_body > 0
                      and body >= self.ORB15_DISP_MIN * median_body):
                    self.orb15_rebreakout_dir = 'bear'
                    self.orb15_rebreakout_time = now_est
                    self.orb15_rebreakout_body = body
                    self.orb15_step = 'signalled'
                    print(f"[Bot] ORB15 bearish signal — bar close={prev_close} < low={self.orb15_low}, "
                          f"body={body:.2f} >= {self.ORB15_DISP_MIN}×median={self.ORB15_DISP_MIN * median_body:.2f}")

            await asyncio.sleep(15)

    def _orb15_reset(self):
        """Reset ORB15 state for a new session."""
        self.orb15_session_open = None
        self.orb15_high = None
        self.orb15_low = None
        self.orb15_range = None
        self.orb15_body_list = []
        self.orb15_step = 'idle'
        self.orb15_breakout_dir = None
        self.orb15_breakout_time = None
        self.orb15_pullback_seen = False
        self.orb15_rebreakout_dir = None
        self.orb15_rebreakout_time = None
        self.orb15_rebreakout_body = None
        self.orb15_evaluated = False
        self._orb15_last_5min_bar_open = None
        self._orb15_bar_period: int | None = None
        # Bar-close tracking
        self._orb15_last_spot: float | None = None
        self._orb15_prev_bar_close: float | None = None
        self._orb15_prev_bar_open: float | None = None
        self._orb15_prev_bar_body: float | None = None

    async def _evaluate_orb15(self, metrics: dict) -> BotSignal | None:
        """
        ORB15 strategy: after 4-step ORB sequence completes (rebreakout with displacement),
        emit a credit spread signal.

        PCS (bullish): short_strike = ORB_low - buffer
        CCS (bearish): short_strike = ORB_high + buffer
        buffer = 0.5% * session_open
        """
        if self.orb15_step != 'signalled':
            return None
        if self.orb15_rebreakout_dir is None:
            return None
        if 'ORB15' in self.active_positions:
            return None
        if self.orb15_session_open is None:
            return None

        buffer = self.ORB15_BUFFER_PCT * self.orb15_session_open

        if self.orb15_rebreakout_dir == 'bull':
            direction = 'BULL_PUT'
            short_strike = (self.orb15_low - buffer) if self.orb15_low is not None else None
            long_strike = (short_strike - self.ORB15_WIDTH) if short_strike is not None else None
            reason = (f"ORB15 bullish rebreakout — PCS: short={short_strike:.0f}, "
                      f"ORB_H={self.orb15_high:.0f} L={self.orb15_low:.0f}, buffer={buffer:.0f}")
        else:
            direction = 'BEAR_CALL'
            short_strike = (self.orb15_high + buffer) if self.orb15_high is not None else None
            long_strike = (short_strike + self.ORB15_WIDTH) if short_strike is not None else None
            reason = (f"ORB15 bearish rebreakout — CCS: short={short_strike:.0f}, "
                      f"ORB_H={self.orb15_high:.0f} L={self.orb15_low:.0f}, buffer={buffer:.0f}")

        if short_strike is None:
            return None

        width = self.ORB15_WIDTH
        entry_credit = 2.50   # estimated; actual from reqTickersAsync at execution
        tp = entry_credit * 0.50
        sl = entry_credit * 2.0
        confidence = 0.75

        self.orb15_evaluated = True

        return BotSignal(
            strategy='ORB15',
            direction=direction,
            short_strike=short_strike,
            long_strike=long_strike,
            width=width,
            entry_credit=entry_credit,
            tp_credit=tp,
            sl_credit=sl,
            confidence=confidence,
            reason=reason,
        )

    async def _evaluate_iron_fly(self, metrics: dict) -> BotSignal | None:
        """IRON_FLY: 0DTE Iron Butterfly on SPXW, entry 1:40-1:55 PM ET, hold to expiry.

        Spec:
          - Days: L, M, J, V (skip Wed — 0DTE OpEx day per backtest)
          - Entry window: 13:40 - 13:55 ET (15-min)
          - VIX filter: 15 - 20 inclusive
          - Short put at -0.50 delta, short call at +0.40 delta
          - Wings: $15 wide (long put 15 below, long call 15 above)
          - Hold to expiration (no TP/SL bracket — engine forces bracket=False)
        """
        now_et = self._est_time()

        # 1. Skip Wednesday (0DTE OpEx day per published backtest)
        if now_et.weekday() == 2:
            return None

        # 2. Time window: 13:40-13:55 ET
        est_min = now_et.hour * 60 + now_et.minute
        if not (13 * 60 + 40 <= est_min <= 13 * 60 + 55):
            return None

        # 3. VIX filter: 15-20 inclusive
        vix = metrics.get('vix')
        if vix is None or not (15.0 <= float(vix) <= 20.0):
            return None

        # 4. Need spot price for anchor (engine resolves strikes via delta lookup)
        spot = metrics.get('spot')
        if spot is None:
            return None

        return BotSignal(
            strategy='IRON_FLY',
            direction='IC',
            short_strike=float(spot),       # anchor (engine overrides via delta lookup)
            long_strike=float(spot) + 15,   # placeholder far wing
            width=15,
            entry_credit=4.00,              # estimate; engine recalculates at execution
            tp_credit=0.0,                  # hold-to-expiry: no TP
            sl_credit=0.0,                  # hold-to-expiry: no SL
            confidence=0.65,
            reason=f"0DTE Iron Fly @ {now_et.strftime('%H:%M')} ET, VIX={float(vix):.2f}",
            delta_target_put=-0.50,
            delta_target_call=+0.40,
        )

    # -------------------------------------------------------------------------
    # Milk Man — weekly ATR premium selling
    # -------------------------------------------------------------------------

    MILK_WIDTH = 50          # pts, spread width
    MILK_PAYOUT = 50.0      # pts, max loss = width × $1
    MILK_ENTRY_START = 10 * 60      # 10:00 ET
    MILK_ENTRY_END = 10 * 60 + 15   # 10:15 ET
    MILK_CLOSE_START = 15 * 60 + 30  # 15:30 ET
    MILK_CLOSE_END = 16 * 60         # 16:00 ET

    def _round5(self, price: float) -> float:
        """Round to nearest multiple of 5."""
        return round(price / 5) * 5

    def _load_milk_odds_history(self) -> list[float]:
        """Load odds history from CSV for 1Y median calculation."""
        import csv as _csv, os
        history_file = 'history/milk_odds_log.csv'
        if not os.path.exists(history_file):
            return []
        odds_list = []
        try:
            with open(history_file, newline='') as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    odds_list.append(float(row['odds']))
        except Exception:
            pass
        return odds_list

    def _save_milk_odds(self, odds: float):
        """Append odds to the persistent CSV log."""
        import csv as _csv, os
        os.makedirs('history', exist_ok=True)
        history_file = 'history/milk_odds_log.csv'
        file_exists = os.path.exists(history_file)
        with open(history_file, 'a', newline='') as f:
            w = _csv.DictWriter(f, fieldnames=['date', 'odds'])
            if not file_exists:
                w.writeheader()
            w.writerow({'date': self._est_date(), 'odds': f'{odds:.6f}'})

    def _calculate_atr14(self, bars: list[dict]) -> float:
        """Calculate ATR(14) from daily bars."""
        if len(bars) < 15:
            return 0.0
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i]['high']
            low = bars[i]['low']
            prev_close = bars[i-1]['close']
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        if len(true_ranges) < 14:
            return 0.0
        return sum(true_ranges[-14:]) / 14.0

    def _get_next_friday(self) -> str:
        """Return next Friday date string YYYYMMDD for SPXW contract."""
        from datetime import timedelta
        now = self._est_time()
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 16:
            days_until_friday = 7
        friday = now.date() + timedelta(days=days_until_friday)
        return friday.strftime('%Y%m%d')

    async def _evaluate_milk_man(self, metrics: dict, force: bool = False) -> BotSignal | None:
        """Milk Man: weekly Bull Put Spread, entry Mon 10:00 ET.

        `force=True` skips the time-window and Monday checks. Used by the
        /api/bot/test_milk_man diagnostic endpoint to evaluate whether
        today's conditions would have produced a signal outside the window.
        """
        now_et = self._est_time()
        est_min = now_et.hour * 60 + now_et.minute

        # 1. Entry window: Mon 10:00-10:15 ET (skipped when force=True)
        if not force:
            if now_et.weekday() != 0:
                return None
            if not (self.MILK_ENTRY_START <= est_min <= self.MILK_ENTRY_END):
                return None
        if 'MILK_MAN' in self.active_positions:
            return None

        # 2. Get prev_week_close (Friday close) from daily bars
        bars = await self.engine.fetch_daily_bars(days=20)
        if len(bars) < 5:
            print("[Bot] Milk Man: insufficient daily bars")
            return None

        # prev_week_close = last Friday close before today
        prev_week_close = None
        today_week = now_et.date().isocalendar()[1]
        for bar in bars:
            bar_date = bar['date']
            if bar_date.weekday() == 4 and bar_date.isocalendar()[1] < today_week:
                prev_week_close = bar['close']
                break
        if prev_week_close is None:
            prev_week_close = bars[1]['close']

        # 3. Calculate ATR(14) and weekly approximation
        atr_daily = self._calculate_atr14(bars)
        atr_weekly = atr_daily * (7 ** 0.5)

        # 4. Short strike = prev_week_close - ATR_weekly, rounded to 5
        short_strike = self._round5(prev_week_close - atr_weekly)
        long_strike = short_strike - self.MILK_WIDTH

        # 5. Get put price at short strike via reqMktData
        spot = metrics.get('spot') if metrics else None
        if spot is None:
            print("[Bot] Milk Man: no spot price")
            return None

        from ib_async import Option
        expiry_str = self._get_next_friday()
        try:
            contract = Option('SPX', expiry_str, int(short_strike), 'P', 'CBOE')
            await self.engine.ib.qualifyContractsAsync(contract)
            ticker = self.engine.ib.reqMktData(contract, '', False, False)
            await asyncio.sleep(2.0)
            put_bid = ticker.bid if ticker.bid and ticker.bid > 0 else 0
            put_ask = ticker.ask if ticker.ask and ticker.ask > 0 else 0
            put_price = (put_bid + put_ask) / 2 if put_bid and put_ask else 0
            self.engine.ib.cancelMktData(contract)
        except Exception as e:
            print(f"[Bot] Milk Man: failed to get put price: {e}")
            put_price = 0.0

        # 6. Calculate odds and apply filter
        odds = put_price / self.MILK_PAYOUT if self.MILK_PAYOUT > 0 else 0.0

        odds_history = self._load_milk_odds_history()
        self.milk_odds_history = odds_history

        if len(odds_history) >= 12:
            median_1y = sorted(odds_history)[len(odds_history) // 2]
            if odds >= median_1y:
                print(f"[Bot] Milk Man: SKIP — odds={odds:.4f} >= median={median_1y:.4f}")
                return None

        print(f"[Bot] Milk Man: short={short_strike}, atr_w={atr_weekly:.2f}, "
              f"put=${put_price:.2f}, odds={odds:.4f}, prev_close={prev_week_close:.2f}")

        self.milk_strike = short_strike
        self.milk_atr = atr_weekly
        self.milk_odds = odds
        self._milk_week_active = True

        return BotSignal(
            strategy='MILK_MAN',
            direction='BULL_PUT',
            short_strike=short_strike,
            long_strike=long_strike,
            width=self.MILK_WIDTH,
            entry_credit=2.50,
            tp_credit=0.0,
            sl_credit=0.0,
            confidence=0.70,
            reason=(f"MILK_MAN: short={short_strike}, ATR_w={atr_weekly:.2f}, "
                    f"odds={odds:.4f}, prev_close={prev_week_close:.2f}"),
        )

    async def _milk_man_loop(self):
        """Background loop: Mon entry window + Fri close/log."""
        print("[Bot] _milk_man_loop started")

        while self.bot_running:
            now_et = self._est_time()
            est_min = now_et.hour * 60 + now_et.minute

            # Monday entry window (10:00-10:15 ET)
            if (now_et.weekday() == 0
                    and self.MILK_ENTRY_START <= est_min <= self.MILK_ENTRY_END
                    and 'MILK_MAN' not in self.active_positions
                    and 'MILK_MAN' in self.enabled_strategies):
                metrics = self.get_metrics()
                if metrics:
                    signal = await self._evaluate_milk_man(metrics)
                    if signal:
                        self.current_signal = signal
                        if self.auto_mode:
                            result = await self.execute_signal(signal, execution_mode='AUTO')
                            print(f"[Bot] Milk Man: auto-executed {result}")
                        else:
                            print("[Bot] Milk Man: signal ready for manual approval")

            # Friday close window — save odds to history
            if (now_et.weekday() == 4
                    and self.MILK_CLOSE_START <= est_min <= self.MILK_CLOSE_END
                    and 'MILK_MAN' in self.active_positions):
                if self.milk_odds is not None:
                    self._save_milk_odds(self.milk_odds)
                    print("[Bot] Milk Man: odds saved to history")

            # New week reset (Monday before entry window)
            if (now_et.weekday() == 0
                    and est_min < self.MILK_ENTRY_START
                    and self._milk_week_active):
                self.milk_strike = None
                self.milk_atr = None
                self.milk_odds = None
                self._milk_week_active = False
                print("[Bot] Milk Man: new week reset")

            await asyncio.sleep(15)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------