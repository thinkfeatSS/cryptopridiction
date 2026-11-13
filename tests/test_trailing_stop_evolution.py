import unittest
import os
import math
import tempfile
import shutil
from datetime import datetime, timezone, timedelta

from app.quant_v16.validation import safe_ratio, safe_float
from app.quant_v16.audit import (
    calculate_trailing_stop_evolution,
    DynamicTradeState,
    TrailingEvolutionMetrics,
    V16AuditManager,
)
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.services.whatsapp_service import WhatsAppService


class TestTrailingStopEvolution(unittest.TestCase):
    """
    Unit & Integration Test Suite for Trailing Stop Evolution:
    Verifies that while initial entry snapshots preserve immutable structural R:R,
    subsequent breakeven and TP1 profit buffer ratchets dynamically compress residual risk
    to zero (R -> 0), handling terminal active trailing R:R cleanly without division-by-zero or 'inf'.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.ledger_file = os.path.join(self.tmp_dir, "test_paper_trading_ledger.json")

    def tearDown(self):
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_01_safe_ratio_guards_against_infinity_and_nan(self):
        """Tests that safe_ratio cleanly deflects non-finite values and parses risk-free runner strings."""
        self.assertEqual(safe_ratio(float('inf'), default=2.0), 2.0)
        self.assertEqual(safe_ratio(float('-inf'), default=2.0), 2.0)
        self.assertEqual(safe_ratio(float('nan'), default=2.0), 2.0)
        self.assertEqual(safe_ratio("1:inf", default=2.0), 2.0)
        self.assertEqual(safe_ratio("1:Infinity", default=2.0), 2.0)
        self.assertEqual(safe_ratio("inf", default=2.0), 2.0)
        self.assertEqual(safe_ratio("nan", default=2.0), 2.0)
        self.assertEqual(safe_ratio("RISK_FREE (LOCKED)", default=2.0), 2.0)
        # Runner string with embedded ratio extracts the runner ratio
        self.assertEqual(safe_ratio("1:FREE (Runner 1:2.4)", default=2.0), 2.4)
        self.assertEqual(safe_ratio("1:2.5", default=2.0), 2.5)
        self.assertEqual(safe_ratio(3.2, default=2.0), 3.2)

    def test_02_calculate_trailing_stop_evolution_structural_to_breakeven_long(self):
        """
        Tests the mathematical progression of a LONG trade from structural risk to Tier-0 breakeven.
        Residual capital risk compresses to 0, preventing division-by-zero.
        """
        entry_p = 100.0
        initial_sl = 95.0
        tp1_p = 110.0
        tp2_p = 120.0

        # Phase 1: Initial Entry Snapshot (Structural Risk)
        evo_init = calculate_trailing_stop_evolution(
            entry_price=entry_p,
            current_sl=initial_sl,
            current_price=entry_p,
            next_target=tp1_p,
            initial_sl=initial_sl,
            initial_target=tp1_p,
            direction="LONG",
            position_size_usd=100.0,
        )
        self.assertFalse(evo_init.is_risk_free)
        self.assertEqual(evo_init.structural_rr, 2.0)  # (110 - 100) / (100 - 95) = 2.0
        self.assertAlmostEqual(evo_init.residual_risk_distance, 5.0, places=4)
        self.assertAlmostEqual(evo_init.residual_risk_usd, 5.0, places=4)
        self.assertEqual(evo_init.risk_state, "STRUCTURAL_RISK")
        self.assertEqual(evo_init.active_rr_ratio, "1:2.0")

        # Phase 2: Micro-Guard (+0.50% MFE cuts risk in half)
        half_risk_sl = 97.5
        evo_mg = calculate_trailing_stop_evolution(
            entry_price=entry_p,
            current_sl=half_risk_sl,
            current_price=101.0,
            next_target=tp1_p,
            initial_sl=initial_sl,
            initial_target=tp1_p,
            direction="LONG",
            position_size_usd=100.0,
        )
        self.assertFalse(evo_mg.is_risk_free)
        self.assertAlmostEqual(evo_mg.residual_risk_distance, 2.5, places=4)
        self.assertAlmostEqual(evo_mg.residual_risk_usd, 2.5, places=4)
        self.assertEqual(evo_mg.risk_state, "MICRO_GUARDED")
        self.assertEqual(evo_mg.active_rr_ratio, "1:4.0")  # (110 - 100) / 2.5 = 4.0

        # Phase 3: Tier-0 Breakeven Ratchet (SL at 100.05) -> R -> 0
        be_sl = 100.05
        evo_be = calculate_trailing_stop_evolution(
            entry_price=entry_p,
            current_sl=be_sl,
            current_price=105.0,
            next_target=tp1_p,
            initial_sl=initial_sl,
            initial_target=tp1_p,
            direction="LONG",
            position_size_usd=100.0,
            is_breakeven_locked=True,
        )
        self.assertTrue(evo_be.is_risk_free)
        self.assertEqual(evo_be.structural_rr, 2.0)  # Structural R:R preserved!
        self.assertEqual(evo_be.residual_risk_distance, 0.0)  # R -> 0
        self.assertEqual(evo_be.residual_risk_usd, 0.0)
        self.assertEqual(evo_be.risk_state, "BREAKEVEN_LOCKED")
        self.assertNotIn("inf", evo_be.active_rr_ratio.lower())
        self.assertNotIn("infinity", evo_be.active_rr_ratio.lower())

    def test_03_calculate_trailing_stop_evolution_tp1_runner_terminal_phase(self):
        """
        Tests TP1 hit where 70% is banked and 30% runner trails towards TP2.
        Capital risk is strictly 0.0, while trailing runner R:R is computed against paper giveback risk.
        """
        entry_p = 60000.0
        initial_sl = 59000.0
        tp1_p = 62000.0
        tp2_p = 64000.0
        profit_buffer_sl = 60500.0  # entry + 0.25*(tp1 - entry)
        curr_p = 62500.0

        evo_tp1 = calculate_trailing_stop_evolution(
            entry_price=entry_p,
            current_sl=profit_buffer_sl,
            current_price=curr_p,
            next_target=tp2_p,
            initial_sl=initial_sl,
            initial_target=tp1_p,
            direction="LONG",
            position_size_usd=150.0,
            remaining_size_usd=45.0,  # 30% runner
            total_realized_partial_usd=4.50,
            is_tp1_locked=True,
        )
        self.assertTrue(evo_tp1.is_risk_free)
        self.assertEqual(evo_tp1.structural_rr, 2.0)  # (62000-60000)/(60000-59000) = 2.0
        self.assertEqual(evo_tp1.residual_risk_distance, 0.0)
        self.assertEqual(evo_tp1.residual_risk_usd, 0.0)
        # Guaranteed locked profit: (60500-60000)/60000 * 45 + 4.50 = 0.375 + 4.50 = 4.875
        self.assertGreater(evo_tp1.locked_profit_usd, 4.50)
        # Trailing runner R:R: (64000 - 62500) / (62500 - 60500) = 1500 / 2000 = 0.75
        self.assertIsNotNone(evo_tp1.trailing_runner_rr)
        self.assertAlmostEqual(evo_tp1.trailing_runner_rr, 0.75, places=2)
        self.assertEqual(evo_tp1.active_rr_ratio, "1:FREE (Runner 1:0.8)")
        self.assertFalse(math.isinf(evo_tp1.trailing_runner_rr))

    def test_04_calculate_trailing_stop_evolution_short_direction(self):
        """
        Tests the mathematical progression for a SHORT trade.
        SL ratchets lower than entry -> R -> 0.
        """
        entry_p = 3000.0
        initial_sl = 3100.0
        tp1_p = 2800.0
        tp2_p = 2600.0
        curr_p = 2750.0
        sl_p = 2950.0  # In profit buffer below entry

        evo_short = calculate_trailing_stop_evolution(
            entry_price=entry_p,
            current_sl=sl_p,
            current_price=curr_p,
            next_target=tp2_p,
            initial_sl=initial_sl,
            initial_target=tp1_p,
            direction="SHORT",
            position_size_usd=100.0,
            remaining_size_usd=30.0,
            total_realized_partial_usd=4.0,
            is_tp1_locked=True,
        )
        self.assertTrue(evo_short.is_risk_free)
        self.assertEqual(evo_short.structural_rr, 2.0)  # (3000-2800)/(3100-3000) = 2.0
        self.assertEqual(evo_short.residual_risk_distance, 0.0)
        self.assertEqual(evo_short.residual_risk_usd, 0.0)
        self.assertGreater(evo_short.locked_profit_usd, 4.0)
        # Runner R:R: (2750 - 2600) / (2950 - 2750) = 150 / 200 = 0.75
        self.assertAlmostEqual(evo_short.trailing_runner_rr, 0.75, places=2)
        self.assertEqual(evo_short.active_rr_ratio, "1:FREE (Runner 1:0.8)")

    def test_05_paper_trading_bot_evolution_on_tick(self):
        """
        Integration test with PaperTradingBot:
        Verifies that position evolves through Tier-0 BE, TP1 hit, and runner trailing
        while updating is_risk_free, residual_risk_usd, and preventing infinite active R:R.
        """
        bot = PaperTradingBot(ledger_file=self.ledger_file)
        bot.enable_breakeven_guard = True
        now_ts = datetime.now(timezone.utc).isoformat()
        pos = {
            "trade_id": "TEST_EVOLUTION_01",
            "symbol": "BTC/USDT",
            "desk": "scalp",
            "direction": "LONG",
            "horizon": "15M",
            "signal_horizon": "15M",
            "leverage": 2,
            "position_size_usd": 100.0,
            "remaining_position_size_usd": 100.0,
            "entry_price": 50000.0,
            "initial_sl_price": 49000.0,
            "sl_price": 49000.0,
            "tp1_price": 52000.0,
            "tp2_price": 54000.0,
            "tp3_price": 56000.0,
            "risk_reward_ratio": "1:2.0",
            "structural_risk_reward": "1:2.0",
            "is_breakeven_locked": False,
            "tp1_hit": False,
            "tp2_hit": False,
            "peak_price_seen": 50000.0,
            "opened_at": now_ts,
            "opened_at_utc": now_ts,
            "status": "OPEN",
            "scaling_policy": "MULTI_TRANCHE_SCALE"
        }
        bot.data["open_positions"] = [pos]

        # Tick 1: Normal open position at 50,200 (structural risk)
        bot.on_tick(live_prices={"BTC/USDT": 50200.0})
        p1 = bot.data["open_positions"][0]
        self.assertFalse(p1.get("is_risk_free"))
        self.assertAlmostEqual(p1.get("residual_risk_usd"), 2.0, places=1)
        self.assertEqual(p1.get("structural_risk_reward"), "1:2.0")

        # Tick 2: Price reaches 51,200 (> 50% TP1 proximity) -> Triggers Tier-0 Breakeven
        bot.on_tick(live_prices={"BTC/USDT": 51200.0})
        p2 = bot.data["open_positions"][0]
        self.assertTrue(p2.get("is_breakeven_locked"))
        self.assertTrue(p2.get("is_risk_free"))
        self.assertEqual(p2.get("residual_risk_usd"), 0.0)
        self.assertNotIn("inf", str(p2.get("active_risk_reward_ratio", "")).lower())

        # Tick 3: Price hits TP1 at 52,100 -> Multi-Tranche 70% scale out + SL ratchets to Profit Buffer
        bot.on_tick(live_prices={"BTC/USDT": 52100.0})
        p3 = bot.data["open_positions"][0]
        self.assertTrue(p3.get("tp1_hit"))
        self.assertTrue(p3.get("is_risk_free"))
        self.assertEqual(p3.get("residual_risk_usd"), 0.0)
        self.assertGreater(p3.get("locked_profit_usd"), 0.0)
        self.assertGreater(float(p3.get("sl_price")), 50000.0)  # SL above entry
        self.assertIsNotNone(p3.get("trailing_runner_rr"))
        self.assertFalse(math.isinf(p3.get("trailing_runner_rr")))
        self.assertIn("1:FREE", p3.get("active_risk_reward_ratio", ""))

    def test_06_whatsapp_service_formats_risk_free_runner_cleanly(self):
        """
        Tests that WhatsAppService formats risk-free runner positions cleanly
        without outputting '1:inf' or unhandled strings.
        """
        wa = WhatsAppService()
        sig = {
            "symbol": "ETH/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "entry_price": 3000.0,
            "current_price": 3150.0,
            "sl_price": 3050.0,
            "tp1_price": 3100.0,
            "tp2_price": 3200.0,
            "tp3_price": 3300.0,
            "risk_reward_ratio": "1:2.0",
            "is_risk_free": True,
            "active_risk_reward_ratio": "1:FREE (Runner 1:1.5)",
            "quality_grade": "Grade A+",
            "win_probability_pct": 82.0,
        }
        card = wa.format_new_signal(sig)
        self.assertNotIn("1:inf", card)
        self.assertNotIn("1:Infinity", card)
        self.assertIn("1:FREE", card)


if __name__ == "__main__":
    unittest.main()
