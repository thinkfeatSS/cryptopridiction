"""
Quant Edge V16: WhatsApp Full Parity & Automation Test Suite
Verifies signal creation, TP hits, SL invalidations, Breakeven profit-locks, and Market Regime alerts.
"""

import unittest
from unittest.mock import patch, MagicMock
from app.services.whatsapp_service import whatsapp_service
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestWhatsAppFullParity(unittest.TestCase):
    def setUp(self):
        # Configure test state
        whatsapp_service._in_memory_dedup.clear()
        self.sample_signal = {
            "signal_id": "SIG_TEST_BTC_1H",
            "symbol": "BTC/USDT",
            "horizon": "1H",
            "direction": "LONG",
            "quality_grade": "Grade A+",
            "conviction": 88.0,
            "meta_win_prob_pct": 74.5,
            "entry_price": 68000.0,
            "tp1_price": 70000.0,
            "tp2_price": 72000.0,
            "tp3_price": 75000.0,
            "sl_price": 67000.0,
            "risk_reward_ratio": "1:2.0",
            "ev_net": 1.45,
            "strategy_archetype": "ORDER_BLOCK_RETEST_LONG"
        }

    def test_01_format_new_signal_structure_and_ev(self):
        """Verifies that format_new_signal produces institutional terminal-aligned text."""
        msg = whatsapp_service.format_new_signal(self.sample_signal)
        self.assertIn("BTC_USDT", msg)
        self.assertIn("Grade A+", msg)
        self.assertIn("68,000", msg)
        self.assertIn("70,000", msg)
        self.assertIn("67,000", msg)

    def test_02_format_and_emit_tp_hits(self):
        """Verifies TP1, TP2, and TP3 hit message formatting."""
        msg_tp1 = whatsapp_service.format_tp_hit(self.sample_signal, "TP1", 70000.0, 2.94)
        self.assertIn("PROFIT TARGET 1 REACHED", msg_tp1)
        self.assertIn("+2.94%", msg_tp1)

        msg_tp2 = whatsapp_service.format_tp_hit(self.sample_signal, "TP2", 72000.0, 5.88)
        self.assertIn("PROFIT TARGET 2 SMASHED", msg_tp2)

        msg_tp3 = whatsapp_service.format_tp_hit(self.sample_signal, "TP3", 75000.0, 10.29)
        self.assertIn("TP3 WON", msg_tp3)
        self.assertIn("+10.29%", msg_tp3)

    def test_03_format_and_emit_sl_hit(self):
        """Verifies Stop Loss invalidation message formatting."""
        msg_sl = whatsapp_service.format_sl_hit(self.sample_signal, 67000.0, -1.47)
        self.assertIn("STOP-LOSS ALERT", msg_sl)
        self.assertIn("-1.47%", msg_sl)
        self.assertIn("Capital preservation rule executed", msg_sl)

    def test_04_format_and_emit_breakeven_locked_and_hit(self):
        """Verifies Breakeven profit-lock and Breakeven exit message formatting."""
        msg_locked = whatsapp_service.format_breakeven_locked(self.sample_signal, 69000.0, 1.47)
        self.assertIn("BREAK-EVEN MOVED", msg_locked)
        self.assertIn("Guaranteed Risk-Free Trade", msg_locked)

        msg_hit = whatsapp_service.format_trail_or_be_hit(
            self.sample_signal, 68000.0, 0.05, "🛡️ BREAKEVEN (TIER-0 GUARD +0.05%)"
        )
        self.assertIn("BREAK-EVEN EXIT", msg_hit)
        self.assertIn("protected capital", msg_hit)

    def test_05_format_and_emit_market_regime_alert(self):
        """Verifies that market regime alert formats correctly."""
        shield_data = {
            "status_code": "BULL_TREND",
            "regime": "BULL_TREND",
            "reason": "Strong EMA continuation",
            "btc_price": 68500.0,
            "cons_prob": 15.0,
            "posture": "NORMAL"
        }
        msg = whatsapp_service.format_regime_shift(shield_data)
        self.assertIn("BULL_TREND", msg)
        self.assertIn("Strong EMA continuation", msg)

    @patch.object(whatsapp_service, "emit_signal_outcome")
    def test_06_paper_trading_bot_sync_invokes_whatsapp_outcomes(self, mock_emit):
        """Verifies PaperTradingBot._sync_paper_exit_to_audit triggers WhatsApp outcomes."""
        bot = PaperTradingBot()

        # 1. Test Stop-Loss Exit
        sl_record = {
            "trade_id": "TEST_SL_001",
            "symbol": "BTC/USDT",
            "horizon": "1H",
            "exit_reason": "STOP_LOSS",
            "exit_price": 66800.0,
            "return_pct": -1.76,
            "outcome": "LOST"
        }
        bot._sync_paper_exit_to_audit(sl_record)
        mock_emit.assert_called()
        call_args = mock_emit.call_args[0]
        self.assertEqual(call_args[1], "SL_HIT")
        self.assertEqual(call_args[2], 66800.0)

        # 2. Test TP3 Exit
        mock_emit.reset_mock()
        tp3_record = {
            "trade_id": "TEST_TP3_001",
            "symbol": "BTC/USDT",
            "horizon": "1H",
            "exit_reason": "TAKE_PROFIT_3",
            "exit_price": 75000.0,
            "return_pct": 10.29,
            "outcome": "WON"
        }
        bot._sync_paper_exit_to_audit(tp3_record)
        mock_emit.assert_called()
        call_args = mock_emit.call_args[0]
        self.assertEqual(call_args[1], "TP3_HIT")
        self.assertEqual(call_args[2], 75000.0)

        # 3. Test Breakeven Guard Exit
        mock_emit.reset_mock()
        be_record = {
            "trade_id": "TEST_BE_001",
            "symbol": "BTC/USDT",
            "horizon": "1H",
            "exit_reason": "STOP_LOSS_BREAKEVEN",
            "exit_price": 68000.0,
            "return_pct": 0.05,
            "outcome": "BREAKEVEN"
        }
        bot._sync_paper_exit_to_audit(be_record)
        mock_emit.assert_called()
        call_args = mock_emit.call_args[0]
        self.assertEqual(call_args[1], "BE_HIT")
        self.assertEqual(call_args[2], 68000.0)

    def test_07_format_v16_canonical_schema_without_zero_dollars(self):
        """Verifies that format_new_signal formats V16 Terminal canonical schemas with exact prices (zero bare $0.)."""
        v16_sig = {
            "signal_id": "BMT_USDT_15M_1793773328",
            "symbol": "BMT/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "entry_price_initial": 0.02988,
            "tp1_initial": 0.032098,
            "tp2_initial": 0.033207,
            "tp3_initial": 0.034870,
            "sl_initial": 0.028771,
            "grade": "⚖️ Grade A (RANGE ROTATION: 1D Range Mean Reversion)",
            "signal_score": 84.0,
            "expected_net_return": 1.003,
            "total_execution_costs": 0.145,
            "risk_reward": 2.0,
            "p_tp1": 57.9,
            "p_sl": 42.1,
            "regime": "RANGE"
        }
        msg = whatsapp_service.format_new_signal(v16_sig)
        self.assertNotIn("$0.\n", msg)
        self.assertNotIn("Target 1: N/A", msg)
        self.assertIn("$0.029880", msg)
        self.assertIn("$0.032098", msg)
        self.assertIn("$0.033207", msg)
        self.assertIn("$0.034870", msg)
        self.assertIn("$0.028771", msg)
        self.assertIn("+1.00%", msg)
        self.assertIn("1:2.0", msg)

    @patch.object(whatsapp_service, "_enqueue_message")
    def test_08_sync_v16_terminal_signals_dispatches_active_trades(self, mock_enqueue):
        """Verifies that sync_v16_terminal_signals successfully reconciles active V16 terminal trades."""
        mock_imm = {
            "TEST_V16_SYNC_01": {
                "signal_id": "TEST_V16_SYNC_01",
                "symbol": "SOL/USDT",
                "horizon": "1H",
                "direction": "LONG",
                "entry_price_initial": 145.0,
                "tp1_initial": 155.0,
                "tp2_initial": 160.0,
                "tp3_initial": 170.0,
                "sl_initial": 140.0,
                "grade": "Grade A+",
                "expected_net_return": 2.50,
                "status": "ACTIVE"
            }
        }
        mock_dyn = {
            "TEST_V16_SYNC_01": {
                "status": "ACTIVE",
                "outcome_label": "RUNNING 🚀",
                "current_price": 148.0
            }
        }
        with patch("app.routers.v16_router._get_v16_store", return_value=(mock_imm, mock_dyn)):
            dispatched = whatsapp_service.sync_v16_terminal_signals()
            self.assertEqual(dispatched, 1)
            mock_enqueue.assert_called()
            # Verify deduplication
            dispatched_again = whatsapp_service.sync_v16_terminal_signals()
            self.assertEqual(dispatched_again, 0)

    @patch.object(whatsapp_service, "emit_signal_created")
    def test_09_paper_trading_bot_entry_dispatches_whatsapp_created(self, mock_created):
        """Verifies that PaperTradingBot.admit_signal invokes emit_signal_created upon execution."""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tmp_path = tf.name
        try:
            bot = PaperTradingBot(ledger_file=tmp_path)
            sample_entry = {
                "symbol": "AVAX/USDT",
                "dominant_timeframe": "1H",
                "dominant_direction": "LONG",
                "direction": "LONG",
                "is_trade_active": True,
                "signal_status": "ACTIVE_SIGNAL",
                "entry_price": 30.0,
                "current_price": 30.0,
                "tp1_price": 32.0,
                "tp2_price": 34.0,
                "tp3_price": 36.0,
                "sl_price": 29.0,
                "quality_grade": "Grade A+",
                "conviction": 90.0,
                "expected_return_pct": 1.50,
                "ev_net": 1.50,
                "risk_reward_ratio": "1:2.0"
            }
            admitted = bot.admit_signal(sample_entry)
            self.assertTrue(admitted)
            mock_created.assert_called()
            dispatched_sig = mock_created.call_args[0][0]
            self.assertEqual(dispatched_sig.get("symbol"), "AVAX/USDT")
            self.assertTrue(dispatched_sig.get("is_trade_active"))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
