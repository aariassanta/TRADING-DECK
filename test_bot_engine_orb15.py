"""Tests for ORB15 strategy logic in bot_engine.py.

Validates the pure logic against Bot_rules spec:
- ORB window: 9:30–9:45 ET (first 3 candles of 5min)
- 4-step state machine: breakout → pullback → rebreakout (with displacement)
- PCS (bullish): short = ORB_low − buffer, long = short − 20
- CCS (bearish): short = ORB_high + buffer, long = short + 20
- Displacement: body ≥ 2.0 × median_body_session

These tests do not require an IBKR connection — they cover the static
constants, the strike formula, gate conditions, and state transitions.
"""
import sys
import unittest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone

sys.path.insert(0, '.')

from bot_engine import BotEngine, BotSignal


def _run(coro):
    """Run an async coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _est(hour: int, minute: int) -> datetime:
    """Build a datetime that the loop reads directly as EST hour/min.

    The bot loop uses `now_est.hour` and `now_est.minute` as EST clock values,
    so this helper returns a datetime whose .hour/.minute ARE the EST values.
    """
    return datetime(2026, 8, 10, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Constants per Bot_rules
# ---------------------------------------------------------------------------

class TestORB15Constants(unittest.TestCase):
    """Bot_rules §Parámetros: WIDTH=20, BUFFER=0.5%, DISP_MIN=2.0."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())

    def test_width_is_20(self):
        self.assertEqual(self.bot.ORB15_WIDTH, 20)

    def test_buffer_pct_is_0_5_percent(self):
        self.assertEqual(self.bot.ORB15_BUFFER_PCT, 0.005)

    def test_displacement_min_is_2x(self):
        self.assertEqual(self.bot.ORB15_DISP_MIN, 2.0)


# ---------------------------------------------------------------------------
# 2. Strike formula via _evaluate_orb15
# ---------------------------------------------------------------------------

class TestORB15StrikeFormula(unittest.TestCase):
    """Validate PCS/CCS strike calculation against Bot_rules example.

    Spec example: session_open=5800, ORB_high=5761.44, ORB_low=5748.42
      buffer = 5800 × 0.005 = 29
      PCS short = 5748.42 − 29 = 5719.42, long = 5719.42 − 20 = 5699.42
      CCS short = 5761.44 + 29 = 5790.44, long = 5790.44 + 20 = 5810.44
    """

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())
        # State: bullish rebreakout has triggered
        self.bot.orb15_step = 'signalled'
        self.bot.orb15_session_open = 5800.0
        self.bot.orb15_high = 5761.44
        self.bot.orb15_low = 5748.42
        self.bot.orb15_rebreakout_body = 15.0
        self.bot.orb15_evaluated = False
        self.bot.active_positions = {}

    def test_pcs_short_strike_equals_orb_low_minus_buffer(self):
        self.bot.orb15_rebreakout_dir = 'bull'
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, 'BULL_PUT')
        self.assertAlmostEqual(sig.short_strike, 5719.42, places=2)

    def test_pcs_long_strike_is_short_minus_width(self):
        self.bot.orb15_rebreakout_dir = 'bull'
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertAlmostEqual(sig.long_strike, 5699.42, places=2)

    def test_ccs_short_strike_equals_orb_high_plus_buffer(self):
        self.bot.orb15_rebreakout_dir = 'bear'
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, 'BEAR_CALL')
        self.assertAlmostEqual(sig.short_strike, 5790.44, places=2)

    def test_ccs_long_strike_is_short_plus_width(self):
        self.bot.orb15_rebreakout_dir = 'bear'
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertAlmostEqual(sig.long_strike, 5810.44, places=2)

    def test_signal_strategy_is_orb15(self):
        self.bot.orb15_rebreakout_dir = 'bull'
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertEqual(sig.strategy, 'ORB15')
        self.assertEqual(sig.width, 20)


# ---------------------------------------------------------------------------
# 3. Gate conditions in _evaluate_orb15
# ---------------------------------------------------------------------------

class TestORB15GateConditions(unittest.TestCase):
    """Signal must be None if any precondition fails."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())
        self.bot.orb15_rebreakout_dir = 'bull'
        self.bot.orb15_session_open = 5800.0
        self.bot.orb15_high = 5761.44
        self.bot.orb15_low = 5748.42
        self.bot.orb15_rebreakout_body = 15.0

    def test_returns_none_when_step_is_not_signalled(self):
        self.bot.orb15_step = 'rebreakout'  # not yet signalled
        self.bot.active_positions = {}
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertIsNone(sig)

    def test_returns_none_when_position_already_open(self):
        self.bot.orb15_step = 'signalled'
        self.bot.active_positions = {'ORB15': {'open': True}}
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertIsNone(sig)

    def test_returns_none_when_session_open_missing(self):
        self.bot.orb15_step = 'signalled'
        self.bot.orb15_session_open = None
        self.bot.active_positions = {}
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertIsNone(sig)

    def test_returns_none_when_rebreakout_dir_missing(self):
        self.bot.orb15_step = 'signalled'
        self.bot.orb15_rebreakout_dir = None
        self.bot.active_positions = {}
        sig = _run(self.bot._evaluate_orb15({}))
        self.assertIsNone(sig)

    def test_marks_evaluated_after_emitting(self):
        self.bot.orb15_step = 'signalled'
        self.bot.active_positions = {}
        self.assertFalse(self.bot.orb15_evaluated)
        _run(self.bot._evaluate_orb15({}))
        self.assertTrue(self.bot.orb15_evaluated)


# ---------------------------------------------------------------------------
# 4. Reset behavior
# ---------------------------------------------------------------------------

class TestORB15Reset(unittest.TestCase):
    """_orb15_reset must clear all state for a new session."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())

    def test_reset_clears_all_state(self):
        # Pollute state
        self.bot.orb15_step = 'signalled'
        self.bot.orb15_session_open = 5800.0
        self.bot.orb15_high = 5761.44
        self.bot.orb15_low = 5748.42
        self.bot.orb15_range = 13.02
        self.bot.orb15_body_list = [1.0, 2.0, 3.0]
        self.bot.orb15_breakout_dir = 'bull'
        self.bot.orb15_breakout_time = _est(10, 0)
        self.bot.orb15_pullback_seen = True
        self.bot.orb15_rebreakout_dir = 'bull'
        self.bot.orb15_rebreakout_time = _est(11, 0)
        self.bot.orb15_rebreakout_body = 8.0
        self.bot.orb15_evaluated = True
        self.bot._orb15_last_5min_bar_open = 5770.0
        self.bot._orb15_bar_period = 120
        self.bot._orb15_last_spot = 5772.0
        self.bot._orb15_prev_bar_close = 5770.0
        self.bot._orb15_prev_bar_open = 5760.0
        self.bot._orb15_prev_bar_body = 10.0

        self.bot._orb15_reset()

        self.assertIsNone(self.bot.orb15_session_open)
        self.assertIsNone(self.bot.orb15_high)
        self.assertIsNone(self.bot.orb15_low)
        self.assertIsNone(self.bot.orb15_range)
        self.assertEqual(self.bot.orb15_body_list, [])
        self.assertEqual(self.bot.orb15_step, 'idle')
        self.assertIsNone(self.bot.orb15_breakout_dir)
        self.assertIsNone(self.bot.orb15_breakout_time)
        self.assertFalse(self.bot.orb15_pullback_seen)
        self.assertIsNone(self.bot.orb15_rebreakout_dir)
        self.assertIsNone(self.bot.orb15_rebreakout_time)
        self.assertIsNone(self.bot.orb15_rebreakout_body)
        self.assertFalse(self.bot.orb15_evaluated)
        self.assertIsNone(self.bot._orb15_last_5min_bar_open)
        self.assertIsNone(self.bot._orb15_bar_period)
        self.assertIsNone(self.bot._orb15_last_spot)
        self.assertIsNone(self.bot._orb15_prev_bar_close)
        self.assertIsNone(self.bot._orb15_prev_bar_open)
        self.assertIsNone(self.bot._orb15_prev_bar_body)


# ---------------------------------------------------------------------------
# 5. End-to-end: ORB15 signal routes to engine with ORB-anchored strike
# ---------------------------------------------------------------------------

class TestORB15SignalRouting(unittest.TestCase):
    """execute_signal must pass signal.short_strike to execute_spread for ORB15.

    Regression for the bug where ORB15 fell through to target_mode='GEX',
    which silently re-anchored the spread to call_wall / put_wall instead of
    the ORB-anchored strike computed by _evaluate_orb15.
    """

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())
        self.bot.engine = MagicMock()
        self.bot.engine.execute_spread = AsyncMock(return_value=MagicMock())

    def test_orb15_passes_short_strike_as_target_value(self):
        sig = BotSignal(
            strategy='ORB15',
            direction='BULL_PUT',
            short_strike=5719.42,
            long_strike=5699.42,
            width=20,
            entry_credit=2.50,
            tp_credit=1.25,
            sl_credit=5.00,
            confidence=0.75,
            reason='test ORB15 signal',
            timestamp=time.time(),
        )
        _run(self.bot.execute_signal(sig, execution_mode='MANUAL'))
        self.bot.engine.execute_spread.assert_awaited_once()
        kwargs = self.bot.engine.execute_spread.await_args.kwargs
        self.assertEqual(kwargs['target_mode'], 'orb15')
        self.assertEqual(kwargs['target_value'], 5719.42)
        self.assertEqual(kwargs['spread_type'], 'PCS')

    def test_non_orb15_still_uses_gex_mode(self):
        sig = BotSignal(
            strategy='FLIP',
            direction='BULL_PUT',
            short_strike=7475.0,
            long_strike=7470.0,
            width=5,
            entry_credit=2.50,
            tp_credit=1.25,
            sl_credit=5.00,
            confidence=0.70,
            reason='test FLIP',
            timestamp=time.time(),
        )
        _run(self.bot.execute_signal(sig, execution_mode='MANUAL'))
        kwargs = self.bot.engine.execute_spread.await_args.kwargs
        self.assertEqual(kwargs['target_mode'], 'GEX')
        self.assertEqual(kwargs['target_value'], 0)


# ---------------------------------------------------------------------------
# 6. State machine transitions (4-step sequence with mocked bars)
# ---------------------------------------------------------------------------

class TestORB15StateMachine(unittest.TestCase):
    """Walk through the 4-step sequence: idle → breakout → pullback → rebreakout → signalled."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())
        self.bot.bot_running = True
        # Mock the underlying paper engine
        self.bot.engine = MagicMock()
        # Pre-load session state: ORB window done, step=breakout
        self.bot.orb15_step = 'breakout'
        self.bot.orb15_session_open = 5800.0
        self.bot.orb15_high = 5761.44
        self.bot.orb15_low = 5748.42
        self.bot.orb15_body_list = [2.0, 3.0, 4.0, 5.0, 6.0]  # median = 4.0
        # Bar tracking — initialize so the loop skips the first-iteration branch.
        # Default: same period as the mocked _est_time so new_bar=False for
        # breakout/pullback tests. Rebreakout tests override _orb15_bar_period.
        self.bot._orb15_bar_period = 120
        self.bot._orb15_last_5min_bar_open = 5755.0
        self.bot._orb15_last_spot = 5760.0
        # Patch _est_time and get_metrics via direct attrs
        self.bot._est_time = MagicMock(return_value=_est(10, 0))  # 600min → period 120
        self.bot.get_metrics = MagicMock(return_value={'spot': 5770.0})

    def test_breakout_bull_when_spot_above_high(self):
        """spot=5770 > ORB_high=5761.44 → bull breakout → step=pullback."""
        self.bot.get_metrics = MagicMock(return_value={'spot': 5770.0})
        self._run_one_tick()
        self.assertEqual(self.bot.orb15_step, 'pullback')
        self.assertEqual(self.bot.orb15_breakout_dir, 'bull')

    def test_breakout_bear_when_spot_below_low(self):
        """spot=5740 < ORB_low=5748.42 → bear breakout → step=pullback."""
        self.bot.get_metrics = MagicMock(return_value={'spot': 5740.0})
        self._run_one_tick()
        self.assertEqual(self.bot.orb15_step, 'pullback')
        self.assertEqual(self.bot.orb15_breakout_dir, 'bear')

    def test_pullback_bull_when_spot_returns_below_low(self):
        """After bull breakout, spot < ORB_low → pullback_seen=True → step=rebreakout."""
        self.bot.orb15_step = 'pullback'
        self.bot.orb15_breakout_dir = 'bull'
        self.bot.get_metrics = MagicMock(return_value={'spot': 5745.0})
        self._run_one_tick()
        self.assertTrue(self.bot.orb15_pullback_seen)
        self.assertEqual(self.bot.orb15_step, 'rebreakout')

    def test_pullback_bear_when_spot_returns_above_high(self):
        """After bear breakout, spot > ORB_high → pullback_seen=True → step=rebreakout."""
        self.bot.orb15_step = 'pullback'
        self.bot.orb15_breakout_dir = 'bear'
        self.bot.get_metrics = MagicMock(return_value={'spot': 5765.0})
        self._run_one_tick()
        self.assertTrue(self.bot.orb15_pullback_seen)
        self.assertEqual(self.bot.orb15_step, 'rebreakout')

    def test_displacement_blocks_small_body(self):
        """Bar close with body < 2×median → stay in rebreakout (no signal)."""
        self.bot.orb15_step = 'rebreakout'
        self.bot.orb15_breakout_dir = 'bull'
        # median body = 4.0; need ≥ 8.0 to signal
        # Just-closed bar: open 5764, close 5770 → body=6 (close > ORB_high)
        self.bot._orb15_prev_bar_close = 5770.0
        self.bot._orb15_prev_bar_open = 5764.0
        self.bot._orb15_prev_bar_body = 6.0
        # Force new_bar event by setting stored period behind current
        self.bot._orb15_bar_period = 100
        self.bot._est_time = MagicMock(return_value=_est(10, 5))  # 605min → period 121
        self.bot._orb15_last_5min_bar_open = 5764.0
        self.bot._orb15_last_spot = 5770.0
        self.bot.get_metrics = MagicMock(return_value={'spot': 5772.0})
        self._run_one_tick()
        self.assertEqual(self.bot.orb15_step, 'rebreakout')
        self.assertIsNone(self.bot.orb15_rebreakout_body)

    def test_displacement_passes_large_body_bull(self):
        """Bar close with body ≥ 2×median AND bull direction → signalled."""
        self.bot.orb15_step = 'rebreakout'
        self.bot.orb15_breakout_dir = 'bull'
        # Just-closed bar: open 5760, close 5770 → body=10, close > ORB_high
        self.bot._orb15_prev_bar_close = 5770.0
        self.bot._orb15_prev_bar_open = 5760.0
        self.bot._orb15_prev_bar_body = 10.0
        self.bot._orb15_bar_period = 100
        self.bot._est_time = MagicMock(return_value=_est(10, 5))  # 605min → period 121
        self.bot._orb15_last_5min_bar_open = 5760.0
        self.bot._orb15_last_spot = 5770.0
        self.bot.get_metrics = MagicMock(return_value={'spot': 5772.0})
        self._run_one_tick()
        self.assertEqual(self.bot.orb15_step, 'signalled')
        self.assertEqual(self.bot.orb15_rebreakout_dir, 'bull')
        self.assertAlmostEqual(self.bot.orb15_rebreakout_body, 10.0, places=2)

    def test_displacement_passes_large_body_bear(self):
        """Bar close with body ≥ 2×median AND bear direction → signalled."""
        self.bot.orb15_step = 'rebreakout'
        self.bot.orb15_breakout_dir = 'bear'
        # Just-closed bar: open 5750, close 5740 → body=10, close < ORB_low
        self.bot._orb15_prev_bar_close = 5740.0
        self.bot._orb15_prev_bar_open = 5750.0
        self.bot._orb15_prev_bar_body = 10.0
        self.bot._orb15_bar_period = 100
        self.bot._est_time = MagicMock(return_value=_est(10, 5))
        self.bot._orb15_last_5min_bar_open = 5750.0
        self.bot._orb15_last_spot = 5740.0
        self.bot.get_metrics = MagicMock(return_value={'spot': 5742.0})
        self._run_one_tick()
        self.assertEqual(self.bot.orb15_step, 'signalled')
        self.assertEqual(self.bot.orb15_rebreakout_dir, 'bear')
        self.assertAlmostEqual(self.bot.orb15_rebreakout_body, 10.0, places=2)

    def test_no_signal_mid_bar_even_if_displacement_met(self):
        """Mid-bar spot above ORB_high with huge body must NOT fire (only bar close does)."""
        self.bot.orb15_step = 'rebreakout'
        self.bot.orb15_breakout_dir = 'bull'
        # Same bar period — not a new bar
        self.bot._orb15_bar_period = 120  # matches current
        self.bot._est_time = MagicMock(return_value=_est(10, 0))  # 600min → 120
        # Even though spot is huge vs bar_open, no signal should fire
        self.bot._orb15_last_5min_bar_open = 5750.0
        self.bot._orb15_last_spot = 5755.0
        self.bot.get_metrics = MagicMock(return_value={'spot': 5800.0})  # huge move
        self._run_one_tick()
        self.assertEqual(self.bot.orb15_step, 'rebreakout')

    def test_bar_close_captures_prev_body_into_list(self):
        """When a new bar starts, the previous bar's body is appended to body_list."""
        self.bot._orb15_bar_period = 100  # stored period
        self.bot._est_time = MagicMock(return_value=_est(10, 5))  # 605min → period 121
        self.bot._orb15_last_5min_bar_open = 5760.0  # prev bar open
        self.bot._orb15_last_spot = 5770.0  # prev bar last seen = close
        self.bot.orb15_body_list = [2.0, 3.0]
        self.bot.get_metrics = MagicMock(return_value={'spot': 5772.0})
        self._run_one_tick()
        # Prev body = |5770 - 5760| = 10 appended
        self.assertIn(10.0, self.bot.orb15_body_list)

    # ------------------------------------------------------------------
    # Helper: run a single tick of _orb15_loop with mocked sleep
    # ------------------------------------------------------------------

    def _run_one_tick(self):
        """Execute one iteration of _orb15_loop, breaking out via fake sleep."""
        loop = asyncio.new_event_loop()
        try:
            # Patch asyncio.sleep inside the bot_engine module to raise after first call
            original_sleep = asyncio.sleep
            call_count = {'n': 0}

            async def fake_sleep(seconds):
                call_count['n'] += 1
                if call_count['n'] >= 1:
                    # Break out of the while loop
                    self.bot.bot_running = False
                # Yield once so other tasks can run
                await original_sleep(0)

            import bot_engine as be
            be.asyncio.sleep = fake_sleep
            try:
                loop.run_until_complete(self.bot._orb15_loop())
            finally:
                be.asyncio.sleep = original_sleep
        finally:
            loop.close()


if __name__ == '__main__':
    unittest.main()
