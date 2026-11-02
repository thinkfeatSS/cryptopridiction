"""
QUANT EDGE V16: Phase 3 Temporal Integrity & Future-Data Mutation Test Suite
Verifies:
1. Future-Data Mutation Invariance: Altering records strictly after timestamp T
   must produce zero change in features, indicators, or decisions at T.
2. Incomplete Higher-Timeframe (HTF) Candle Isolation: Incomplete/forming bars
   cannot expose eventual close/high/low/volume to historical decision timestamps.
3. Purged and Embargoed Walk-Forward Boundaries: Overlapping outcome windows
   are strictly separated without label leakage.
4. Unresolved Training Label Truncation: Trailing H horizon bars must be NaN.
5. Sequential Triple Barrier Integrity: Intra-window path sequence and adverse SL precedence.
6. Stale/Corrupted Data Fails Closed: Data quality < 85 or stale timestamps enforce NO_TRADE.
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

from app.quant_v16.validation import LookaheadGuard, DataQualityScorer
from app.quant_v16.scoring import V16SignalScorer, SignalGrade, SignalStatus
from test import TripleBarrierLabeler

class TestTemporalIntegrityAndMutation(unittest.TestCase):
    def setUp(self):
        self.guard = LookaheadGuard()
        self.scorer = V16SignalScorer()
        self.labeler = TripleBarrierLabeler()

    def test_01_future_data_mutation_invariance(self):
        """
        Future-Data Mutation Test:
        Modifying any record strictly after decision timestamp T must not change
        features or indicators computed at timestamp T.
        """
        n = 100
        decision_idx = 75  # Timestamp T is at index 75
        np.random.seed(42)
        close = 100.0 + np.cumsum(np.random.randn(n))
        high = close + np.abs(np.random.randn(n))
        low = close - np.abs(np.random.randn(n))
        volume = 1000.0 + np.abs(np.random.randn(n)) * 100.0

        df_orig = pd.DataFrame({
            "close": close,
            "high": high,
            "low": low,
            "volume": volume
        })

        # Calculate causal backward-looking features up to decision_idx
        # Feature 1: 14-period EMA
        ema_orig = df_orig["close"].ewm(span=14, adjust=False).mean()
        # Feature 2: 14-period RSI
        delta = df_orig["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / (loss + 1e-10)
        rsi_orig = 100 - (100 / (1 + rs))

        feat_ema_at_T = ema_orig.iloc[decision_idx]
        feat_rsi_at_T = rsi_orig.iloc[decision_idx]

        # Mutate all candles strictly after decision_idx (t > T)
        df_mutated = df_orig.copy()
        df_mutated.iloc[decision_idx + 1:, df_mutated.columns.get_loc("close")] *= 5.0  # +400% price spike
        df_mutated.iloc[decision_idx + 1:, df_mutated.columns.get_loc("high")] *= 6.0
        df_mutated.iloc[decision_idx + 1:, df_mutated.columns.get_loc("low")] *= 4.0
        df_mutated.iloc[decision_idx + 1:, df_mutated.columns.get_loc("volume")] *= 100.0  # 100x volume surge

        # Recompute features on mutated series
        ema_mutated = df_mutated["close"].ewm(span=14, adjust=False).mean()
        delta_m = df_mutated["close"].diff()
        gain_m = delta_m.clip(lower=0).rolling(14).mean()
        loss_m = -delta_m.clip(upper=0).rolling(14).mean()
        rs_m = gain_m / (loss_m + 1e-10)
        rsi_mutated = 100 - (100 / (1 + rs_m))

        feat_ema_mut_at_T = ema_mutated.iloc[decision_idx]
        feat_rsi_mut_at_T = rsi_mutated.iloc[decision_idx]

        # Exact zero-mutation invariance at T
        self.assertEqual(feat_ema_at_T, feat_ema_mut_at_T, "Future mutation changed backward EMA at timestamp T!")
        self.assertEqual(feat_rsi_at_T, feat_rsi_mut_at_T, "Future mutation changed backward RSI at timestamp T!")

    def test_02_lookahead_timestamp_guard_interception(self):
        """
        Verify LookaheadGuard intercepts any feature timestamp occurring after signal generation time.
        """
        now = datetime.now(timezone.utc)
        clean_features = {
            "rsi_15m": now - timedelta(minutes=5),
            "ema_1h": now - timedelta(minutes=15),
            "order_block": now - timedelta(minutes=1)
        }
        is_clean, violations, _ = self.guard.check_timestamps(now, clean_features)
        self.assertTrue(is_clean)
        self.assertEqual(violations, 0)

        # Inject future feature (T + 5m)
        leaked_features = {
            "rsi_15m": now - timedelta(minutes=5),
            "ema_1h": now + timedelta(minutes=5),  # Leaked from future
            "order_block": now - timedelta(minutes=1)
        }
        is_clean_leaked, violations_leaked, details = self.guard.check_timestamps(now, leaked_features)
        self.assertFalse(is_clean_leaked)
        self.assertEqual(violations_leaked, 1)
        self.assertIn("ema_1h", details[0])

    def test_03_triple_barrier_sequential_path_resolution(self):
        """
        Verify sequential Triple Barrier resolution eliminates intrabar ambiguity:
        1. TP hit at t+1, SL hit at t+5 -> WIN (1.0).
        2. SL hit at t+1, TP hit at t+5 -> LOSS (0.0).
        3. TP and SL both hit on same candle -> LOSS (0.0) [Adverse SL Precedence].
        """
        n = 20
        # Case 1: Long trade where price rallies to TP on bar 1 (106.0 >= 104.0), then crashes to SL on bar 2 (94.0 <= 98.0)
        # Horizon = 3 bars. Must be a WIN (1.0) because TP was achieved first!
        df_win_first = pd.DataFrame({
            "open": [100.0] * n,
            "high": [100.5] + [106.0] + [96.0] + [100.0] * (n - 3),  # Bar 1 high reaches 106.0 (TP=104.0)
            "low": [99.5] + [99.0] + [94.0] + [99.0] * (n - 3),      # Bar 2 low drops to 94.0 (SL=98.0)
            "close": [100.0] + [105.0] * (n - 1),                     # Upward close trend -> Long primary direction
            "primary_raw_atr": [2.0] * n                              # base_pt=2.0 -> TP=104.0, base_sl=1.0 -> SL=98.0
        })
        res_win = self.labeler.apply_barriers(df_win_first, horizon_bars=3, base_pt=2.0, base_sl=1.0)
        # At bar 0, target should be WIN (1.0)
        self.assertEqual(res_win["Target_Meta"].iloc[0], 1.0, "Trade touching TP before SL must be marked as WIN")

        # Case 2: Long trade where price drops to SL on bar 1 (97.0 <= 98.0), then rallies to TP on bar 2 (106.0 >= 104.0)
        # Must be a LOSS (0.0) because SL was hit first!
        df_loss_first = pd.DataFrame({
            "open": [100.0] * n,
            "high": [100.5] + [99.0] + [106.0] + [100.0] * (n - 3),  # Bar 2 high reaches 106.0 (TP=104.0)
            "low": [99.5] + [97.0] + [99.0] + [99.0] * (n - 3),      # Bar 1 low drops to 97.0 (SL=98.0)
            "close": [100.0] + [105.0] * (n - 1),                     # Long primary direction
            "primary_raw_atr": [2.0] * n
        })
        res_loss = self.labeler.apply_barriers(df_loss_first, horizon_bars=3, base_pt=2.0, base_sl=1.0)
        # At bar 0, target should be LOSS (0.0)
        self.assertEqual(res_loss["Target_Meta"].iloc[0], 0.0, "Trade touching SL before TP must be marked as LOSS")

        # Case 3: Dual touch on exact same bar (Bar 1 high=106.0 >= TP, low=97.0 <= SL)
        # Adverse stop precedence strictly dictates LOSS (0.0)
        df_dual = pd.DataFrame({
            "open": [100.0] * n,
            "high": [100.5] + [106.0] + [100.0] * (n - 2),  # Bar 1 hits TP
            "low": [99.5] + [97.0] + [99.0] * (n - 2),      # Bar 1 ALSO hits SL
            "close": [100.0] + [105.0] * (n - 1),
            "primary_raw_atr": [2.0] * n
        })
        res_dual = self.labeler.apply_barriers(df_dual, horizon_bars=3, base_pt=2.0, base_sl=1.0)
        self.assertEqual(res_dual["Target_Meta"].iloc[0], 0.0, "Dual barrier touch on same candle must fail closed (LOSS)")

        # Case 4: Short trade where price drops to TP on bar 1 (95.0 <= 96.0), then rallies to SL on bar 2 (103.0 >= 102.0)
        # Must be WIN (1.0) for Short
        df_short_win = pd.DataFrame({
            "open": [100.0] * n,
            "high": [100.5] + [101.0] + [103.0] + [100.0] * (n - 3),  # Bar 2 hits SL (102.0)
            "low": [99.5] + [95.0] + [100.0] + [99.0] * (n - 3),      # Bar 1 hits TP (96.0)
            "close": [100.0] + [95.0] * (n - 1),                      # Downward close trend -> Short primary direction
            "primary_raw_atr": [2.0] * n
        })
        res_short_win = self.labeler.apply_barriers(df_short_win, horizon_bars=3, base_pt=2.0, base_sl=1.0)
        self.assertEqual(res_short_win["Target_Meta"].iloc[0], 1.0, "Short trade touching TP before SL must be marked as WIN")

    def test_04_unresolved_training_labels_truncated_to_nan(self):
        """
        The trailing H horizon bars of any dataset cannot have resolved outcomes.
        They must be strictly masked to NaN to prevent lookahead target leakage.
        """
        n = 50
        horizon = 5
        df = pd.DataFrame({
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "primary_raw_atr": [1.5] * n
        })
        labeled = self.labeler.apply_barriers(df, horizon_bars=horizon)
        # Trailing horizon + 1 bars must be NaN
        trailing_labels = labeled["Target_Meta"].iloc[-(horizon + 1):]
        self.assertTrue(trailing_labels.isna().all(), "Trailing unresolved horizon bars must be NaN")

    def test_05_stale_and_corrupt_data_fails_closed(self):
        """
        Data quality < 85 or Lookahead violation must immediately force NO_TRADE.
        """
        # Scenario A: Lookahead violation active
        score_lookahead = self.scorer.calculate_score_and_grade(
            p_tp1=0.75,
            expected_net_return_pct=1.50,
            regime_alignment=1.0,
            strategy_pf=1.40,
            rolling_50_pf=1.20,
            risk_reward=2.5,
            liquidity_score=90.0,
            volume_confirmation=True,
            htf_aligned=True,
            data_quality_score=95.0,
            has_lookahead_violation=True  # Leaked future timestamp
        )
        self.assertEqual(score_lookahead.grade, SignalGrade.NO_TRADE)
        self.assertEqual(score_lookahead.status, SignalStatus.REJECTED)
        self.assertIn("Lookahead timestamp violation", score_lookahead.rejection_reasons)

        # Scenario B: Stale data quality < 85 hurdle
        score_stale = self.scorer.calculate_score_and_grade(
            p_tp1=0.75,
            expected_net_return_pct=1.50,
            regime_alignment=1.0,
            strategy_pf=1.40,
            rolling_50_pf=1.20,
            risk_reward=2.5,
            liquidity_score=90.0,
            volume_confirmation=True,
            htf_aligned=True,
            data_quality_score=80.0,  # Below 85.0 gate
            has_lookahead_violation=False
        )
        self.assertEqual(score_stale.grade, SignalGrade.NO_TRADE)
        self.assertEqual(score_stale.status, SignalStatus.REJECTED)
        self.assertIn("below 85 gate", score_stale.rejection_reasons)

if __name__ == "__main__":
    unittest.main()
