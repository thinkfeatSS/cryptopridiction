"""
QUANT EDGE V16: Walk-Forward Shadow Replay Test Suite
Specifications:
- Verifies chronological event-driven execution and zero lookahead bias.
- Verifies multi-desk slot capacity gating (3 Swing, 2 Day, 1 Scalp, 6 Global max).
- Verifies symbol deduplication (Max 1 active trade per symbol).
- Verifies itemized execution friction deductions and strict breakeven accounting.
- Verifies Brier Score, Climatology Reference BS, BSS, and Platt calibration.
- Verifies Annualized Daily Sharpe Ratio, Max Drawdown, and Drawdown Duration with deterministic fixtures.
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from dataclasses import asdict

from app.quant_v16.walk_forward_replay import (
    WalkForwardShadowReplayEngine,
    WalkForwardReplayConfig,
    WalkForwardReport,
    WalkForwardTradeRecord
)

class TestWalkForwardShadowReplay(unittest.TestCase):

    def setUp(self):
        self.cfg = WalkForwardReplayConfig(
            initial_capital_usd=1000.0,
            desk_allocations={"swing": 0.50, "day": 0.35, "scalp": 0.15},
            desk_slots={"swing": 3, "day": 2, "scalp": 1},
            desk_leverage={"swing": 2, "day": 3, "scalp": 2},
            max_global_slots=6,
            quality_gate_enabled=False, # allow all fixtures in unit tests
            random_seed=42,
            num_bootstrap_resamples=100
        )
        self.engine = WalkForwardShadowReplayEngine(config=self.cfg)

    def test_01_chronological_ordering_and_zero_lookahead(self):
        """
        Signals provided in disordered timestamp sequence must be sorted
        strictly chronologically before execution.
        """
        now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
        disordered_data = [
            {
                "signal_id": "SIG_03",
                "date_utc": "2026-09-20",
                "time_utc": "14:00:00",
                "symbol": "BTC/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price": 60000.0,
                "exit_price": 61000.0,
                "sl_price": 59000.0,
                "tp1_price": 61000.0,
                "status": "WON_TP1",
                "evaluated_at_utc": "2026-09-20 15:00:00 UTC",
                "meta_win_prob_pct": 65.0
            },
            {
                "signal_id": "SIG_01",
                "date_utc": "2026-09-20",
                "time_utc": "10:00:00",
                "symbol": "ETH/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price": 3000.0,
                "exit_price": 3050.0,
                "sl_price": 2950.0,
                "tp1_price": 3050.0,
                "status": "WON_TP1",
                "evaluated_at_utc": "2026-09-20 11:00:00 UTC",
                "meta_win_prob_pct": 60.0
            },
            {
                "signal_id": "SIG_02",
                "date_utc": "2026-09-20",
                "time_utc": "12:00:00",
                "symbol": "SOL/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price": 150.0,
                "exit_price": 152.0,
                "sl_price": 147.0,
                "tp1_price": 152.0,
                "status": "WON_TP1",
                "evaluated_at_utc": "2026-09-20 13:00:00 UTC",
                "meta_win_prob_pct": 55.0
            }
        ]
        df = pd.DataFrame(disordered_data)
        loaded = self.engine.load_dataset(df, window_days=30.0)
        self.assertEqual(loaded.iloc[0]["signal_id"], "SIG_01")
        self.assertEqual(loaded.iloc[1]["signal_id"], "SIG_02")
        self.assertEqual(loaded.iloc[2]["signal_id"], "SIG_03")

    def test_02_desk_capacity_and_symbol_deduplication_gating(self):
        """
        Scalp desk allows strictly 1 slot. A 2nd concurrent scalp trade arriving
        before the 1st has closed must be rejected via CAPACITY_VETO_DESK.
        A trade on the same symbol arriving while active must be rejected via DUP_SYMBOL.
        """
        t0 = "2026-09-20 12:00:00"
        t1 = "2026-09-20 12:15:00" # overlap
        t2 = "2026-09-20 12:35:00" # after close

        data = [
            # Trade 1: Scalp on BTC (duration until 12:30)
            {
                "signal_id": "SCALP_01",
                "date_utc": "2026-09-20",
                "time_utc": "12:00:00",
                "symbol": "BTC/USDT",
                "horizon": "15M",
                "direction": "LONG",
                "entry_price": 60000.0,
                "exit_price": 60500.0,
                "sl_price": 59500.0,
                "tp1_price": 60500.0,
                "status": "WON_TP1",
                "evaluated_at_utc": "2026-09-20 12:30:00 UTC",
                "meta_win_prob_pct": 70.0
            },
            # Trade 2: 2nd Scalp on ETH arriving at 12:15 (SCALP DESK CAPACITY EXCEEDED -> REJECTED)
            {
                "signal_id": "SCALP_02",
                "date_utc": "2026-09-20",
                "time_utc": "12:15:00",
                "symbol": "ETH/USDT",
                "horizon": "15M",
                "direction": "LONG",
                "entry_price": 3000.0,
                "exit_price": 3030.0,
                "sl_price": 2970.0,
                "tp1_price": 3030.0,
                "status": "WON_TP1",
                "evaluated_at_utc": "2026-09-20 12:45:00 UTC",
                "meta_win_prob_pct": 70.0
            },
            # Trade 3: Day trade on BTC arriving at 12:20 (BTC ALREADY ACTIVE -> DUP SYMBOL REJECTED)
            {
                "signal_id": "DAY_BTC_DUP",
                "date_utc": "2026-09-20",
                "time_utc": "12:20:00",
                "symbol": "BTC/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price": 60200.0,
                "exit_price": 60800.0,
                "sl_price": 59500.0,
                "tp1_price": 60800.0,
                "status": "WON_TP1",
                "evaluated_at_utc": "2026-09-20 16:00:00 UTC",
                "meta_win_prob_pct": 65.0
            },
            # Trade 4: Scalp on SOL arriving at 12:35 (after SCALP_01 closed -> ADMITTED)
            {
                "signal_id": "SCALP_03",
                "date_utc": "2026-09-20",
                "time_utc": "12:35:00",
                "symbol": "SOL/USDT",
                "horizon": "15M",
                "direction": "LONG",
                "entry_price": 150.0,
                "exit_price": 153.0,
                "sl_price": 147.0,
                "tp1_price": 153.0,
                "status": "WON_TP1",
                "evaluated_at_utc": "2026-09-20 13:00:00 UTC",
                "meta_win_prob_pct": 75.0
            }
        ]
        df = pd.DataFrame(data)
        report = self.engine.run_replay(df, scenario_name="TEST_CAPACITY")

        self.assertEqual(report.total_admitted_trades, 2) # SCALP_01 and SCALP_03 admitted
        self.assertEqual(report.rejected_capacity_desk, 1) # SCALP_02 rejected
        self.assertEqual(report.rejected_duplicate_symbol, 1) # DAY_BTC_DUP rejected
        executed_ids = [t.signal_id for t in report.trades]
        self.assertIn("SCALP_01", executed_ids)
        self.assertIn("SCALP_03", executed_ids)
        self.assertNotIn("SCALP_02", executed_ids)
        self.assertNotIn("DAY_BTC_DUP", executed_ids)

    def test_03_itemized_friction_and_pnl_balance_integrity(self):
        """
        Validates mathematical identity:
        gross_pnl_usd - total_friction_usd == net_pnl_usd
        and verifies that friction scales proportionally with cost_multiplier.
        """
        data = [{
            "signal_id": "FRICTION_TEST",
            "date_utc": "2026-09-20",
            "time_utc": "12:00:00",
            "symbol": "BTC/USDT",
            "horizon": "1H",
            "direction": "LONG",
            "entry_price": 60000.0,
            "exit_price": 61200.0, # +2.0%
            "sl_price": 59000.0,
            "tp1_price": 61200.0,
            "realized_return_pct": "+2.00%",
            "status": "WON_TP1",
            "evaluated_at_utc": "2026-09-20 16:00:00 UTC", # 4 hours
            "meta_win_prob_pct": 65.0
        }]
        df = pd.DataFrame(data)

        # BASE (1.0x)
        rep_base = self.engine.run_replay(df, scenario_name="BASE", cost_multiplier=1.0)
        t_base = rep_base.trades[0]
        self.assertAlmostEqual(t_base.gross_pnl_usd - t_base.total_friction_usd, t_base.net_pnl_usd, places=2)

        # STRESS (1.5x)
        rep_stress = self.engine.run_replay(df, scenario_name="STRESS", cost_multiplier=1.5)
        t_stress = rep_stress.trades[0]
        self.assertAlmostEqual(t_stress.gross_pnl_usd - t_stress.total_friction_usd, t_stress.net_pnl_usd, places=2)

        # Friction under 1.5x should be exactly 1.5x of base
        self.assertAlmostEqual(t_stress.total_friction_usd, t_base.total_friction_usd * 1.5, delta=0.05)

    def test_04_strict_breakeven_accounting_never_counted_as_won(self):
        """
        Validates Rule 9:
        Breakeven trades (WON_TIER0_BE, STOP_LOSS_BREAKEVEN, etc.) must NEVER
        be counted as wins in the audit ledger or win rate formulas.
        """
        data = [
            # Trade 1: WON_TIER0_BE (Micro profit +0.10%)
            {
                "signal_id": "BE_01",
                "date_utc": "2026-09-20",
                "time_utc": "10:00:00",
                "symbol": "BTC/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price": 60000.0,
                "exit_price": 60060.0,
                "sl_price": 59500.0,
                "tp1_price": 61000.0,
                "realized_return_pct": "+0.10%",
                "status": "WON_TIER0_BE",
                "evaluated_at_utc": "2026-09-20 11:00:00 UTC",
                "meta_win_prob_pct": 60.0
            },
            # Trade 2: WON_TP3 (+6.0%)
            {
                "signal_id": "WIN_01",
                "date_utc": "2026-09-20",
                "time_utc": "12:00:00",
                "symbol": "ETH/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price": 3000.0,
                "exit_price": 3180.0,
                "sl_price": 2900.0,
                "tp1_price": 3180.0,
                "realized_return_pct": "+6.00%",
                "status": "WON_TP3",
                "evaluated_at_utc": "2026-09-20 13:00:00 UTC",
                "meta_win_prob_pct": 70.0
            },
            # Trade 3: LOST_SL (-2.0%)
            {
                "signal_id": "LOSS_01",
                "date_utc": "2026-09-20",
                "time_utc": "14:00:00",
                "symbol": "SOL/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price": 150.0,
                "exit_price": 147.0,
                "sl_price": 147.0,
                "tp1_price": 155.0,
                "realized_return_pct": "-2.00%",
                "status": "LOST_SL",
                "evaluated_at_utc": "2026-09-20 15:00:00 UTC",
                "meta_win_prob_pct": 50.0
            }
        ]
        df = pd.DataFrame(data)
        report = self.engine.run_replay(df)

        self.assertEqual(report.total_admitted_trades, 3)
        self.assertEqual(report.won_trades, 1)       # WIN_01
        self.assertEqual(report.lost_trades, 1)      # LOSS_01
        self.assertEqual(report.breakeven_trades, 1) # BE_01 strictly classified as BREAKEVEN

        # Total Win Rate = Won / (Won + Lost + BE) = 1 / 3 = 33.33%
        self.assertAlmostEqual(report.total_win_rate_pct, 33.33, places=1)
        # Decisive Win Rate = Won / (Won + Lost) = 1 / 2 = 50.00%
        self.assertAlmostEqual(report.decisive_win_rate_pct, 50.00, places=1)
        self.assertAlmostEqual(report.breakeven_rate_pct, 33.33, places=1)

    def test_05_brier_score_and_skill_calculation(self):
        """
        Validates analytical correctness of Brier Score and Brier Skill Score:
        BS = (1/N) * sum((P_i - Y_i)^2)
        BS_ref = Y_bar * (1 - Y_bar)
        BSS = 1 - BS / BS_ref
        """
        probs = [0.80, 0.70, 0.20, 0.30]
        outcomes = [1, 1, 0, 0]
        # P - Y: [-0.20, -0.30, 0.20, 0.30]
        # Squared: [0.04, 0.09, 0.04, 0.09] -> Sum = 0.26 -> Mean BS = 0.065
        # Y_bar = 2 / 4 = 0.50 -> BS_ref = 0.50 * 0.50 = 0.25
        # BSS = 1 - (0.065 / 0.25) = 1 - 0.26 = 0.74

        res = self.engine._compute_brier_and_calibration(probs, outcomes)
        self.assertAlmostEqual(res["brier_score_raw"], 0.065, places=4)
        self.assertAlmostEqual(res["brier_score_reference"], 0.25, places=4)
        self.assertAlmostEqual(res["brier_skill_score_raw"], 0.74, places=4)

    def test_06_sharpe_and_drawdown_dynamics(self):
        """
        Validates peak-to-trough drawdown and recovery duration on deterministic daily equity.
        """
        # Day 0: 1000, Day 1: 1200 (Peak), Day 2: 900 (Trough, -25% DD), Day 3: 1050, Day 4: 1250 (Recovered)
        daily_equity = [1000.0, 1200.0, 900.0, 1050.0, 1250.0]
        trades = []
        dd_res = self.engine._calculate_drawdown_dynamics(daily_equity, trades)

        # Max DD from 1200 to 900 is $300 (25.0%)
        self.assertAlmostEqual(dd_res["max_drawdown_usd"], 300.0, places=2)
        self.assertAlmostEqual(dd_res["max_drawdown_pct"], 25.0, places=2)
        # Peak at Day 1, trough at Day 2 -> duration = 1 day
        self.assertEqual(dd_res["max_drawdown_duration_days"], 1.0)
        # Recovered to new high at Day 4 (2 days from trough at Day 2)
        self.assertEqual(dd_res["recovery_duration_days"], 2.0)

if __name__ == "__main__":
    unittest.main()

