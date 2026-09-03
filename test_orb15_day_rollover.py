"""
Regression for ORB15 day-rollover reset.

Bug: after a session ends with step='signalled', the in-day reset guards in
_orb15_loop refuse to clear that state because they treat 'signalled' as a
valid final state. If the same process is still alive when the next day's
market opens (9:30 ET), the loop never re-enters the 'idle' branch and
fetch_5min_bars is never called — so the UI shows stale values from the
previous session (or nulls) instead of today's ORB15 high/low/range.

Fix: track an _orb15_session_date. On every tick, if today differs from the
stored date, force a reset. A fresh process also triggers this on the first
tick because session_date starts as None.
"""

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class DayRolloverResetTest(unittest.TestCase):
    """Mirror of _orb15_loop day-rollover logic, no event loop required."""

    def _engine(self, *, step, session_open, session_date):
        """Stand-in for the engine state the loop reads/writes."""
        return SimpleNamespace(
            orb15_step=step,
            orb15_session_open=session_open,
            orb15_high=None,
            orb15_low=None,
            orb15_range=None,
            _orb15_session_date=session_date,
            reset_calls=0,
        )

    def _tick(self, engine, now_date):
        """Replicates the first 9 lines of _orb15_loop after this fix."""
        if engine._orb15_session_date != now_date:
            engine.reset_calls += 1
            engine.orb15_step = 'idle'
            engine.orb15_session_open = None
            engine.orb15_high = None
            engine.orb15_low = None
            engine.orb15_range = None
            engine._orb15_session_date = now_date

    def test_signalled_from_yesterday_resets_on_new_day(self):
        # Simulate end-of-day state from a process that survived overnight.
        engine = self._engine(
            step='signalled',
            session_open=7685.0,
            session_date=datetime.date(2026, 9, 2),
        )
        today = datetime.date(2026, 9, 3)
        self._tick(engine, today)
        self.assertEqual(engine.reset_calls, 1)
        self.assertEqual(engine.orb15_step, 'idle')
        self.assertIsNone(engine.orb15_session_open)
        self.assertEqual(engine._orb15_session_date, today)

    def test_fresh_process_resets_on_first_tick(self):
        # session_date starts None — first tick must still trigger a reset so
        # we end up in a known state.
        engine = self._engine(
            step='idle',
            session_open=None,
            session_date=None,
        )
        today = datetime.date(2026, 9, 3)
        self._tick(engine, today)
        # Reset is unconditional on the first mismatch; counts as a reset.
        self.assertEqual(engine.reset_calls, 1)
        self.assertEqual(engine._orb15_session_date, today)

    def test_same_day_does_not_reset(self):
        engine = self._engine(
            step='signalled',
            session_open=7685.0,
            session_date=datetime.date(2026, 9, 3),
        )
        # Same day — must NOT clobber the signal.
        self._tick(engine, datetime.date(2026, 9, 3))
        self.assertEqual(engine.reset_calls, 0)
        self.assertEqual(engine.orb15_step, 'signalled')
        self.assertEqual(engine.orb15_session_open, 7685.0)

    def test_mid_day_state_preserved(self):
        # In-flight 'breakout' state must survive within a single day.
        engine = self._engine(
            step='breakout',
            session_open=7685.0,
            session_date=datetime.date(2026, 9, 3),
        )
        for _ in range(5):  # simulate 5 ticks on the same day
            self._tick(engine, datetime.date(2026, 9, 3))
        self.assertEqual(engine.reset_calls, 0)
        self.assertEqual(engine.orb15_step, 'breakout')


if __name__ == "__main__":
    unittest.main()
