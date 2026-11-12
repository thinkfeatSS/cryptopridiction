"""
Quant Edge V16: Anees Mehdi 15M Scalp Pipeline Unit & Integration Suite
Validates persistent rectangle registry, dynamic score hurdle, dual-trigger execution,
strict 1:2.0 R:R enforcement, and admission into PaperTradingBot's 5 Scalp slots.
"""

import unittest
import os
import shutil
import tempfile
import pandas as pd
import numpy as np

from app.quant_v16.rectangle_strategy.strategy_config import RectangleStrategyConfig
from app.quant_v16.rectangle_strategy.rectangle_engine import RectangleEngine, DynamicRectangle, RectangleStatus
from app.quant_v16.rectangle_strategy.weakness_detector import WeaknessConfirmation
from app.quant_v16.rectangle_strategy.liquidity_sweep import LiquiditySweepEvent
from app.quant_v16.rectangle_strategy.m1_entry_engine import M1EntryEngine
from app.quant_v16.rectangle_strategy.strategy_orchestrator import RectangleStrategyOrchestrator
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestAneesMehdi15MScalpPipeline(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_anees_mehdi_")
        self.state_file = os.path.join(self.test_dir, "test_active_rectangles.json")
        self.ledger_file = os.path.join(self.test_dir, "test_ledger.json")
        self.config = RectangleStrategyConfig()
        self.config.min_signal_score = 65.0
        self.engine = RectangleEngine(self.config, state_file=self.state_file)
        self.bot = PaperTradingBot(ledger_file=self.ledger_file)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_weakness(self, symbol="BTC/USDT", direction="BULLISH", close=100.0, low=98.0, high=102.0):
        sw = LiquiditySweepEvent(
            sweep_id=f"SWEEP_{symbol}_{direction}_1",
            direction=direction,
            swept_level_price=99.0,
            swept_level_type="SWING_LOW" if direction == "BULLISH" else "SWING_HIGH",
            swept_swing_idx=5,
            sweep_candle_idx=10,
            sweep_timestamp=1700000000,
            sweep_candle_open=99.0,
            sweep_candle_high=high,
            sweep_candle_low=low,
            sweep_candle_close=close,
            extreme_price=low if direction == "BULLISH" else high,
            sweep_depth=1.0,
            sweep_depth_atr=0.5,
            rejection_wick_size=1.0,
            rejection_wick_pct=0.45,
            wick_to_body_ratio=1.5,
            rejection_strength=8.0,
            is_valid_weakness=True,
            classification="VALID_WEAKNESS",
            sweep_score=15.0
        )
        return WeaknessConfirmation(
            status="CONFIRMED",
            is_confirmed=True,
            confirmation_candle_idx=10,
            confirmation_timestamp=1700000000,
            direction=direction,
            target_swing_level=99.0,
            sweep_event=sw,
            weakness_score=12.0
        )

    def test_01_rectangle_creation_and_multibar_persistence(self):
        """Verifies rectangle creation, symbol registration, and atomic state save/load."""
        weak = self._create_mock_weakness(symbol="ETH/USDT", direction="BULLISH", close=3000.0, low=2950.0)
        df_mock = pd.DataFrame()
        rect = self.engine.create_rectangle("ETH/USDT", weak, df_mock)

        self.assertIsNotNone(rect)
        self.assertEqual(rect.symbol, "ETH/USDT")
        self.assertEqual(rect.direction, "LONG")
        self.assertEqual(rect.upper_boundary, 3000.0)
        self.assertEqual(rect.lower_boundary, 2950.0)
        self.assertEqual(rect.status, RectangleStatus.WAITING_FOR_M1_CONFIRMATION)

        # Verify active rectangle lookup by symbol
        active = self.engine.get_active_rectangle("ETH/USDT")
        self.assertIsNotNone(active)
        self.assertEqual(active.rectangle_id, rect.rectangle_id)

        # Verify atomic disk save & load
        self.assertTrue(os.path.exists(self.state_file))
        new_engine = RectangleEngine(self.config, state_file=self.state_file)
        loaded = new_engine.get_active_rectangle("ETH/USDT")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.upper_boundary, 3000.0)

    def test_02_dynamic_score_hurdle_65_qualification(self):
        """Verifies that setups with score >= 65.0 qualify as VALID under dynamic configuration."""
        from app.quant_v16.rectangle_strategy.signal_scorer import SignalScorer
        scorer = SignalScorer(self.config)

        # Setup with total score 68.0 (Passes >= 65.0 hurdle)
        res = scorer.evaluate_score(
            ema_score=12.0,
            structure_score=12.0,
            sweep_score=15.0,
            wick_score=8.0,
            weakness_score=11.0,
            fvg_score=0.0,
            session_score=0.0,
            m1_flip_score=10.0,
            has_valid_trend=True,
            has_valid_structure=True,
            has_valid_sweep=True,
            has_confirmed_weakness=True,
            has_valid_rectangle=True,
            has_confirmed_m1_flip=True,
            has_valid_sl=True,
            has_min_rr=True
        )
        self.assertTrue(res.mandatory_gates_passed)
        self.assertEqual(res.total_score, 68.0)
        self.assertEqual(res.grade, "VALID")

        # Setup with score 62.0 (Fails < 65.0 hurdle)
        res_low = scorer.evaluate_score(
            ema_score=8.0,
            structure_score=8.0,
            sweep_score=15.0,
            wick_score=8.0,
            weakness_score=11.0,
            fvg_score=0.0,
            session_score=0.0,
            m1_flip_score=10.0,
            has_valid_trend=True,
            has_valid_structure=True,
            has_valid_sweep=True,
            has_confirmed_weakness=True,
            has_valid_rectangle=True,
            has_confirmed_m1_flip=True,
            has_valid_sl=True,
            has_min_rr=True
        )
        self.assertEqual(res_low.total_score, 60.0)
        self.assertEqual(res_low.grade, "REJECTED")

    def test_03_dual_trigger_15m_breakout(self):
        """Verifies that a 15M candle close above upper boundary triggers a valid breakout flip."""
        weak = self._create_mock_weakness(symbol="SOL/USDT", direction="BULLISH", close=100.0, low=95.0)
        df_mock = pd.DataFrame()
        rect = self.engine.create_rectangle("SOL/USDT", weak, df_mock)

        m1_engine = M1EntryEngine(self.config)
        # 15M candle closing above upper boundary (101.5 > 100.0)
        df_15m_breakout = pd.DataFrame([{
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.5,
            "timestamp": 1700000900
        }])

        trigger_res = m1_engine.evaluate_candle_breakout(rect, df_15m_breakout, current_idx=0, timeframe="15m")
        self.assertIsNotNone(trigger_res)
        self.assertTrue(trigger_res.is_triggered)
        self.assertEqual(trigger_res.direction, "LONG")
        self.assertEqual(trigger_res.trigger_price, 101.5)
        self.assertEqual(rect.status, RectangleStatus.ENTRY_CONFIRMED)

    def test_04_paper_trading_admission_to_5_scalp_slots(self):
        """Verifies that Anees Mehdi Rectangle signals are admitted into PaperTradingBot's 5 scalp slots."""
        normal_btc = {"is_ntz_active": False, "regime": "BULL_TREND", "status_code": "NORMAL"}
        self.bot.data["open_positions"] = []

        # Admit up to 5 Anees Mehdi Scalp Signals
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "LINK/USDT"]
        for idx, sym in enumerate(symbols, start=1):
            sig = {
                "signal_id": f"SIG_RECT_SCALP_{idx}",
                "symbol": sym,
                "horizon": "15M",
                "direction": "LONG",
                "entry_price": 100.0 * idx,
                "tp1_price": 105.0 * idx, # 1:2.5 RR
                "sl_price": 98.0 * idx,
                "ev_net": 1.25,
                "quality_grade": "💎 Grade A+ (THE ONLY 1 MINUTE RECTANGLE STRATEGY)",
                "canonical_strategy": "THE_ONLY_1_MINUTE_RECTANGLE_STRATEGY",
                "is_trade_active": True,
                "signal_status": "ACTIVE_SIGNAL"
            }
            admitted = self.bot.admit_signal(sig, btc_shield_state=normal_btc)
            self.assertTrue(admitted, f"Anees Mehdi signal #{idx} ({sym}) must be admitted to Scalp Desk")

        # 6th signal must be rejected (max 5 slots)
        sig_6 = {
            "signal_id": "SIG_RECT_SCALP_6",
            "symbol": "NEAR/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "entry_price": 5.0,
            "tp1_price": 5.5,
            "sl_price": 4.8,
            "ev_net": 1.25,
            "quality_grade": "💎 Grade A+ (THE ONLY 1 MINUTE RECTANGLE STRATEGY)",
            "canonical_strategy": "THE_ONLY_1_MINUTE_RECTANGLE_STRATEGY",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL"
        }
        self.assertFalse(self.bot.admit_signal(sig_6, btc_shield_state=normal_btc), "6th signal must be blocked by slot cap")

    def test_05_invalidation_on_adverse_blowout(self):
        """Verifies that a severe opposite boundary violation invalidates the rectangle."""
        weak = self._create_mock_weakness(symbol="AVAX/USDT", direction="BULLISH", close=50.0, low=48.0)
        df_mock = pd.DataFrame()
        rect = self.engine.create_rectangle("AVAX/USDT", weak, df_mock)

        m1_engine = M1EntryEngine(self.config)
        # Severe crash below lower boundary (46.0 < 48.0 - 1.0)
        df_crash = pd.DataFrame([{
            "open": 49.0,
            "high": 49.5,
            "low": 45.0,
            "close": 46.0,
            "timestamp": 1700000900
        }])

        res = m1_engine.evaluate_candle_breakout(rect, df_crash, current_idx=0, timeframe="15m")
        self.assertIsNone(res)
        self.assertEqual(rect.status, RectangleStatus.INVALIDATED)


if __name__ == "__main__":
    unittest.main()
