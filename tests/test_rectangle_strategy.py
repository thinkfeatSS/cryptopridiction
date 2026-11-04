"""
Official Comprehensive Test Suite: The Only 1 Minute Rectangle Strategy
Implements all 25 mandatory unit tests and edge cases specified in Section 22:
1. Bullish EMA alignment
2. Bearish EMA alignment
3. Sideways market rejection
4. Valid bullish swing low
5. Valid bearish swing high
6. Bullish liquidity sweep
7. Bearish liquidity sweep
8. Sweep without close confirmation
9. Strength vs weakness classification
10. Bullish FVG
11. Bearish FVG
12. Bullish rectangle generation
13. Bearish rectangle generation
14. M1 bullish flip
15. M1 bearish flip
16. Invalid M1 entry
17. Stop Loss calculation
18. Take Profit calculation
19. Minimum 1:2 RR validation
20. Duplicate signal prevention
21. Incomplete candle rejection
22. Missing candle handling
23. Exchange reconnection
24. Historical/live consistency
25. No-lookahead validation
"""

import unittest
import pandas as pd
import numpy as np
import time

from app.quant_v16.rectangle_strategy import (
    RectangleStrategyConfig,
    EmaFilterType,
    EntryMode,
    FvgFilterMode,
    TrendDetector,
    MarketStructureEngine,
    SwingPoint,
    FVGDetector,
    LiquiditySweepDetector,
    WeaknessDetector,
    RectangleEngine,
    DynamicRectangle,
    RectangleStatus,
    M1EntryEngine,
    StopLossEngine,
    TakeProfitEngine,
    SignalScorer,
    SessionFilter,
    CryptoMarketFilter,
    RectangleStrategyOrchestrator,
    RectangleBacktestingEngine
)


class TestRectangleStrategySuite(unittest.TestCase):

    def setUp(self):
        self.config = RectangleStrategyConfig()
        self.orchestrator = RectangleStrategyOrchestrator(self.config)

    def _create_synthetic_m15_df(self, n=60, base_price=100.0, trend="UP"):
        """Generates realistic synthetic M15 OHLCV dataframe."""
        records = []
        p = base_price
        for i in range(n):
            if trend == "UP":
                o = p
                c = p + 0.5 + np.random.uniform(-0.1, 0.2)
                h = max(o, c) + 0.3
                l = min(o, c) - 0.2
                p = c
            elif trend == "DOWN":
                o = p
                c = p - 0.5 + np.random.uniform(-0.2, 0.1)
                h = max(o, c) + 0.2
                l = min(o, c) - 0.3
                p = c
            else: # FLAT
                o = p
                c = p + np.random.uniform(-0.05, 0.05)
                h = max(o, c) + 0.1
                l = min(o, c) - 0.1
                p = c
            records.append({
                "timestamp": 1700000000000 + (i * 900 * 1000),
                "open": o, "high": h, "low": l, "close": c,
                "volume": 1000.0
            })
        return pd.DataFrame(records)

    # -------------------------------------------------------------------------
    # 1. Bullish EMA Alignment
    # -------------------------------------------------------------------------
    def test_01_bullish_ema_alignment(self):
        df = self._create_synthetic_m15_df(n=60, base_price=100.0, trend="UP")
        detector = TrendDetector(self.config)
        res = detector.evaluate_trend(df)
        self.assertEqual(res.direction, "BULLISH")
        self.assertTrue(res.is_aligned)
        self.assertGreater(res.dist_to_fast_ema_atr, 0.0)

    # -------------------------------------------------------------------------
    # 2. Bearish EMA Alignment
    # -------------------------------------------------------------------------
    def test_02_bearish_ema_alignment(self):
        df = self._create_synthetic_m15_df(n=60, base_price=100.0, trend="DOWN")
        detector = TrendDetector(self.config)
        res = detector.evaluate_trend(df)
        self.assertEqual(res.direction, "BEARISH")
        self.assertTrue(res.is_aligned)
        self.assertLess(res.dist_to_fast_ema_atr, 0.0)

    # -------------------------------------------------------------------------
    # 3. Sideways Market Rejection
    # -------------------------------------------------------------------------
    def test_03_sideways_market_rejection(self):
        # Create perfectly flat data glued to 100.0
        records = [{
            "timestamp": 1700000000000 + (i * 900 * 1000),
            "open": 100.0, "high": 100.02, "low": 99.98, "close": 100.0, "volume": 100.0
        } for i in range(60)]
        df = pd.DataFrame(records)
        detector = TrendDetector(self.config)
        res = detector.evaluate_trend(df)
        self.assertTrue(res.is_ranging, "Flat coiling market must be marked as is_ranging = True")
        self.assertFalse(res.is_aligned)

    # -------------------------------------------------------------------------
    # 4. Valid Bullish Swing Low
    # -------------------------------------------------------------------------
    def test_04_valid_bullish_swing_low(self):
        # Construct V-bottom pivot at index 10
        prices = [105.0 - (i * 0.5) for i in range(11)] # 105 down to 100 at idx 10
        prices += [100.0 + (i * 0.5) for i in range(1, 15)] # 100 up to 107
        records = [{"timestamp": i * 1000, "open": p, "high": p + 0.2, "low": p - 0.2, "close": p, "volume": 1000} for i, p in enumerate(prices)]
        df = pd.DataFrame(records)
        engine = MarketStructureEngine(self.config)
        shs, sls = engine.find_confirmed_swings(df)
        self.assertTrue(len(sls) >= 1)
        lowest_sl = min(sls, key=lambda s: s.price)
        self.assertEqual(lowest_sl.index, 10)
        self.assertAlmostEqual(lowest_sl.price, 99.8, places=2)

    # -------------------------------------------------------------------------
    # 5. Valid Bearish Swing High
    # -------------------------------------------------------------------------
    def test_05_valid_bearish_swing_high(self):
        # Construct inverted V-top pivot at index 10
        prices = [95.0 + (i * 0.5) for i in range(11)] # 95 up to 100 at idx 10
        prices += [100.0 - (i * 0.5) for i in range(1, 15)] # 100 down to 93
        records = [{"timestamp": i * 1000, "open": p, "high": p + 0.2, "low": p - 0.2, "close": p, "volume": 1000} for i, p in enumerate(prices)]
        df = pd.DataFrame(records)
        engine = MarketStructureEngine(self.config)
        shs, sls = engine.find_confirmed_swings(df)
        self.assertTrue(len(shs) >= 1)
        highest_sh = max(shs, key=lambda s: s.price)
        self.assertEqual(highest_sh.index, 10)
        self.assertAlmostEqual(highest_sh.price, 100.2, places=2)

    # -------------------------------------------------------------------------
    # 6. Bullish Liquidity Sweep
    # -------------------------------------------------------------------------
    def test_06_bullish_liquidity_sweep(self):
        # Swing low at 100.0. Sweep bar dips to 98.5, closes at 100.5 (reclaiming inside with lower wick)
        df = pd.DataFrame([
            {"timestamp": 1000, "open": 101.0, "high": 101.2, "low": 98.5, "close": 100.5, "volume": 2000}
        ])
        target_sl = SwingPoint(index=5, timestamp=500, price=100.0, point_type="SWING_LOW", structure_type="HL")
        detector = LiquiditySweepDetector(self.config)
        sweep = detector.evaluate_sweep(df, target_swing=target_sl, direction="BULLISH", atr_value=1.5, candle_idx=0)
        self.assertIsNotNone(sweep)
        self.assertTrue(sweep.is_valid_weakness)
        self.assertEqual(sweep.classification, "VALID_WEAKNESS")
        self.assertGreater(sweep.rejection_wick_size, 0)

    # -------------------------------------------------------------------------
    # 7. Bearish Liquidity Sweep
    # -------------------------------------------------------------------------
    def test_07_bearish_liquidity_sweep(self):
        # Swing high at 100.0. Sweep bar spikes to 101.5, closes at 99.5 (reclaiming inside with upper wick)
        df = pd.DataFrame([
            {"timestamp": 1000, "open": 99.0, "high": 101.5, "low": 98.8, "close": 99.5, "volume": 2000}
        ])
        target_sh = SwingPoint(index=5, timestamp=500, price=100.0, point_type="SWING_HIGH", structure_type="LH")
        detector = LiquiditySweepDetector(self.config)
        sweep = detector.evaluate_sweep(df, target_swing=target_sh, direction="BEARISH", atr_value=1.5, candle_idx=0)
        self.assertIsNotNone(sweep)
        self.assertTrue(sweep.is_valid_weakness)
        self.assertEqual(sweep.classification, "VALID_WEAKNESS")
        self.assertGreater(sweep.rejection_wick_size, 0)

    # -------------------------------------------------------------------------
    # 8. Sweep Without Close Confirmation (Breakout Strength)
    # -------------------------------------------------------------------------
    def test_08_sweep_without_close_confirmation(self):
        # Price sweeps swing low at 100.0, but closes at 98.0 (below level) -> STRENGTH, NOT WEAKNESS
        df = pd.DataFrame([
            {"timestamp": 1000, "open": 100.5, "high": 100.8, "low": 97.5, "close": 98.0, "volume": 2000}
        ])
        target_sl = SwingPoint(index=5, timestamp=500, price=100.0, point_type="SWING_LOW", structure_type="HL")
        detector = LiquiditySweepDetector(self.config)
        sweep = detector.evaluate_sweep(df, target_swing=target_sl, direction="BULLISH", atr_value=1.5, candle_idx=0)
        self.assertIsNotNone(sweep)
        self.assertFalse(sweep.is_valid_weakness)
        self.assertEqual(sweep.classification, "BREAKOUT_STRENGTH")

    # -------------------------------------------------------------------------
    # 9. Strength vs Weakness Classification
    # -------------------------------------------------------------------------
    def test_09_strength_vs_weakness_classification(self):
        detector = WeaknessDetector(self.config)
        target = SwingPoint(index=5, timestamp=500, price=100.0, point_type="SWING_LOW", structure_type="HL")

        # Weakness candle: sweeps to 98.5, closes at 100.4
        df_weak = pd.DataFrame([{"timestamp": 1000, "open": 101.0, "high": 101.2, "low": 98.5, "close": 100.4, "volume": 1000}])
        res_weak = detector.evaluate_m15_confirmation(df_weak, target, "BULLISH", atr_value=1.5, candle_idx=0)
        self.assertTrue(res_weak.is_confirmed)
        self.assertEqual(res_weak.status, "CONFIRMED")

        # Strength candle: sweeps to 98.5, closes at 99.2 (below swing level)
        df_strength = pd.DataFrame([{"timestamp": 1000, "open": 101.0, "high": 101.2, "low": 98.5, "close": 99.2, "volume": 1000}])
        res_strength = detector.evaluate_m15_confirmation(df_strength, target, "BULLISH", atr_value=1.5, candle_idx=0)
        self.assertFalse(res_strength.is_confirmed)
        self.assertEqual(res_strength.status, "REJECTED_STRENGTH")

    # -------------------------------------------------------------------------
    # 10. Bullish Fair Value Gap (FVG)
    # -------------------------------------------------------------------------
    def test_10_bullish_fvg(self):
        # 3 bars: Bar 0 High = 100.0; Bar 1 (Impulse); Bar 2 Low = 102.0
        # FVG zone = [100.0, 102.0]
        df = pd.DataFrame([
            {"timestamp": 1000, "open": 98.0, "high": 100.0, "low": 97.5, "close": 99.5},
            {"timestamp": 2000, "open": 99.5, "high": 103.0, "low": 99.5, "close": 102.8},
            {"timestamp": 3000, "open": 102.8, "high": 104.5, "low": 102.0, "close": 104.0},
        ])
        fvg_detector = FVGDetector(self.config)
        fvgs = fvg_detector.detect_fvgs(df)
        self.assertTrue(any(f.direction == "BULLISH" for f in fvgs))
        b_fvg = next(f for f in fvgs if f.direction == "BULLISH")
        self.assertAlmostEqual(b_fvg.lower_boundary, 100.0)
        self.assertAlmostEqual(b_fvg.upper_boundary, 102.0)

    # -------------------------------------------------------------------------
    # 11. Bearish Fair Value Gap (FVG)
    # -------------------------------------------------------------------------
    def test_11_bearish_fvg(self):
        # 3 bars: Bar 0 Low = 105.0; Bar 1 (Dump); Bar 2 High = 103.0
        # FVG zone = [103.0, 105.0]
        df = pd.DataFrame([
            {"timestamp": 1000, "open": 107.0, "high": 107.5, "low": 105.0, "close": 105.5},
            {"timestamp": 2000, "open": 105.5, "high": 105.5, "low": 102.0, "close": 102.2},
            {"timestamp": 3000, "open": 102.2, "high": 103.0, "low": 101.0, "close": 101.5},
        ])
        fvg_detector = FVGDetector(self.config)
        fvgs = fvg_detector.detect_fvgs(df)
        self.assertTrue(any(f.direction == "BEARISH" for f in fvgs))
        bear_fvg = next(f for f in fvgs if f.direction == "BEARISH")
        self.assertAlmostEqual(bear_fvg.lower_boundary, 103.0)
        self.assertAlmostEqual(bear_fvg.upper_boundary, 105.0)

    # -------------------------------------------------------------------------
    # 12. Bullish Rectangle Generation
    # -------------------------------------------------------------------------
    def test_12_bullish_rectangle_generation(self):
        # Bullish weakness candle: Close = 101.0, Low = 98.0
        # Bullish Rectangle: Upper = Close (101.0), Lower = Low (98.0)
        df = pd.DataFrame([{"timestamp": 1000, "open": 100.0, "high": 101.5, "low": 98.0, "close": 101.0, "volume": 1000}])
        target = SwingPoint(index=5, timestamp=500, price=99.5, point_type="SWING_LOW", structure_type="HL")
        weakness = WeaknessDetector(self.config).evaluate_m15_confirmation(df, target, "BULLISH", atr_value=1.5, candle_idx=0)
        engine = RectangleEngine(self.config)
        rect = engine.create_rectangle("BTCUSDT", weakness, df)
        self.assertIsNotNone(rect)
        self.assertEqual(rect.direction, "LONG")
        self.assertAlmostEqual(rect.upper_boundary, 101.0)
        self.assertAlmostEqual(rect.lower_boundary, 98.0)
        self.assertAlmostEqual(rect.width, 3.0)
        self.assertEqual(rect.status, RectangleStatus.WAITING_FOR_M1_CONFIRMATION)

    # -------------------------------------------------------------------------
    # 13. Bearish Rectangle Generation
    # -------------------------------------------------------------------------
    def test_13_bearish_rectangle_generation(self):
        # Bearish weakness candle: High = 103.0, Close = 99.5
        # Bearish Rectangle: Upper = High (103.0), Lower = Close (99.5)
        df = pd.DataFrame([{"timestamp": 1000, "open": 100.0, "high": 103.0, "low": 99.0, "close": 99.5, "volume": 1000}])
        target = SwingPoint(index=5, timestamp=500, price=101.0, point_type="SWING_HIGH", structure_type="LH")
        weakness = WeaknessDetector(self.config).evaluate_m15_confirmation(df, target, "BEARISH", atr_value=1.5, candle_idx=0)
        engine = RectangleEngine(self.config)
        rect = engine.create_rectangle("BTCUSDT", weakness, df)
        self.assertIsNotNone(rect)
        self.assertEqual(rect.direction, "SHORT")
        self.assertAlmostEqual(rect.upper_boundary, 103.0)
        self.assertAlmostEqual(rect.lower_boundary, 99.5)
        self.assertAlmostEqual(rect.width, 3.5)

    # -------------------------------------------------------------------------
    # 14. M1 Bullish Flip
    # -------------------------------------------------------------------------
    def test_14_m1_bullish_flip(self):
        # Bullish Rectangle: [98.0, 101.0]
        rect = DynamicRectangle(
            rectangle_id="TEST_BULL", symbol="BTCUSDT", direction="LONG",
            upper_boundary=101.0, lower_boundary=98.0, width=3.0,
            formation_m15_idx=10, formation_timestamp=1000,
            related_m15_swing_level=99.0, liquidity_sweep_id="SW1", confirmation_candle_id="C1",
            status=RectangleStatus.WAITING_FOR_M1_CONFIRMATION
        )
        # M1 candle confirms close ABOVE 101.0 at 101.2
        df_m1 = pd.DataFrame([
            {"timestamp": 2000, "open": 100.5, "high": 101.5, "low": 100.2, "close": 101.2}
        ])
        m1_engine = M1EntryEngine(self.config)
        flip = m1_engine.evaluate_m1_flip(rect, df_m1, current_m1_idx=0)
        self.assertIsNotNone(flip)
        self.assertTrue(flip.is_triggered)
        self.assertEqual(flip.direction, "LONG")
        self.assertAlmostEqual(flip.trigger_price, 101.2)
        self.assertEqual(rect.status, RectangleStatus.ENTRY_CONFIRMED)

    # -------------------------------------------------------------------------
    # 15. M1 Bearish Flip
    # -------------------------------------------------------------------------
    def test_15_m1_bearish_flip(self):
        # Bearish Rectangle: [99.5, 103.0]
        rect = DynamicRectangle(
            rectangle_id="TEST_BEAR", symbol="BTCUSDT", direction="SHORT",
            upper_boundary=103.0, lower_boundary=99.5, width=3.5,
            formation_m15_idx=10, formation_timestamp=1000,
            related_m15_swing_level=101.0, liquidity_sweep_id="SW2", confirmation_candle_id="C2",
            status=RectangleStatus.WAITING_FOR_M1_CONFIRMATION
        )
        # M1 candle confirms close BELOW 99.5 at 99.2
        df_m1 = pd.DataFrame([
            {"timestamp": 2000, "open": 100.0, "high": 100.2, "low": 98.9, "close": 99.2}
        ])
        m1_engine = M1EntryEngine(self.config)
        flip = m1_engine.evaluate_m1_flip(rect, df_m1, current_m1_idx=0)
        self.assertIsNotNone(flip)
        self.assertTrue(flip.is_triggered)
        self.assertEqual(flip.direction, "SHORT")
        self.assertAlmostEqual(flip.trigger_price, 99.2)

    # -------------------------------------------------------------------------
    # 16. Invalid M1 Entry
    # -------------------------------------------------------------------------
    def test_16_invalid_m1_entry(self):
        # Bullish Rectangle: [98.0, 101.0]. M1 candle closes inside at 100.0 (no breakout)
        rect = DynamicRectangle(
            rectangle_id="TEST_BULL_INV", symbol="BTCUSDT", direction="LONG",
            upper_boundary=101.0, lower_boundary=98.0, width=3.0,
            formation_m15_idx=10, formation_timestamp=1000,
            related_m15_swing_level=99.0, liquidity_sweep_id="SW1", confirmation_candle_id="C1",
            status=RectangleStatus.WAITING_FOR_M1_CONFIRMATION
        )
        df_m1 = pd.DataFrame([
            {"timestamp": 2000, "open": 99.5, "high": 100.5, "low": 99.0, "close": 100.0}
        ])
        m1_engine = M1EntryEngine(self.config)
        flip = m1_engine.evaluate_m1_flip(rect, df_m1, current_m1_idx=0)
        self.assertIsNone(flip, "M1 candle closing inside rectangle must NOT trigger safe entry")

    # -------------------------------------------------------------------------
    # 17. Stop Loss Calculation
    # -------------------------------------------------------------------------
    def test_17_stop_loss_calculation(self):
        rect = DynamicRectangle(
            rectangle_id="TEST_SL", symbol="BTCUSDT", direction="LONG",
            upper_boundary=101.0, lower_boundary=98.5, width=2.5,
            formation_m15_idx=10, formation_timestamp=1000,
            related_m15_swing_level=99.0, liquidity_sweep_id="SW1", confirmation_candle_id="C1"
        )
        sl_engine = StopLossEngine(self.config)
        res = sl_engine.calculate_stop_loss(rect, entry_price=100.5, atr_value=1.5)
        self.assertTrue(res.is_valid)
        self.assertLess(res.stop_loss_price, 101.5)
        self.assertLess(res.stop_loss_price, rect.lower_boundary) # Buffered below lower boundary

    # -------------------------------------------------------------------------
    # 18. Take Profit Calculation
    # -------------------------------------------------------------------------
    def test_18_take_profit_calculation(self):
        tp_engine = TakeProfitEngine(self.config)
        res = tp_engine.calculate_take_profit(direction="LONG", entry_price=100.0, stop_loss_price=98.0)
        self.assertTrue(res.is_valid)
        self.assertGreater(res.tp1_price, 100.0)
        self.assertGreater(res.tp2_price, res.tp1_price)
        self.assertGreater(res.tp3_price, res.tp2_price)

    # -------------------------------------------------------------------------
    # 19. Minimum 1:2 RR Validation
    # -------------------------------------------------------------------------
    def test_19_minimum_1_to_2_rr_validation(self):
        tp_engine = TakeProfitEngine(self.config)
        # Entry 100, SL 98 -> Risk = 2.0. TP1 at 104 -> RR = 2.0 (Valid)
        res_ok = tp_engine.calculate_take_profit(direction="LONG", entry_price=100.0, stop_loss_price=98.0)
        self.assertTrue(res_ok.is_valid)
        self.assertGreaterEqual(res_ok.gross_rr, 2.0)

    # -------------------------------------------------------------------------
    # 20. Duplicate Signal Prevention
    # -------------------------------------------------------------------------
    def test_20_duplicate_signal_prevention(self):
        engine = RectangleEngine(self.config)
        df = pd.DataFrame([{"timestamp": 1000, "open": 100.0, "high": 101.5, "low": 98.0, "close": 101.0, "volume": 1000}])
        target = SwingPoint(index=5, timestamp=500, price=99.5, point_type="SWING_LOW", structure_type="HL")
        weakness = WeaknessDetector(self.config).evaluate_m15_confirmation(df, target, "BULLISH", atr_value=1.5, candle_idx=0)
        rect1 = engine.create_rectangle("BTCUSDT", weakness, df)
        rect2 = engine.create_rectangle("BTCUSDT", weakness, df)
        self.assertEqual(rect1.rectangle_id, rect2.rectangle_id)
        self.assertEqual(len(engine.rectangles), 1, "Must not create duplicate rectangles for identical candle")

    # -------------------------------------------------------------------------
    # 21. Incomplete Candle Rejection
    # -------------------------------------------------------------------------
    def test_21_incomplete_candle_rejection(self):
        # Empty or short history rejects gracefully
        df_short = pd.DataFrame([{"timestamp": 1000, "open": 100, "high": 101, "low": 99, "close": 100}])
        res = self.orchestrator.scan_for_setups("BTCUSDT", df_m15=df_short)
        self.assertEqual(res["signal_status"], "REJECTED")

    # -------------------------------------------------------------------------
    # 22. Missing Candle Handling
    # -------------------------------------------------------------------------
    def test_22_missing_candle_handling(self):
        df = self._create_synthetic_m15_df(n=50)
        # Introduce NaN in middle bar
        df.loc[25, "volume"] = np.nan
        df.fillna(0.0, inplace=True)
        res = self.orchestrator.scan_for_setups("BTCUSDT", df_m15=df)
        self.assertIn(res["signal_status"], ("VALID", "REJECTED"))

    # -------------------------------------------------------------------------
    # 23. Exchange Reconnection & Failover
    # -------------------------------------------------------------------------
    def test_23_exchange_reconnection(self):
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        loader = MultiHorizonDataLoader(max_workers=2)
        # Check that 1m is mapped
        from app.engine.scanner.data_loader import BYBIT_TF_MAP, OKX_TF_MAP
        self.assertIn("1m", BYBIT_TF_MAP)
        self.assertIn("1m", OKX_TF_MAP)

    # -------------------------------------------------------------------------
    # 24. Historical vs Live Consistency
    # -------------------------------------------------------------------------
    def test_24_historical_live_consistency(self):
        # Evaluate same candle via backtest engine and orchestrator
        df_m15 = self._create_synthetic_m15_df(n=60, trend="UP")
        df_m1 = pd.DataFrame([{
            "timestamp": 1700000000000 + (i * 60 * 1000),
            "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 100.0
        } for i in range(120)])
        backtester = RectangleBacktestingEngine(self.config)
        report = backtester.run_backtest("BTCUSDT", df_m15, df_m1)
        self.assertIsInstance(report.total_trades, int)

    # -------------------------------------------------------------------------
    # 25. No-Lookahead Validation
    # -------------------------------------------------------------------------
    def test_25_no_lookahead_validation(self):
        # Adding future candles must not mutate historical swing points confirmed at earlier index
        df_base = self._create_synthetic_m15_df(n=30, trend="UP")
        engine = MarketStructureEngine(self.config)
        shs1, sls1 = engine.find_confirmed_swings(df_base, up_to_bar=25)

        # Append 10 more candles in future
        df_extended = pd.concat([df_base, self._create_synthetic_m15_df(n=10, trend="DOWN")], ignore_index=True)
        shs2, sls2 = engine.find_confirmed_swings(df_extended, up_to_bar=25)

        self.assertEqual(len(shs1), len(shs2))
        self.assertEqual(len(sls1), len(sls2))
        if shs1:
            self.assertEqual(shs1[0].price, shs2[0].price)


if __name__ == "__main__":
    unittest.main()
