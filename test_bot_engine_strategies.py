"""Tests for FLIP, PINNING, and TREND strategy evaluators in bot_engine.py.

These strategies depend on GEX-derived metrics (regime, bias, breakout_risk,
walls) rather than the ORB window used by ORB15.
"""
import sys
import unittest
import asyncio
from unittest.mock import MagicMock

sys.path.insert(0, '.')

from bot_engine import BotEngine


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def base_metrics(**overrides):
    """Build a GEX metrics dict with sensible defaults."""
    defaults = {
        'spot': 5800.0,
        'call_wall': 5820.0,
        'put_wall': 5780.0,
        'gamma_flip': 5800.0,
        'net_gex_total': 10.0,
        'regime': 'NEUTRAL',
        'bias': 'NEUTRAL',
        'breakout_risk': 'MEDIUM',
        'pinning_candidate': None,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# FLIP — detects GEX sign change
# ---------------------------------------------------------------------------

class TestFLIP(unittest.TestCase):
    """FLIP emits when net_gex changes sign AND |new| >= $5M."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())

    def test_first_call_seeds_prev_and_returns_none(self):
        """No previous GEX yet — just record and skip."""
        self.bot._prev_net_gex = None
        sig = _run(self.bot._evaluate_flip(base_metrics(), net_gex=10.0))
        self.assertIsNone(sig)
        self.assertEqual(self.bot._prev_net_gex, 10.0)

    def test_no_signal_when_sign_unchanged(self):
        """Both positive → no flip."""
        self.bot._prev_net_gex = 8.0
        sig = _run(self.bot._evaluate_flip(base_metrics(), net_gex=5.0))
        self.assertIsNone(sig)
        self.assertEqual(self.bot._prev_net_gex, 5.0)

    def test_no_signal_when_flip_too_small(self):
        """Flip to |new| < 5M is too thin — skip."""
        self.bot._prev_net_gex = 8.0
        sig = _run(self.bot._evaluate_flip(base_metrics(bias='BULLISH'), net_gex=-3.0))
        self.assertIsNone(sig)

    def test_bull_put_signal_on_positive_to_negative_with_bullish_bias(self):
        self.bot._prev_net_gex = 10.0
        m = base_metrics(bias='BULLISH', put_wall=5780.0)
        sig = _run(self.bot._evaluate_flip(m, net_gex=-8.0))
        self.assertIsNotNone(sig)
        self.assertEqual(sig.strategy, 'FLIP')
        self.assertEqual(sig.direction, 'BULL_PUT')
        self.assertEqual(sig.short_strike, 5780.0)
        self.assertEqual(sig.long_strike, 5775.0)  # short - 5
        self.assertEqual(sig.width, 5)
        self.assertAlmostEqual(sig.entry_credit, 2.50)
        self.assertAlmostEqual(sig.tp_credit, 1.25)  # 50% TP
        self.assertAlmostEqual(sig.sl_credit, 5.00)

    def test_bear_call_signal_on_negative_to_positive_with_bearish_bias(self):
        self.bot._prev_net_gex = -10.0
        m = base_metrics(bias='BEARISH', call_wall=5820.0)
        sig = _run(self.bot._evaluate_flip(m, net_gex=8.0))
        self.assertIsNotNone(sig)
        self.assertEqual(sig.strategy, 'FLIP')
        self.assertEqual(sig.direction, 'BEAR_CALL')
        self.assertEqual(sig.short_strike, 5820.0)
        self.assertEqual(sig.long_strike, 5825.0)  # short + 5

    def test_no_signal_on_flip_with_neutral_bias(self):
        self.bot._prev_net_gex = 10.0
        m = base_metrics(bias='NEUTRAL')
        sig = _run(self.bot._evaluate_flip(m, net_gex=-8.0))
        self.assertIsNone(sig)


# ---------------------------------------------------------------------------
# PINNING — LONG_GAMMA regime → Iron Condor
# ---------------------------------------------------------------------------

class TestPINNING(unittest.TestCase):
    """PINNING emits IC when regime=LONG_GAMMA and breakout risk is not HIGH."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())

    def test_no_signal_outside_long_gamma(self):
        m = base_metrics(regime='SHORT_GAMMA', bias='BULLISH')
        sig = _run(self.bot._evaluate_pinning(m))
        self.assertIsNone(sig)

    def test_no_signal_when_breakout_risk_high(self):
        m = base_metrics(regime='LONG_GAMMA', breakout_risk='HIGH')
        sig = _run(self.bot._evaluate_pinning(m))
        self.assertIsNone(sig)

    def test_emits_ic_when_long_gamma_and_walls_present(self):
        m = base_metrics(
            regime='LONG_GAMMA',
            breakout_risk='LOW',
            put_wall=5780.0,
            call_wall=5820.0,
            pinning_candidate=5800.0,
        )
        sig = _run(self.bot._evaluate_pinning(m))
        self.assertIsNotNone(sig)
        self.assertEqual(sig.strategy, 'PINNING')
        self.assertEqual(sig.direction, 'IC')
        # IC encodes short_put as short_strike and long_call as long_strike
        self.assertEqual(sig.short_strike, 5780.0)
        self.assertEqual(sig.long_strike, 5825.0)
        self.assertEqual(sig.width, 5)
        self.assertAlmostEqual(sig.entry_credit, 4.00)
        self.assertAlmostEqual(sig.tp_credit, 2.00)  # 50%
        self.assertAlmostEqual(sig.sl_credit, 8.00)

    def test_tp_is_50_percent(self):
        """PINNING TP uses 50% (vs TREND's 60%)."""
        m = base_metrics(regime='LONG_GAMMA', breakout_risk='LOW')
        sig = _run(self.bot._evaluate_pinning(m))
        self.assertAlmostEqual(sig.tp_credit, sig.entry_credit * 0.50)


# ---------------------------------------------------------------------------
# TREND — SHORT_GAMMA + directional bias + LOW breakout risk
# ---------------------------------------------------------------------------

class TestTREND(unittest.TestCase):
    """TREND emits directional spread on SHORT_GAMMA + non-NEUTRAL bias + LOW risk."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())

    def test_no_signal_outside_short_gamma(self):
        m = base_metrics(regime='LONG_GAMMA', bias='BULLISH')
        sig = _run(self.bot._evaluate_trend(m))
        self.assertIsNone(sig)

    def test_no_signal_with_neutral_bias(self):
        m = base_metrics(regime='SHORT_GAMMA', bias='NEUTRAL')
        sig = _run(self.bot._evaluate_trend(m))
        self.assertIsNone(sig)

    def test_no_signal_when_breakout_risk_not_low(self):
        m = base_metrics(regime='SHORT_GAMMA', bias='BULLISH', breakout_risk='MEDIUM')
        sig = _run(self.bot._evaluate_trend(m))
        self.assertIsNone(sig)

    def test_bull_put_signal_short_gamma_bullish_low_risk(self):
        m = base_metrics(
            regime='SHORT_GAMMA',
            bias='BULLISH',
            breakout_risk='LOW',
            put_wall=5780.0,
        )
        sig = _run(self.bot._evaluate_trend(m))
        self.assertIsNotNone(sig)
        self.assertEqual(sig.strategy, 'TREND')
        self.assertEqual(sig.direction, 'BULL_PUT')
        self.assertEqual(sig.short_strike, 5780.0)
        self.assertEqual(sig.long_strike, 5775.0)
        self.assertAlmostEqual(sig.tp_credit, sig.entry_credit * 0.60)

    def test_bear_call_signal_short_gamma_bearish_low_risk(self):
        m = base_metrics(
            regime='SHORT_GAMMA',
            bias='BEARISH',
            breakout_risk='LOW',
            call_wall=5820.0,
        )
        sig = _run(self.bot._evaluate_trend(m))
        self.assertIsNotNone(sig)
        self.assertEqual(sig.strategy, 'TREND')
        self.assertEqual(sig.direction, 'BEAR_CALL')
        self.assertEqual(sig.short_strike, 5820.0)
        self.assertEqual(sig.long_strike, 5825.0)

    def test_tp_is_60_percent(self):
        """TREND TP uses 60% (higher R:R than FLIP/PINNING's 50%)."""
        m = base_metrics(regime='SHORT_GAMMA', bias='BULLISH', breakout_risk='LOW')
        sig = _run(self.bot._evaluate_trend(m))
        self.assertAlmostEqual(sig.tp_credit, sig.entry_credit * 0.60)


# ---------------------------------------------------------------------------
# Strategy signal scan — priority and gate checks via scan_and_signal
# ---------------------------------------------------------------------------

class TestScanPriority(unittest.TestCase):
    """scan_and_signal must respect enabled strategies and active positions."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())
        # Default: all strategies enabled, no positions
        self.bot.enabled_strategies = {'FLIP', 'PINNING', 'TREND', 'ORB', 'ORB15'}
        self.bot.active_positions = {}
        self.bot.daily_trades = []

    def test_disabled_strategy_does_not_emit(self):
        """FLIP disabled → no FLIP signal even if metrics qualify."""
        self.bot.enabled_strategies = set()  # nothing enabled
        self.bot._prev_net_gex = 10.0
        m = base_metrics(bias='BULLISH')
        # get_metrics is called inside scan_and_signal
        self.bot.get_metrics = MagicMock(return_value=m)
        sig = _run(self.bot.scan_and_signal())
        self.assertIsNone(sig)

    def test_active_position_blocks_repeat_signal(self):
        """FLIP already in active_positions → no second FLIP signal."""
        self.bot.enabled_strategies = {'FLIP'}
        self.bot.active_positions = {'FLIP': {'open': True}}
        self.bot._prev_net_gex = 10.0
        m = base_metrics(bias='BULLISH')
        self.bot.get_metrics = MagicMock(return_value=m)
        sig = _run(self.bot.scan_and_signal())
        self.assertIsNone(sig)


if __name__ == '__main__':
    unittest.main()
