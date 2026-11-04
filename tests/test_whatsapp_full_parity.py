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


if __name__ == "__main__":
    unittest.main()
