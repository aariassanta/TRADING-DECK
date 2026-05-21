import sys
import unittest
import math
from engine import IBKREngine

class TestGexZones(unittest.TestCase):
    def setUp(self):
        # We don't need a real IB connection for the static method
        self.engine = IBKREngine()

    def test_classify_zones_neutral(self):
        # Mock data: no GEX
        gex_profile = {}
        oi_profile = {}
        vol_profile = {}
        price = 5800.0
        
        result = IBKREngine._classify_gex_zones(
            gex_profile, oi_profile, vol_profile, price, 
            call_wall=5850, put_wall=5750, gamma_flip=5800
        )
        
        self.assertEqual(result['regime'], "NEUTRAL")
        self.assertEqual(result['bias'], "NEUTRAL")
        self.assertEqual(result['gex_zones'], [])

    def test_classify_zones_long_gamma(self):
        # Mock data: Positive GEX clusters (Stabilizing)
        price = 5800.0
        gex_profile = {
            5810: 100.0,
            5815: 150.0,
            5820: 120.0,
            5790: 80.0,
            5785: 90.0
        }
        oi_profile = {k: 1000 for k in gex_profile}
        vol_profile = {5815: 600} # Confluence at 5815 (600 > 0.5 * 1000)
        
        result = IBKREngine._classify_gex_zones(
            gex_profile, oi_profile, vol_profile, price, 
            call_wall=5815, put_wall=5785, gamma_flip=5750
        )
        
        self.assertEqual(result['regime'], "LONG_GAMMA") # 5800 > 5750 flip
        self.assertEqual(result['bias'], "BULLISH") # Net GEX > 0
        
        # Check zones
        zones = result['gex_zones']
        self.assertTrue(len(zones) >= 1)
        
        fade_zone = next(z for z in zones if z['peak_strike'] == 5815)
        self.assertEqual(fade_zone['type'], "FADE")
        self.assertTrue(fade_zone['confluence'])

    def test_classify_zones_short_gamma_breakout(self):
        # Mock data: Negative GEX cluster near spot (Accelerator)
        price = 5802.0
        gex_profile = {
            5795: -200.0,
            5800: -250.0,
            5805: -210.0,
            5850: 500.0 # Far away positive wall
        }
        oi_profile = {k: 2000 for k in gex_profile}
        vol_profile = {}
        
        result = IBKREngine._classify_gex_zones(
            gex_profile, oi_profile, vol_profile, price, 
            call_wall=5850, put_wall=5700, gamma_flip=5820
        )
        
        self.assertEqual(result['regime'], "SHORT_GAMMA") # 5800 < 5820 flip
        
        # Check zones
        zones = result['gex_zones']
        break_zone = next(z for z in zones if z['peak_strike'] == 5800)
        self.assertEqual(break_zone['type'], "BREAKOUT")
        
        # Check setups
        breakout_setups = result['breakout_setups']
        self.assertTrue(len(breakout_setups) >= 1)
        # Should suggest a directional setup near the breakout zone
        self.assertEqual(breakout_setups[0]['anchor'], 5800)
        self.assertEqual(breakout_setups[0]['tp'], 5850) # Target the next positive wall


class TestIntradayNormalization(unittest.TestCase):
    """Test case for the strike price normalization and aggregation logic."""

    def test_strike_normalization_and_aggregation(self):
        """Verify that _log_intraday_data normalizes strikes to multiples of 5 and aggregates data."""
        import os
        import csv
        import datetime
        from engine import IBKREngine

        engine = IBKREngine()

        # Mock inputs:
        # 5802 -> 5800, 5801 -> 5800 (aggregate)
        # 5803 -> 5805, 5807 -> 5805 (aggregate)
        gex_dict = {
            5802.0: 10.0,
            5803.0: 15.0,
            5807.0: 20.0,
            5801.0: 5.0
        }
        vol_dict = {
            5802.0: 100,
            5803.0: 200,
            5807.0: 300,
            5801.0: 50
        }

        test_expiry = "TEST_NORM_99"

        # Ensure target test file does not exist initially
        today_str = datetime.datetime.now().strftime('%Y%m%d')
        history_dir = os.path.join(os.path.dirname(__file__), 'history')
        test_file = os.path.join(history_dir, f'gex_intraday_{today_str}_{test_expiry}.csv')
        if os.path.exists(test_file):
            os.remove(test_file)

        try:
            # Execute logging of data
            engine._log_intraday_data(5800.0, test_expiry, gex_dict, vol_dict)

            # Verify file exists
            self.assertTrue(os.path.exists(test_file))

            # Read and verify records
            records = []
            with open(test_file, 'r', newline='') as f:
                reader = csv.reader(f)
                headers = next(reader)
                self.assertEqual(headers, ['Timestamp', 'Spot', 'Strike', 'NetGEX', 'Volume'])
                for row in reader:
                    records.append(row)

            # Check that duplicate normalized strikes were correctly aggregated
            # Normalized strikes should be 5800 and 5805
            # For 5800: k=5802 (norm 5800), k=5801 (norm 5800) -> GEX = 10.0 + 5.0 = 15.0, Vol = 100 + 50 = 150
            # For 5805: k=5803 (norm 5805), k=5807 (norm 5805) -> GEX = 15.0 + 20.0 = 35.0, Vol = 200 + 300 = 500
            self.assertEqual(len(records), 2)

            # Verify 5800 record
            rec_5800 = records[0]
            self.assertEqual(int(rec_5800[2]), 5800)
            self.assertAlmostEqual(float(rec_5800[3]), 15.0)
            self.assertEqual(int(rec_5800[4]), 150)

            # Verify 5805 record
            rec_5805 = records[1]
            self.assertEqual(int(rec_5805[2]), 5805)
            self.assertAlmostEqual(float(rec_5805[3]), 35.0)
            self.assertEqual(int(rec_5805[4]), 500)

        finally:
            # Clean up test file
            if os.path.exists(test_file):
                os.remove(test_file)


if __name__ == '__main__':
    unittest.main()
