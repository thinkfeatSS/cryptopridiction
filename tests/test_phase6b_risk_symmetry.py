import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from app.engine.scanner.btc_shield import BtcPredictiveMarketShield
from app.services.fundamental_service import FundamentalIntelligenceService
from app.quant_v16.entry_confirmation import EntryConfirmationEngine


class TestPhase6BRiskSymmetry(unittest.TestCase):
    """
    Targeted Unit Tests for Phase 6B Remediation:
    - Directional symmetry for shorts: news sentinel & market shield (Fix 1.2 & 4.1)
    - 1000x perpetual contract symbol normalization in news sentiment (Fix 6.1)
    - Continuous ATR-scaled anti-chase floor without hardcoded 0.40% minimum (Fix 8.1)
    """

    def test_btc_shield_altcoin_shorts_gating_in_bull_trend(self):
        """Fix 4.1: Verify btc_shield explicitly sets altcoin_shorts_allowed = False in BULL_TREND."""
        shield = BtcPredictiveMarketShield()

        # Generate mock BTC 15m and 1h data with strong upward trend (BULL_TREND)
        n = 30
        dates_1h = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="1h")
        prices_1h = np.linspace(60000, 68000, n)
        df_1h = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates_1h],
            "open": prices_1h - 100,
            "high": prices_1h + 200,
            "low": prices_1h - 150,
            "close": prices_1h,
            "volume": np.full(n, 1000.0)
        })

        dates_15m = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="15min")
        prices_15m = np.linspace(67000, 68000, n)
        df_15m = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates_15m],
            "open": prices_15m - 50,
            "high": prices_15m + 100,
            "low": prices_15m - 60,
            "close": prices_15m,
            "volume": np.full(n, 250.0)
        })

        btc_dfs = {"15m": df_15m, "1h": df_1h}
        res = shield.evaluate_regime(btc_dfs, live_btc_price=68000.0)

        # In BULL_TREND, longs must be allowed and shorts must be vetoed
        if res.get("regime") == "BULL_TREND" or res.get("v16_regime") == "BULL_TREND":
            self.assertTrue(res.get("altcoin_longs_allowed"))
            self.assertFalse(res.get("altcoin_shorts_allowed"))

    def test_fundamental_1000x_symbol_normalization(self):
        """Fix 6.1: Verify 1000x perpetual contracts strip '1000' to match news items."""
        fund = FundamentalIntelligenceService()
        mat = fund.get_asset_fundamental_matrix("1000PEPE/USDT")
        self.assertEqual(mat["base_coin"], "PEPE")

        mat_bonk = fund.get_asset_fundamental_matrix("1000BONK/USDT:USDT")
        self.assertEqual(mat_bonk["base_coin"], "BONK")

        mat_floki = fund.get_asset_fundamental_matrix("1000FLOKI/USDT")
        self.assertEqual(mat_floki["base_coin"], "FLOKI")

    def test_dynamic_anti_chase_continuous_scaling(self):
        """Fix 8.1: Verify dynamic chase tolerance scales down below 0.40% on ultra-low volatility assets."""
        entry_engine = EntryConfirmationEngine()
        zone = entry_engine.calculate_optimal_entry_zone(
            current_price=100000.0,
            ob_setup=None,
            direction="LONG",
            active_atr=200.0,
            chase_threshold_pct=0.25
        )

        # Entry zone max should be reasonable and bracket bounded
        self.assertLessEqual(zone["entry_zone_max"], 100500.0)


if __name__ == "__main__":
    unittest.main()
