"""
Regression for ORB15 step transition after bars load.

Hypothesis: the bars-loaded branch (engine.py:1053) populates session_open,
high, low, range, body_list AND sets step='breakout' — all in one block. So
if high/low/range/session_open are populated, step cannot be 'idle'.

This test simulates that branch in isolation to confirm: given bars in the
9:30-9:45 window, after the branch step is 'breakout'.

Run with: ./venv_new/bin/python -m pytest test_orb15_loop_state.py -v
"""

import datetime
import unittest


def _simulate_idle_branch_load(self, bars):
    """Replicates engine.py:1041-1072 verbatim."""
    self.orb15_step = 'idle'
    self.orb15_session_open = None
    self.orb15_high = None
    self.orb15_low = None
    self.orb15_range = None
    self.orb15_body_list = []

    # First-pass filter — only the 9:30-9:45 (570 ≤ min < 600) buckets.
    orb_bars = [b for b in bars if 570 <= b['total_min'] < 600][:3]
    if not orb_bars:
        return False

    self.orb15_session_open = orb_bars[0]['open']
    self.orb15_high = max(b['high'] for b in orb_bars)
    self.orb15_low = min(b['low'] for b in orb_bars)
    self.orb15_range = self.orb15_high - self.orb15_low
    orb_max_total = 585
    self.orb15_body_list = [
        abs(b['close'] - b['open'])
        for b in bars
        if b['total_min'] >= orb_max_total and abs(b['close'] - b['open']) > 0
    ]
    self.orb15_step = 'breakout'
    return True


class Orb15StepTransitionTest(unittest.TestCase):
    def setUp(self):
        self.bot = type('Bot', (), {})()
        self.bot.orb15_step = 'idle'
        self.bot.orb15_session_open = None
        self.bot.orb15_high = None
        self.bot.orb15_low = None
        self.bot.orb15_range = None
        self.bot.orb15_body_list = []

    def _bars(self):
        """9:30, 9:35, 9:40 ORB bars + 9:45-9:50 post-ORB bar."""
        return [
            {'open': 7670.0, 'high': 7685.0, 'low': 7668.0, 'close': 7684.0, 'total_min': 570},
            {'open': 7684.0, 'high': 7690.0, 'low': 7682.0, 'close': 7688.0, 'total_min': 575},
            {'open': 7688.0, 'high': 7695.0, 'low': 7686.0, 'close': 7693.0, 'total_min': 580},
            {'open': 7693.0, 'high': 7700.0, 'low': 7691.0, 'close': 7699.0, 'total_min': 585},
        ]

    def test_all_populated_state_transitions_to_breakout(self):
        ok = _simulate_idle_branch_load(self.bot, self._bars())
        self.assertTrue(ok)
        # Confirms population
        self.assertIsNotNone(self.bot.orb15_session_open)
        self.assertIsNotNone(self.bot.orb15_high)
        self.assertIsNotNone(self.bot.orb15_low)
        self.assertGreater(len(self.bot.orb15_body_list), 0)
        # The transition MUST hold — that's the contract.
        self.assertEqual(self.bot.orb15_step, 'breakout')

    def test_no_orb_bars_keeps_state_at_idle(self):
        """Edge case: bars returned but none in the ORB window — should NOT
        populate state and step stays 'idle'."""
        no_orb = [
            {'open': 7700.0, 'high': 7710.0, 'low': 7699.0, 'close': 7709.0, 'total_min': 600},
            {'open': 7709.0, 'high': 7715.0, 'low': 7708.0, 'close': 7714.0, 'total_min': 605},
        ]
        ok = _simulate_idle_branch_load(self.bot, no_orb)
        self.assertFalse(ok)
        self.assertIsNone(self.bot.orb15_session_open)
        self.assertEqual(self.bot.orb15_step, 'idle')


if __name__ == "__main__":
    unittest.main()
