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

if __name__ == '__main__':
    unittest.main()
