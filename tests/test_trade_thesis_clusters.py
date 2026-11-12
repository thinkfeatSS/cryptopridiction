import unittest
import os
import json
import tempfile
import shutil
from typing import Dict, Any

from app.quant_v16.thesis import (
    TradeThesisEngine,
    TradeThesis,
    normalize_horizon,
    CANONICAL_HORIZONS,
    HORIZON_SORT_ORDER,
    get_thesis_engine
)
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.services.whatsapp_service import WhatsAppService
from fastapi.testclient import TestClient
from app.main import app


class TestTradeThesisClusters(unittest.TestCase):
    """
    Forensic verification suite for Trade Thesis Clustering & Correlation Deduplication:
    1. Multi-horizon signal clustering under canonical root ID (THESIS-SYMBOL-DIRECTION).
    2. Horizon normalization across noisy/emoji display inputs to canonical timeframes.
    3. Dynamic thesis strength escalation based on multi-horizon confirmation.
    4. Zero Stacking Guard (Section 27): max 1 executed position per thesis.
    5. Thesis position lifecycle transitions (open, close, resolution).
    6. Atomic disk persistence and rehydration (trade_theses.json).
    7. Reconciliation and synchronization from audit ledger records.
    8. PaperTradingBot admission blocking on active thesis duplication.
    9. REST API /api/v16/theses contract and canonical horizon ordering.
    10. WhatsApp alert message canonical thesis identifier formatting.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_thesis_export_")
        self.engine = TradeThesisEngine(export_dir=self.test_dir)
        self.test_ledger_file = os.path.join(self.test_dir, "test_paper_ledger.json")

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir, ignore_errors=True)
        except Exception:
            pass

    def test_multi_horizon_signal_clustering_and_canonical_id(self):
        """Verifies multi-horizon signals on same asset & direction cluster into 1 root thesis."""
        # 1st signal: 15M
        th1, is_new1 = self.engine.register_or_update(
            symbol="BTC/USDT",
            direction="LONG",
            horizon="15M",
            strategy="BREAKOUT_LONG",
            regime="BULL_TREND",
            expected_net_return=0.85,
            signal_id="SIG-BTC-15M"
        )
        self.assertTrue(is_new1)
        self.assertEqual(th1.thesis_id, "THESIS-BTCUSDT-LONG")
        self.assertEqual(th1.participating_horizons, ["15M"])
        self.assertEqual(th1.signals, ["SIG-BTC-15M"])
        self.assertEqual(th1.signals_count, 1)

        # 2nd signal: 1H on same asset & direction
        th2, is_new2 = self.engine.register_or_update(
            symbol="BTCUSDT",
            direction="LONG",
            horizon="1H",
            strategy="TREND_FOLLOWING",
            regime="BULL_TREND",
            expected_net_return=1.20,
            signal_id="SIG-BTC-1H"
        )
        self.assertFalse(is_new2)
        self.assertEqual(th2.thesis_id, "THESIS-BTCUSDT-LONG")
        self.assertIn("1H", th2.participating_horizons)
        self.assertEqual(th2.signals_count, 2)
        self.assertEqual(th2.highest_net_ev, 1.20)

        # 3rd signal: 4H
        th3, is_new3 = self.engine.register_or_update(
            symbol="BTC/USDT",
            direction="LONG",
            horizon="4H",
            strategy="BREAKOUT_LONG",
            regime="BULL_TREND",
            expected_net_return=1.50,
            signal_id="SIG-BTC-4H"
        )
        self.assertFalse(is_new3)
        self.assertEqual(th3.thesis_id, "THESIS-BTCUSDT-LONG")
        self.assertEqual(th3.participating_horizons, ["15M", "1H", "4H"])
        self.assertEqual(th3.signals_count, 3)

        # 4th signal: Opposite direction (SHORT) must form a distinct independent thesis
        th_short, is_new_short = self.engine.register_or_update(
            symbol="BTC/USDT",
            direction="SHORT",
            horizon="15M",
            strategy="MEAN_REVERSION_SHORT",
            regime="CHOPPY",
            expected_net_return=0.75,
            signal_id="SIG-BTC-SHORT-15M"
        )
        self.assertTrue(is_new_short)
        self.assertEqual(th_short.thesis_id, "THESIS-BTCUSDT-SHORT")

    def test_horizon_normalization_edge_cases(self):
        """Verifies robust normalization of dirty, emoji, and alias strings into canonical horizons."""
        test_cases = [
            ("⏳ Intraday (4H)", "4H"),
            ("🌊 Swing (1H)", "1H"),
            ("🌗 12H", "12H"),
            ("⚡ 15M Scalp", "15M"),
            ("5M", "5M"),
            ("24H Daily", "24H"),
            ("1D", "24H"),
            ("DAILY", "24H"),
            ("SWING", "24H"),
            ("SCALP", "15M"),
            ("INTRADAY", "1H"),
            ("MACRO", "24H"),
            ("7D", "7D"),
            ("15D", "15D"),
            ("1M", "1M"),
            (None, "1H"),
            ("", "1H"),
            ("UNKNOWN", "1H")
        ]
        for raw, expected in test_cases:
            normalized = normalize_horizon(raw)
            self.assertEqual(normalized, expected, f"Failed normalizing '{raw}': expected {expected}, got {normalized}")
            self.assertIn(normalized, CANONICAL_HORIZONS)

    def test_dynamic_thesis_strength_scaling(self):
        """Verifies dynamic thesis strength scaling from base 75.0 up to 100.0 with multi-horizon confirmation."""
        # 1 horizon: base 75.0
        th, _ = self.engine.register_or_update("ETH/USDT", "LONG", "15M", "TREND", "BULL", 0.90, "SIG-ETH-15M")
        self.assertEqual(th.thesis_strength, 75.0)

        # Duplicate signal on SAME horizon should NOT inflate strength or horizon count
        th, _ = self.engine.register_or_update("ETH/USDT", "LONG", "15M", "TREND", "BULL", 0.90, "SIG-ETH-15M-BIS")
        self.assertEqual(th.thesis_strength, 75.0)
        self.assertEqual(len(th.participating_horizons), 1)

        # 2nd horizon: +5.0 -> 80.0
        th, _ = self.engine.register_or_update("ETH/USDT", "LONG", "1H", "TREND", "BULL", 0.95, "SIG-ETH-1H")
        self.assertEqual(th.thesis_strength, 80.0)

        # 3rd horizon: +5.0 -> 85.0
        th, _ = self.engine.register_or_update("ETH/USDT", "LONG", "4H", "TREND", "BULL", 1.05, "SIG-ETH-4H")
        self.assertEqual(th.thesis_strength, 85.0)

        # 4th horizon: +5.0 -> 90.0
        th, _ = self.engine.register_or_update("ETH/USDT", "LONG", "12H", "TREND", "BULL", 1.15, "SIG-ETH-12H")
        self.assertEqual(th.thesis_strength, 90.0)

        # 5th horizon: +5.0 -> 95.0
        th, _ = self.engine.register_or_update("ETH/USDT", "LONG", "24H", "TREND", "BULL", 1.25, "SIG-ETH-24H")
        self.assertEqual(th.thesis_strength, 95.0)

        # 6th horizon: +5.0 -> 100.0 (ceiling)
        th, _ = self.engine.register_or_update("ETH/USDT", "LONG", "7D", "TREND", "BULL", 1.35, "SIG-ETH-7D")
        self.assertEqual(th.thesis_strength, 100.0)

        # 7th horizon: capped at 100.0
        th, _ = self.engine.register_or_update("ETH/USDT", "LONG", "15D", "TREND", "BULL", 1.40, "SIG-ETH-15D")
        self.assertEqual(th.thesis_strength, 100.0)

    def test_zero_stacking_guard_admission_control(self):
        """Verifies Section 27 Zero Stacking Guard: max 1 executed position per thesis."""
        th, _ = self.engine.register_or_update("SOL/USDT", "LONG", "1H", "BREAKOUT", "BULL", 1.10)
        th_id = th.thesis_id

        # 1. Initially eligible
        can_open, reason = self.engine.can_open_position(th_id, symbol="SOL/USDT")
        self.assertTrue(can_open)
        self.assertEqual(reason, "Eligible")

        # 2. Mark position opened
        self.engine.mark_position_opened(th_id, trade_id="TR-SOL-001")
        self.assertTrue(th.is_position_open)

        # 3. Subsequent check blocked by thesis
        can_open_2, reason_2 = self.engine.can_open_position(th_id, symbol="SOL/USDT")
        self.assertFalse(can_open_2)
        self.assertIn("already has an open executed position", reason_2)

        # 4. Check blocked by asset rule even if checked by unmapped/variant ID
        can_open_3, reason_3 = self.engine.can_open_position("THESIS-SOLUSDT-UNMAPPED", symbol="SOL/USDT")
        self.assertFalse(can_open_3)
        self.assertIn("Max 1 per asset rule", reason_3)

        # 5. Position closed -> releases execution cap
        self.engine.mark_position_closed(th_id, exit_price=150.0, pnl_pct=3.5)
        self.assertFalse(th.is_position_open)
        self.assertEqual(th.current_price, 150.0)
        self.assertEqual(th.unrealized_net_pnl_pct, 3.5)

        can_open_4, reason_4 = self.engine.can_open_position(th_id, symbol="SOL/USDT")
        self.assertTrue(can_open_4)
        self.assertEqual(reason_4, "Eligible")

    def test_thesis_resolution_lifecycle(self):
        """Verifies thesis resolution when signals terminate."""
        th, _ = self.engine.register_or_update("AVAX/USDT", "LONG", "1H", "TREND", "BULL", 0.90, "SIG-AVAX-1")
        th_id = th.thesis_id
        self.assertTrue(th.is_active)

        self.engine.resolve_thesis(th_id)
        self.assertFalse(th.is_active)
        self.assertFalse(th.is_position_open)
        self.assertEqual(th.active_signals_count, 0)

        # After resolution, symbol_direction_map is cleared for fresh cycles
        self.assertNotIn(("AVAXUSDT", "LONG"), self.engine.symbol_direction_map)

    def test_atomic_disk_persistence_and_reload(self):
        """Verifies atomic JSON disk persistence and rehydration without state loss."""
        # Create multiple theses
        self.engine.register_or_update("BNB/USDT", "LONG", "1H", "TREND", "BULL", 1.2, "SIG-BNB-1H")
        self.engine.register_or_update("BNB/USDT", "LONG", "4H", "TREND", "BULL", 1.5, "SIG-BNB-4H")
        self.engine.register_or_update("XRP/USDT", "SHORT", "15M", "REVERSION", "BEAR", 0.8, "SIG-XRP-15M")

        bnb_th = self.engine.get_thesis("THESIS-BNBUSDT-LONG")
        self.engine.mark_position_opened("THESIS-BNBUSDT-LONG", trade_id="TR-BNB-1")

        # Save to disk
        self.engine.save_theses_to_disk()

        cache_path = os.path.join(self.test_dir, "trade_theses.json")
        self.assertTrue(os.path.exists(cache_path))

        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["total_theses"], 2)
        self.assertEqual(data["active_theses_count"], 2)
        theses_dict = {t["thesis_id"]: t for t in data["theses"]}
        self.assertIn("THESIS-BNBUSDT-LONG", theses_dict)
        self.assertIn("THESIS-XRPUSDT-SHORT", theses_dict)
        self.assertTrue(theses_dict["THESIS-BNBUSDT-LONG"]["is_position_open"])
        self.assertEqual(theses_dict["THESIS-BNBUSDT-LONG"]["participating_horizons"], ["1H", "4H"])

        # Reload in a brand new engine instance pointing to same export dir
        new_engine = TradeThesisEngine(export_dir=self.test_dir)
        loaded_bnb = new_engine.get_thesis("THESIS-BNBUSDT-LONG")
        self.assertIsNotNone(loaded_bnb)
        self.assertEqual(loaded_bnb.participating_horizons, ["1H", "4H"])
        self.assertTrue(loaded_bnb.is_position_open)
        self.assertEqual(loaded_bnb.signals, ["SIG-BNB-1H", "SIG-BNB-4H"])

    def test_sync_from_audit_records_reconciliation(self):
        """Verifies sync_from_audit_records parses ledger records and reconciles open positions."""
        audit_records = [
            {
                "signal_id": "SIG-ADA-1",
                "symbol": "ADA/USDT",
                "direction": "LONG",
                "horizon": "⏳ Intraday (4H)",
                "strategy_archetype": "BREAKOUT",
                "market_shield": "BULL",
                "expected_return_pct": 1.1,
                "status": "PENDING"
            },
            {
                "signal_id": "SIG-ADA-2",
                "symbol": "ADA/USDT",
                "direction": "LONG",
                "horizon": "🌊 Swing (1H)",
                "strategy_archetype": "BREAKOUT",
                "market_shield": "BULL",
                "expected_return_pct": 1.3,
                "status": "WON_TIER1_TP1"
            },
            {
                "signal_id": "SIG-DOGE-1",
                "symbol": "DOGE/USDT",
                "direction": "SHORT",
                "horizon": "15M",
                "strategy_archetype": "PULLBACK",
                "market_shield": "CHOPPY",
                "expected_return_pct": 0.9,
                "status": "PENDING"
            }
        ]

        open_positions = [
            {"trade_thesis_id": "THESIS-ADAUSDT-LONG", "symbol": "ADA/USDT", "direction": "LONG"}
        ]

        self.engine.sync_from_audit_records(audit_records, open_positions=open_positions)

        ada_th = self.engine.get_thesis("THESIS-ADAUSDT-LONG")
        self.assertIsNotNone(ada_th)
        # Horizons normalized and sorted: ["1H", "4H"]
        self.assertEqual(ada_th.participating_horizons, ["1H", "4H"])
        self.assertTrue(ada_th.is_position_open)
        # One signal pending, one won -> active signals count is 1
        self.assertEqual(ada_th.active_signals_count, 1)

        doge_th = self.engine.get_thesis("THESIS-DOGEUSDT-SHORT")
        self.assertIsNotNone(doge_th)
        self.assertFalse(doge_th.is_position_open)

    def test_paper_trading_bot_zero_stacking_enforcement(self):
        """Verifies PaperTradingBot enforces Zero Stacking Guard on trade_thesis_id."""
        bot = PaperTradingBot(ledger_file=self.test_ledger_file)
        bot.data["open_positions"] = []

        # Signal 1: LINK LONG on 15M
        sig1 = {
            "signal_id": "SIG-LINK-15M",
            "trade_id": "SIG-LINK-15M",
            "symbol": "LINK/USDT",
            "dominant_direction": "LONG",
            "direction": "LONG",
            "dominant_timeframe": "15M",
            "horizon": "15M",
            "active_signal_horizon": "15M",
            "trade_thesis_id": "THESIS-LINKUSDT-LONG",
            "entry_price": 15.0,
            "tp1_price": 16.0,
            "tp2_price": 16.5,
            "tp3_price": 17.0,
            "sl_price": 14.5,
            "signal_score": 92.0,
            "ev_net": 1.2,
            "grade": "Grade A+",
            "quality_grade": "Grade A+",
            "meta_win_prob_pct": 75.0,
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL"
        }

        # Admit Signal 1
        admitted1 = bot.admit_signal(sig1)
        self.assertTrue(admitted1, "Signal 1 should be admitted")
        self.assertEqual(len(bot.data["open_positions"]), 1)
        pos1 = bot.data["open_positions"][0]
        self.assertEqual(pos1.get("trade_thesis_id"), "THESIS-LINKUSDT-LONG")

        # Signal 2: LINK LONG on 1H (same thesis cluster)
        sig2 = {
            "signal_id": "SIG-LINK-1H",
            "trade_id": "SIG-LINK-1H",
            "symbol": "LINK/USDT",
            "dominant_direction": "LONG",
            "direction": "LONG",
            "dominant_timeframe": "1H",
            "horizon": "1H",
            "active_signal_horizon": "1H",
            "trade_thesis_id": "THESIS-LINKUSDT-LONG",
            "entry_price": 15.1,
            "tp1_price": 16.2,
            "tp2_price": 16.8,
            "tp3_price": 17.2,
            "sl_price": 14.6,
            "signal_score": 94.0,
            "ev_net": 1.4,
            "grade": "Grade A+",
            "quality_grade": "Grade A+",
            "meta_win_prob_pct": 75.0,
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL"
        }

        # Admit Signal 2: MUST be blocked by Zero Stacking Guard
        admitted2 = bot.admit_signal(sig2)
        self.assertFalse(admitted2, "Signal 2 must be blocked by Section 27 Zero Stacking Guard")
        self.assertEqual(len(bot.data["open_positions"]), 1)

        # Signal 3: NEAR LONG (different thesis cluster)
        sig3 = {
            "signal_id": "SIG-NEAR-1H",
            "trade_id": "SIG-NEAR-1H",
            "symbol": "NEAR/USDT",
            "dominant_direction": "LONG",
            "direction": "LONG",
            "dominant_timeframe": "1H",
            "horizon": "1H",
            "active_signal_horizon": "1H",
            "trade_thesis_id": "THESIS-NEARUSDT-LONG",
            "entry_price": 5.0,
            "tp1_price": 5.5,
            "tp2_price": 5.8,
            "tp3_price": 6.2,
            "sl_price": 4.7,
            "signal_score": 90.0,
            "ev_net": 1.1,
            "grade": "Grade A+",
            "quality_grade": "Grade A+",
            "meta_win_prob_pct": 75.0,
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL"
        }

        admitted3 = bot.admit_signal(sig3)
        self.assertTrue(admitted3, "Signal 3 on different thesis should be admitted")
        self.assertEqual(len(bot.data["open_positions"]), 2)
        self.assertEqual(bot.data["open_positions"][1].get("trade_thesis_id"), "THESIS-NEARUSDT-LONG")

    def test_api_v16_theses_endpoint_contract(self):
        """Verifies GET /api/v16/theses returns valid contract with canonical horizons."""
        client = TestClient(app)
        res = client.get("/api/v16/theses")
        self.assertEqual(res.status_code, 200)

        data = res.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("total_theses", data)
        self.assertIn("active_theses_count", data)
        self.assertIn("data", data)
        self.assertIsInstance(data["data"], list)

        # Verify each thesis item conforms to strict contract
        for th in data["data"]:
            self.assertIn("thesis_id", th)
            self.assertTrue(th["thesis_id"].startswith("THESIS-"))
            self.assertIn("symbol", th)
            self.assertIn("direction", th)
            self.assertIn("participating_horizons", th)
            # Ensure every participating horizon is canonical
            for hz in th["participating_horizons"]:
                self.assertIn(hz, CANONICAL_HORIZONS)
                # Ensure no emojis or raw labels leak into horizon list
                self.assertNotIn("⏳", hz)
                self.assertNotIn("🌊", hz)
                self.assertNotIn("Intraday", hz)

    def test_whatsapp_service_canonical_thesis_formatting(self):
        """Verifies WhatsAppService formats canonical thesis identifier properly."""
        sig = {
            "signal_id": "SIG-TEST-WA",
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "trade_thesis_id": "THESIS-BTCUSDT-LONG",
            "horizon": "1H",
            "entry_price": 68000.0,
            "sl": 67000.0,
            "tp1": 69000.0,
            "tp2": 70000.0,
            "tp3": 72000.0,
            "expected_net_return": 1.25,
            "signal_score": 95.0,
            "regime": "BULL_TREND"
        }

        wa = WhatsAppService()
        msg = wa.format_new_signal(sig)
        self.assertIn("THESIS-BTCUSDT-LONG", msg)
        self.assertNotIn("THESIS-BTCUSDT-LONG-2026", msg)


if __name__ == "__main__":
    unittest.main()
