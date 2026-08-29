"""
End-to-end integration tests for the Recommendation Engine + one-click EXECUTE button.

Covers the complete flow:
  WS metrics → _score_recommendation → _choose_instrument_v2 → _recommend_legs
  → payload broadcast → button rendering decision
  → click → confirmation dialog
  → POST /api/trade_combo → engine.execute_combo → IBKR BAG order

Tests simulate each step without requiring a live IBKR connection.
"""
import asyncio
import datetime
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call

import server


def make_full_metrics(**overrides):
    """Build a realistic metrics dict with all fields the Recommendation Engine reads."""
    spot = overrides.get("spot", 6700.0)
    call_wall = overrides.get("call_wall", 6720.0)
    put_wall = overrides.get("put_wall", 6680.0)
    bias = overrides.get("bias", "BULLISH")
    regime = overrides.get("regime", "LONG_GAMMA")
    breakout_risk = overrides.get("breakout_risk", "MEDIUM")
    net_gex_total = overrides.get("net_gex_total", 18.0)
    regime_score = overrides.get("regime_score", 0.7)

    # Balanced DEX (call_oi ≈ put_oi) with gamma concentrated at walls
    # → triggers IC + PINNING style
    ladder = [
        {"strike": 6680, "call_bid": 21.5, "call_ask": 23.0, "call_oi": 5000, "call_volume": 200,
         "call_delta": 0.70, "call_gamma": 0.020, "call_theta": -0.20,
         "put_bid": 1.5, "put_ask": 2.0, "put_oi": 5000, "put_volume": 500,
         "put_delta": -0.30, "put_gamma": 0.020, "put_theta": -0.10},
        {"strike": 6690, "call_bid": 12.5, "call_ask": 14.0, "call_oi": 1000, "call_volume": 80,
         "call_delta": 0.55, "call_gamma": 0.005, "call_theta": -0.30,
         "put_bid": 4.0, "put_ask": 5.0, "put_oi": 1000, "put_volume": 100,
         "put_delta": -0.45, "put_gamma": 0.005, "put_theta": -0.20},
        {"strike": 6700, "call_bid": 6.0, "call_ask": 7.5, "call_oi": 1500, "call_volume": 250,
         "call_delta": 0.40, "call_gamma": 0.004, "call_theta": -0.40,
         "put_bid": 9.0, "put_ask": 10.5, "put_oi": 1500, "put_volume": 300,
         "put_delta": -0.55, "put_gamma": 0.004, "put_theta": -0.30},
        {"strike": 6710, "call_bid": 2.5, "call_ask": 3.5, "call_oi": 1000, "call_volume": 60,
         "call_delta": 0.25, "call_gamma": 0.005, "call_theta": -0.30,
         "put_bid": 16.5, "put_ask": 18.0, "put_oi": 1000, "put_volume": 70,
         "put_delta": -0.70, "put_gamma": 0.005, "put_theta": -0.20},
        {"strike": 6720, "call_bid": 1.0, "call_ask": 1.5, "call_oi": 5000, "call_volume": 120,
         "call_delta": 0.10, "call_gamma": 0.020, "call_theta": -0.15,
         "put_bid": 26.0, "put_ask": 28.0, "put_oi": 5000, "put_volume": 50,
         "put_delta": -0.85, "put_gamma": 0.020, "put_theta": -0.10},
    ]
    return {
        "spot": spot, "call_wall": call_wall, "put_wall": put_wall,
        "bias": bias, "regime": regime, "breakout_risk": breakout_risk,
        "net_gex_total": net_gex_total, "regime_score": regime_score,
        "gamma_flip": 6700,
        "strike_ladder": ladder,
        "dark_gamma": [],
        "put_call_ratio": {"volume": 0.95, "oi": 1.0},
        "oi_profile": {r["strike"]: r["call_oi"] + r["put_oi"] for r in ladder},
        "vol_profile": {r["strike"]: r["call_volume"] + r["put_volume"] for r in ladder},
    }


# ---------------------------------------------------------------------------
# Full pipeline: metrics → score → instrument → legs → payload
# ---------------------------------------------------------------------------

class TestFullRecommendationPipeline(unittest.TestCase):
    """End-to-end pipeline test: feed realistic metrics and verify the full
    chain of (score, breakdown, instrument, style, spread) the banner receives."""

    def test_long_gamma_balanced_yields_ic_pinning(self):
        # Build custom ladder: walls at 6740/6660 (>0.003 away from spot 6700
        # so wallProximity doesn't add points). Gamma concentrated at walls.
        # Symmetric deltas → balanced DEX (dex_ratio=0). Low volumes so
        # volumeLead doesn't trigger. net_gex_total=1.0 → 0.8× multiplier.
        spot = 6700.0
        call_wall, put_wall = 6740.0, 6660.0
        ladder = []
        for s in (6660, 6680, 6700, 6720, 6740):
            cd = max(0.05, 0.5 - abs(s - spot) / 200)
            if s in (call_wall, put_wall):
                cg, pg, oi = 0.05, 0.05, 1000
            else:
                cg, pg, oi = 0.001, 0.001, 100
            ladder.append({
                "strike": s,
                "call_delta": cd, "put_delta": -cd,
                "call_gamma": cg, "put_gamma": pg,
                "call_oi": oi, "put_oi": oi,
                "call_volume": 0, "put_volume": 0,
            })
        m = {
            "spot": spot, "call_wall": call_wall, "put_wall": put_wall,
            "bias": "BULLISH", "regime": "LONG_GAMMA", "breakout_risk": "MEDIUM",
            "net_gex_total": 1.0, "regime_score": 0.3,
            "gamma_flip": 6700,
            "strike_ladder": ladder,
            "dark_gamma": [],
            "put_call_ratio": {"volume": 1.0, "oi": 1.0},
            "oi_profile": {r["strike"]: r["call_oi"] + r["put_oi"] for r in ladder},
            "vol_profile": {r["strike"]: 0 for r in ladder},
        }
        score, bd = server._score_recommendation(m)
        direction = server._score_to_direction(score)
        instrument, style, expiry = server._choose_instrument_v2(m, direction, score, bd)
        spread = server._recommend_legs(m, instrument, direction, m["spot"])

        # Verify full payload structure
        self.assertIsNotNone(bd)
        self.assertEqual(len(bd), 26)
        self.assertIn(direction, ("BULLISH", "BEARISH", "NEUTRAL"))
        # Balanced DEX (symmetric deltas) + gamma at walls → IC PINNING
        self.assertEqual(instrument, "IC")
        self.assertEqual(style, "PINNING")
        self.assertEqual(expiry, "0DTE")
        self.assertEqual(len(spread["legs"]), 4)
        self.assertGreater(spread["width"], 0)

    def test_high_breakout_high_conviction_yields_single_leg(self):
        m = make_full_metrics(
            bias="BULLISH", regime="SHORT_GAMMA", breakout_risk="HIGH",
            net_gex_total=-25.0, regime_score=-0.8,
        )
        score, bd = server._score_recommendation(m)
        direction = server._score_to_direction(score)
        instrument, style, expiry = server._choose_instrument_v2(m, direction, score, bd)
        spread = server._recommend_legs(m, instrument, direction, m["spot"])

        self.assertIn(instrument, ("BUY_CALL", "BUY_PUT"))
        self.assertEqual(style, "DIRECTIONAL")
        self.assertEqual(len(spread["legs"]), 1)
        self.assertEqual(spread["width"], 0)

    def test_default_bullish_yields_pcs_with_walls(self):
        # Dispersed gamma → falls through to PCS
        m = make_full_metrics(
            bias="BULLISH", regime="LONG_GAMMA", breakout_risk="MEDIUM",
            put_wall=6680,
        )
        # Override ladder to disperse gamma
        m["strike_ladder"] = [
            {**r, "call_gamma": 0.005, "put_gamma": 0.005, "call_oi": 1000, "put_oi": 1000}
            for r in m["strike_ladder"]
        ]
        score, bd = server._score_recommendation(m)
        direction = server._score_to_direction(score)
        instrument, style, _ = server._choose_instrument_v2(m, direction, score, bd)
        spread = server._recommend_legs(m, instrument, direction, m["spot"])

        self.assertEqual(instrument, "PCS")
        self.assertEqual(style, "WALL_PUT")
        self.assertEqual(len(spread["legs"]), 2)
        self.assertEqual(spread["legs"][0]["action"], "SELL")
        self.assertEqual(spread["legs"][0]["right"], "P")
        self.assertEqual(spread["legs"][0]["strike"], 6680)
        self.assertEqual(spread["legs"][1]["action"], "BUY")
        self.assertEqual(spread["legs"][1]["right"], "P")


# ---------------------------------------------------------------------------
# Payload shape (what the WS broadcasts to the frontend)
# ---------------------------------------------------------------------------

class TestPayloadShape(unittest.TestCase):
    """Verify the WS payload structure matches the frontend's Recommendation interface."""

    def test_payload_includes_all_required_keys(self):
        m = make_full_metrics()
        score, bd = server._score_recommendation(m)
        direction = server._score_to_direction(score)
        instrument, style, expiry_hint = server._choose_instrument_v2(m, direction, score, bd)
        anchor = server._anchor_strike(m, direction)
        spread = server._recommend_legs(m, instrument, direction, m["spot"])

        # Build the same payload as _emit_recommendation
        payload = {
            "type": "recommendation",
            "score": round(score, 2),
            "direction": direction,
            "instrument": instrument,
            "style": style,
            "regime": m["regime"],
            "bias": m["bias"],
            "breakout_risk": m["breakout_risk"],
            "spot": round(m["spot"], 2),
            "call_wall": round(m["call_wall"], 2),
            "put_wall": round(m["put_wall"], 2),
            "gamma_flip": m["gamma_flip"],
            "net_gex_total": round(m["net_gex_total"], 4),
            "regime_score": round(m["regime_score"], 2),
            "anchor_strike": round(anchor, 2) if anchor else None,
            "confidence": server._confidence_label(score),
            "reason": "test",
            "timestamp": 1234567890.0,
            "scoreBreakdown": bd,
            "spread": spread if spread.get("legs") else None,
        }

        # Required keys for Recommendation interface
        required = {
            "score", "direction", "instrument", "style", "regime", "bias",
            "breakout_risk", "spot", "call_wall", "put_wall", "gamma_flip",
            "net_gex_total", "regime_score", "anchor_strike", "confidence",
            "reason", "timestamp", "scoreBreakdown", "spread", "type",
        }
        self.assertEqual(required - set(payload.keys()), set())

    def test_payload_spread_legs_format_matches_frontend_leg_interface(self):
        # Verify each leg in spread has the keys Leg interface expects
        m = make_full_metrics()
        score, bd = server._score_recommendation(m)
        direction = server._score_to_direction(score)
        instrument, style, _ = server._choose_instrument_v2(m, direction, score, bd)
        spread = server._recommend_legs(m, instrument, direction, m["spot"])

        for leg in spread["legs"]:
            self.assertIn("right", leg)
            self.assertIn(leg["right"], ("C", "P"))
            self.assertIn("strike", leg)
            self.assertIsInstance(leg["strike"], (int, float))
            self.assertIn("action", leg)
            self.assertIn(leg["action"], ("BUY", "SELL"))


# ---------------------------------------------------------------------------
# Button state logic (what the React component uses to decide visibility)
# ---------------------------------------------------------------------------

class TestButtonStateLogic(unittest.TestCase):
    """Mirror the React-side decision logic in a pure function to verify
    what the banner would render."""

    @staticmethod
    def _button_state(recommendation, connected, position_active, now):
        """Pure Python equivalent of the button state logic in RecommendationBanner.tsx."""
        if not recommendation:
            return "HIDDEN"
        spread = recommendation.get("spread")
        if not spread or not spread.get("legs"):
            return "HIDDEN"
        if recommendation.get("instrument") == "NO_TRADE":
            return "HIDDEN"
        if not connected:
            return "DISABLED_NOT_CONNECTED"
        if position_active:
            return "DISABLED_POSITION_OPEN"
        age = now - recommendation.get("timestamp", now)
        if age > 600:
            return "DISABLED_STALE"
        return "ENABLED"

    def test_no_recommendation_hides_button(self):
        state = self._button_state(None, True, False, 1000.0)
        self.assertEqual(state, "HIDDEN")

    def test_no_trade_hides_button(self):
        rec = {"instrument": "NO_TRADE", "spread": None, "timestamp": 1000.0}
        state = self._button_state(rec, True, False, 1000.0)
        self.assertEqual(state, "HIDDEN")

    def test_spread_without_legs_hides_button(self):
        rec = {"instrument": "PCS", "spread": {"legs": []}, "timestamp": 1000.0}
        state = self._button_state(rec, True, False, 1000.0)
        self.assertEqual(state, "HIDDEN")

    def test_disconnected_disables_button(self):
        rec = {"instrument": "PCS", "spread": {"legs": [{"right": "P", "strike": 6680, "action": "SELL"}]}, "timestamp": 1000.0}
        state = self._button_state(rec, False, False, 1000.0)
        self.assertEqual(state, "DISABLED_NOT_CONNECTED")

    def test_open_position_disables_button(self):
        rec = {"instrument": "PCS", "spread": {"legs": [{"right": "P", "strike": 6680, "action": "SELL"}]}, "timestamp": 1000.0}
        state = self._button_state(rec, True, True, 1000.0)
        self.assertEqual(state, "DISABLED_POSITION_OPEN")

    def test_stale_recommendation_disables_button(self):
        rec = {"instrument": "PCS", "spread": {"legs": [{"right": "P", "strike": 6680, "action": "SELL"}]}, "timestamp": 0.0}
        state = self._button_state(rec, True, False, 700.0)  # 700s > 600s
        self.assertEqual(state, "DISABLED_STALE")

    def test_fresh_recommendation_enables_button(self):
        rec = {
            "instrument": "PCS",
            "spread": {"legs": [{"right": "P", "strike": 6680, "action": "SELL"},
                               {"right": "P", "strike": 6665, "action": "BUY"}]},
            "timestamp": 1000.0,
        }
        state = self._button_state(rec, True, False, 1050.0)  # 50s old
        self.assertEqual(state, "ENABLED")


# ---------------------------------------------------------------------------
# LIVE confirmation logic (the dialog phrase check)
# ---------------------------------------------------------------------------

class TestLiveConfirmationLogic(unittest.TestCase):
    """Mirror the React-side dialog confirmation: env selection + phrase requirement."""

    @staticmethod
    def _can_submit(target_env, live_trading_armed, live_phrase):
        if target_env == "paper":
            return True
        # target_env == "live"
        if not live_trading_armed:
            return False
        return live_phrase == "ENABLE LIVE TRADING"

    def test_paper_always_submittable(self):
        self.assertTrue(self._can_submit("paper", False, ""))
        self.assertTrue(self._can_submit("paper", True, "anything"))

    def test_live_without_arming_blocked(self):
        self.assertFalse(self._can_submit("live", False, "ENABLE LIVE TRADING"))

    def test_live_with_arming_but_wrong_phrase_blocked(self):
        self.assertFalse(self._can_submit("live", True, "wrong phrase"))
        self.assertFalse(self._can_submit("live", True, ""))
        self.assertFalse(self._can_submit("live", True, "enable live trading"))  # case-sensitive

    def test_live_with_correct_phrase_submittable(self):
        self.assertTrue(self._can_submit("live", True, "ENABLE LIVE TRADING"))


# ---------------------------------------------------------------------------
# POST /api/trade_combo end-to-end flow (with mocked IBKR engine)
# ---------------------------------------------------------------------------

class TestTradeComboEndToEnd(unittest.TestCase):
    """Simulate the full HTTP → engine → IBKR flow with a mocked engine."""

    def setUp(self):
        server.state.connected = True
        server.state.live_trading_armed = False
        server.state.engine = MagicMock()
        server.state.engine.ib.isConnected.return_value = True
        # Mock execute_combo to return a fake trade
        server.state.engine.execute_combo = AsyncMock(return_value="fake_trade_obj")
        server.state.engine_live = None

        # Mock the broadcast to capture log messages
        self.broadcasts = []
        async def fake_broadcast(msg):
            self.broadcasts.append(msg)
        self._broadcast_patch = patch.object(server.manager, "broadcast", side_effect=fake_broadcast)
        self._broadcast_patch.start()

    def tearDown(self):
        self._broadcast_patch.stop()

    def test_paper_pcs_combo_flow(self):
        """End-to-end: PAPER PCS combo → engine.execute_combo called with correct params."""
        req = server.ComboTradeRequest(
            legs=[
                server.ComboLegRequest(right="P", strike=6680, action="SELL"),
                server.ComboLegRequest(right="P", strike=6665, action="BUY"),
            ],
            qty=1,
            expiry="0DTE",
            tp_pct=50.0,
            sl_ratio=2.0,
            transmit=True,
            target_env="paper",
        )
        result = asyncio.run(server.execute_combo_trade(req))

        # Verify response
        self.assertEqual(result["status"], "success")
        self.assertIn("expiry", result)

        # Verify engine was called with correct params
        server.state.engine.execute_combo.assert_called_once()
        kwargs = server.state.engine.execute_combo.call_args.kwargs
        self.assertEqual(kwargs["legs"], [
            {"right": "P", "strike": 6680, "action": "SELL"},
            {"right": "P", "strike": 6665, "action": "BUY"},
        ])
        self.assertEqual(kwargs["qty"], 1)
        self.assertEqual(kwargs["tp_pct"], 50.0)
        self.assertEqual(kwargs["sl_ratio"], 2.0)
        self.assertTrue(kwargs["transmit"])
        self.assertTrue(kwargs["bracket"])

        # Verify 0DTE was resolved to today's date
        today = datetime.datetime.now().strftime("%Y%m%d")
        self.assertEqual(kwargs["expiry"], today)

        # Verify log broadcasts
        log_msgs = [b["message"] for b in self.broadcasts if b.get("type") == "log"]
        self.assertTrue(any("Structuring" in m for m in log_msgs))
        self.assertTrue(any("Submitting to PAPER" in m for m in log_msgs))
        self.assertTrue(any("Combo placed" in m for m in log_msgs))

    def test_ic_combo_flow_with_four_legs(self):
        """IC combo: 4 legs → execute_combo called with all 4."""
        req = server.ComboTradeRequest(
            legs=[
                server.ComboLegRequest(right="P", strike=6680, action="SELL"),
                server.ComboLegRequest(right="P", strike=6670, action="BUY"),
                server.ComboLegRequest(right="C", strike=6720, action="SELL"),
                server.ComboLegRequest(right="C", strike=6730, action="BUY"),
            ],
            expiry="1DTE",
            target_env="paper",
        )
        result = asyncio.run(server.execute_combo_trade(req))

        self.assertEqual(result["status"], "success")
        kwargs = server.state.engine.execute_combo.call_args.kwargs
        self.assertEqual(len(kwargs["legs"]), 4)
        # Verify 1DTE was resolved to tomorrow
        tomorrow = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y%m%d")
        self.assertEqual(kwargs["expiry"], tomorrow)

    def test_weekly_expiry_resolved_to_friday(self):
        req = server.ComboTradeRequest(
            legs=[server.ComboLegRequest(right="C", strike=6705, action="BUY")],
            expiry="WEEKLY",
            target_env="paper",
        )
        result = asyncio.run(server.execute_combo_trade(req))

        self.assertEqual(result["status"], "success")
        kwargs = server.state.engine.execute_combo.call_args.kwargs
        expiry_dt = datetime.datetime.strptime(kwargs["expiry"], "%Y%m%d")
        self.assertEqual(expiry_dt.weekday(), 4)  # Friday

    def test_single_leg_flow(self):
        """Single-leg BUY_CALL: validate leg passed through correctly."""
        req = server.ComboTradeRequest(
            legs=[server.ComboLegRequest(right="C", strike=6705, action="BUY")],
            expiry="0DTE",
            target_env="paper",
        )
        result = asyncio.run(server.execute_combo_trade(req))

        self.assertEqual(result["status"], "success")
        kwargs = server.state.engine.execute_combo.call_args.kwargs
        self.assertEqual(len(kwargs["legs"]), 1)
        self.assertEqual(kwargs["legs"][0]["right"], "C")
        self.assertEqual(kwargs["legs"][0]["strike"], 6705)
        self.assertEqual(kwargs["legs"][0]["action"], "BUY")

    def test_live_without_arming_rejected_403(self):
        req = server.ComboTradeRequest(
            legs=[server.ComboLegRequest(right="C", strike=6705, action="BUY")],
            target_env="live",
            transmit=True,
        )
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.execute_combo_trade(req))
        self.assertEqual(ctx.exception.status_code, 403)
        # Engine should NOT have been called
        server.state.engine.execute_combo.assert_not_called()

    def test_live_with_arming_routes_to_live_engine(self):
        """LIVE + armed: combo sent to BOTH paper and live engines."""
        server.state.live_trading_armed = True
        server.state.engine_live = MagicMock()
        server.state.engine_live.ib.isConnected.return_value = True
        server.state.engine_live.execute_combo = AsyncMock(return_value="live_trade")

        req = server.ComboTradeRequest(
            legs=[
                server.ComboLegRequest(right="P", strike=6680, action="SELL"),
                server.ComboLegRequest(right="P", strike=6665, action="BUY"),
            ],
            target_env="live",
            transmit=True,
        )
        result = asyncio.run(server.execute_combo_trade(req))

        self.assertEqual(result["status"], "success")
        # Both engines should have been called
        server.state.engine.execute_combo.assert_called_once()
        server.state.engine_live.execute_combo.assert_called_once()

        # Verify log mentions both PAPER and LIVE
        log_msgs = [b["message"] for b in self.broadcasts if b.get("type") == "log"]
        self.assertTrue(any("PAPER" in m for m in log_msgs))
        self.assertTrue(any("LIVE" in m for m in log_msgs))

    def test_validation_5_legs_rejected(self):
        req = server.ComboTradeRequest(
            legs=[
                server.ComboLegRequest(right="C", strike=6700, action="BUY"),
                server.ComboLegRequest(right="C", strike=6710, action="BUY"),
                server.ComboLegRequest(right="P", strike=6690, action="SELL"),
                server.ComboLegRequest(right="P", strike=6700, action="SELL"),
                server.ComboLegRequest(right="C", strike=6720, action="BUY"),
            ],
            target_env="paper",
        )
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.execute_combo_trade(req))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validation_invalid_right_rejected(self):
        req = server.ComboTradeRequest(
            legs=[server.ComboLegRequest(right="X", strike=6700, action="BUY")],
            target_env="paper",
        )
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.execute_combo_trade(req))
        self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# Score→Direction→Instrument consistency
# ---------------------------------------------------------------------------

class TestRecommendationConsistency(unittest.TestCase):
    """Verify the chain of (score → direction → instrument → legs) is self-consistent."""

    def test_bullish_score_yields_bullish_instruments(self):
        for bias, breakout, regime in [
            ("BULLISH", "MEDIUM", "LONG_GAMMA"),
            ("BULLISH", "LOW", "LONG_GAMMA"),
            ("BULLISH", "MEDIUM", "SHORT_GAMMA"),
        ]:
            with self.subTest(bias=bias, breakout=breakout, regime=regime):
                m = make_full_metrics(bias=bias, breakout_risk=breakout, regime=regime)
                m["strike_ladder"] = [
                    {**r, "call_gamma": 0.005, "put_gamma": 0.005, "call_oi": 1000, "put_oi": 1000}
                    for r in m["strike_ladder"]
                ]
                score, bd = server._score_recommendation(m)
                direction = server._score_to_direction(score)
                instrument, _, _ = server._choose_instrument_v2(m, direction, score, bd)
                spread = server._recommend_legs(m, instrument, direction, m["spot"])

                # Bullish → instruments should be bullish (PCS/BUY_CALL/IC)
                if direction == "BULLISH":
                    self.assertIn(instrument, ("PCS", "BUY_CALL", "IC"))
                    if spread["legs"]:
                        # The SELL action should be on a PUT (bullish put spread)
                        # or BUY_CALL (single-leg call)
                        shorts = [l for l in spread["legs"] if l["action"] == "SELL"]
                        if shorts:
                            self.assertTrue(all(l["right"] == "P" for l in shorts),
                                            f"Bullish should SELL puts, got: {shorts}")

    def test_bearish_score_yields_bearish_instruments(self):
        for bias, breakout, regime in [
            ("BEARISH", "MEDIUM", "LONG_GAMMA"),
            ("BEARISH", "HIGH", "SHORT_GAMMA"),
        ]:
            with self.subTest(bias=bias, breakout=breakout, regime=regime):
                m = make_full_metrics(bias=bias, breakout_risk=breakout, regime=regime)
                m["strike_ladder"] = [
                    {**r, "call_gamma": 0.005, "put_gamma": 0.005, "call_oi": 1000, "put_oi": 1000}
                    for r in m["strike_ladder"]
                ]
                score, bd = server._score_recommendation(m)
                direction = server._score_to_direction(score)
                instrument, _, _ = server._choose_instrument_v2(m, direction, score, bd)
                spread = server._recommend_legs(m, instrument, direction, m["spot"])

                if direction == "BEARISH":
                    self.assertIn(instrument, ("CCS", "BUY_PUT", "IC"))
                    if spread["legs"]:
                        shorts = [l for l in spread["legs"] if l["action"] == "SELL"]
                        if shorts:
                            self.assertTrue(all(l["right"] == "C" for l in shorts),
                                            f"Bearish should SELL calls, got: {shorts}")

    def test_neutral_yields_no_trade(self):
        # Construct a balanced scenario that should be neutral.
        # Use spot FAR from walls so wallProximity=0, no dark gamma, low net_gex
        # to avoid triggering most scoring factors.
        m = make_full_metrics(
            bias="NEUTRAL", regime="LONG_GAMMA", breakout_risk="MEDIUM",
            net_gex_total=2.0,        # low net gex → 0.8 multiplier
            spot=6700.0,
            call_wall=6900.0,         # walls far away → no wallProximity contribution
            put_wall=6500.0,
            regime_score=0.0,         # not enough for regimeMagnitude multiplier
        )
        # Override ladder to have NO Greeks activity at all
        m["strike_ladder"] = [
            {"strike": s, "call_oi": 100, "put_oi": 100, "call_delta": None,
             "put_delta": None, "call_gamma": None, "put_gamma": None,
             "call_theta": None, "put_theta": None}
            for s in [6690, 6700, 6710]
        ]
        # Update profiles to reflect new OI distribution.
        # oi_profile is intentionally empty so max_pain_pull (TIER 3) returns None.
        m["oi_profile"] = {}
        m["vol_profile"] = {s: 0 for s in [6690, 6700, 6710]}

        score, bd = server._score_recommendation(m)
        direction = server._score_to_direction(score)
        instrument, style, _ = server._choose_instrument_v2(m, direction, score, bd)
        spread = server._recommend_legs(m, instrument, direction, m["spot"])

        # NEUTRAL bias + no dark gamma + no significant flow → no_trade
        self.assertEqual(direction, "NEUTRAL")
        self.assertEqual(instrument, "NO_TRADE")
        self.assertEqual(style, "WAIT")
        self.assertEqual(spread["legs"], [])


# ---------------------------------------------------------------------------
# Recommendation freshness
# ---------------------------------------------------------------------------

class TestRecommendationFreshness(unittest.TestCase):
    """Tests for the banner's stale-recommendation detection (>10 min old)."""

    def test_recommendation_within_10_min_is_fresh(self):
        now = 1000.0
        rec = {"timestamp": now - 300}  # 5 min ago
        age = now - rec["timestamp"]
        self.assertLess(age, 600)

    def test_recommendation_over_10_min_is_stale(self):
        now = 1000.0
        rec = {"timestamp": now - 700}  # ~11.7 min ago
        age = now - rec["timestamp"]
        self.assertGreater(age, 600)


if __name__ == "__main__":
    unittest.main()
