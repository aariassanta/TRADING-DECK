"""
Tests for the V2 Recommendation Engine (DEX + Greeks factors, instrument selection, leg recommendations).

Covers:
- _estimate_delta (moneyness fallback)
- _dex_ratio_near_spot (DEX imbalance computation)
- _gamma_wall_share (gamma concentration at walls)
- _theta_bleed_penalty (late-day theta decay penalty)
- _round5 (SPX strike rounding)
- _score_recommendation with new factors
- _choose_instrument_v2 (instrument + style + expiry)
- _recommend_legs (concrete strikes for PCS/CCS/IC/single-leg)
- _resolve_expiry (0DTE/1DTE/WEEKLY/YYYYMMDD)
- ComboLegRequest / ComboTradeRequest validation
- /api/trade_combo endpoint validation (live gate, leg count, right/action validation)
"""
import datetime
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

import server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_metrics(
    spot=6700.0,
    call_wall=6720.0,
    put_wall=6680.0,
    bias="BULLISH",
    regime="LONG_GAMMA",
    breakout_risk="MEDIUM",
    net_gex_total=15.0,
    regime_score=0.6,
    ladder=None,
    dark_gamma=None,
    put_call_ratio=None,
    oi_profile=None,
    vol_profile=None,
    pinning_candidate=None,
    vix=None,
    fade_setups=None,
    breakout_setups=None,
):
    if ladder is None:
        # Default 5-strike ladder with Greeks populated
        ladder = [
            {"strike": 6670, "call_bid": 31.0, "call_ask": 33.0, "call_oi": 1000, "call_volume": 50,
             "call_delta": 0.85, "call_gamma": 0.005, "call_theta": -0.10,
             "put_bid": 0.5, "put_ask": 1.0, "put_oi": 500, "put_volume": 30,
             "put_delta": -0.15, "put_gamma": 0.005, "put_theta": -0.05},
            {"strike": 6680, "call_bid": 21.5, "call_ask": 23.0, "call_oi": 5000, "call_volume": 200,
             "call_delta": 0.70, "call_gamma": 0.008, "call_theta": -0.20,
             "put_bid": 1.5, "put_ask": 2.0, "put_oi": 8000, "put_volume": 500,
             "put_delta": -0.30, "put_gamma": 0.008, "put_theta": -0.10},
            {"strike": 6690, "call_bid": 12.5, "call_ask": 14.0, "call_oi": 1500, "call_volume": 100,
             "call_delta": 0.55, "call_gamma": 0.010, "call_theta": -0.30,
             "put_bid": 4.0, "put_ask": 5.0, "put_oi": 2000, "put_volume": 150,
             "put_delta": -0.45, "put_gamma": 0.010, "put_theta": -0.20},
            {"strike": 6700, "call_bid": 6.0, "call_ask": 7.5, "call_oi": 2000, "call_volume": 300,
             "call_delta": 0.40, "call_gamma": 0.012, "call_theta": -0.40,
             "put_bid": 9.0, "put_ask": 10.5, "put_oi": 2500, "put_volume": 400,
             "put_delta": -0.55, "put_gamma": 0.012, "put_theta": -0.30},
            {"strike": 6710, "call_bid": 2.5, "call_ask": 3.5, "call_oi": 1200, "call_volume": 80,
             "call_delta": 0.25, "call_gamma": 0.010, "call_theta": -0.30,
             "put_bid": 16.5, "put_ask": 18.0, "put_oi": 1500, "put_volume": 100,
             "put_delta": -0.70, "put_gamma": 0.010, "put_theta": -0.20},
            {"strike": 6720, "call_bid": 1.0, "call_ask": 1.5, "call_oi": 6000, "call_volume": 150,
             "call_delta": 0.10, "call_gamma": 0.006, "call_theta": -0.15,
             "put_bid": 26.0, "put_ask": 28.0, "put_oi": 1200, "put_volume": 60,
             "put_delta": -0.85, "put_gamma": 0.006, "put_theta": -0.10},
        ]
    # Build profiles defensively (in case custom ladders omit OI/volume keys)
    if oi_profile is None:
        oi_profile = {r["strike"]: r.get("call_oi", 0) + r.get("put_oi", 0) for r in ladder}
    if vol_profile is None:
        vol_profile = {r["strike"]: r.get("call_volume", 0) + r.get("put_volume", 0) for r in ladder}
    return {
        "spot": spot,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "bias": bias,
        "regime": regime,
        "breakout_risk": breakout_risk,
        "net_gex_total": net_gex_total,
        "regime_score": regime_score,
        "gamma_flip": 6700,
        "strike_ladder": ladder,
        "dark_gamma": dark_gamma or [],
        "put_call_ratio": put_call_ratio or {"volume": 0.9, "oi": 1.0},
        "oi_profile": oi_profile,
        "vol_profile": vol_profile,
        # TIER 2 inputs
        "pinning_candidate": pinning_candidate,
        "vix": vix,
        "fade_setups": fade_setups or [],
        "breakout_setups": breakout_setups or [],
    }


# ---------------------------------------------------------------------------
# Helpers unit tests
# ---------------------------------------------------------------------------

class TestEstimateDelta(unittest.TestCase):
    def test_atm_call(self):
        d = server._estimate_delta(6700, 6700, "C")
        self.assertAlmostEqual(d, 0.5, places=3)

    def test_atm_put(self):
        d = server._estimate_delta(6700, 6700, "P")
        self.assertAlmostEqual(d, -0.5, places=3)

    def test_otm_call(self):
        # strike above spot → call delta > 0.5
        d = server._estimate_delta(6800, 6700, "C")
        self.assertGreater(d, 0.5)
        self.assertLessEqual(d, 1.0)

    def test_itm_put(self):
        # strike below spot → put delta closer to -1
        d = server._estimate_delta(6600, 6700, "P")
        self.assertLess(d, -0.5)
        self.assertGreaterEqual(d, -1.0)

    def test_invalid_spot_returns_neutral(self):
        d = server._estimate_delta(6700, 0, "C")
        self.assertEqual(d, 0.5)


class TestRound5(unittest.TestCase):
    def test_exact_multiple(self):
        self.assertEqual(server._round5(6700), 6700)

    def test_round_up(self):
        self.assertEqual(server._round5(6703), 6705)

    def test_round_down(self):
        self.assertEqual(server._round5(6698), 6700)

    def test_negative(self):
        self.assertEqual(server._round5(-3), -5)


class TestResolveExpiry(unittest.TestCase):
    def test_0dte_returns_today(self):
        result = server._resolve_expiry("0DTE")
        self.assertEqual(result, datetime.datetime.now().strftime("%Y%m%d"))

    def test_1dte_returns_tomorrow(self):
        result = server._resolve_expiry("1DTE")
        expected = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y%m%d")
        self.assertEqual(result, expected)

    def test_weekly_returns_friday(self):
        result = server._resolve_expiry("WEEKLY")
        # Parse and verify it's a Friday
        dt = datetime.datetime.strptime(result, "%Y%m%d")
        self.assertEqual(dt.weekday(), 4)  # Friday

    def test_lowercase_0dte(self):
        result = server._resolve_expiry("0dte")
        self.assertEqual(result, datetime.datetime.now().strftime("%Y%m%d"))

    def test_already_yyyymmdd_passes_through(self):
        self.assertEqual(server._resolve_expiry("20260829"), "20260829")


# ---------------------------------------------------------------------------
# DEX + Greeks factor tests
# ---------------------------------------------------------------------------

class TestDexRatioNearSpot(unittest.TestCase):
    def test_balanced_returns_near_zero(self):
        # Symmetric OI/delta → ratio ≈ 0
        m = make_metrics(spot=6700, ladder=[
            {"strike": s, "call_oi": 1000, "call_delta": 0.5, "put_oi": 1000, "put_delta": -0.5}
            for s in [6680, 6690, 6700, 6710, 6720]
        ])
        ratio = server._dex_ratio_near_spot(m)
        self.assertAlmostEqual(ratio, 0.0, places=3)

    def test_call_heavy_returns_positive(self):
        # More call_oi → ratio > 0
        m = make_metrics(spot=6700, ladder=[
            {"strike": 6700, "call_oi": 5000, "call_delta": 0.5, "put_oi": 1000, "put_delta": -0.5},
        ])
        ratio = server._dex_ratio_near_spot(m)
        self.assertGreater(ratio, 0.0)

    def test_put_heavy_returns_negative(self):
        # More put_oi → ratio < 0
        m = make_metrics(spot=6700, ladder=[
            {"strike": 6700, "call_oi": 1000, "call_delta": 0.5, "put_oi": 5000, "put_delta": -0.5},
        ])
        ratio = server._dex_ratio_near_spot(m)
        self.assertLess(ratio, 0.0)

    def test_missing_greeks_falls_back_to_moneyness(self):
        # No call_delta/put_delta → uses _estimate_delta
        # Strike 6720 is within ±25 of spot 6700; moneyness gives call_delta > 0.5
        m = make_metrics(spot=6700, ladder=[
            {"strike": 6720, "call_oi": 1000, "put_oi": 1000},  # both greeks missing
        ])
        ratio = server._dex_ratio_near_spot(m)
        # ITM call (call_delta=1.0) + OTM put (put_delta=0.0)
        # call DEX (1000) > put DEX (0) → positive ratio
        self.assertGreater(ratio, 0.0)

    def test_empty_ladder_returns_zero(self):
        m = make_metrics(ladder=[])
        self.assertEqual(server._dex_ratio_near_spot(m), 0.0)


class TestGammaWallShare(unittest.TestCase):
    def test_high_concentration_at_walls(self):
        # Massive gamma at put_wall + call_wall, low elsewhere
        m = make_metrics(
            put_wall=6680, call_wall=6720,
            ladder=[
                {"strike": 6680, "call_gamma": 0.05, "put_gamma": 0.05, "call_oi": 10000, "put_oi": 10000},
                {"strike": 6700, "call_gamma": 0.001, "put_gamma": 0.001, "call_oi": 100, "put_oi": 100},
                {"strike": 6720, "call_gamma": 0.05, "put_gamma": 0.05, "call_oi": 10000, "put_oi": 10000},
            ],
        )
        share = server._gamma_wall_share(m)
        self.assertGreater(share, 0.95)

    def test_dispersed_returns_low(self):
        # Gamma spread evenly across MANY strikes so wall share is small
        m = make_metrics(
            put_wall=6680, call_wall=6720,
            ladder=[
                {"strike": 6680, "call_gamma": 0.01, "put_gamma": 0.01, "call_oi": 1000, "put_oi": 1000},
                {"strike": 6690, "call_gamma": 0.01, "put_gamma": 0.01, "call_oi": 1000, "put_oi": 1000},
                {"strike": 6700, "call_gamma": 0.01, "put_gamma": 0.01, "call_oi": 1000, "put_oi": 1000},
                {"strike": 6710, "call_gamma": 0.01, "put_gamma": 0.01, "call_oi": 1000, "put_oi": 1000},
                {"strike": 6720, "call_gamma": 0.01, "put_gamma": 0.01, "call_oi": 1000, "put_oi": 1000},
            ],
        )
        share = server._gamma_wall_share(m)
        # With 5 strikes evenly dispersed: share = 2/5 = 0.4 → less than 0.5
        self.assertLess(share, 0.5)

    def test_no_walls_returns_zero(self):
        m = make_metrics(put_wall=None, call_wall=None)
        self.assertEqual(server._gamma_wall_share(m), 0.0)


class TestThetaBleedPenalty(unittest.TestCase):
    def test_before_window_no_penalty(self):
        # Default ladder has small theta magnitudes
        m = make_metrics()
        with patch.object(server.datetime, "datetime", wraps=datetime.datetime) as mock_dt:
            # Force a 10:00 ET time (well before 13:30 window)
            mock_dt.now.return_value = datetime.datetime(2026, 8, 29, 10, 0)
            penalty = server._theta_bleed_penalty(m)
        self.assertEqual(penalty, 0.0)

    def test_high_theta_late_day_penalized(self):
        # Build a ladder with massive theta (above threshold of 50)
        m = make_metrics(ladder=[
            {"strike": 6700, "call_theta": -30.0, "put_theta": -30.0},
        ])
        with patch.object(server.datetime, "datetime", wraps=datetime.datetime) as mock_dt:
            # Force a 15:00 ET time (in the penalty window: hour_factor > 0.5)
            mock_dt.now.return_value = datetime.datetime(2026, 8, 29, 15, 0)
            penalty = server._theta_bleed_penalty(m)
        self.assertEqual(penalty, -0.5)

    def test_no_ladder_no_penalty(self):
        m = make_metrics(ladder=[])
        self.assertEqual(server._theta_bleed_penalty(m), 0.0)


# ---------------------------------------------------------------------------
# _score_recommendation with new factors
# ---------------------------------------------------------------------------

class TestScoreRecommendationExtension(unittest.TestCase):
    def test_breakdown_has_24_keys(self):
        m = make_metrics()
        score, bd = server._score_recommendation(m)
        expected_keys = {
            "regimeBias",
            "wallProximity", "wallProximityCall", "wallProximityPut",
            "wallBreak", "darkGamma",
            "volumeOiDivergence",
            "wallOiBuildup", "wallOiBuildupCall", "wallOiBuildupPut",
            "volumeLead", "breakoutRisk",
            "netGexMultiplier", "regimeMagnitude",
            "dexImbalance", "gammaWallStickiness", "thetaBleed",
            # TIER 2 quick-win factors
            "pinningCandidate", "vixContext", "setupConfluence", "gexFlip",
            "calendarWeekday", "sessionPhase", "positionState",
        }
        self.assertEqual(set(bd.keys()), expected_keys)

    def test_dex_imbalance_reinforces_bullish_bias(self):
        # Strong call DEX (dealer long delta) + bullish bias → positive contribution
        m = make_metrics(
            bias="BULLISH",
            ladder=[
                {"strike": 6700, "call_oi": 10000, "call_delta": 0.5, "put_oi": 1000, "put_delta": -0.5},
                {"strike": 6710, "call_oi": 10000, "call_delta": 0.5, "put_oi": 1000, "put_delta": -0.5},
            ],
        )
        score, bd = server._score_recommendation(m)
        self.assertGreater(bd["dexImbalance"], 0)

    def test_gamma_concentration_adds_score(self):
        # Gamma concentrated at walls with bullish bias → +0.5
        m = make_metrics(
            bias="BULLISH",
            put_wall=6680, call_wall=6720,
            ladder=[
                {"strike": 6680, "call_gamma": 0.05, "put_gamma": 0.05, "call_oi": 10000, "put_oi": 10000},
                {"strike": 6720, "call_gamma": 0.05, "put_gamma": 0.05, "call_oi": 10000, "put_oi": 10000},
                {"strike": 6700, "call_gamma": 0.001, "put_gamma": 0.001, "call_oi": 100, "put_oi": 100},
            ],
        )
        score, bd = server._score_recommendation(m)
        self.assertEqual(bd["gammaWallStickiness"], 0.5)

    def test_dispered_gamma_high_breakout_penalizes(self):
        # Gamma dispersed + HIGH breakout → -0.5
        m = make_metrics(
            bias="BULLISH", breakout_risk="HIGH",
            put_wall=6680, call_wall=6720,
            ladder=[
                {"strike": 6680, "call_gamma": 0.001, "put_gamma": 0.001, "call_oi": 100, "put_oi": 100},
                {"strike": 6690, "call_gamma": 0.001, "put_gamma": 0.001, "call_oi": 100, "put_oi": 100},
                {"strike": 6700, "call_gamma": 0.001, "put_gamma": 0.001, "call_oi": 100, "put_oi": 100},
                {"strike": 6710, "call_gamma": 0.001, "put_gamma": 0.001, "call_oi": 100, "put_oi": 100},
                {"strike": 6720, "call_gamma": 0.001, "put_gamma": 0.001, "call_oi": 100, "put_oi": 100},
            ],
        )
        score, bd = server._score_recommendation(m)
        # Walls = 2 of 5 strikes → share = 0.4 < 0.5 → triggers dispersion penalty
        # However the test setup has bias=BULLISH so by default the regimeBias is +1
        # → the gamma dispersion condition requires share < 0.15 for the -0.5
        # With share = 0.4 it's between 0.15 and 0.40 → no contribution.
        # Fix: make gamma truly dispersed with more strikes so share < 0.15
        m2 = make_metrics(
            bias="BULLISH", breakout_risk="HIGH",
            put_wall=6680, call_wall=6720,
            ladder=[
                {"strike": s, "call_gamma": 0.001, "put_gamma": 0.001, "call_oi": 100, "put_oi": 100}
                for s in range(6650, 6755, 5)
            ],
        )
        score2, bd2 = server._score_recommendation(m2)
        self.assertEqual(bd2["gammaWallStickiness"], -0.5)

    def test_score_clamped_to_3(self):
        # Construct metrics that would score very high
        m = make_metrics(
            bias="BULLISH", regime="SHORT_GAMMA", breakout_risk="LOW",
            net_gex_total=20, regime_score=1.0,
        )
        score, _ = server._score_recommendation(m)
        self.assertLessEqual(score, 3.0)
        self.assertGreaterEqual(score, -3.0)


class TestTier1BugFixes(unittest.TestCase):
    """Regression tests for the TIER 1 deterministic bugs."""

    def test_wall_proximity_accumulates_both_sides(self):
        # Spot inside 0.3% of BOTH walls → both Call+Put contributions must show
        # individually AND the legacy aggregated key must equal their sum.
        spot = 6700.0
        # gap of 0.0025 (~16.75 pts) — comfortably inside the 0.3% band
        call_wall = spot * 1.0025
        put_wall = spot * 0.9975
        m = make_metrics(spot=spot, put_wall=put_wall, call_wall=call_wall, bias="BULLISH")
        _, bd = server._score_recommendation(m)
        # BULLISH bias: call_wall proximity contributes +1.5, put_wall contributes -0.5
        self.assertEqual(bd["wallProximityCall"], 1.5)
        self.assertEqual(bd["wallProximityPut"], -0.5)
        self.assertEqual(bd["wallProximity"], 1.5 + (-0.5))

    def test_wall_oi_buildup_accumulates_both_sides(self):
        # Both walls have OI > 2× average → both contribute and the legacy key sums.
        spot = 6700.0
        call_wall, put_wall = 6740.0, 6660.0  # outside 0.3% band → no proximity
        # Default make_metrics gives OI profile sized by ladder rows
        m = make_metrics(spot=spot, call_wall=call_wall, put_wall=put_wall)
        # Force OI buildup only at the wall strikes by setting a flat low baseline
        # and very high OI at the wall strikes.
        m["oi_profile"] = {
            6660: 20000,   # put wall — triggers buildup
            6680: 100, 6700: 100, 6720: 100,
            6740: 20000,   # call wall — triggers buildup
        }
        m["vol_profile"] = {k: 0 for k in m["oi_profile"]}
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["wallOiBuildupPut"], -0.5)
        self.assertEqual(bd["wallOiBuildupCall"], 0.5)
        self.assertEqual(bd["wallOiBuildup"], 0.0)

    def test_volume_oi_no_double_count(self):
        # pcr_vol=1.5 (>1.3 nuanced) + pcr_oi=1.05 (<1.1 nuanced) + BULLISH:
        # nuanced bucket should fire (-0.5) and the simple bucket (+1.0) must NOT
        # also fire. Net must be exactly -0.5, not +0.5.
        m = make_metrics(
            bias="BULLISH",
            put_call_ratio={"volume": 1.5, "oi": 1.05},
        )
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["volumeOiDivergence"], -0.5)

    def test_volume_oi_simple_only_when_no_nuanced(self):
        # pcr_vol=1.25 (>1.2 simple) + pcr_oi=1.0 (NOT <1.1 nuanced):
        # nuanced does NOT fire; simple bucket +1.0 should fire for BULLISH.
        m = make_metrics(
            bias="BULLISH",
            put_call_ratio={"volume": 1.25, "oi": 1.0},
        )
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["volumeOiDivergence"], 1.0)

    def test_gamma_wall_share_int_float_mismatch(self):
        # Ladder has strikes as ints (6680) but wall comes as float (6680.0).
        # Old code: `r["strike"] == s` → False → wall_gamma=0. New: abs() tolerance works.
        m = {
            "spot": 6700.0,
            "call_wall": 6720.0,
            "put_wall": 6680.0,
            "strike_ladder": [
                {"strike": 6680, "call_gamma": 0.05, "put_gamma": 0.05,
                 "call_oi": 10000, "put_oi": 10000},
                {"strike": 6700, "call_gamma": 0.001, "put_gamma": 0.001,
                 "call_oi": 100, "put_oi": 100},
                {"strike": 6720, "call_gamma": 0.05, "put_gamma": 0.05,
                 "call_oi": 10000, "put_oi": 10000},
            ],
        }
        share = server._gamma_wall_share(m)
        self.assertGreater(share, 0.95)  # would be 0 with old strict-equality code

    def test_wall_break_contradictory_resets_to_zero(self):
        # Both CALL_WALL_BREAK and PUT_WALL_BREAK simultaneously → score must NOT
        # be ±4; should be 0 (whipsaw reset) and the breakdown must reflect it.
        with patch.object(server.state, "_alert_state", {"CALL_WALL_BREAK": True, "PUT_WALL_BREAK": True}):
            m = make_metrics()
            score_before, _ = server._score_recommendation(m)
            _, bd = server._score_recommendation(m)
            # The wallBreak contribution to the score must be 0 (no +2/-2 stacking)
            # We verify the breakdown key directly.
            self.assertEqual(bd["wallBreak"], 0.0)

    def test_theta_threshold_constant_exists(self):
        # The magic 50.0 is now a named constant accessible at module scope.
        self.assertTrue(hasattr(server, "THETA_BLEED_MAG_THRESHOLD"))
        self.assertEqual(server.THETA_BLEED_MAG_THRESHOLD, 50.0)

    def test_v1_choose_instrument_removed(self):
        # Dead code v1 should no longer be defined.
        self.assertFalse(hasattr(server, "_choose_instrument"))


class TestTier2QuickWins(unittest.TestCase):
    """Tests for the TIER 2 factors that wire already-computed metrics into the score."""

    def test_pinning_candidate_near(self):
        m = make_metrics(spot=6700.0, pinning_candidate=6705.0)  # gap < 0.3%
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["pinningCandidate"], 0.5)

    def test_pinning_candidate_far(self):
        m = make_metrics(spot=6700.0, pinning_candidate=6900.0)  # gap > 1%
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["pinningCandidate"], -0.3)

    def test_pinning_candidate_missing_is_zero(self):
        m = make_metrics()  # no pinning_candidate
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["pinningCandidate"], 0.0)

    def test_vix_low_complacency(self):
        # VIX < 12 → +0.5 (or -0.5 if bearish bias)
        m = make_metrics(vix=10.0, bias="BULLISH")
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["vixContext"], 0.5)

    def test_vix_high_fear_contrarian_bullish(self):
        m = make_metrics(vix=35.0)
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["vixContext"], 0.5)

    def test_vix_neutral_25_to_30_bearish(self):
        m = make_metrics(vix=27.0, bias="BEARISH")
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["vixContext"], -0.5)

    def test_vix_neutral_band_zero(self):
        m = make_metrics(vix=18.0, bias="BULLISH")
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["vixContext"], 0.0)

    def test_setup_confluence_fade_two_or_more(self):
        m = make_metrics(
            fade_setups=[
                {"action": "sell_put", "strike": 6680, "tp": 1.5},
                {"action": "sell_call", "strike": 6720, "tp": 1.5},
            ],
        )
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["setupConfluence"], 0.5)

    def test_setup_confluence_breakout_requires_high_risk(self):
        m = make_metrics(
            breakout_risk="LOW",
            breakout_setups=[
                {"action": "buy_call", "strike": 6730},
                {"action": "buy_put", "strike": 6670},
            ],
        )
        _, bd = server._score_recommendation(m)
        # breakout_risk != HIGH → factor should not fire
        self.assertEqual(bd["setupConfluence"], 0.0)

    def test_gex_flip_positive(self):
        # Previous was negative (-5), now positive (+3) → flip → +1.5
        m = make_metrics(net_gex_total=3.0)
        _, bd = server._score_recommendation(m, prev_net_gex=-5.0)
        self.assertEqual(bd["gexFlip"], 1.5)

    def test_gex_flip_negative(self):
        m = make_metrics(net_gex_total=-2.0)
        _, bd = server._score_recommendation(m, prev_net_gex=4.0)
        self.assertEqual(bd["gexFlip"], -1.5)

    def test_gex_no_flip_when_sign_unchanged(self):
        m = make_metrics(net_gex_total=5.0)
        _, bd = server._score_recommendation(m, prev_net_gex=8.0)
        self.assertEqual(bd["gexFlip"], 0.0)

    def test_gex_flip_unavailable_first_call(self):
        m = make_metrics(net_gex_total=5.0)
        # prev_net_gex=None → first call → no flip contribution
        _, bd = server._score_recommendation(m, prev_net_gex=None)
        self.assertEqual(bd["gexFlip"], 0.0)

    @patch.object(server, "_now_et_hour_weekday")
    def test_calendar_wednesday_opex(self, mock_now):
        mock_now.return_value = (12.0, 2)  # hour=12, weekday=Wed
        m = make_metrics()
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["calendarWeekday"], 0.5)

    @patch.object(server, "_now_et_hour_weekday")
    def test_calendar_monday_gap_risk(self, mock_now):
        mock_now.return_value = (12.0, 0)  # Mon
        m = make_metrics()
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["calendarWeekday"], -0.3)

    @patch.object(server, "_now_et_hour_weekday")
    def test_calendar_friday_pre_power_hour(self, mock_now):
        mock_now.return_value = (11.0, 4)  # Fri before 14:30
        m = make_metrics()
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["calendarWeekday"], -0.5)

    @patch.object(server, "_now_et_hour_weekday")
    def test_calendar_friday_power_hour_no_penalty(self, mock_now):
        mock_now.return_value = (15.0, 4)  # Fri in power hour
        m = make_metrics()
        _, bd = server._score_recommendation(m)
        # After 14:5 the Friday rule shouldn't fire
        self.assertEqual(bd["calendarWeekday"], 0.0)

    @patch.object(server, "_now_et_hour_weekday")
    def test_session_phase_orb_high_risk(self, mock_now):
        mock_now.return_value = (10.0, 2)  # 10:00 ET Wed
        m = make_metrics(breakout_risk="HIGH")
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["sessionPhase"], 0.5)

    @patch.object(server, "_now_et_hour_weekday")
    def test_session_phase_power_hour_penalty(self, mock_now):
        mock_now.return_value = (15.0, 2)  # 15:00 ET
        m = make_metrics()
        _, bd = server._score_recommendation(m)
        self.assertEqual(bd["sessionPhase"], -0.3)

    @patch.object(server, "_now_et_hour_weekday")
    def test_session_phase_moc_zeroes_score(self, mock_now):
        mock_now.return_value = (15.9, 2)  # 15:54 ET
        m = make_metrics(net_gex_total=10.0)  # would normally multiply
        score, bd = server._score_recommendation(m)
        self.assertEqual(bd["sessionPhase"], 0.0)
        self.assertEqual(score, 0.0)  # score *= 0 → neutralized

    def test_position_state_same_direction_penalized(self):
        m = make_metrics(bias="BULLISH")
        _, bd = server._score_recommendation(
            m, position={"active": True, "direction": "BULLISH"}
        )
        self.assertEqual(bd["positionState"], -1.0)

    def test_position_state_opposite_direction_boosted(self):
        m = make_metrics(bias="BULLISH")
        _, bd = server._score_recommendation(
            m, position={"active": True, "direction": "BEARISH"}
        )
        self.assertEqual(bd["positionState"], 0.5)

    def test_position_state_inactive_no_effect(self):
        m = make_metrics(bias="BULLISH")
        _, bd = server._score_recommendation(
            m, position={"active": False}
        )
        self.assertEqual(bd["positionState"], 0.0)

    def test_position_state_none_no_effect(self):
        m = make_metrics(bias="BULLISH")
        _, bd = server._score_recommendation(m, position=None)
        self.assertEqual(bd["positionState"], 0.0)


# ---------------------------------------------------------------------------
# _choose_instrument_v2
# ---------------------------------------------------------------------------

class TestChooseInstrumentV2(unittest.TestCase):
    def test_neutral_returns_no_trade(self):
        m = make_metrics()
        instr, style, expiry = server._choose_instrument_v2(m, "NEUTRAL", 0.0, {})
        self.assertEqual(instr, "NO_TRADE")
        self.assertEqual(style, "WAIT")
        self.assertIsNone(expiry)

    def test_high_conviction_high_breakout_returns_single_leg(self):
        m = make_metrics(breakout_risk="HIGH")
        instr, style, expiry = server._choose_instrument_v2(m, "BULLISH", 2.5, {})
        self.assertEqual(instr, "BUY_CALL")
        self.assertEqual(style, "DIRECTIONAL")
        self.assertEqual(expiry, "0DTE")

    def test_high_conviction_high_breakout_bearish(self):
        m = make_metrics(breakout_risk="HIGH")
        instr, style, expiry = server._choose_instrument_v2(m, "BEARISH", -2.5, {})
        self.assertEqual(instr, "BUY_PUT")
        self.assertEqual(style, "DIRECTIONAL")

    def test_balanced_dex_gamma_walls_returns_ic(self):
        # Balanced DEX (call_oi ≈ put_oi), gamma at walls, low-mid score
        m = make_metrics(
            bias="BULLISH", regime="LONG_GAMMA", breakout_risk="MEDIUM",
            put_wall=6680, call_wall=6720,
            ladder=[
                # Walls
                {"strike": 6680, "call_oi": 5000, "put_oi": 5000, "call_delta": 0.5, "put_delta": -0.5,
                 "call_gamma": 0.05, "put_gamma": 0.05},
                {"strike": 6720, "call_oi": 5000, "put_oi": 5000, "call_delta": 0.5, "put_delta": -0.5,
                 "call_gamma": 0.05, "put_gamma": 0.05},
                # ATM
                {"strike": 6700, "call_oi": 1000, "put_oi": 1000, "call_delta": 0.5, "put_delta": -0.5,
                 "call_gamma": 0.01, "put_gamma": 0.01},
            ],
        )
        instr, style, expiry = server._choose_instrument_v2(m, "BULLISH", 0.5, {})
        self.assertEqual(instr, "IC")
        self.assertIn(style, ("PINNING", "BUTTERFLY"))

    def test_theta_bleed_promotes_butterfly(self):
        # Same as above but with thetaBleed active
        m = make_metrics(
            bias="BULLISH", regime="LONG_GAMMA", breakout_risk="MEDIUM",
            put_wall=6680, call_wall=6720,
            ladder=[
                {"strike": 6680, "call_oi": 5000, "put_oi": 5000, "call_delta": 0.5, "put_delta": -0.5,
                 "call_gamma": 0.05, "put_gamma": 0.05},
                {"strike": 6720, "call_oi": 5000, "put_oi": 5000, "call_delta": 0.5, "put_delta": -0.5,
                 "call_gamma": 0.05, "put_gamma": 0.05},
                {"strike": 6700, "call_oi": 1000, "put_oi": 1000, "call_delta": 0.5, "put_delta": -0.5,
                 "call_gamma": 0.01, "put_gamma": 0.01},
            ],
        )
        instr, style, _ = server._choose_instrument_v2(m, "BULLISH", 0.5, {"thetaBleed": -0.5})
        self.assertEqual(instr, "IC")
        self.assertEqual(style, "BUTTERFLY")

    def test_default_bullish_returns_pcs(self):
        # Build a ladder with dispersed gamma (NOT at walls) so default falls through to PCS
        m = make_metrics(
            bias="BULLISH", regime="LONG_GAMMA", breakout_risk="MEDIUM",
            ladder=[
                {"strike": 6690, "call_oi": 1000, "put_oi": 1000,
                 "call_delta": 0.55, "put_delta": -0.45,
                 "call_gamma": 0.01, "put_gamma": 0.01},
                {"strike": 6700, "call_oi": 1000, "put_oi": 1000,
                 "call_delta": 0.40, "put_delta": -0.55,
                 "call_gamma": 0.01, "put_gamma": 0.01},
                {"strike": 6710, "call_oi": 1000, "put_oi": 1000,
                 "call_delta": 0.25, "put_delta": -0.70,
                 "call_gamma": 0.01, "put_gamma": 0.01},
            ],
        )
        instr, style, _ = server._choose_instrument_v2(m, "BULLISH", 1.0, {})
        self.assertEqual(instr, "PCS")
        self.assertEqual(style, "WALL_PUT")

    def test_default_bearish_returns_ccs(self):
        m = make_metrics(
            bias="BEARISH", regime="LONG_GAMMA", breakout_risk="MEDIUM",
            ladder=[
                {"strike": 6690, "call_oi": 1000, "put_oi": 1000,
                 "call_delta": 0.55, "put_delta": -0.45,
                 "call_gamma": 0.01, "put_gamma": 0.01},
                {"strike": 6700, "call_oi": 1000, "put_oi": 1000,
                 "call_delta": 0.40, "put_delta": -0.55,
                 "call_gamma": 0.01, "put_gamma": 0.01},
                {"strike": 6710, "call_oi": 1000, "put_oi": 1000,
                 "call_delta": 0.25, "put_delta": -0.70,
                 "call_gamma": 0.01, "put_gamma": 0.01},
            ],
        )
        instr, style, _ = server._choose_instrument_v2(m, "BEARISH", -1.0, {})
        self.assertEqual(instr, "CCS")
        self.assertEqual(style, "WALL_CALL")


# ---------------------------------------------------------------------------
# _recommend_legs
# ---------------------------------------------------------------------------

class TestRecommendLegs(unittest.TestCase):
    def test_no_trade_returns_empty_legs(self):
        m = make_metrics()
        result = server._recommend_legs(m, "NO_TRADE", "NEUTRAL", 6700)
        self.assertEqual(result["legs"], [])
        self.assertEqual(result["width"], 0)

    def test_buy_call_single_leg(self):
        m = make_metrics(spot=6700)
        result = server._recommend_legs(m, "BUY_CALL", "BULLISH", 6700)
        self.assertEqual(len(result["legs"]), 1)
        self.assertEqual(result["legs"][0]["right"], "C")
        self.assertEqual(result["legs"][0]["action"], "BUY")
        self.assertEqual(result["width"], 0)
        self.assertEqual(result["expiry_hint"], "0DTE")

    def test_buy_put_single_leg(self):
        m = make_metrics(spot=6700)
        result = server._recommend_legs(m, "BUY_PUT", "BEARISH", 6700)
        self.assertEqual(len(result["legs"]), 1)
        self.assertEqual(result["legs"][0]["right"], "P")

    def test_pcs_two_legs_at_put_wall(self):
        m = make_metrics(spot=6700, put_wall=6680)
        result = server._recommend_legs(m, "PCS", "BULLISH", 6700)
        self.assertEqual(len(result["legs"]), 2)
        # First leg: SELL the wall strike
        self.assertEqual(result["legs"][0]["action"], "SELL")
        self.assertEqual(result["legs"][0]["right"], "P")
        self.assertEqual(result["legs"][0]["strike"], 6680)
        # Second leg: BUY the wing
        self.assertEqual(result["legs"][1]["action"], "BUY")
        self.assertEqual(result["legs"][1]["right"], "P")
        # Wing is below short by width
        self.assertEqual(result["legs"][0]["strike"] - result["legs"][1]["strike"], result["width"])

    def test_ccs_two_legs_at_call_wall(self):
        m = make_metrics(spot=6700, call_wall=6720)
        result = server._recommend_legs(m, "CCS", "BEARISH", 6700)
        self.assertEqual(len(result["legs"]), 2)
        self.assertEqual(result["legs"][0]["right"], "C")
        self.assertEqual(result["legs"][0]["strike"], 6720)
        self.assertEqual(result["legs"][0]["action"], "SELL")

    def test_ic_four_legs_walls_far_apart(self):
        # Walls 50 pts apart, width 10 → wall-anchored IC
        m = make_metrics(spot=6700, put_wall=6650, call_wall=6750)
        result = server._recommend_legs(m, "IC", "NEUTRAL", 6700)
        self.assertEqual(len(result["legs"]), 4)
        # First leg SELL P at put_wall
        self.assertEqual(result["legs"][0]["action"], "SELL")
        self.assertEqual(result["legs"][0]["right"], "P")
        self.assertEqual(result["legs"][0]["strike"], 6650)
        # Third leg SELL C at call_wall
        self.assertEqual(result["legs"][2]["action"], "SELL")
        self.assertEqual(result["legs"][2]["right"], "C")
        self.assertEqual(result["legs"][2]["strike"], 6750)

    def test_ic_falls_back_to_butterfly_when_walls_close(self):
        # Walls too close for viable IC
        m = make_metrics(spot=6700, put_wall=6695, call_wall=6705)
        result = server._recommend_legs(m, "IC", "NEUTRAL", 6700)
        self.assertEqual(len(result["legs"]), 4)
        # Should mention butterfly in rationale
        self.assertIn("butterfly", result["rationale"].lower())

    def test_width_depends_on_gamma_concentration(self):
        # High gamma at walls → width=5
        m = make_metrics(
            spot=6700, put_wall=6680, call_wall=6720,
            ladder=[
                {"strike": 6680, "call_gamma": 0.05, "put_gamma": 0.05, "call_oi": 10000, "put_oi": 10000,
                 "call_delta": 0.5, "put_delta": -0.5, "call_theta": -0.1, "put_theta": -0.1},
                {"strike": 6720, "call_gamma": 0.05, "put_gamma": 0.05, "call_oi": 10000, "put_oi": 10000,
                 "call_delta": 0.5, "put_delta": -0.5, "call_theta": -0.1, "put_theta": -0.1},
                {"strike": 6700, "call_gamma": 0.01, "put_gamma": 0.01, "call_oi": 100, "put_oi": 100,
                 "call_delta": 0.5, "put_delta": -0.5, "call_theta": -0.1, "put_theta": -0.1},
            ],
        )
        result = server._recommend_legs(m, "PCS", "BULLISH", 6700)
        self.assertEqual(result["width"], 5)


# ---------------------------------------------------------------------------
# Endpoint validation tests (ComboLegRequest / ComboTradeRequest)
# ---------------------------------------------------------------------------

class TestComboTradeRequestValidation(unittest.TestCase):
    def test_valid_request(self):
        req = server.ComboTradeRequest(
            legs=[
                server.ComboLegRequest(right="P", strike=6680, action="SELL"),
                server.ComboLegRequest(right="P", strike=6670, action="BUY"),
            ],
            qty=1,
            expiry="0DTE",
        )
        self.assertEqual(len(req.legs), 2)
        self.assertEqual(req.legs[0].action, "SELL")

    def test_invalid_right_rejected_by_pydantic(self):
        # Pydantic does not enforce enum constraints by default for str;
        # validation happens in the endpoint handler. We just verify the
        # model accepts arbitrary strings (handler validates).
        req = server.ComboTradeRequest(
            legs=[server.ComboLegRequest(right="X", strike=6700, action="BUY")],
        )
        self.assertEqual(req.legs[0].right, "X")


# ---------------------------------------------------------------------------
# IBKREngine.execute_combo validation
# ---------------------------------------------------------------------------

class TestExecuteComboValidation(unittest.TestCase):
    """Test the validation logic in execute_combo (mocked IBKR connection)."""

    def setUp(self):
        # Mock the engine without going through __init__
        self.engine = server.IBKREngine.__new__(server.IBKREngine)
        self.engine.ib = MagicMock()
        self.engine.ib.isConnected.return_value = True
        self.engine.ib.client.getReqId.return_value = 12345

    def test_no_legs_raises(self):
        import asyncio
        with self.assertRaises(ValueError):
            asyncio.run(self.engine.execute_combo(legs=[], expiry="20260829"))

    def test_too_many_legs_raises(self):
        import asyncio
        legs = [{"right": "C", "strike": 6700, "action": "BUY"}] * 5
        with self.assertRaises(ValueError):
            asyncio.run(self.engine.execute_combo(legs=legs, expiry="20260829"))

    def test_invalid_right_raises(self):
        import asyncio
        with self.assertRaises(ValueError):
            asyncio.run(self.engine.execute_combo(
                legs=[{"right": "X", "strike": 6700, "action": "BUY"}],
                expiry="20260829",
            ))

    def test_invalid_action_raises(self):
        import asyncio
        with self.assertRaises(ValueError):
            asyncio.run(self.engine.execute_combo(
                legs=[{"right": "C", "strike": 6700, "action": "HOLD"}],
                expiry="20260829",
            ))

    def test_not_connected_raises(self):
        import asyncio
        self.engine.ib.isConnected.return_value = False
        with self.assertRaises(RuntimeError):
            asyncio.run(self.engine.execute_combo(
                legs=[{"right": "C", "strike": 6700, "action": "BUY"}],
                expiry="20260829",
            ))


# ---------------------------------------------------------------------------
# /api/trade_combo endpoint validation (live gate)
# ---------------------------------------------------------------------------

class TestTradeComboEndpoint(unittest.TestCase):
    """Test the endpoint handler with mocked state and engine."""

    def setUp(self):
        # Reset state for each test
        server.state.connected = True
        server.state.engine = MagicMock()
        server.state.engine.ib.isConnected.return_value = True
        server.state.engine_live = None
        server.state.live_trading_armed = False

    def test_live_without_arming_returns_403(self):
        from fastapi import HTTPException
        import asyncio

        req = server.ComboTradeRequest(
            legs=[server.ComboLegRequest(right="C", strike=6700, action="BUY")],
            target_env="live",
            transmit=True,
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.execute_combo_trade(req))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_invalid_leg_count_returns_400(self):
        from fastapi import HTTPException
        import asyncio

        req = server.ComboTradeRequest(
            legs=[
                server.ComboLegRequest(right="C", strike=6700, action="BUY"),
                server.ComboLegRequest(right="C", strike=6710, action="BUY"),
                server.ComboLegRequest(right="P", strike=6690, action="BUY"),
                server.ComboLegRequest(right="P", strike=6700, action="SELL"),
                server.ComboLegRequest(right="P", strike=6710, action="SELL"),
            ],
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.execute_combo_trade(req))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_engine_not_connected_returns_400(self):
        from fastapi import HTTPException
        import asyncio

        server.state.connected = False
        req = server.ComboTradeRequest(
            legs=[server.ComboLegRequest(right="C", strike=6700, action="BUY")],
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.execute_combo_trade(req))
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
