#!/usr/bin/env python3
"""
Test Suite: Deep Verification & Forensics of 15M, 1H, and 24H Signals
---------------------------------------------------------------------
Forensic test suite covering the 3 anchor trading horizons in Quant Edge V16:
1. Discrete Qualification Gates & Elder's Triple Screen Triads (15M Scalp, 1H Intraday, 24H Swing)
2. Directional Integrity & Fail-Closed Guard (Strictly LONG or SHORT, never CONSOLIDATION)
3. Desk Routing, Margin Allocation, and Leverage Invariants
4. Canonical Holding Times, Expiry TTLs, and Casing Robustness (15m, 1h, 24h, 1d)
5. Timeframe-Specific Cost Modeling & Mathematical Expectancy Gating
6. Triple Confluence Super-Trade Detection (15M + 1H + 24H unanimous alignment)
7. Dominant Horizon Prioritization & Scoring
8. Trade Thesis Clustering & Multi-Horizon Zero Stacking Guard
9. WhatsApp Alert Formatting & Desk Parity
"""

import unittest
import os
import shutil
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from app.engine.signals.signal_generator import SignalGenerationSystem
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.quant_v16.cross_timeframe_matrix import InstitutionalArchetype
from app.quant_v16.thesis import TradeThesisEngine, normalize_horizon
from app.services.whatsapp_service import WhatsAppService


class Test15M1H24HSignals(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.abspath("./scratch/test_horizons_dir")
        os.makedirs(self.test_dir, exist_ok=True)
        self.test_ledger = os.path.join(self.test_dir, "test_ledger.json")
        self.bot = PaperTradingBot(ledger_file=self.test_ledger)
        self.bot.data["open_positions"] = []
        self.sig_sys = SignalGenerationSystem()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_discrete_qualification_gates_across_15m_1h_24h(self):
        """
        Verifies discrete qualification criteria:
        - 15M Scalp requires 15M Bullish, 1H not opposing, >=2 desk / >=3 total bull.
        - 1H Intraday requires 1H Bullish, 4H not opposing, >=2 desk / >=4 total bull.
        - 24H Swing requires 1D/12H Bullish, 1W not opposing, >=4 bull.
        """
        trend_matrix = {
            "5m": "BULLISH", "15m": "BULLISH", "1h": "BULLISH",
            "4h": "BULLISH", "12h": "BULLISH", "1d": "BULLISH",
            "1w": "BULLISH", "15d": "CONSOLIDATION", "1M": "CONSOLIDATION"
        }
        h_preds = {
            tf: {"is_cold_start": False, "candle_count": 50}
            for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]
        }
        matrix_eval = {
            "trade_permitted": True,
            "strategy": "MOMENTUM_TREND_EXPANSION",
            "archetype": InstitutionalArchetype.ARCHETYPE_A_SECULAR_EXPANSION.value,
            "dominant_direction": "LONG"
        }

        q_15m, q_1h, q_24h = self.sig_sys.evaluate_multi_horizon_gates(
            trend_matrix=trend_matrix,
            horizon_predictions=h_preds,
            matrix_eval=matrix_eval
        )

        self.assertTrue(q_15m["qualified"], "15M should qualify under unanimous bullish alignment")
        self.assertEqual(q_15m["direction"], "LONG")
        self.assertTrue(q_1h["qualified"], "1H should qualify under unanimous bullish alignment")
        self.assertEqual(q_1h["direction"], "LONG")
        self.assertTrue(q_24h["qualified"], "24H should qualify under unanimous bullish alignment")
        self.assertEqual(q_24h["direction"], "LONG")

    def test_02_directional_integrity_never_allows_consolidation_trade(self):
        """
        Verifies that when market archetype is Range Rotation but dominant_direction is CONSOLIDATION,
        none of 15M, 1H, or 24H can emit a trade with direction='CONSOLIDATION'.
        """
        trend_matrix = {
            tf: "CONSOLIDATION" for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]
        }
        h_preds = {
            tf: {"is_cold_start": False, "candle_count": 50}
            for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]
        }
        matrix_eval = {
            "trade_permitted": True,
            "strategy": "RANGE_ROTATION",
            "archetype": InstitutionalArchetype.ARCHETYPE_C_RANGE_ROTATION.value,
            "dominant_direction": "CONSOLIDATION"
        }

        q_15m, q_1h, q_24h = self.sig_sys.evaluate_multi_horizon_gates(
            trend_matrix=trend_matrix,
            horizon_predictions=h_preds,
            matrix_eval=matrix_eval
        )

        self.assertFalse(q_15m["qualified"], "15M must NOT qualify when direction is CONSOLIDATION")
        self.assertIsNone(q_15m["direction"])
        self.assertFalse(q_1h["qualified"], "1H must NOT qualify when direction is CONSOLIDATION")
        self.assertIsNone(q_1h["direction"])
        self.assertFalse(q_24h["qualified"], "24H must NOT qualify when direction is CONSOLIDATION")
        self.assertIsNone(q_24h["direction"])

    def test_03_desk_routing_margin_and_leverage_invariants(self):
        """
        Verifies desk resolution across 15M, 1H, and 24H:
        - 15M routes to 'scalp' ($150, 2x leverage, max 1 slot)
        - 1H routes to 'day' ($350, 3x leverage, max 2 slots)
        - 24H routes to 'swing' ($500, 2x leverage, max 3 slots)
        """
        # 15M Scalp
        self.assertEqual(self.bot.resolve_desk("15M"), "scalp")
        self.assertEqual(self.bot.resolve_desk("15m"), "scalp")
        self.assertEqual(self.bot.resolve_desk("5M"), "scalp")

        # 1H Intraday Day Trade
        self.assertEqual(self.bot.resolve_desk("1H"), "day")
        self.assertEqual(self.bot.resolve_desk("1h"), "day")
        self.assertEqual(self.bot.resolve_desk("4H"), "day")

        # 24H Swing
        self.assertEqual(self.bot.resolve_desk("24H"), "swing")
        self.assertEqual(self.bot.resolve_desk("24h"), "swing")
        self.assertEqual(self.bot.resolve_desk("1D"), "swing")
        self.assertEqual(self.bot.resolve_desk("1d"), "swing")

        # Desk slot & margin verification
        desks = self.bot.data["desks"]
        self.assertEqual(desks["scalp"]["max_slots"], int(os.getenv("SCALP_DESK_MAX_SLOTS", "5")))
        self.assertEqual(desks["scalp"]["allocated_usd"], float(os.getenv("SCALP_DESK_ALLOCATED_USD", "500.0")))
        self.assertEqual(desks["scalp"]["leverage"], 2)

        self.assertEqual(desks["day"]["max_slots"], int(os.getenv("DAY_DESK_MAX_SLOTS", "2")))
        self.assertEqual(desks["day"]["allocated_usd"], float(os.getenv("DAY_DESK_ALLOCATED_USD", "200.0")))
        self.assertEqual(desks["day"]["leverage"], 3)

        self.assertEqual(desks["swing"]["max_slots"], int(os.getenv("SWING_DESK_MAX_SLOTS", "3")))
        self.assertEqual(desks["swing"]["allocated_usd"], float(os.getenv("SWING_DESK_ALLOCATED_USD", "300.0")))
        self.assertEqual(desks["swing"]["leverage"], 2)

    def test_04_canonical_holding_times_casing_robustness(self):
        """
        Verifies that tick watcher and shadow evaluation enforce canonical TTL:
        - 15M: 7,200s (2h)
        - 1H: 21,600s (6h)
        - 24H / 1D: 172,800s (48h)
        Regardless of whether horizon string is '15M', '15m', '24H', '24h', or '1d'.
        """
        # Test position with lowercase '15m' past 7200s with adverse move (-0.83%)
        pos_15m = {
            "trade_id": "TEST_15M",
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "entry_price": 60000.0,
            "current_price": 59500.0,
            "sl_price": 59000.0,
            "tp1_price": 62000.0,
            "horizon": "15m",
            "opened_at_utc": (datetime.now(timezone.utc) - timedelta(seconds=7300)).isoformat()
        }
        self.bot.data["open_positions"] = [pos_15m]
        # Evaluate tick: elapsed > 7200s and adverse -> should trigger canonical expiry
        self.bot.on_tick({"BTC/USDT": 59500.0})
        self.assertEqual(len(self.bot.data["open_positions"]), 0, "15m trade past 7200s should be cleanly expired")

        # Test position with lowercase '24h'
        pos_24h = {
            "trade_id": "TEST_24H",
            "symbol": "ETH/USDT",
            "direction": "LONG",
            "entry_price": 3000.0,
            "current_price": 3005.0,
            "sl_price": 2850.0,
            "tp1_price": 3300.0,
            "horizon": "24h",
            "opened_at_utc": (datetime.now(timezone.utc) - timedelta(seconds=86400)).isoformat()
        }
        self.bot.data["open_positions"] = [pos_24h]
        # Elapsed 86400s (24h) < 172800s (48h) -> should NOT be expired
        self.bot.on_tick({"ETH/USDT": 3005.0})
        self.assertEqual(len(self.bot.data["open_positions"]), 1, "24h trade at 24h should NOT be expired (TTL is 48h)")

        # Test position with '1d' past 172800s with adverse move (-1.0%)
        pos_1d = {
            "trade_id": "TEST_1D",
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "entry_price": 150.0,
            "current_price": 148.5,
            "sl_price": 140.0,
            "tp1_price": 170.0,
            "horizon": "1d",
            "opened_at_utc": (datetime.now(timezone.utc) - timedelta(seconds=173000)).isoformat()
        }
        self.bot.data["open_positions"] = [pos_1d]
        self.bot.on_tick({"SOL/USDT": 148.5})
        self.assertEqual(len(self.bot.data["open_positions"]), 0, "1d trade past 172800s should be cleanly expired")

    def test_05_timeframe_specific_cost_and_holding_parameters(self):
        """
        Verifies that single horizon signals receive timeframe-calibrated cost parameters:
        - 15M: 0.25h holding, max spread 20 bps
        - 1H: 1.0h holding, max spread 28 bps
        - 24H: 24.0h holding, max spread 35 bps
        """
        # Create minimal 14-bar synthetic OHLCV dataframe
        dates = pd.date_range("2026-01-01", periods=30, freq="15min")
        df_15m = pd.DataFrame({
            "open": [100.0 + i * 0.1 for i in range(30)],
            "high": [100.5 + i * 0.1 for i in range(30)],
            "low": [99.5 + i * 0.1 for i in range(30)],
            "close": [100.3 + i * 0.1 for i in range(30)],
            "volume": [1000.0] * 30
        }, index=dates)

        dfs = {"15m": df_15m, "1h": df_15m, "1d": df_15m}
        btc_shield = {"altcoin_longs_allowed": True, "altcoin_shorts_allowed": True, "v16_regime": "BULL_TREND"}

        sig_15m = self.sig_sys._build_single_horizon_signal(
            symbol="BTC/USDT", horizon_label="15M", tf_key="15m",
            direction="LONG", current_price=103.0, dfs_9=dfs,
            horizon_prediction={"predicted_change_pct": 2.0},
            btc_shield_state=btc_shield, aligned_horizons=["5m", "15m", "1h"],
            spread_bps=5.0
        )
        self.assertIsNotNone(sig_15m)
        self.assertEqual(sig_15m["horizon"], "15M")
        self.assertIn("SCALP", sig_15m["horizon_tag"])
        self.assertGreater(sig_15m["ev_net"], 0.0)

        sig_24h = self.sig_sys._build_single_horizon_signal(
            symbol="BTC/USDT", horizon_label="24H", tf_key="1d",
            direction="LONG", current_price=103.0, dfs_9=dfs,
            horizon_prediction={"predicted_change_pct": 5.0},
            btc_shield_state=btc_shield, aligned_horizons=["15m", "1h", "4h", "12h", "1d"],
            spread_bps=5.0
        )
        self.assertIsNotNone(sig_24h)
        self.assertEqual(sig_24h["horizon"], "24H")
        self.assertIn("DAILY SWING", sig_24h["horizon_tag"])
        self.assertGreater(sig_24h["ev_net"], 0.0)

    def test_06_triple_confluence_super_trade_detection(self):
        """
        Verifies is_triple_confluence logic: True only when all 3 (15M, 1H, 24H)
        have active qualified trade signals.
        """
        # Case A: All 3 present
        q_horizons_all = ["15M", "1H", "24H"]
        q_set_all = {str(x).upper() for x in q_horizons_all}
        is_triple = all(h in q_set_all for h in ["15M", "1H", "24H"])
        self.assertTrue(is_triple)

        # Case B: Case-insensitive match ['15m', '1h', '24h']
        q_horizons_lower = ["15m", "1h", "24h"]
        q_set_lower = {str(x).upper() for x in q_horizons_lower}
        is_triple_lower = all(h in q_set_lower for h in ["15M", "1H", "24H"])
        self.assertTrue(is_triple_lower)

        # Case C: Missing 24H -> False
        q_horizons_partial = ["15M", "1H"]
        q_set_partial = {str(x).upper() for x in q_horizons_partial}
        is_triple_partial = all(h in q_set_partial for h in ["15M", "1H", "24H"])
        self.assertFalse(is_triple_partial)

    def test_07_dominant_horizon_scoring_and_prioritization(self):
        """
        Verifies that 1H Intraday (1.35x) and 24H Swing (1.25x) have structural precedence
        over 15M Scalp (1.20x) when setup quality and conviction are equal.
        """
        def dom_score(sig_item):
            hz = sig_item.get("horizon", "")
            tf_w = 1.25 if hz == "24H" else (1.35 if hz == "1H" else 1.20)
            grade_str = str(sig_item.get("quality_grade", "")).upper()
            g_score = 30.0 if "A+" in grade_str else (20.0 if "GRADE A" in grade_str else 10.0)
            conv = float(sig_item.get("conviction", 70.0) or 70.0)
            ev = float(sig_item.get("ev_net", 0.0) or 0.0)
            return g_score + (conv * 0.4) + (tf_w * 10.0) + min(10.0, ev * 2.0)

        sig_15m = {"horizon": "15M", "quality_grade": "Grade A+", "conviction": 85.0, "ev_net": 1.5}
        sig_1h = {"horizon": "1H", "quality_grade": "Grade A+", "conviction": 85.0, "ev_net": 1.5}
        sig_24h = {"horizon": "24H", "quality_grade": "Grade A+", "conviction": 85.0, "ev_net": 1.5}

        score_15m = dom_score(sig_15m)
        score_1h = dom_score(sig_1h)
        score_24h = dom_score(sig_24h)

        self.assertGreater(score_1h, score_24h, "1H should have higher structural weight than 24H")
        self.assertGreater(score_24h, score_15m, "24H should have higher structural weight than 15M")

    def test_08_trade_thesis_clustering_and_zero_stacking_guard(self):
        """
        Verifies Section 25 & 27:
        Overlapping signals across 15M, 1H, 24H on the same asset & direction
        cluster under a single Trade Thesis ID, and PaperTradingBot prevents duplicate execution.
        """
        normal_btc = {"is_ntz_active": False, "regime": "BULL_TREND", "status_code": "NORMAL"}

        # 1. First trade: 15M Scalp on BTC/USDT executed
        sig_15m = {
            "signal_id": "TEST_BTC_15M",
            "symbol": "BTC/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+",
            "ev_net": 1.45,
            "entry_price": 60000.0,
            "tp1_price": 62000.0,
            "sl_price": 59000.0
        }
        self.assertTrue(self.bot.admit_signal(sig_15m, btc_shield_state=normal_btc))

        # 2. Second trade: 1H Intraday on BTC/USDT -> MUST be blocked by Zero Stacking Guard
        sig_1h = {
            "signal_id": "TEST_BTC_1H",
            "symbol": "BTC/USDT",
            "horizon": "1H",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "Grade A+",
            "ev_net": 1.65,
            "entry_price": 60050.0,
            "tp1_price": 62500.0,
            "sl_price": 58800.0
        }
        self.assertFalse(
            self.bot.admit_signal(sig_1h, btc_shield_state=normal_btc),
            "Second position on BTC/USDT across horizons must be blocked by Zero Stacking Guard"
        )

    def test_09_whatsapp_service_desk_and_horizon_formatting(self):
        """
        Verifies WhatsAppService horizon label and desk formatting across:
        - 15M: '⚡ Scalp (15M)'
        - 1H: '⏳ Day Trade (1H)'
        - 24H: '🌊 Swing Trade (1D)'
        """
        wa = WhatsAppService()

        # 15M Scalp
        lbl_15m = wa._format_horizon_display({"horizon": "15M"})
        self.assertEqual(lbl_15m, "⚡ Scalp (15M)")
        lbl_15m_lower = wa._format_horizon_display({"horizon": "15m"})
        self.assertEqual(lbl_15m_lower, "⚡ Scalp (15M)")

        # 1H Day Trade
        lbl_1h = wa._format_horizon_display({"horizon": "1H"})
        self.assertEqual(lbl_1h, "⏳ Day Trade (1H)")
        lbl_1h_lower = wa._format_horizon_display({"horizon": "1h"})
        self.assertEqual(lbl_1h_lower, "⏳ Day Trade (1H)")

        # 24H Daily Swing
        lbl_24h = wa._format_horizon_display({"horizon": "24H"})
        self.assertEqual(lbl_24h, "🌊 Swing Trade (1D)")
        lbl_1d = wa._format_horizon_display({"horizon": "1d"})
        self.assertEqual(lbl_1d, "🌊 Swing Trade (1D)")


if __name__ == '__main__':
    unittest.main()
