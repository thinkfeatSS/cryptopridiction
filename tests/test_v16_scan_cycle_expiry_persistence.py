import unittest
import sys
import os
import tempfile
import json
import shutil
import csv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.signal import SignalAudit

class TestV16ScanCycleExpiryPersistence(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dyn_file = os.path.join(self.test_dir, "v16_dynamic_states.json")
        self.imm_file = os.path.join(self.test_dir, "v16_immutable_signals.json")
        self.csv_file = os.path.join(self.test_dir, "trader_signals_tracker.csv")

        # Initialize test state files
        initial_dyn = {
            "SIG_TEST_EXP_1": {
                "signal_id": "SIG_TEST_EXP_1",
                "symbol": "TEST/USDT",
                "horizon": "1H",
                "status": "ACTIVE",
                "outcome_label": "RUNNING 🚀",
                "current_price": 10.0,
                "exit_price": None,
                "realized_return_pct": None,
                "unrealized_net_pnl_pct": 0.0,
            }
        }
        with open(self.dyn_file, "w", encoding="utf-8") as f:
            json.dump(initial_dyn, f)

        initial_imm = {
            "SIG_TEST_EXP_1": {
                "signal_id": "SIG_TEST_EXP_1",
                "symbol": "TEST/USDT",
                "horizon": "1H",
                "status": "ACTIVE",
            }
        }
        with open(self.imm_file, "w", encoding="utf-8") as f:
            json.dump(initial_imm, f)

        # Initialize mock CSV
        with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "signal_id", "symbol", "horizon", "direction", "entry_price",
                "status", "outcome_label", "exit_price", "realized_return_pct",
                "evaluated_at_utc", "sl_price"
            ])
            writer.writeheader()
            writer.writerow({
                "signal_id": "SIG_TEST_EXP_1",
                "symbol": "TEST/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price": 10.0,
                "status": "ACTIVE",
                "outcome_label": "RUNNING 🚀",
                "exit_price": "",
                "realized_return_pct": "",
                "evaluated_at_utc": "",
                "sl_price": 9.0
            })

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sync_updates_persists_exit_and_return_to_dynamic_states(self):
        """Verifies that signal_service._sync_updates_to_tracker_csv writes exit_price and realized_return_pct to JSON."""
        from app.services.signal_service import signal_service
        from app.config import settings

        old_export = settings.EXPORT_DIR
        try:
            settings.EXPORT_DIR = self.test_dir

            # Create mock signal
            sig = SignalAudit(
                id=10,
                signal_id="SIG_TEST_EXP_1",
                symbol="TEST/USDT",
                horizon="1H",
                direction="LONG",
                entry_price=10.0,
                status="EXPIRED_HORIZON",
                outcome_label="⏱️ EXPIRED",
                exit_price=10.0,
                realized_return_pct=0.0,
                evaluated_at_utc="2026-10-27 15:00:00 UTC",
            )

            signal_service._sync_updates_to_tracker_csv([sig])

            with open(self.dyn_file, "r", encoding="utf-8") as f:
                saved_dyn = json.load(f)

            entry = saved_dyn["SIG_TEST_EXP_1"]
            self.assertEqual(entry["status"], "EXPIRED_HORIZON")
            self.assertEqual(entry["outcome_label"], "⏱️ EXPIRED")
            self.assertEqual(entry["exit_price"], 10.0)
            self.assertEqual(entry["realized_return_pct"], 0.0)

            with open(self.imm_file, "r", encoding="utf-8") as f:
                saved_imm = json.load(f)
            self.assertEqual(saved_imm["SIG_TEST_EXP_1"]["status"], "EXPIRED_HORIZON")

            # Check CSV row
            with open(self.csv_file, "r", encoding="utf-8") as f:
                reader = list(csv.DictReader(f))
            self.assertEqual(len(reader), 1)
            self.assertEqual(reader[0]["status"], "EXPIRED_HORIZON")
            self.assertEqual(reader[0]["outcome_label"], "⏱️ EXPIRED")
            self.assertEqual(float(reader[0]["exit_price"]), 10.0)
            self.assertEqual(float(reader[0]["realized_return_pct"]), 0.0)
        finally:
            settings.EXPORT_DIR = old_export

if __name__ == "__main__":
    unittest.main()
