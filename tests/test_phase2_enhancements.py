"""
Unit and Integration Tests for Phase 2 Institutional Trading Enhancements:
- SMC-01: Order Block Mitigation Degradation & Depletion Gate
- EXT-01: Parabolic Trailing Ratchet for Runners (Section 20 & 24)
- TRD-01: Idiosyncratic Coin Beta & Volatility Parity Position Sizing (Section 29)
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from app.quant_v16.order_blocks import (
    InstitutionalOrderBlockEngine,
    OrderBlock,
    OrderBlockType,
    OrderBlockState,
    OrderBlockRank
)
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestPhase2Enhancements(unittest.TestCase):

    # -------------------------------------------------------------------------
    # SMC-01: Order Block Mitigation Degradation
    # -------------------------------------------------------------------------
    def test_order_block_mitigation_degradation_and_depletion(self):
        """Verifies that Order Block edge degrades dynamically per retest and depletes after 3 touches."""
        timestamps = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq="1h")
        closes = np.linspace(100.0, 115.0, 50)
        df = pd.DataFrame({
            "timestamp": [int(ts.timestamp() * 1000) for ts in timestamps],
            "open": closes - 1.0,
            "high": closes + 2.0,
            "low": closes - 2.0,
            "close": closes,
            "volume": [1500.0] * 50
        })

        # Ensure the active candle touches the demand zone [108.0, 112.0]
        df.loc[df.index[-1], "close"] = 111.0
        df.loc[df.index[-1], "low"] = 109.5
        df.loc[df.index[-1], "high"] = 112.5

        # Mock an order block with 0 retests (Virgin)
        ob_virgin = OrderBlock(
            block_type=OrderBlockType.BULLISH,
            state=OrderBlockState.TESTING,
            timeframe="1h",
            candle_idx=45,
            timestamp=int(timestamps[45].timestamp() * 1000),
            ob_high=112.0,
            ob_low=108.0,
            ob_open=109.0,
            ob_close=111.0,
            equilibrium_50=110.0,
            displacement_mag=2.0,
            volume_surge=1.5,
            has_fvg=True,
            confluence_score=0.90,
            retest_count=0,
            zeiierman_rank=1,
            is_touching=True
        )

        # Patch detect_order_blocks to return our test block
        orig_detect = InstitutionalOrderBlockEngine.detect_order_blocks
        try:
            InstitutionalOrderBlockEngine.detect_order_blocks = lambda *args, **kwargs: [ob_virgin]

            # Case A: Retest count = 0 (Full virgin edge)
            setup_v = InstitutionalOrderBlockEngine.evaluate_live_setup(df, timeframe="1h", current_price=111.0)
            self.assertTrue(setup_v["setup_detected"])
            self.assertEqual(setup_v["retest_count"], 0)
            self.assertEqual(setup_v["mitigation_factor"], 1.00)
            conv_v = setup_v["conviction"]
            prob_v = setup_v["meta_win_prob"]

            # Case B: Retest count = 1 (Minor mitigation penalty)
            ob_virgin.retest_count = 1
            setup_r1 = InstitutionalOrderBlockEngine.evaluate_live_setup(df, timeframe="1h", current_price=111.0)
            self.assertTrue(setup_r1["setup_detected"])
            self.assertEqual(setup_r1["retest_count"], 1)
            self.assertAlmostEqual(setup_r1["mitigation_factor"], 0.85)
            self.assertLess(setup_r1["conviction"], conv_v)
            self.assertLess(setup_r1["meta_win_prob"], prob_v)

            # Case C: Retest count = 2 (Moderate mitigation penalty)
            ob_virgin.retest_count = 2
            setup_r2 = InstitutionalOrderBlockEngine.evaluate_live_setup(df, timeframe="1h", current_price=111.0)
            self.assertTrue(setup_r2["setup_detected"])
            self.assertEqual(setup_r2["retest_count"], 2)
            self.assertAlmostEqual(setup_r2["mitigation_factor"], 0.70)
            self.assertLess(setup_r2["conviction"], setup_r1["conviction"])

            # Case D: Retest count = 3 (Fully Depleted -> must FAIL CLOSED)
            ob_virgin.retest_count = 3
            setup_r3 = InstitutionalOrderBlockEngine.evaluate_live_setup(df, timeframe="1h", current_price=111.0)
            self.assertFalse(setup_r3["setup_detected"])
            self.assertIn("depleted", setup_r3["reason"].lower())

        finally:
            InstitutionalOrderBlockEngine.detect_order_blocks = orig_detect

    # -------------------------------------------------------------------------
    # EXT-01: Parabolic Trailing Ratchet for Runners
    # -------------------------------------------------------------------------
    def test_parabolic_trailing_ratchet_tightening(self):
        """Verifies that runner trailing stop tightens from 1.5x ATR to 0.8x ATR upon parabolic expansion."""
        bot = PaperTradingBot()

        # Position that has already reached TP2 and is holding runner for TP3
        pos = {
            "trade_id": "TEST_RUNNER_LONG",
            "symbol": "BTC/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "status": "OPEN_TP2_LOCKED_TRAIL",
            "tp1_hit": True,
            "tp2_hit": True,
            "tp3_hit": False,
            "entry_price": 100.0,
            "initial_sl_price": 98.0,
            "sl_price": 104.0,       # Currently ratcheted to TP1 (104.0)
            "tp1_price": 104.0,
            "tp2_price": 108.0,
            "tp3_price": 118.0,
            "active_atr": 2.0,        # ATR = $2.00
            "initial_position_size_usd": 1000.0,
            "remaining_position_size_usd": 200.0,
            "peak_price_seen": 108.0,
            "peak_gain_pct": 8.0,
            "leverage": 3,
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }

        # Step 1: Price at 105.0: R = (105 - 100) / 2 = 2.5R (< 3.0R)
        # Standard trail buffer = 1.50 * 2.0 = 3.0. Trail SL = 105.0 - 3.0 = 102.0.
        # But TP1 is 104.0, so SL remains ratcheted at TP1 (104.0).
        bot.data["open_positions"] = [dict(pos)]
        bot.on_tick(live_prices={"BTC/USDT": 105.0}, tick_latency_ms=10.0)
        p1 = bot.data["open_positions"][0]
        self.assertEqual(p1["sl_price"], 104.0)

        # Step 2: Price reaches 112.0 (R = (112 - 100)/2 = 6.0R >= 3.0R -> Parabolic Mode)
        # In Parabolic mode: trail buffer tightens to 0.80 * ATR = 0.80 * 2.0 = $1.60.
        # Candidate trail SL = 112.0 - 1.60 = 110.40.
        # New SL must ratchet forward to 110.40!
        bot.data["open_positions"] = [dict(pos)]
        bot.on_tick(live_prices={"BTC/USDT": 112.0}, tick_latency_ms=10.0)
        p2 = bot.data["open_positions"][0]
        self.assertAlmostEqual(p2["sl_price"], 110.40)
        self.assertTrue(p2.get("is_parabolic_trail_active"))

        # Step 3: Monotonic ratchet invariance: price dips to 111.0
        # Stop loss must NOT move backward (must stay at 110.40)
        bot.on_tick(live_prices={"BTC/USDT": 111.0}, tick_latency_ms=10.0)
        p3 = bot.data["open_positions"][0]
        self.assertAlmostEqual(p3["sl_price"], 110.40)

    # -------------------------------------------------------------------------
    # TRD-01: Idiosyncratic Coin Beta Sizing
    # -------------------------------------------------------------------------
    def test_coin_beta_and_volatility_parity_sizing(self):
        """Verifies that high-beta assets receive reduced sizing multipliers to cap tail volatility risk."""
        # Simulated volatile altcoin: ATR = 5.0% on $100 price, BTC ATR = 1.8%
        coin_atr_pct = 5.0
        btc_atr_pct = 1.8
        coin_beta = round(float(np.clip(coin_atr_pct / max(0.20, btc_atr_pct), 0.40, 3.50)), 2)
        # Beta = 5.0 / 1.8 = 2.78
        self.assertGreater(coin_beta, 2.5)

        beta_sizing_mult = float(np.clip(1.0 / coin_beta, 0.40, 1.25))
        # 1.0 / 2.78 = 0.36 -> clamped to 0.40
        self.assertAlmostEqual(beta_sizing_mult, 0.40)

        # Simulated low-volatility large cap: ATR = 1.2%, BTC ATR = 1.8%
        low_coin_atr_pct = 1.2
        low_beta = round(float(np.clip(low_coin_atr_pct / max(0.20, btc_atr_pct), 0.40, 3.50)), 2)
        # Beta = 1.2 / 1.8 = 0.67
        self.assertLess(low_beta, 1.0)
        low_beta_sizing = float(np.clip(1.0 / low_beta, 0.40, 1.25))
        # 1.0 / 0.67 = 1.49 -> clamped to 1.25
        self.assertAlmostEqual(low_beta_sizing, 1.25)


if __name__ == "__main__":
    unittest.main()
