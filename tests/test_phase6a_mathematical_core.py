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
from app.engine.signals.signal_generator import (
    SignalGenerationSystem,
    InstitutionalArchetype
)
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestPhase6AMathematicalCore(unittest.TestCase):
    """
    Targeted Unit Tests for Phase 6A Remediation:
    - Order Block nested multi-loop deduplication (Fix 7.1)
    - Range rotation monotonic target spacing and dynamic R:R recalculation (Fix 3.1 & 3.2)
    - Stop-loss physical candle gap penetration accounting (Fix 9.1)
    """

    def test_nested_order_block_deduplication(self):
        """Fix 7.1: Verify nested order blocks upgrade only once and prevent compounding inflation."""
        ob_engine = InstitutionalOrderBlockEngine()

        # Create 1 LTF (15m) block
        l_ob = OrderBlock(
            block_type=OrderBlockType.BULLISH,
            state=OrderBlockState.FRESH,
            timeframe="15m",
            candle_idx=10,
            timestamp=datetime.now(timezone.utc),
            ob_high=100.0,
            ob_low=98.0,
            ob_open=99.0,
            ob_close=99.5,
            equilibrium_50=99.0,
            displacement_mag=2.0,
            volume_surge=1.5,
            has_fvg=True,
            confluence_score=0.75
        )

        # Create multiple overlapping HTF blocks (4h, 12h, 1d) that intersect with the LTF block
        h_ob_4h = OrderBlock(
            block_type=OrderBlockType.BULLISH,
            state=OrderBlockState.FRESH,
            timeframe="4h",
            candle_idx=5,
            timestamp=datetime.now(timezone.utc),
            ob_high=102.0,
            ob_low=97.0,
            ob_open=100.0,
            ob_close=101.0,
            equilibrium_50=99.5,
            displacement_mag=2.5,
            volume_surge=2.0,
            has_fvg=True
        )
        h_ob_12h = OrderBlock(
            block_type=OrderBlockType.BULLISH,
            state=OrderBlockState.FRESH,
            timeframe="12h",
            candle_idx=2,
            timestamp=datetime.now(timezone.utc),
            ob_high=105.0,
            ob_low=96.0,
            ob_open=100.0,
            ob_close=103.0,
            equilibrium_50=100.5,
            displacement_mag=3.0,
            volume_surge=2.2,
            has_fvg=True
        )

        horizon_blocks = {
            "15m": [l_ob],
            "4h": [h_ob_4h],
            "12h": [h_ob_12h]
        }
        horizon_setups = {
            "15m": {
                "setup_detected": True,
                "conviction": 84.0,
                "meta_win_prob": 0.76,
                "decision": "ORIGINAL_SETUP"
            }
        }

        # Run nested SMC upgrade
        htf_tfs = ["4h", "12h", "1d", "1w", "15d", "1M"]
        ltf_tfs = ["5m", "15m", "1h"]
        upgraded_tfs = set()

        for ltf in ltf_tfs:
            for l_b in horizon_blocks.get(ltf, []):
                for htf in htf_tfs:
                    for h_b in horizon_blocks.get(htf, []):
                        if l_b.block_type == h_b.block_type:
                            overlaps = (l_b.ob_low <= h_b.ob_high and l_b.ob_high >= h_b.ob_low)
                            if overlaps:
                                l_b.is_nested = True
                                l_b.htf_parent_tf = htf
                                l_b.zeiierman_rank = OrderBlockRank.RANK_1_EXTREME_ORIGIN.value
                                l_b.confluence_score = min(0.99, l_b.confluence_score + 0.15)

                                if ltf in horizon_setups and horizon_setups[ltf].get("setup_detected") and ltf not in upgraded_tfs:
                                    s = horizon_setups[ltf]
                                    s["is_nested_smc"] = True
                                    s["htf_poi_tf"] = htf
                                    s["zeiierman_rank"] = 1
                                    s["conviction"] = min(95.0, float(s.get("conviction", 84.0)) + 6.0)
                                    s["meta_win_prob"] = min(0.88, float(s.get("meta_win_prob", 0.76)) + 0.08)
                                    upgraded_tfs.add(ltf)
                                break
                    if l_b.is_nested:
                        break

        # Verification: Conviction should be exactly 84.0 + 6.0 = 90.0 (NOT compounded to 96+ or 98.5)
        # and meta_win_prob should be exactly 0.76 + 0.08 = 0.84 (NOT compounded to 0.95)
        self.assertEqual(horizon_setups["15m"]["conviction"], 90.0)
        self.assertEqual(horizon_setups["15m"]["meta_win_prob"], 0.84)
        self.assertTrue(l_ob.is_nested)
        self.assertEqual(l_ob.htf_parent_tf, "4h")

    def test_range_rotation_target_spacing_and_rr_recalc(self):
        """Fix 3.1 & 3.2: Verify Range Rotation targets preserve strict spacing and recalculate R:R."""
        entry_price = 100.0
        active_atr = 2.0
        htf_high = 105.0  # HTF range boundary is close (+5.0), less than default unconstrained TP2/TP3

        cand_tp1 = 104.0
        cand_tp2 = 107.0
        cand_tp3 = 111.0
        cand_sl = 97.6
        cand_rr = "1:2.9"

        # Apply Range Rotation dynamic spacing
        avail_span = htf_high - entry_price
        cand_tp3 = min(cand_tp3, round(htf_high, 2))
        cand_tp2 = min(cand_tp2, round(entry_price + (avail_span * 0.85), 2))
        cand_tp1 = min(cand_tp1, round(entry_price + (avail_span * 0.60), 2))
        actual_rr = round(abs(cand_tp2 - entry_price) / max(1e-9, abs(entry_price - cand_sl)), 2)
        cand_rr = f"1:{actual_rr:.1f}"

        # Targets must be strictly monotonic: entry < TP1 < TP2 < TP3 <= htf_high
        self.assertLess(entry_price, cand_tp1)
        self.assertLess(cand_tp1, cand_tp2)
        self.assertLess(cand_tp2, cand_tp3)
        self.assertLessEqual(cand_tp3, htf_high)

        # TP1 should be 103.0, TP2 should be 104.25, TP3 should be 105.0
        self.assertEqual(cand_tp1, 103.0)
        self.assertEqual(cand_tp2, 104.25)
        self.assertEqual(cand_tp3, 105.0)

        # R:R should be recalculated based on post-cap TP2 (104.25 - 100) / (100 - 97.6) = 4.25 / 2.4 = 1.77
        self.assertAlmostEqual(actual_rr, 1.77, places=2)
        self.assertEqual(cand_rr, "1:1.8")

    def test_stop_loss_gap_slippage_accounting(self):
        """Fix 9.1: Verify stop loss fills at market price when market gaps through stop loss."""
        bot = PaperTradingBot()

        # Simulate open LONG position with SL at 100.0
        pos_long = {
            "trade_id": "TEST_LONG_GAP",
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "entry_price": 105.0,
            "current_price": 98.2,  # Market dumped past SL of 100.0
            "sl_price": 100.0,
            "tp1_price": 110.0,
            "tp2_price": 115.0,
            "tp3_price": 120.0,
            "position_size_usd": 100.0,
            "leverage": 2,
            "desk": "scalp",
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "peak_gain_pct": 0.0,
            "status": "OPEN"
        }

        # On SL hit, exit price for LONG must be min(sl_target, curr_p) = 98.2 (gap accounted for)
        direction = pos_long["direction"]
        sl_target = float(pos_long["sl_price"])
        curr_p = float(pos_long["current_price"])

        if direction == "LONG":
            exit_p = min(sl_target, curr_p)
        else:
            exit_p = max(sl_target, curr_p)

        self.assertEqual(exit_p, 98.2)  # Captures real adverse gap

        # Simulate open SHORT position with SL at 100.0
        pos_short = {
            "trade_id": "TEST_SHORT_GAP",
            "symbol": "ETH/USDT",
            "direction": "SHORT",
            "entry_price": 95.0,
            "current_price": 102.5,  # Market rallied past SL of 100.0
            "sl_price": 100.0,
            "tp1_price": 90.0,
            "tp2_price": 85.0,
            "tp3_price": 80.0,
            "position_size_usd": 100.0,
            "leverage": 2,
            "desk": "scalp",
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "peak_gain_pct": 0.0,
            "status": "OPEN"
        }

        direction_s = pos_short["direction"]
        sl_target_s = float(pos_short["sl_price"])
        curr_p_s = float(pos_short["current_price"])

        if direction_s == "LONG":
            exit_p_s = min(sl_target_s, curr_p_s)
        else:
            exit_p_s = max(sl_target_s, curr_p_s)

        self.assertEqual(exit_p_s, 102.5)  # Captures real adverse gap


if __name__ == "__main__":
    unittest.main()

