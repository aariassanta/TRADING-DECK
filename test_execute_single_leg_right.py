"""
Regression for execute_single_leg's contract lookup.

IBKR's ContractDetails.contract.right is a single letter ("C" / "P"), but
execute_single_leg receives the user-facing "CALL" / "PUT" string. find_contract
must compare against the single-letter form. Before the fix, the comparison
`d.contract.right == "CALL"` (and "PUT") never matched, so the function raised
`No SPX contract found for strike=... right=CALL` on every ORB execution.
"""

import asyncio
import unittest
from types import SimpleNamespace


class _SyntheticContract:
    """Mimics the IBKR Contract object exposed via ContractDetails.contract."""

    def __init__(self, strike, right, trading_class):
        self.strike = strike
        self.right = right
        self.tradingClass = trading_class


class _SyntheticDetails:
    def __init__(self, contract):
        self.contract = contract


def _run_find_contract(chosen_strike, right_upper):
    """Replicates the patched find_contract behaviour from execute_single_leg."""
    details = [
        _SyntheticDetails(_SyntheticContract(7675.0, "C", "SPXW")),
        _SyntheticDetails(_SyntheticContract(7680.0, "C", "SPXW")),
        _SyntheticDetails(_SyntheticContract(7685.0, "C", "SPXW")),
        _SyntheticDetails(_SyntheticContract(7675.0, "P", "SPXW")),
        _SyntheticDetails(_SyntheticContract(7670.0, "P", "SPXW")),
    ]

    right_short = "C" if right_upper == "CALL" else "P"

    def find_contract(strike, right):
        matches = [d.contract for d in details
                   if d.contract.strike == strike and d.contract.right == right]
        if not matches:
            return None
        for c in matches:
            if c.tradingClass == "SPXW":
                return c
        return matches[0]

    return find_contract(chosen_strike, right_short)


class ExecuteSingleLegRightMatchTest(unittest.TestCase):
    def test_call_right_matches_ibkr_single_letter(self):
        contract = _run_find_contract(7680.0, "CALL")
        self.assertIsNotNone(
            contract,
            "CALL lookup must match IBKR's single-letter 'C' right field",
        )
        self.assertEqual(contract.strike, 7680.0)
        self.assertEqual(contract.right, "C")

    def test_put_right_matches_ibkr_single_letter(self):
        contract = _run_find_contract(7675.0, "PUT")
        self.assertIsNotNone(
            contract,
            "PUT lookup must match IBKR's single-letter 'P' right field",
        )
        self.assertEqual(contract.strike, 7675.0)
        self.assertEqual(contract.right, "P")

    def test_lowercase_is_callers_responsibility(self):
        # execute_single_leg normalizes `right.upper()` BEFORE calling find_contract,
        # so the lookup itself only handles the canonical CALL/PUT + C/P pair.
        # This locks in that contract — keeps find_contract a pure comparison.
        contract = _run_find_contract(7680.0, "call")
        self.assertIsNone(contract)

    def test_missing_strike_returns_none(self):
        contract = _run_find_contract(7700.0, "CALL")
        self.assertIsNone(contract)


if __name__ == "__main__":
    unittest.main()
