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


# ---------------------------------------------------------------------------
# IRON_FLY — 0DTE Iron Butterfly, 1:40-1:55 PM ET, VIX 15-20, hold-to-expiry
# ---------------------------------------------------------------------------

class TestIRON_FLY(unittest.TestCase):
    """IRON_FLY emits an IC signal with delta-based strike targets."""

    def setUp(self):
        self.bot = BotEngine(paper_engine=MagicMock(), metrics_cache=MagicMock())
        self.bot.enabled_strategies = {'IRON_FLY'}
        self.bot.active_positions = {}
        self.bot._orb15_evaluated = False

    def _patch_time(self, dt):
        """Mock _est_time() to return the given datetime."""
        self.bot._est_time = MagicMock(return_value=dt)

    def _good_metrics(self, vix=17.0, spot=5800.0):
        """Metrics dict that satisfies all IRON_FLY gates (except time)."""
        return {
            'spot': spot,
            'vix': vix,
            'regime': 'LONG_GAMMA',
            'bias': 'NEUTRAL',
            'call_wall': 5820.0,
            'put_wall': 5780.0,
            'gamma_flip': 5800.0,
            'net_gex_total': 10.0,
            'breakout_risk': 'LOW',
            'pinning_candidate': 5800.0,
        }

    def test_emits_when_all_conditions_met(self):
        """Mon 13:45 ET, VIX=17, spot=5800 → emit IC signal with delta targets."""
        from datetime import datetime, timezone
        monday_1345 = datetime(2026, 8, 10, 13, 45, tzinfo=timezone.utc)
        self._patch_time(monday_1345)
        sig = _run(self.bot._evaluate_iron_fly(self._good_metrics()))
        self.assertIsNotNone(sig)
        self.assertEqual(sig.strategy, 'IRON_FLY')
        self.assertEqual(sig.direction, 'IC')
        self.assertEqual(sig.width, 15)
        self.assertAlmostEqual(sig.delta_target_put, -0.50)
        self.assertAlmostEqual(sig.delta_target_call, 0.40)
        self.assertEqual(sig.tp_credit, 0.0)  # hold-to-expiry
        self.assertEqual(sig.sl_credit, 0.0)  # hold-to-expiry

    def test_skip_wednesday(self):
        """Wed 13:45 ET — skip regardless of metrics."""
        from datetime import datetime, timezone
        wed_1345 = datetime(2026, 8, 12, 13, 45, tzinfo=timezone.utc)
        self._patch_time(wed_1345)
        sig = _run(self.bot._evaluate_iron_fly(self._good_metrics()))
        self.assertIsNone(sig)

    def test_skip_outside_time_window(self):
        """Mon 14:00 ET — past window close 13:55 → skip."""
        from datetime import datetime, timezone
        mon_1400 = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)
        self._patch_time(mon_1400)
        sig = _run(self.bot._evaluate_iron_fly(self._good_metrics()))
        self.assertIsNone(sig)

    def test_skip_before_time_window(self):
        """Mon 13:30 ET — before window open 13:40 → skip."""
        from datetime import datetime, timezone
        mon_1330 = datetime(2026, 8, 10, 13, 30, tzinfo=timezone.utc)
        self._patch_time(mon_1330)
        sig = _run(self.bot._evaluate_iron_fly(self._good_metrics()))
        self.assertIsNone(sig)

    def test_skip_when_vix_below_range(self):
        """VIX=14 — below range → skip."""
        from datetime import datetime, timezone
        self._patch_time(datetime(2026, 8, 10, 13, 45, tzinfo=timezone.utc))
        sig = _run(self.bot._evaluate_iron_fly(self._good_metrics(vix=14.0)))
        self.assertIsNone(sig)

    def test_skip_when_vix_above_range(self):
        """VIX=22 — above range → skip."""
        from datetime import datetime, timezone
        self._patch_time(datetime(2026, 8, 10, 13, 45, tzinfo=timezone.utc))
        sig = _run(self.bot._evaluate_iron_fly(self._good_metrics(vix=22.0)))
        self.assertIsNone(sig)

    def test_skip_when_vix_missing(self):
        """VIX=None (fetch failed) — fail-safe skip."""
        from datetime import datetime, timezone
        self._patch_time(datetime(2026, 8, 10, 13, 45, tzinfo=timezone.utc))
        sig = _run(self.bot._evaluate_iron_fly(self._good_metrics(vix=None)))
        self.assertIsNone(sig)

    def test_skip_when_spot_missing(self):
        """spot=None — cannot anchor strikes → skip."""
        from datetime import datetime, timezone
        self._patch_time(datetime(2026, 8, 10, 13, 45, tzinfo=timezone.utc))
        m = self._good_metrics()
        m['spot'] = None
        sig = _run(self.bot._evaluate_iron_fly(m))
        self.assertIsNone(sig)

    def test_inclusive_window_boundaries(self):
        """Both 13:40 and 13:55 should emit (inclusive)."""
        from datetime import datetime, timezone
        for h, m in [(13, 40), (13, 55)]:
            self._patch_time(datetime(2026, 8, 10, h, m, tzinfo=timezone.utc))
            sig = _run(self.bot._evaluate_iron_fly(self._good_metrics()))
            self.assertIsNotNone(sig, f"failed at {h:02d}:{m:02d}")

    def test_signal_routed_to_iron_fly_target_mode(self):
        """execute_signal should route IRON_FLY to target_mode='iron_fly' and force bracket=False."""
        from bot_engine import BotSignal
        sig = BotSignal(
            strategy='IRON_FLY',
            direction='IC',
            short_strike=5800.0,
            long_strike=5815.0,
            width=15,
            entry_credit=4.0,
            tp_credit=0.0,
            sl_credit=0.0,
            confidence=0.65,
            reason='test',
            delta_target_put=-0.50,
            delta_target_call=0.40,
        )
        # Spy on the engine
        captured = {}

        async def spy_execute_spread(*a, **kw):
            captured.update(kw)
            mock = type('M', (), {'orderStatus': type('S', (), {'status': 'PreSubmitted'})()})()
            return mock

        # Bypass the ORB branch by mocking all branches we don't want to hit
        # ORB15 branch is skipped because signal.strategy == 'IRON_FLY'
        # We need to mock _log_trade_to_csv to avoid file I/O
        self.bot._log_trade_to_csv = MagicMock()
        # Mock active_positions so no re-entry block
        self.bot.active_positions = {}
        self.bot.daily_trades = []
        self.bot.engine = MagicMock()
        self.bot.engine.execute_spread = spy_execute_spread

        result = _run(self.bot.execute_signal(sig, execution_mode='MANUAL', transmit=True, bracket=True))
        self.assertTrue(result.get('ok'), f"execute_signal failed: {result.get('error')}")
        self.assertEqual(captured.get('target_mode'), 'iron_fly')
        self.assertEqual(captured.get('spread_type'), 'IC')
        self.assertEqual(captured.get('bracket'), False)  # forced False for IRON_FLY
        self.assertAlmostEqual(captured.get('delta_target_put'), -0.50)
        self.assertAlmostEqual(captured.get('delta_target_call'), 0.40)


if __name__ == '__main__':
    unittest.main()
