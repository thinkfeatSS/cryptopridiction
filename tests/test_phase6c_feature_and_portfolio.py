import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from app.engine.signals.meta_labeler import CoinSpecificMetaLabeler
from app.services.model_retrainer import extract_features_from_records
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestPhase6CFeatureAndPortfolio(unittest.TestCase):
    """
    Targeted Unit Tests for Phase 6C Remediation:
    - Feature parity: 5M in is_scalp, 12H in is_swing (Fix 2.1)
    - Dynamic meme coin set membership from config (Fix 2.2)
    - Cross-desk archetype concentration limits (Fix 5.1)
    """

    def test_dynamic_meme_detection(self):
        """Fix 2.2: Verify coins from MEME_AND_SHITCOIN_BASES are correctly classified as meme."""
        meta_labeler = CoinSpecificMetaLabeler()

        # Non-meme tokens must have is_meme == 0.0
        vec_btc = meta_labeler.build_meta_feature_vector("BTC/USDT", {"conviction": 85.0})
        self.assertEqual(vec_btc["is_meme"].iloc[0], 0.0)

        vec_eth = meta_labeler.build_meta_feature_vector("ETH/USDT", {"conviction": 85.0})
        self.assertEqual(vec_eth["is_meme"].iloc[0], 0.0)

        # Meme tokens from expanded config must have is_meme == 1.0
        vec_pengu = meta_labeler.build_meta_feature_vector("PENGU/USDT", {"conviction": 85.0})
        self.assertEqual(vec_pengu["is_meme"].iloc[0], 1.0)

        vec_neiro = meta_labeler.build_meta_feature_vector("NEIRO/USDT", {"conviction": 85.0})
        self.assertEqual(vec_neiro["is_meme"].iloc[0], 1.0)

        vec_pepe = meta_labeler.build_meta_feature_vector("1000PEPE/USDT", {"conviction": 85.0})
        self.assertEqual(vec_pepe["is_meme"].iloc[0], 1.0)

    def test_feature_extraction_5m_and_12h_parity(self):
        """Fix 2.1: Verify model_retrainer extracts is_scalp=1 for 5M and is_swing=1 for 12H."""
        df_records = pd.DataFrame([
            {
                "symbol": "BTC/USDT",
                "horizon": "5M",
                "status": "CLOSED_TP1",
                "outcome_label": "WON_TP1",
                "entry_price": 60000.0,
                "tp1_price": 61200.0,
                "sl_price": 59400.0,
                "conviction_pct": 85.0
            },
            {
                "symbol": "ETH/USDT",
                "horizon": "12H",
                "status": "CLOSED_TP1",
                "outcome_label": "WON_TP1",
                "entry_price": 3000.0,
                "tp1_price": 3150.0,
                "sl_price": 2900.0,
                "conviction_pct": 88.0
            }
        ])

        feats = extract_features_from_records(df_records)
        self.assertEqual(len(feats), 2)
        # First row (5M) must be scalp
        self.assertEqual(feats["is_scalp"].iloc[0], 1.0)
        self.assertEqual(feats["is_swing"].iloc[0], 0.0)

        # Second row (12H) must be swing
        self.assertEqual(feats["is_scalp"].iloc[1], 0.0)
        self.assertEqual(feats["is_swing"].iloc[1], 1.0)

    def test_cross_desk_archetype_concentration_limit(self):
        """Fix 5.1: Verify paper trading bot strictly blocks a 3rd concurrent position in the same archetype family."""
        bot = PaperTradingBot()

        # Seed with 2 open BREAKOUT positions across different desks
        bot.data["open_positions"] = [
            {
                "trade_id": "POS_1",
                "symbol": "BTC/USDT",
                "desk": "scalp",
                "strategy": "BREAKOUT_LONG",
                "canonical_strategy": "BREAKOUT_LONG",
                "direction": "LONG",
                "entry_price": 60000.0,
                "status": "OPEN"
            },
            {
                "trade_id": "POS_2",
                "symbol": "ETH/USDT",
                "desk": "day",
                "strategy": "BREAKOUT_LONG",
                "canonical_strategy": "BREAKOUT_LONG",
                "direction": "LONG",
                "entry_price": 3000.0,
                "status": "OPEN"
            }
        ]

        # Candidate 3 on swing desk has available slots, but is also in the BREAKOUT family
        cand_signal = {
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "horizon": "24H",
            "strategy": "BREAKOUT_LONG",
            "canonical_strategy": "BREAKOUT_LONG",
            "entry_price": 180.0,
            "tp1_price": 195.0,
            "sl_price": 172.0,
            "conviction": 90.0
        }

        # Must be rejected because same_fam_count is already 2
        admitted = bot.admit_signal(cand_signal)
        self.assertFalse(admitted)


if __name__ == "__main__":
    unittest.main()

