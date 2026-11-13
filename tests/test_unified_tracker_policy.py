"""
Quant Edge AI V16 - Unified Tracker Policy & Cross-Service Synchronization Tests
Authoritative Test Suite verifying that:
1. SignalAuditTracker (test.py), SignalService (app/services/signal_service.py),
   and PaperTradingBot (app/engine/execution/paper_trading_bot.py) adhere strictly
   to the single canonical "One Best Tracker Policy".
2. Breakeven trades (BREAKEVEN_GUARD, STOP_LOSS_BREAKEVEN, WON_TIER0_BE) are NEVER
   counted as wins in any tracker or KPI summary (Rule 1, 4.1, and 9).
3. The authoritative CSV ledger is strictly 'trader_signals_tracker.csv' across all
   routers, retrainers, paper bots, and scanners.
4. Two-way disk reconciliation between PaperTradingBot/SignalService and SignalAuditTracker
   prevents race conditions and overwrites.
"""

import os
import sys
import json
import csv
import time
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

# Ensure project root is in path
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.quant_v16.audit import classify_signal_outcome
from test import SignalAuditTracker


class TestUnifiedTrackerPolicy(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="quant_unified_tracker_")
        self.csv_path = os.path.join(self.test_dir, "trader_signals_tracker.csv")
        self.ledger_path = os.path.join(self.test_dir, "paper_trading_ledger.json")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_classify_signal_outcome_canonical_breakeven(self):
        """Verifies that BREAKEVEN_GUARD, STOP_LOSS_BREAKEVEN, TIER0_GUARD, and legacy WON_TIER0_BE
        strictly classify as BREAKEVEN, never as WON or LOST."""
        cases = [
            ("BREAKEVEN_GUARD", "🛡️ BREAKEVEN (TIER-0 GUARD +0.25%)", 0.25),
            ("BREAKEVEN_GUARD", "🛡️ BREAKEVEN (+0.05%)", 0.05),
            ("STOP_LOSS_BREAKEVEN", "🛡️ BREAKEVEN (SL AT ENTRY)", 0.0),
            ("TIER0_GUARD", "🛡️ TIER-0 PROTECTED", 0.30),
            ("WON_TIER0_BE", "🛡️ BREAKEVEN (TIER-0 GUARD +0.35%)", 0.35),
            ("EXPIRED_BREAKEVEN", "⏱️ EXPIRED (CONSOLIDATION BE +0.02%)", 0.02),
            ("BREAKEVEN_EXP", "⚪ BREAKEVEN (EXPIRY -0.01%)", -0.01),
        ]
        for st, out, ret in cases:
            cat = classify_signal_outcome(st, out, ret)
            self.assertEqual(cat, "BREAKEVEN", f"Failed for {st} ({out}): got {cat}")

    def test_signal_audit_tracker_breakeven_status_is_breakeven_guard(self):
        """SignalAuditTracker must stamp BREAKEVEN_GUARD (never WON_TIER0_BE) when resolving
        Tier-0 breakeven stop-outs or matching paper trading breakeven exits."""
        tracker = SignalAuditTracker(export_dir=self.test_dir)

        # 1. Test paper trade match resolution
        pt_ledger = {
            "closed_trades": [
                {
                    "symbol": "BTC/USDT",
                    "horizon": "15M",
                    "exit_reason": "STOP_LOSS_BREAKEVEN",
                    "exit_price": 65000.0,
                    "return_pct": 0.15,
                    "closed_at_utc": "2026-11-07 12:00:00 UTC"
                }
            ]
        }
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            json.dump(pt_ledger, f)

        tracker.records = [
            {
                "signal_id": "SIG_BTC_001",
                "symbol": "BTC/USDT",
                "horizon": "15M",
                "direction": "LONG",
                "entry_price": 64900.0,
                "status": "PENDING_EVALUATION",
                "tp1_price": 66000.0,
                "sl_price": 64000.0,
            }
        ]

        # Evaluate against live prices
        tracker.evaluate_signals({"BTC/USDT": 65000.0})

        r = tracker.records[0]
        self.assertEqual(r["status"], "BREAKEVEN_GUARD", "Paper breakeven match must set BREAKEVEN_GUARD")
        self.assertIn("BREAKEVEN", r["outcome_label"])
        self.assertNotIn("WON_TIER0_BE", r["status"], "Must never stamp WON_TIER0_BE")

    def test_signal_audit_tracker_internal_tier0_stop_out(self):
        """SignalAuditTracker must stamp BREAKEVEN_GUARD when a Tier-0 protected trade gets stopped out."""
        tracker = SignalAuditTracker(export_dir=self.test_dir)
        tracker.records = [
            {
                "signal_id": "SIG_ETH_001",
                "symbol": "ETH/USDT",
                "horizon": "15M",
                "direction": "LONG",
                "entry_price": 3000.0,
                "tp1_price": 3060.0,
                "sl_price": 3003.0,  # Soft BE level
                "status": "TIER0_PROTECTED_BREAKEVEN",
                "is_tier0_locked": True,
                "peak_price_seen": 3030.0,
                "trough_price_seen": 3000.0,
            }
        ]

        # Price drops to hit the BE SL (3003.0)
        tracker.evaluate_signals({"ETH/USDT": 3002.0})

        r = tracker.records[0]
        self.assertEqual(r["status"], "BREAKEVEN_GUARD", "Tier-0 stop hit must resolve as BREAKEVEN_GUARD")
        self.assertIn("BREAKEVEN", r["outcome_label"])
        self.assertNotIn("WON_TIER0_BE", r["status"])

    def test_kpi_win_rate_strict_breakeven_exclusion(self):
        """Rule 1 & Rule 9: Breakevens must NEVER be counted as wins in the audit ledger or win rate formulas.
        Verifies both Decisive Win Rate and Total Closed Win Rate."""
        tracker = SignalAuditTracker(export_dir=self.test_dir)
        tracker.records = [
            # 3 WON
            {"signal_id": "W1", "status": "WON_TP3", "outcome_label": "🟢 WON (TP3 HIT)", "realized_return_pct": "+5.0%"},
            {"signal_id": "W2", "status": "WON_TP2_TRAIL", "outcome_label": "🟢 WON (TP2 HIT)", "realized_return_pct": "+3.0%"},
            {"signal_id": "W3", "status": "WON_EXP_PROFIT", "outcome_label": "🟢 WON (EXP PROFIT)", "realized_return_pct": "+1.2%"},
            # 1 LOST
            {"signal_id": "L1", "status": "LOST_SL", "outcome_label": "🔴 LOST (SL HIT)", "realized_return_pct": "-2.0%"},
            # 2 BREAKEVEN
            {"signal_id": "BE1", "status": "BREAKEVEN_GUARD", "outcome_label": "🛡️ BREAKEVEN (TIER-0 GUARD +0.20%)", "realized_return_pct": "+0.20%"},
            {"signal_id": "BE2", "status": "STOP_LOSS_BREAKEVEN", "outcome_label": "🛡️ BREAKEVEN (BE 0.00%)", "realized_return_pct": "+0.00%"},
            # 1 EXPIRED (flat)
            {"signal_id": "E1", "status": "EXPIRED_BREAKEVEN", "outcome_label": "⏱️ EXPIRED (CONSOLIDATION)", "realized_return_pct": "0.0%"},
            # 2 PENDING (must NOT be counted)
            {"signal_id": "P1", "status": "ACTIVE", "outcome_label": "ACTIVE 🟢", "realized_return_pct": "+10.0%"},
            {"signal_id": "P2", "status": "TP1_LOCKED_BREAKEVEN", "outcome_label": "🟢 TP1 HIT (SL @ BREAKEVEN)", "realized_return_pct": "+2.0%"},
        ]

        summary = tracker.build_kpi_summary()

        self.assertEqual(summary["won_signals_count"], 3)
        self.assertEqual(summary["lost_signals_count"], 1)
        self.assertEqual(summary["breakeven_signals_count"], 3)  # BE1, BE2, E1
        self.assertEqual(summary["pending_signals_count"], 2)

        # Decisive Win Rate = 3 / (3 + 1) = 75.0%
        # Breakeven trades must NOT inflate won count
        self.assertAlmostEqual(summary["win_rate_pct"], 75.0, places=1)

    def test_reconcile_disk_records_prevents_clobber(self):
        """SignalAuditTracker.reconcile_disk_records must detect external status resolutions
        written to trader_signals_tracker.csv by PaperTradingBot and merge them safely."""
        tracker = SignalAuditTracker(export_dir=self.test_dir)
        initial_records = [
            {
                "signal_id": "SIG_SOL_001",
                "symbol": "SOL/USDT",
                "horizon": "15M",
                "direction": "LONG",
                "entry_price": 150.0,
                "status": "ACTIVE",
                "outcome_label": "ACTIVE 🟢",
            }
        ]
        tracker.records = list(initial_records)
        tracker.save_records()

        # Simulate PaperTradingBot directly closing the trade and writing to trader_signals_tracker.csv
        time.sleep(0.05)
        with open(self.csv_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            if r["signal_id"] == "SIG_SOL_001":
                r["status"] = "BREAKEVEN_GUARD"
                r["outcome_label"] = "🛡️ BREAKEVEN (TIER-0 GUARD +0.25%)"
                r["exit_price"] = "150.375"
                r["realized_return_pct"] = "+0.25%"
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

        # Force mtime update to guarantee detection
        os.utime(self.csv_path, (time.time() + 2, time.time() + 2))

        # SignalAuditTracker runs evaluation cycle
        tracker.evaluate_signals({})

        # Verify that tracker.records merged the external resolution rather than reverting it to ACTIVE
        sol_record = next(r for r in tracker.records if r["signal_id"] == "SIG_SOL_001")
        self.assertEqual(sol_record["status"], "BREAKEVEN_GUARD")
        self.assertIn("BREAKEVEN", sol_record["outcome_label"])
        self.assertEqual(sol_record["realized_return_pct"], "+0.25%")

    def test_paper_trading_bot_sync_only_targets_canonical_csv(self):
        """Verifies that PaperTradingBot._sync_paper_partial_tp_to_audit and exit sync
        write exclusively to trader_signals_tracker.csv, with zero references to today_trader_signals_tracker.csv."""
        from app.engine.execution.paper_trading_bot import PaperTradingBot

        # Inspect source code of PaperTradingBot to verify single-target policy
        import inspect
        src = inspect.getsource(PaperTradingBot._sync_paper_partial_tp_to_audit)
        self.assertNotIn("today_trader_signals_tracker.csv", src,
                         "PaperTradingBot must not dual-write to today_trader_signals_tracker.csv")
        self.assertIn("trader_signals_tracker.csv", src,
                      "PaperTradingBot must update the authoritative trader_signals_tracker.csv")

    def test_signal_service_breakeven_status_is_breakeven_guard(self):
        """SignalService.evaluate_active_signals must stamp BREAKEVEN_GUARD when a Tier-0 protected trade is stopped out."""
        from types import SimpleNamespace
        from app.services.signal_service import SignalService

        sig = SimpleNamespace(
            signal_id="SIG_TEST_BE_001",
            symbol="BTC/USDT",
            horizon="15M",
            direction="LONG",
            entry_price=60000.0,
            tp1_price=61200.0,
            tp2_price=62400.0,
            tp3_price=63600.0,
            sl_price=59400.0,
            initial_sl_price=59400.0,
            status="ACTIVE",
            outcome_label="RUNNING 🚀",
            peak_price_seen=60000.0,
            trough_price_seen=60000.0,
            created_at=datetime.now(timezone.utc),
            date_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            time_utc=datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            quality_grade="Grade A+",
            meta_win_prob_pct=75.0,
            realized_return_pct=None,
            exit_price=None,
            evaluated_at_utc=None
        )

        service = SignalService()
        now = datetime.now(timezone.utc)
        old_be = os.environ.get("ENABLE_BREAKEVEN_GUARD")
        os.environ["ENABLE_BREAKEVEN_GUARD"] = "true"
        try:
            # 1. Price surges to 60600 (+1.0% MFE) -> activates TIER0_PROTECTED_BREAKEVEN
            service.evaluate_active_signals([sig], live_prices={"BTC/USDT": 60600.0}, now_utc=now)
            self.assertEqual(sig.status, "TIER0_PROTECTED_BREAKEVEN")
            soft_be = sig.sl_price
            self.assertGreater(soft_be, 60000.0)

            # 2. Price falls back and breaches soft BE -> resolves to BREAKEVEN_GUARD
            service.evaluate_active_signals([sig], live_prices={"BTC/USDT": 60000.0}, now_utc=now)
            self.assertEqual(sig.status, "BREAKEVEN_GUARD")
            self.assertIn("BREAKEVEN", sig.outcome_label)
            self.assertNotIn("WON_TIER0_BE", sig.status)
        finally:
            if old_be is None:
                os.environ.pop("ENABLE_BREAKEVEN_GUARD", None)
            else:
                os.environ["ENABLE_BREAKEVEN_GUARD"] = old_be

    def test_router_csv_candidate_priority(self):
        """Verifies that v16_router prioritizes trader_signals_tracker.csv ahead of any fallback snapshots."""
        from app.routers.v16_router import _get_v16_store
        import inspect
        src = inspect.getsource(_get_v16_store)

        # The first entry in csv_candidates must point to trader_signals_tracker.csv
        cand_start = src.find("csv_candidates = [")
        cand_end = src.find("]", cand_start)
        cand_block = src[cand_start:cand_end]

        lines = [l.strip() for l in cand_block.splitlines() if "os.path.join" in l]
        first_line = lines[0]
        self.assertIn("trader_signals_tracker.csv", first_line,
                      f"Authoritative tracker must be first candidate, got: {first_line}")

    def test_micro_guard_ratchet_immunity_against_exponential_decay(self):
        """Verifies that Stage 1 Micro-Guard (+0.50% MFE) anchors strictly to sl_original
        and does NOT exponentially decay Stop Loss across consecutive evaluation cycles."""
        from app.services.signal_service import SignalService
        from app.models.signal import SignalAudit

        # Simulating exact SIGN/USDT SHORT trade setup
        sig = SignalAudit(
            signal_id="SIG_TEST_SHORT_MICRO_GUARD",
            symbol="SIGN/USDT",
            horizon="15M",
            direction="SHORT",
            entry_price=0.00904,
            tp1_price=0.00877455,
            tp2_price=0.00864088,
            tp3_price=0.00850784,
            sl_price=0.00917304,
            sl_original=0.00917304,
            status="ACTIVE",
            outcome_label="RUNNING 🚀",
            peak_price_seen=0.00904,
            trough_price_seen=0.00899, # +0.55% gain seen
            max_potential_gain_pct=0.55,
            spread_bps=22.4,
            date_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            time_utc=datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            quality_grade="Grade A",
            meta_win_prob_pct=64.1
        )

        service = SignalService()
        now = datetime.now(timezone.utc)
        old_be = os.environ.get("ENABLE_BREAKEVEN_GUARD")
        os.environ["ENABLE_BREAKEVEN_GUARD"] = "true"
        try:
            # Cycle 1: Price at 0.00902 -> Micro-Guard fires and halves risk to 0.009107
            service.evaluate_active_signals([sig], live_prices={"SIGN/USDT": 0.00902}, now_utc=now)
            expected_sl = 0.009107
            self.assertEqual(sig.sl_price, expected_sl, f"Cycle 1 expected SL {expected_sl}, got {sig.sl_price}")
            self.assertEqual(sig.status, "ACTIVE")

            # Cycles 2, 3, 4, 5: Consecutive daemon scans must NEVER decay the Stop Loss further
            for cycle in range(2, 6):
                service.evaluate_active_signals([sig], live_prices={"SIGN/USDT": 0.00903}, now_utc=now)
                self.assertEqual(
                    sig.sl_price,
                    expected_sl,
                    f"Cycle {cycle} decayed SL! Expected {expected_sl}, but got {sig.sl_price}"
                )
                self.assertEqual(sig.status, "ACTIVE")
        finally:
            if old_be is None:
                os.environ.pop("ENABLE_BREAKEVEN_GUARD", None)
            else:
                os.environ["ENABLE_BREAKEVEN_GUARD"] = old_be

        # Crucial: Spot price touches 0.009056 (which previously killed the trade)
        # Because SL remains protected at 0.009107, 0.009056 is NOT a stop-out!
        service.evaluate_active_signals([sig], live_prices={"SIGN/USDT": 0.009056}, now_utc=now)
        self.assertNotEqual(sig.status, "LOST_SL", "Trade was prematurely stopped out at 0.009056!")
        self.assertEqual(sig.status, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
