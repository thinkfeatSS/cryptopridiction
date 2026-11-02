"""
QUANT EDGE V16: Phase 5 Trade Lifecycle, Shadow Tracking & Exit Compaction Test Suite
Covers:
- Feature 5.1: Shadow Tracking Mode for Paused Strategies (Resolving Cold-Lock)
- Feature 5.2: Dynamic Time-Decay Take-Profit Compaction
- Feature 5.3: Live Horizon-Specific Brier Score & Reliability Metrics Streaming
"""

import unittest
import os
import json
import time
import math
from datetime import datetime, timezone, timedelta

from app.quant_v16.strategies import StrategyRegistry, StrategyArchetype, StrategyStatus, StrategyPerformance
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.config import settings


class TestPhase5TradeLifecycle(unittest.TestCase):

    def setUp(self):
        self.test_export_dir = os.path.join(".", "scratch", "test_phase5_dir")
        os.makedirs(self.test_export_dir, exist_ok=True)
        self.ledger_file = os.path.join(self.test_export_dir, "test_paper_ledger.json")
        self.priors_file = os.path.join(self.test_export_dir, "test_strategy_priors.json")

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_export_dir):
            try:
                shutil.rmtree(self.test_export_dir)
            except Exception:
                pass

    def test_feature_5_1_strategy_shadow_tracking_and_auto_unpause(self):
        """
        AC-P5-01: Verifies that when a strategy is PAUSED:
        1. is_strategy_shadow_eligible() returns True.
        2. admit_shadow_signal() admits the trade to shadow_positions without taking capital or slots.
        3. Shadow outcomes update rolling PF and auto-restore status to ACTIVE once hurdle is cleared.
        """
        registry = StrategyRegistry(persistence_file=self.priors_file)
        strat_id = StrategyArchetype.MOMENTUM_SHORT.value

        # Intentionally force strategy into PAUSED state
        perf = registry.strategies[strat_id]
        perf.status = StrategyStatus.PAUSED
        perf.rolling_50_pf = 0.82
        perf.expectancy_net_pct = 0.15
        registry.save_to_disk()

        # 1. Verify eligibility check
        is_allowed, reason = registry.is_strategy_allowed(strat_id, current_regime="BEAR_TREND")
        self.assertFalse(is_allowed, "PAUSED strategy must not be allowed in live trading")

        is_shadow_ok, shadow_msg = registry.is_strategy_shadow_eligible(strat_id, current_regime="BEAR_TREND")
        self.assertTrue(is_shadow_ok, f"PAUSED strategy must be shadow eligible: {shadow_msg}")

        # 2. Test PaperTradingBot shadow admission
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        candidate_sig = {
            "symbol": "BTC/USDT",
            "direction": "SHORT",
            "horizon": "15M",
            "entry_price": 50000.0,
            "tp1_price": 49000.0,
            "tp2_price": 48500.0,
            "tp3_price": 48000.0,
            "sl_price": 50500.0,
            "canonical_strategy": strat_id,
            "strategy": strat_id,
            "active_regime": "BEAR_TREND"
        }

        admitted = bot.admit_shadow_signal(candidate_sig)
        self.assertTrue(admitted, "Shadow signal must be successfully admitted")
        self.assertEqual(len(bot.data["shadow_positions"]), 1)
        self.assertEqual(len(bot.data["open_positions"]), 0, "Shadow trades must NOT occupy open_positions")
        self.assertEqual(bot.data["desks"]["scalp"]["active_slots"], 0, "Shadow trades must NOT consume desk slot quota")

        # 3. Simulate winning shadow trades to unpause
        # Trigger resolution by feeding profitable tick
        unpause_res = registry.record_shadow_outcome(
            strategy_id=strat_id,
            is_win=True,
            net_return_pct=3.50,
            regime="BEAR_TREND"
        )
        self.assertTrue(unpause_res["rolling_50_pf"] > 0.82)

        # Feed consecutive winning shadow outcomes until hurdle cleared
        while registry.strategies[strat_id].status == StrategyStatus.PAUSED and registry.strategies[strat_id].shadow_resolved_count < 60:
            unpause_res = registry.record_shadow_outcome(
                strategy_id=strat_id,
                is_win=True,
                net_return_pct=5.00,
                regime="BEAR_TREND"
            )

        self.assertTrue(unpause_res["unpaused"], "Strategy must successfully auto-unpause after sufficient shadow wins")
        self.assertEqual(registry.strategies[strat_id].status, StrategyStatus.ACTIVE)
        is_now_allowed, _ = registry.is_strategy_allowed(strat_id, current_regime="BEAR_TREND")
        self.assertTrue(is_now_allowed, "Strategy must now be admitted for live execution")

    def test_feature_5_2_dynamic_time_decay_take_profit_compaction(self):
        """
        AC-P5-02: Verifies that when a trade has consumed >= 80% of its horizon TTL,
        TP1 dynamically compacts towards entry price, allowing profitable exit before timeout.
        """
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        # Seed an active position with 85% elapsed hold time (15M horizon = 7200s TTL; 85% = 6120s)
        opened_ts = (datetime.now(timezone.utc) - timedelta(seconds=6200)).isoformat()
        pos = {
            "trade_id": "TEST_TIME_DECAY_1",
            "symbol": "ETH/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 5,
            "position_size_usd": 500.0,
            "remaining_position_size_usd": 500.0,
            "entry_price": 2500.0,
            "tp1_price": 2560.0, # Initial target (+2.4%)
            "tp2_price": 2590.0,
            "tp3_price": 2620.0,
            "sl_price": 2470.0,
            "opened_at": opened_ts,
            "opened_at_utc": opened_ts,
            "status": "OPEN",
            "peak_gain_pct": 1.2,
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]
        bot.data["desks"]["scalp"]["active_slots"] = 1

        # Feed tick price at 2530.0 - triggers compaction (original 2560.0 decays towards entry)
        live_prices = {"ETH/USDT": 2530.0}
        bot.on_tick(live_prices=live_prices)

        # Check that TP1 compacted below original 2560.0
        updated_pos = [p for p in bot.data.get("open_positions", []) if p.get("trade_id") == "TEST_TIME_DECAY_1"]
        self.assertEqual(len(updated_pos), 1)
        self.assertTrue(updated_pos[0].get("is_tp_compacted"), "Position must have engaged time-decay TP compaction")
        self.assertEqual(updated_pos[0].get("original_tp1_price"), 2560.0)
        compacted_tp1 = updated_pos[0]["tp1_price"]
        self.assertTrue(compacted_tp1 < 2560.0, f"Compacted TP1 ({compacted_tp1}) must be tighter than original TP1 (2560.0)")

        # Now feed price at 2542.0 (above compacted_tp1, but below original 2560.0)
        # Without compaction, this price would NOT hit TP1. With compaction, it triggers TP1 Hit!
        bot.on_tick(live_prices={"ETH/USDT": 2542.0})
        self.assertTrue(updated_pos[0].get("tp1_hit"), "Compacted TP1 must trigger partial profit realization at 2542.0")
        self.assertTrue(updated_pos[0].get("is_breakeven_locked"), "TP1 hit must ratchet stop-loss to Breakeven")

    def test_feature_5_3_live_brier_score_and_calibration_metrics(self):
        """
        AC-P5-03: Verifies that signal service computes live Brier scores and calibration
        metrics by horizon, and exports them to v16_calibration_metrics.json.
        """
        from app.database import SessionLocal
        from app.services.signal_service import signal_service
        from app.models.signal import SignalAudit

        db = SessionLocal()
        try:
            kpi_data = signal_service.get_kpi_summary(db)
            self.assertIn("calibration_metrics", kpi_data)
            calib = kpi_data["calibration_metrics"]
            self.assertIn("overall", calib)
            self.assertIn("by_horizon", calib)
            self.assertIn("15M", calib["by_horizon"])
            self.assertIn("1H", calib["by_horizon"])
            self.assertIn("24H", calib["by_horizon"])

            # Verify numerical boundedness
            overall_bs = calib["overall"]["brier_score"]
            self.assertTrue(0.0 <= overall_bs <= 1.0, f"Brier score must be within [0.0, 1.0], got {overall_bs}")

            # Verify exported JSON file exists
            exported_file = os.path.join(settings.EXPORT_DIR, "v16_calibration_metrics.json")
            self.assertTrue(os.path.exists(exported_file), f"v16_calibration_metrics.json must be written to {exported_file}")
            with open(exported_file, "r", encoding="utf-8") as f:
                saved_json = json.load(f)
            self.assertIn("overall", saved_json)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
