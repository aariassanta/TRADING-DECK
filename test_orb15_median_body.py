"""
Regression for ORB15 median_body population after the ORB window closes.

Bug: body_list filter used `b['total_min'] >= 600`, but 600 min = 10:00 ET.
The ORB window closes at 9:45 ET (bucket 580 is the last ORB bar; bucket 585
is the first post-ORB bar that closes at 9:50 ET). With threshold=600,
the just-closed 9:45-9:50 bar was excluded, so body_list stayed empty until
10:00+ ET — meaning median_body was always None whenever the ORB15 STATUS
card was looked at between 9:45 and 10:00.

Fix: orb_max_total = 585 (first bucket after the ORB window).
"""

import unittest


def _backfill_body_list(bars, orb_max_total):
    """Mirror of the body_list backfill in _orb15_loop."""
    return [
        abs(b['close'] - b['open'])
        for b in bars
        if b['total_min'] >= orb_max_total
        and abs(b['close'] - b['open']) > 0
    ]


def _buckets(opens_highs_lows_closes, total_mins):
    """Helper: build fake bars from lists."""
    bars = []
    for total_min, (o, h, l, c) in zip(total_mins, opens_highs_lows_closes):
        bars.append({
            'open': o, 'high': h, 'low': l, 'close': c,
            'total_min': total_min,
        })
    return bars


class Orb15MedianBodyTest(unittest.TestCase):

    def test_threshold_585_includes_first_post_orb_bar(self):
        # ORB bars (570/575/580 — 9:30/9:35/9:40) have body=10 each.
        # First post-ORB bar (585 — 9:45-9:50 close) has body=8.
        bars = _buckets(
            opens_highs_lows_closes=[
                (100, 105, 99, 110),   # 570 — body 10
                (110, 120, 109, 120),  # 575 — body 10
                (120, 130, 119, 130),  # 580 — body 10
                (130, 138, 129, 138),  # 585 — body 8  <-- this should be in body_list
                (138, 140, 137, 140),  # 590 — body 2 (still filling)
            ],
            total_mins=[570, 575, 580, 585, 590],
        )
        body_list = _backfill_body_list(bars, orb_max_total=585)

        # ORB bars excluded (570/575/580 < 585? No, 580 < 585, so excluded).
        # Wait: 580 < 585 is True → 580 excluded. Correct.
        # 585 included. 590 included.
        self.assertEqual(len(body_list), 2)
        self.assertEqual(body_list, [8, 2])

    def test_old_threshold_600_was_broken(self):
        bars = _buckets(
            opens_highs_lows_closes=[
                (100, 105, 99, 110),
                (110, 120, 109, 120),
                (120, 130, 119, 130),
                (130, 138, 129, 138),
            ],
            total_mins=[570, 575, 580, 585],
        )
        body_list_old = _backfill_body_list(bars, orb_max_total=600)
        self.assertEqual(body_list_old, [], "old threshold excludes the just-closed bar")

    def test_median_computed_with_one_post_orb_bar(self):
        body_list = [8]  # only the 9:45-9:50 bar
        median = float(sorted(body_list)[len(body_list) // 2])
        self.assertEqual(median, 8.0)

    def test_zero_body_bars_excluded(self):
        # Doji (open == close) shouldn't inflate the median.
        bars = _buckets(
            opens_highs_lows_closes=[
                (100, 105, 95, 100),   # 585 — body 0 (doji, filtered out)
                (100, 102, 99, 101),   # 590 — body 1
            ],
            total_mins=[585, 590],
        )
        body_list = _backfill_body_list(bars, orb_max_total=585)
        self.assertEqual(body_list, [1])


if __name__ == "__main__":
    unittest.main()
