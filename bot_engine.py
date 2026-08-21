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
    strategy: Literal['FLIP', 'PINNING', 'TREND', 'ORB']
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
    TIME_EXIT_HOUR = 15        # 15:30 EST — force close all

    def __init__(self, paper_engine, metrics_cache, capital: float = 25000):
        self.engine = paper_engine
        self.get_metrics = metrics_cache          # () -> GexData dict
        self.capital = capital

        # State
        self.enabled_strategies: set[str] = {'FLIP', 'PINNING', 'TREND', 'ORB'}
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

    async def execute_signal(self, signal: BotSignal, execution_mode: Literal['AUTO', 'MANUAL'] = 'MANUAL') -> dict:
        """Execute a signal (human-approved). Returns result dict."""
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

        try:
            await self.engine.execute_spread(
                spread_type=spread_type,
                qty=1,
                target_mode='GEX',
                target_value=0,
                width=signal.width,
                tp_pct=50 if signal.strategy != 'TREND' else 60,
                sl_ratio=2.0,
                transmit=True,
                entry_trigger_price=signal.entry_trigger,
                tp_trigger_price=signal.tp_trigger,
                sl_trigger_price=signal.sl_trigger,
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
        row = {
            'timestamp': trade.get('timestamp', time.time()),
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
        """Return current EST datetime."""
        now_utc = datetime.now(timezone.utc)
        est_hour = (now_utc.hour - 5) % 24
        if now_utc.hour < 5:
            # Rolled to previous day
            yesterday = now_utc.replace(hour=now_utc.hour + 19)
            return yesterday
        return now_utc.replace(hour=est_hour)

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
    # Helpers
    # -------------------------------------------------------------------------