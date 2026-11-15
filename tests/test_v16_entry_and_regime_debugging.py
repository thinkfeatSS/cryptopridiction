import os
import time
import unittest
import pandas as pd
import numpy as np

from app.quant_v16.entry_confirmation import EntryConfirmationEngine
from app.quant_v16.strategies import StrategyRegistry, StrategyArchetype, StrategyStatus, normalize_regime_key
from app.quant_v16.regime import MarketRegime
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.engine.signals.signal_generator import map_canonical_strategy, SignalGenerationSystem
from app.quant_v16.order_blocks import InstitutionalOrderBlockEngine, OrderBlock, OrderBlockType, OrderBlockState


class TestV16EntryAndRegimeDebugging(unittest.TestCase):
    """
    Forensic test suite verifying the resolution of all identified confirmation candle,
    regime activation, resting limit execution, and module alignment issues.
    """

    def setUp(self):
        self.reg = StrategyRegistry()

    def test_01_fvg_retest_strictly_prior_to_trigger(self):
        """
        Verify that a 3-candle FVG formed prior to trigger candle is correctly detected,
        and that a normal monotonic trend candle does NOT trigger false FVG retest.
        """
        # Scenario A: Monotonic uptrend with no FVG formed prior to trigger
        # Prices: 100 -> 101 -> 102 -> 103 -> 104 -> 105 (Live)
        bars_monotonic = [
            {"open": 100.0, "high": 100.5, "low": 99.8, "close": 100.4, "volume": 1000},
            {"open": 100.4, "high": 101.5, "low": 100.2, "close": 101.4, "volume": 1000},
            {"open": 101.4, "high": 102.5, "low": 101.2, "close": 102.4, "volume": 1000},
            {"open": 102.4, "high": 103.5, "low": 102.2, "close": 103.4, "volume": 1000},
            {"open": 103.4, "high": 104.5, "low": 103.2, "close": 104.4, "volume": 1000}, # Trigger candle
            {"open": 104.4, "high": 105.0, "low": 104.3, "close": 104.9, "volume": 1000}, # Live candle
        ]
        df_mono = pd.DataFrame(bars_monotonic)
        conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df_mono, direction="LONG", current_price=104.9
        )
        # Should NOT be flagged as FVG retest
        self.assertFalse(metrics.get("is_fvg_retest", False), "Monotonic trend should not be falsely marked as FVG retest")

        # Scenario B: Genuine Bullish FVG formed at bars 0, 1, 2, then retested at bar 3 (trigger)
        # Bar 0: High = 100.0
        # Bar 1 (Displacement): Low = 100.2, High = 103.0
        # Bar 2: Low = 101.5 (Gap between Bar 0 High 100.0 and Bar 2 Low 101.5 = 1.5; CE = 100.75)
        # Bar 3 (Trigger): Dips to Low 101.0 (into gap) and closes at 101.8 (above CE 100.75)
        # Bar 4 (Live bar)
        bars_fvg = [
            {"open": 99.0, "high": 100.0, "low": 98.8, "close": 99.8, "volume": 1000},     # c1
            {"open": 100.0, "high": 103.0, "low": 99.9, "close": 102.8, "volume": 2500},   # c2 (displacement)
            {"open": 102.8, "high": 103.5, "low": 101.5, "close": 103.2, "volume": 1200},   # c3 (gap: 100.0 to 101.5, CE = 100.75)
            {"open": 103.2, "high": 103.3, "low": 101.0, "close": 101.8, "volume": 1500},   # Trigger candle: dips to 101.0 (<= 101.5) and closes 101.8 (>= 100.75)
            {"open": 101.8, "high": 102.0, "low": 101.7, "close": 101.9, "volume": 800},    # Live bar
        ]
        df_fvg = pd.DataFrame(bars_fvg)
        conf_fvg, reason_fvg, metrics_fvg = EntryConfirmationEngine.validate_candle_trigger(
            df_fvg, direction="LONG", current_price=101.9
        )
        self.assertTrue(metrics_fvg.get("is_fvg_retest"), "Genuine FVG retest must be recognized")
        self.assertEqual(metrics_fvg.get("pattern"), "FVG_RETEST_LONG")

    def test_02_live_bar_blowout_guard_with_live_current_price(self):
        """
        Verify that an acute adverse market dump in the active live bar
        is immediately intercepted via current_price.
        """
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.8, "close": 100.5, "volume": 1000},
            {"open": 100.5, "high": 100.6, "low": 98.5, "close": 100.5, "volume": 1000}, # Live bar with stale close
        ]
        df = pd.DataFrame(bars)
        # Real-time market tick dumped to 98.5 (adverse -2.0% dump with no absorption wick)
        conf, reason, metrics = EntryConfirmationEngine.validate_candle_trigger(
            df, direction="LONG", current_price=98.5
        )
        self.assertFalse(conf, "Acute adverse live dump must be rejected by blowout guard")
        self.assertTrue(metrics.get("is_live_blowout"))
        self.assertIn("Waterfall Dump", reason)

    def test_03_adverse_candle_fallthrough_rejection(self):
        """
        Verify that a falling red bar without buyer absorption is strictly rejected for Long entry,
        and a rising green bar without seller rejection is strictly rejected for Short entry.
        """
        # Red bar that does not trigger Marubozu (body_ratio 0.40 < 0.65) but has insufficient wick absorption
        # Open 100.2, High 100.5, Low 99.5, Close 99.8. Range = 1.0. Lower wick = 0.3 (30%? let's make low 99.65 -> lower wick 0.15 = 15%).
        # Body = 0.4. Body ratio = 0.40. Close pos = (99.8 - 99.65)/1.0 = 0.35
        bars_red = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
            {"open": 100.2, "high": 100.65, "low": 99.65, "close": 99.8, "volume": 1000}, # Trigger candle: Red, body_ratio 0.40, lower_wick_ratio 0.15 (<0.25)
            {"open": 99.8, "high": 99.9, "low": 99.7, "close": 99.8, "volume": 500},
        ]
        df_red = pd.DataFrame(bars_red)
        conf_long, reason_long, _ = EntryConfirmationEngine.validate_candle_trigger(
            df_red, direction="LONG", current_price=99.8
        )
        self.assertFalse(conf_long, "Red candle without buyer absorption must NOT confirm Long entry")
        self.assertIn("Awaiting Bullish Absorption", reason_long)

        # Green bar that does not trigger Marubozu but has insufficient seller rejection
        # Open 99.8, High 100.35, Low 99.35, Close 100.2. Range = 1.0. Upper wick = 0.15 (15% < 25%).
        # Body = 0.4. Body ratio = 0.40. Close pos = (100.2 - 99.35)/1.0 = 0.85 (or let's adjust high to 100.5 and close to 100.0, close pos 0.65)
        # Open 99.8, High 100.15, Low 99.15, Close 100.0. Rng = 1.0. Upper wick = 100.15 - 100.0 = 0.15 (15%). Body = 0.20.
        bars_green = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
            {"open": 99.8, "high": 100.2, "low": 99.2, "close": 100.1, "volume": 1000}, # Trigger candle: Green, upper wick 0.10/1.0 = 10% (<25%)
            {"open": 100.1, "high": 100.2, "low": 100.0, "close": 100.1, "volume": 500},
        ]
        df_green = pd.DataFrame(bars_green)
        conf_short, reason_short, _ = EntryConfirmationEngine.validate_candle_trigger(
            df_green, direction="SHORT", current_price=100.1
        )
        self.assertFalse(conf_short, "Green candle without seller rejection must NOT confirm Short entry")
        self.assertIn("Awaiting Bearish Rejection", reason_short)

    def test_04_order_block_in_zone_no_false_chase(self):
        """
        Verify that when price is inside the detected Order Block zone,
        it is recognized as MARKET_CONFIRMED without falsely flagging is_chasing = True.
        """
        ob_setup = {
            "setup_detected": True,
            "order_block_zone": [100.0, 102.0],
            "optimal_entry_limit": 101.0,
            "tp1_price": 106.0,
            "sl_price": 98.5
        }
        # Price is 101.8 (within [100.0, 102.0])
        res = EntryConfirmationEngine.calculate_optimal_entry_zone(
            current_price=101.8,
            ob_setup=ob_setup,
            direction="LONG",
            active_atr=1.5,
            chase_threshold_pct=0.40,
            strategy="ORDER_BLOCK_LONG"
        )
        self.assertFalse(res["is_limit_pending"], "Price inside Order Block zone must not be flagged as resting limit")
        self.assertEqual(res["entry_mode"], "MARKET_CONFIRMED")
        self.assertGreaterEqual(float(res["entry_zone_max"]), 101.8)
        self.assertLessEqual(float(res["entry_zone_min"]), 101.0)

    def test_05_strategy_registry_regime_kill_switches_all_archetypes(self):
        """
        Verify that all 32 archetypes are fully registered with priors,
        and that normalize_regime_key correctly enforces kill switches.
        """
        # 1. Total registered strategies must match StrategyArchetype enum count (32)
        self.assertEqual(len(self.reg.strategies), len(StrategyArchetype))

        # 2. Bull/Bear normalization
        self.assertEqual(normalize_regime_key("BEAR"), "BEAR_TREND")
        self.assertEqual(normalize_regime_key("FLASH_DUMP"), "BEAR_TREND")
        self.assertEqual(normalize_regime_key("BULL"), "BULL_TREND")
        self.assertEqual(normalize_regime_key("RANGE_SQUEEZE"), "SQUEEZE")
        self.assertEqual(normalize_regime_key("CONSOLIDATION"), "RANGE")

        # 3. Kill-switch enforcement: Longs paused in BEAR_TREND
        long_strats = [
            StrategyArchetype.ORDER_BLOCK_LONG.value,
            StrategyArchetype.BREAKER_BLOCK_LONG.value,
            StrategyArchetype.DIP_BUY_LONG.value,
            StrategyArchetype.MOMENTUM_LONG.value,
            StrategyArchetype.DIRECTIONAL_TREND_LONG.value,
            StrategyArchetype.FVG_RETEST_LONG.value
        ]
        for s in long_strats:
            allowed, reason = self.reg.is_strategy_allowed(s, current_regime="BEAR_TREND")
            self.assertFalse(allowed, f"{s} must be paused in BEAR_TREND. Reason: {reason}")
            # Also test alias "BEAR"
            allowed_alias, _ = self.reg.is_strategy_allowed(s, current_regime="BEAR")
            self.assertFalse(allowed_alias, f"{s} must be paused in BEAR alias")

        # 4. Shorts paused in BULL_TREND
        short_strats = [
            StrategyArchetype.ORDER_BLOCK_SHORT.value,
            StrategyArchetype.BREAKER_BLOCK_SHORT.value,
            StrategyArchetype.RALLY_FADE_SHORT.value,
            StrategyArchetype.TOP_REVERSAL_SHORT.value,
            StrategyArchetype.MOMENTUM_SHORT.value,
            StrategyArchetype.DIRECTIONAL_TREND_SHORT.value
        ]
        for s in short_strats:
            allowed, reason = self.reg.is_strategy_allowed(s, current_regime="BULL_TREND")
            self.assertFalse(allowed, f"{s} must be paused in BULL_TREND. Reason: {reason}")
            # Also test alias "BULL"
            allowed_alias, _ = self.reg.is_strategy_allowed(s, current_regime="BULL")
            self.assertFalse(allowed_alias, f"{s} must be paused in BULL alias")

    def test_06_paper_trading_bot_resting_limit_no_instant_cancellation(self):
        """
        Verify that a resting limit order is NOT instantly cancelled on tick 1,
        and cleanly fills when price touches limit.
        """
        import tempfile
        temp_ledger = os.path.join(tempfile.gettempdir(), f"test_ledger_{int(time.time()*1000)}.json")
        bot = PaperTradingBot(ledger_file=temp_ledger)
        signal = {
            "signal_id": "TEST_RESTING_001",
            "symbol": "SOL/USDT",
            "dominant_direction": "LONG",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "current_price": 100.0,
            "entry_price": 99.0,
            "optimal_entry_limit": 99.0,
            "entry_zone_min": 98.5,
            "entry_zone_max": 100.5,
            "is_limit_pending": True,
            "entry_mode": "RESTING_LIMIT",
            "tp1_price": 104.0,
            "tp2_price": 108.0,
            "sl_price": 97.0,
            "quality_grade": "Grade A+",
            "conviction": 85.0,
            "meta_win_prob_pct": 72.0,
            "dominant_timeframe": "15M",
            "horizon": "15M",
            "desk": "scalp"
        }
        # 1. Admit signal as resting limit
        opened = bot.admit_signal(signal)
        self.assertTrue(opened, "Resting limit signal must be admitted")

        # Find the resting position
        open_pos = [p for p in bot.data["open_positions"] if p["trade_id"] == "TEST_RESTING_001"]
        self.assertEqual(len(open_pos), 1)
        pos = open_pos[0]
        self.assertEqual(pos["status"], "RESTING_LIMIT")
        self.assertEqual(pos.get("admission_price"), 100.0)

        # 2. Tick 1: Price still at 100.0 (admission price) -> Must NOT be cancelled!
        bot.on_tick({"SOL/USDT": 100.0})
        self.assertEqual(pos["status"], "RESTING_LIMIT", "Must remain RESTING_LIMIT on initial price tick")

        # 3. Tick 2: Price pulls back to 99.0 -> Limit touches and fills to OPEN!
        bot.on_tick({"SOL/USDT": 99.0})
        self.assertEqual(pos["status"], "OPEN", "Must fill and transition to OPEN when touching limit price")
        self.assertEqual(pos["entry_price"], 99.0)

    def test_07_canonical_strategy_and_metadata_alignment(self):
        """
        Verify that is_engulfing maps to MOMENTUM_LONG / MOMENTUM_SHORT,
        and that canonical_strategy, candle_trigger_confirmed, candle_trigger_reason,
        and candle_metrics are properly integrated.
        """
        # Bullish engulfing mapping
        m_long = map_canonical_strategy("UNKNOWN_RAW", "LONG", candle_metrics={"is_engulfing": True})
        self.assertEqual(m_long, StrategyArchetype.MOMENTUM_LONG.value)

        # Bearish engulfing mapping
        m_short = map_canonical_strategy("UNKNOWN_RAW", "SHORT", candle_metrics={"is_engulfing": True})
        self.assertEqual(m_short, StrategyArchetype.MOMENTUM_SHORT.value)

        # Liquidity sweep reclaim mapping
        m_sweep = map_canonical_strategy("UNKNOWN_RAW", "LONG", candle_metrics={"is_sweep_reclaim": True})
        self.assertEqual(m_sweep, StrategyArchetype.LIQUIDITY_RECLAIM_LONG.value)

        # FVG retest mapping
        m_fvg = map_canonical_strategy("UNKNOWN_RAW", "SHORT", candle_metrics={"is_fvg_retest": True})
        self.assertEqual(m_fvg, StrategyArchetype.FVG_RETEST_SHORT.value)

    def test_08_order_blocks_are_passive_features_not_triggers(self):
        """
        Verify that Order Blocks are passive spatial features / POIs, not autonomous structural trade triggers:
        1. When price slices into a Bullish Order Block with an unabsorbed falling red candle,
           it reports is_passive_poi = True, in_order_block_zone = True, but structural_trigger_confirmed = False.
        2. When price enters with confirmed lower wick absorption or bullish reversal close,
           it confirms structural_trigger_confirmed = True and execution_mode = 'MARKET_TRIGGER'.
        3. Similarly for Bearish Order Blocks with unrejected green candles vs confirmed upper wick rejection.
        """
        # Create synthetic DF with 30 candles
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=30, freq="1h")
        base = 100.0
        # Candle 10 forms a bullish displacement order block
        df = pd.DataFrame({
            "open": [base + i * 0.1 for i in range(30)],
            "high": [base + i * 0.1 + 0.5 for i in range(30)],
            "low": [base + i * 0.1 - 0.5 for i in range(30)],
            "close": [base + i * 0.1 + 0.2 for i in range(30)],
            "volume": [1000.0] * 30
        }, index=dates)

        # Mock an active Order Block
        ob_bull = OrderBlock(
            block_type=OrderBlockType.BULLISH,
            state=OrderBlockState.TESTING,
            timeframe="1h",
            candle_idx=10,
            timestamp=dates[10],
            ob_high=102.0,
            ob_low=100.0,
            ob_open=100.5,
            ob_close=101.5,
            equilibrium_50=101.0,
            displacement_mag=2.5,
            volume_surge=2.0,
            has_fvg=True,
            confluence_score=0.85,
            is_touching=True,
            touch_type="MEAN_THRESHOLD_50",
            zeiierman_rank=1
        )

        orig_detect = InstitutionalOrderBlockEngine.detect_order_blocks
        try:
            InstitutionalOrderBlockEngine.detect_order_blocks = lambda *args, **kwargs: [ob_bull]

            # Case A: Adverse red candle slicing down through the demand block (no buyer absorption)
            # Candle open = 102.0, close = 100.5 (low wick is tiny: 100.5 - 100.4 = 0.1 / 1.7 = 5.8%)
            df_adverse = df.copy()
            df_adverse.iloc[-1] = {
                "open": 102.0, "high": 102.1, "low": 100.4, "close": 100.5, "volume": 1000.0
            }
            res_adverse = InstitutionalOrderBlockEngine.evaluate_live_setup(df_adverse, timeframe="1h", current_price=100.5)
            self.assertTrue(res_adverse["setup_detected"])
            self.assertTrue(res_adverse["is_passive_poi"], "Order Block must be designated as a passive POI")
            self.assertTrue(res_adverse["in_order_block_zone"])
            self.assertFalse(res_adverse["structural_trigger_confirmed"], "Adverse falling candle must NOT confirm a structural trigger")
            self.assertEqual(res_adverse["execution_mode"], "RESTING_LIMIT", "Unconfirmed passive POI must enforce RESTING_LIMIT execution")
            self.assertTrue(res_adverse["requires_trigger_confirmation"])
            self.assertIn("AWAITING TRIGGER", res_adverse["decision"])

            # Case B: Confirmed buyer absorption with lower rejection wick (hammer reaction off demand)
            # Candle open = 101.2, low = 100.1, close = 101.6, high = 101.7 -> lower wick = (101.2 - 100.1)/1.6 = 68.7%
            df_confirmed = df.copy()
            df_confirmed.iloc[-1] = {
                "open": 101.2, "high": 101.7, "low": 100.1, "close": 101.6, "volume": 1600.0
            }
            res_confirmed = InstitutionalOrderBlockEngine.evaluate_live_setup(df_confirmed, timeframe="1h", current_price=101.6)
            self.assertTrue(res_confirmed["setup_detected"])
            self.assertTrue(res_confirmed["is_passive_poi"])
            self.assertTrue(res_confirmed["structural_trigger_confirmed"], "Buyer wick absorption must confirm structural trigger")
            self.assertEqual(res_confirmed["execution_mode"], "MARKET_TRIGGER")
            self.assertFalse(res_confirmed["requires_trigger_confirmation"])
            self.assertIn("RETEST (LONG)", res_confirmed["decision"])

        finally:
            InstitutionalOrderBlockEngine.detect_order_blocks = orig_detect

    def test_09_passive_order_block_does_not_override_market_trend(self):
        """
        Verify that in signal generation:
        1. A passive Order Block touch without structural trigger confirmation does NOT
           autonomously flip a Bearish trend into Long.
        2. A passive Order Block touch opposing the qualified trend does NOT hijack trade direction.
        """
        sig_gen = SignalGenerationSystem()

        trend_matrix = {
            "5m": "BEARISH",
            "15m": "BEARISH",
            "1h": "BEARISH",
            "4h": "BEARISH",
            "12h": "BEARISH",
            "1d": "BEARISH",
            "1w": "BEARISH",
            "15d": "BEARISH",
            "1M": "BEARISH"
        }
        horizon_preds = {
            tf: {"predicted_trend": "BEARISH", "is_cold_start": False, "candle_count": 50}
            for tf in trend_matrix
        }
        matrix_eval = {
            "archetype": "ARCHETYPE_A_SECULAR_EXPANSION",
            "dominant_direction": "SHORT",
            "trade_permitted": True
        }

        # Passive bullish Order Block touch without structural trigger confirmation
        ob_passive_bull = {
            "setup_detected": True,
            "direction": "LONG",
            "zeiierman_rank": 1,
            "zeiierman_rank_label": "🏆 RANK 1 DEMAND",
            "is_passive_poi": True,
            "structural_trigger_confirmed": False,
            "trigger_type": "AWAITING_STRUCTURAL_TRIGGER",
            "execution_mode": "RESTING_LIMIT",
            "order_block_zone": [100.0, 102.0],
            "optimal_entry_limit": 101.0,
            "tp1_price": 108.0,
            "tp2_price": 112.0,
            "tp3_price": 116.0,
            "sl_price": 98.0
        }

        q_15m, q_1h, q_24h = sig_gen.evaluate_multi_horizon_gates(
            trend_matrix=trend_matrix,
            horizon_predictions=horizon_preds,
            matrix_eval=matrix_eval,
            ob_setup_15m=ob_passive_bull,
            ob_setup_1h=ob_passive_bull,
            ob_setup_24h=ob_passive_bull
        )

        # 1. Candidate directions must remain SHORT (with the trend), NOT flipped to LONG
        self.assertEqual(q_15m["direction"], "SHORT", "Passive Bullish OB touch must NOT invert Bearish 15M trend")
        self.assertEqual(q_1h["direction"], "SHORT", "Passive Bullish OB touch must NOT invert Bearish 1H trend")
        self.assertEqual(q_24h["direction"], "SHORT", "Passive Bullish OB touch must NOT invert Bearish 24H trend")

        # 2. In _build_single_horizon_signal, an opposing passive OB must not override SHORT direction
        btc_shield_state = {
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "v16_regime": "BEAR_TREND",
            "status_code": "NORMAL"
        }
        sig = sig_gen._build_single_horizon_signal(
            symbol="BTC/USDT",
            horizon_label="1H",
            tf_key="1h",
            direction="SHORT",
            current_price=101.5,
            dfs_9={"1h": pd.DataFrame({"high": [103.0]*20, "low": [100.0]*20, "close": [101.5]*20, "open": [102.0]*20})},
            horizon_prediction={"predicted_trend": "BEARISH", "consensus_probability": 0.65, "predicted_change_pct": 0.02},
            btc_shield_state=btc_shield_state,
            aligned_horizons=["15m", "1h", "4h"],
            order_block_setup=ob_passive_bull
        )
        self.assertFalse(sig["is_order_block_signal"], "Opposing passive OB must not hijack trade into LONG")
        self.assertNotEqual(sig["direction"], "LONG", "Trade direction must NOT be flipped to LONG by opposing passive OB")

    def test_10_stale_hl_lh_15m_anchor_and_dynamic_chase_tolerance(self):
        """
        Regression Test (0G/USDT 2026-11-11 Anomaly):
        1. A stale/distant historical 15M HL (> 1.8 * ATR / > 1.6% below spot) must be refined
           to a reachable recent 15M Higher Low / EMA pullback instead of placing an unfillable -2.7% limit.
        2. Symmetric LH anchor for SHORT preserves SL > Entry > TP1 > TP2 > TP3.
        3. Generated signal exports dynamic ATR-scaled chase_threshold_pct and omits retired 1w/15d horizons.
        """
        # Simulate 0G/USDT 15m climbing from ~$0.1508 up to $0.1554
        closes = [0.1510, 0.1514, 0.1518, 0.1523, 0.1529, 0.1533, 0.1538, 0.1542, 0.1546, 0.1549, 0.1551, 0.1554]
        df_15m = pd.DataFrame({
            "open": [c - 0.0002 for c in closes],
            "high": [c + 0.0005 for c in closes],
            "low": [c - 0.0005 for c in closes],
            "close": closes,
            "volume": [10000.0] * len(closes),
        })
        anchored_long = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_15m,
            hl_pivot_price=0.1508,
            current_price=0.1554,
        )
        self.assertGreater(anchored_long["entry_price"], 0.1525, "Stale deep HL anchor should be refined near recent 15M pullback")
        self.assertLess(anchored_long["sl_price"], anchored_long["entry_price"])
        self.assertLess(anchored_long["entry_price"], anchored_long["tp1_price"])
        self.assertLess(anchored_long["tp1_price"], anchored_long["tp2_price"])
        self.assertLess(anchored_long["tp2_price"], anchored_long["tp3_price"])

        # Symmetric SHORT check with stale faraway LH
        closes_dn = [0.1590, 0.1585, 0.1580, 0.1574, 0.1569, 0.1565, 0.1561, 0.1558, 0.1555, 0.1552, 0.1548, 0.1545]
        df_15m_dn = pd.DataFrame({
            "open": [c + 0.0002 for c in closes_dn],
            "high": [c + 0.0005 for c in closes_dn],
            "low": [c - 0.0005 for c in closes_dn],
            "close": closes_dn,
            "volume": [10000.0] * len(closes_dn),
        })
        anchored_short = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
            df_15m=df_15m_dn,
            lh_pivot_price=0.1595,
            current_price=0.1545,
        )
        self.assertLess(anchored_short["entry_price"], 0.1575, "Stale high LH anchor should be refined near recent 15M bounce")
        self.assertGreater(anchored_short["sl_price"], anchored_short["entry_price"])
        self.assertGreater(anchored_short["entry_price"], anchored_short["tp1_price"])
        self.assertGreater(anchored_short["tp1_price"], anchored_short["tp2_price"])
        self.assertGreater(anchored_short["tp2_price"], anchored_short["tp3_price"])

        # SignalGenerationSystem should export dynamic chase_threshold_pct and exclude retired 1w/15d
        sig_gen = SignalGenerationSystem()
        sig = sig_gen._build_single_horizon_signal(
            symbol="0G/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=0.1554,
            dfs_9={"15m": df_15m},
            horizon_prediction={"predicted_trend": "BULLISH", "consensus_probability": 0.66, "predicted_change_pct": 0.02},
            btc_shield_state={"altcoin_longs_allowed": True, "altcoin_shorts_allowed": True, "v16_regime": "BULL_TREND", "status_code": "NORMAL"},
            aligned_horizons=["5m", "15m", "1h", "4h"],
        )
        self.assertIn("chase_threshold_pct", sig)
        self.assertGreaterEqual(sig["chase_threshold_pct"], 0.55)

        tm = {"5m": "BULLISH", "15m": "BULLISH", "1h": "BULLISH", "4h": "BULLISH", "12h": "BULLISH", "1d": "BULLISH"}
        hp = {tf: {"predicted_trend": "BULLISH", "is_cold_start": False, "candle_count": 50} for tf in tm}
        me = {"archetype": "ARCHETYPE_A_SECULAR_EXPANSION", "dominant_direction": "LONG", "trade_permitted": True}
        _, q_1h, q_24h = sig_gen.evaluate_multi_horizon_gates(trend_matrix=tm, horizon_predictions=hp, matrix_eval=me)
        self.assertNotIn("1w", q_1h.get("required_horizons", []))
        self.assertNotIn("1w", q_24h.get("required_horizons", []))
        self.assertNotIn("15d", q_24h.get("required_horizons", []))

    def test_11_cancelled_limit_preserves_live_market_price_not_limit(self):
        """
        Regression Test (0G_USDT_15M_1794414488 Price Integrity):
        When an unfilled resting limit order is cancelled via CANCELLED_CHASE_EXCEEDED,
        cancel_market_price captures true live market price and audit sync MUST NOT
        overwrite v16_dynamic_states['current_price'] or exit_price with unfilled optimal_entry_limit.
        """
        import json
        import tempfile
        import shutil
        from unittest.mock import patch

        tmp_dir = tempfile.mkdtemp(prefix="test_canc_mkt_price_")
        try:
            ledger_path = os.path.join(tmp_dir, "test_canc_ledger.json")
            dyn_path = os.path.join(tmp_dir, "v16_dynamic_states.json")
            csv_path = os.path.join(tmp_dir, "trader_signals_tracker.csv")
            sig_id = "0G_USDT_15M_1794414488"

            with open(dyn_path, "w", encoding="utf-8") as f:
                json.dump({
                    sig_id: {
                        "signal_id": sig_id,
                        "symbol": "0G/USDT",
                        "status": "ACTIVE",
                        "current_price": 0.1554,
                    }
                }, f)

            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("signal_id,symbol,horizon,status,outcome_label,entry_price,exit_price,realized_return_pct,evaluated_at_utc\n")
                f.write(f"{sig_id},0G/USDT,15M,PENDING_EVALUATION,PENDING,0.151266,,,\n")

            with patch("app.engine.execution.paper_trading_bot.EXPORT_DIR", tmp_dir):
                bot = PaperTradingBot(ledger_file=ledger_path)
                bot.enable_signal_expiry = True
                signal = {
                    "signal_id": sig_id,
                    "symbol": "0G/USDT",
                    "direction": "LONG",
                    "is_trade_active": True,
                    "signal_status": "ACTIVE_SIGNAL",
                    "current_price": 0.1554,
                    "entry_price": 0.151266,
                    "optimal_entry_limit": 0.151266,
                    "entry_zone_min": 0.1510,
                    "entry_zone_max": 0.1515,
                    "is_limit_pending": True,
                    "entry_mode": "RESTING_LIMIT",
                    "chase_threshold_pct": 0.40,
                    "tp1_price": 0.161345,
                    "tp2_price": 0.1650,
                    "sl_price": 0.144041,
                    "quality_grade": "Grade B",
                    "conviction": 78.0,
                    "meta_win_prob_pct": 56.1,
                    "horizon": "15M",
                    "desk": "scalp",
                }
                self.assertTrue(bot.admit_signal(signal))
                bot.on_tick({"0G/USDT": 0.1565})

                canc_list = bot.data.get("cancelled_orders", [])
                self.assertEqual(len(canc_list), 1)
                self.assertEqual(canc_list[0]["cancellation_reason"], "CANCELLED_CHASE_EXCEEDED")
                self.assertAlmostEqual(canc_list[0]["cancel_market_price"], 0.1565, places=6)

            with open(dyn_path, "r", encoding="utf-8") as f:
                dyn_after = json.load(f)
            self.assertAlmostEqual(dyn_after[sig_id]["current_price"], 0.1565, places=6)
            self.assertAlmostEqual(dyn_after[sig_id]["exit_price"], 0.1565, places=6)
            self.assertNotAlmostEqual(dyn_after[sig_id]["current_price"], 0.151266, places=6)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_12_signal_service_coinpaprika_rank_dedup_and_cancelled_live_price(self):
        """
        Verify Coinpaprika fallback in signal_service prefers lowest market-cap rank
        (so rank #1 BTC is never overwritten by a lower-ranked clone sharing symbol BTC).
        """
        import requests as _req
        from unittest.mock import patch, MagicMock
        import app.services.signal_service as sig_svc

        class FakeResp:
            def __init__(self, code, data):
                self.status_code = code
                self._data = data
            def json(self):
                return self._data

        def fake_get(url, timeout=3.5):
            if "coinpaprika.com" in url:
                return FakeResp(200, [
                    {"symbol": "BTC", "rank": 1, "quotes": {"USD": {"price": 95000.0}}},
                    {"symbol": "BTC", "rank": 4999, "quotes": {"USD": {"price": 0.00012}}},
                    {"symbol": "0G", "rank": 220, "quotes": {"USD": {"price": 0.1554}}},
                ])
            return FakeResp(503, {})

        with patch.object(sig_svc, "_FETCHING_TICKERS", False), \
             patch.object(sig_svc, "_LIVE_PRICES_CACHE", {}), \
             patch.object(sig_svc, "_PAPRIKA_THROTTLED_UNTIL", 0.0), \
             patch.object(_req, "get", side_effect=fake_get):
            sig_svc._async_refresh_tickers(sync=True)
            self.assertAlmostEqual(sig_svc._LIVE_PRICES_CACHE.get("BTC/USDT"), 95000.0, places=2)
            self.assertAlmostEqual(sig_svc._LIVE_PRICES_CACHE.get("0G/USDT"), 0.1554, places=4)

    def test_13_bear_trap_wick_ratio_and_btc_shield_dump_cascade(self):
        """
        Verify that:
        1. Bear trap liquidity sweep requires significant absorption wick (>= 35%),
           allowing solid red breakdown candles touching support to confirm short entry.
        2. Bull trap liquidity sweep requires significant rejection wick (>= 35%),
           allowing solid green breakout candles touching resistance to confirm long entry.
        3. BTC Market Shield does not falsely trigger FLASH_DUMP / BEAR_CASCADE_BLACKOUT
           merely because price is below 1H EMA50, preserving normal BEAR_TREND short alpha.
        """
        # --- 1. SHORT Breakdown without absorption wick ---
        # Prior low was 100.0. Trigger candle sweeps low to 99.8, closes at 100.05 (above 100.0).
        # Range = 1.0 (High 100.8, Low 99.8). Lower wick = 100.05 - 99.8 = 0.25 (25% < 35%). Red body = 0.65.
        bars_short_breakdown = [
            {"open": 101.0, "high": 102.0, "low": 100.0, "close": 100.5, "volume": 1000},
            {"open": 100.5, "high": 101.0, "low": 100.0, "close": 100.2, "volume": 1000},
            {"open": 100.2, "high": 100.5, "low": 100.0, "close": 100.1, "volume": 1000},
            {"open": 100.1, "high": 100.3, "low": 100.0, "close": 100.1, "volume": 1000},
            {"open": 100.7, "high": 100.8, "low": 99.8, "close": 100.02, "volume": 5000},  # Low 99.8 < 100.0, lower wick 0.22/1.0 = 22% (<35%)
            {"open": 100.02, "high": 100.05, "low": 99.8, "close": 99.9, "volume": 1000},   # Live candle
        ]
        df_sb = pd.DataFrame(bars_short_breakdown)
        conf_sb, reason_sb, metrics_sb = EntryConfirmationEngine.validate_candle_trigger(
            df_sb, direction="SHORT", current_price=99.9
        )
        self.assertTrue(conf_sb, f"Breakdown candle with small wick should confirm short. Reason: {reason_sb}")
        self.assertNotIn("Bear Trap Liquidity Sweep", reason_sb)

        # --- 2. SHORT Bear Trap with genuine absorption wick (>= 35%) ---
        bars_short_trap = [
            {"open": 101.0, "high": 102.0, "low": 100.0, "close": 100.5, "volume": 1000},
            {"open": 100.5, "high": 101.0, "low": 100.0, "close": 100.2, "volume": 1000},
            {"open": 100.2, "high": 100.5, "low": 100.0, "close": 100.1, "volume": 1000},
            {"open": 100.1, "high": 100.3, "low": 100.0, "close": 100.1, "volume": 1000},
            {"open": 100.4, "high": 100.5, "low": 99.0, "close": 100.1, "volume": 5000},  # Swept 99.0, closed 100.1, lower wick (100.1-99.0)/1.5 = 73% (>=35%)
            {"open": 100.1, "high": 100.3, "low": 100.0, "close": 100.2, "volume": 1000},
        ]
        df_st = pd.DataFrame(bars_short_trap)
        conf_st, reason_st, _ = EntryConfirmationEngine.validate_candle_trigger(
            df_st, direction="SHORT", current_price=100.2
        )
        self.assertFalse(conf_st, "Bear trap with 73% absorption wick must be vetoed")
        self.assertIn("Bear Trap Liquidity Sweep Absorption", reason_st)

        # --- 3. LONG Bull Trap with genuine rejection wick (>= 35%) ---
        bars_long_trap = [
            {"open": 99.0, "high": 100.0, "low": 98.0, "close": 99.5, "volume": 1000},
            {"open": 99.5, "high": 100.0, "low": 99.0, "close": 99.8, "volume": 1000},
            {"open": 99.8, "high": 100.0, "low": 99.2, "close": 99.9, "volume": 1000},
            {"open": 99.9, "high": 100.0, "low": 99.5, "close": 99.9, "volume": 1000},
            {"open": 99.8, "high": 101.5, "low": 99.7, "close": 99.9, "volume": 5000},   # Swept 101.5, closed 99.9, upper wick (101.5-99.9)/1.8 = 88% (>=35%)
            {"open": 99.9, "high": 100.0, "low": 99.8, "close": 99.9, "volume": 1000},
        ]
        df_lt = pd.DataFrame(bars_long_trap)
        conf_lt, reason_lt, _ = EntryConfirmationEngine.validate_candle_trigger(
            df_lt, direction="LONG", current_price=99.9
        )
        self.assertFalse(conf_lt, "Bull trap with 88% rejection wick must be vetoed")
        self.assertIn("Bull Trap Liquidity Sweep Fakeout", reason_lt)

        # --- 4. BTC Shield Dump Cascade vs Normal Bear Trend ---
        from app.engine.scanner.btc_shield import BtcPredictiveMarketShield
        shield = BtcPredictiveMarketShield()

        # Case A: BTC below 1H EMA50 but with normal intraday returns (e.g. -0.15% on 1h, +0.02% on 15m)
        # Price is $64,600, EMA50 is ~$68,000 (c_now < ema50 * 0.95), but market is NOT flash dumping.
        n = 60
        prices_1h = np.linspace(70000.0, 64600.0, n)
        # Make the last two candles flat
        prices_1h[-1] = 64600.0
        prices_1h[-2] = 64650.0 # ret_1h = -0.07%
        df_1h_norm = pd.DataFrame({
            "open": prices_1h * 1.001,
            "high": prices_1h * 1.002,
            "low": prices_1h * 0.998,
            "close": prices_1h,
            "volume": np.full(n, 500.0)
        })
        prices_15m = np.linspace(64630.0, 64600.0, 20)
        prices_15m[-1] = 64600.0
        prices_15m[-2] = 64590.0 # ret_15m = +0.01%
        df_15m_norm = pd.DataFrame({
            "open": prices_15m * 1.0005,
            "high": prices_15m * 1.001,
            "low": prices_15m * 0.999,
            "close": prices_15m,
            "volume": np.full(20, 100.0)
        })
        btc_dfs_norm = {"15m": df_15m_norm, "1h": df_1h_norm}
        state_norm = shield.evaluate_regime(btc_dfs_norm, live_btc_price=64600.0)

        # Must NOT be classified as FLASH_DUMP or BEAR_CASCADE_BLACKOUT
        self.assertNotEqual(state_norm.get("regime"), "FLASH_DUMP")
        self.assertNotEqual(state_norm.get("status_code"), "BEAR_CASCADE_BLACKOUT")
        self.assertTrue(state_norm.get("altcoin_shorts_allowed"))

        # Case B: Acute Flash Dump Cascade (-3.0% in 15m)
        prices_15m_dump = np.linspace(67000.0, 67000.0, 20)
        prices_15m_dump[-1] = 64900.0 # -3.1% dump
        prices_15m_dump[-2] = 67000.0
        df_15m_dump = pd.DataFrame({
            "open": prices_15m_dump * 1.001,
            "high": prices_15m_dump * 1.002,
            "low": prices_15m_dump * 0.998,
            "close": prices_15m_dump,
            "volume": np.full(20, 5000.0)
        })
        btc_dfs_dump = {"15m": df_15m_dump, "1h": df_1h_norm}
        state_dump = shield.evaluate_regime(btc_dfs_dump, live_btc_price=64900.0)
        self.assertEqual(state_dump.get("regime"), "FLASH_DUMP")
        self.assertEqual(state_dump.get("status_code"), "BEAR_CASCADE_BLACKOUT")
        self.assertFalse(state_dump.get("altcoin_longs_allowed"))

    def test_14_adverse_limit_penetration_and_dynamic_blowout_guard(self):
        """
        Forensic Regression Test for Losing Signal S_USDT_15M_1794695654:
        1. validate_resting_limit_fill defers fill if price has blown adversely past the limit
           (e.g., green rocket > 0.40% through Short limit or red waterfall < -0.40% through Long limit).
        2. PaperTradingBot dynamic blowout guard tightens base_blowout_pct based on SL distance
           (45% of SL distance), cancelling resting orders before they can fill into a breakout.
        3. anchor_to_lower_high_and_ob and anchor_to_higher_low_and_ob enforce >= 1.40x ATR
           and >= 1.80% SL noise floor, preventing 1.08x ATR noise stop-outs.
        """
        # 1. validate_resting_limit_fill adverse overshoot protection
        limit_short = 0.03244
        # Case A: Clean touch at limit price
        conf_clean, rsn_clean, _ = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="SHORT", limit_price=limit_short, current_price=0.03244
        )
        self.assertTrue(conf_clean, f"Clean touch must confirm fill. Reason: {rsn_clean}")

        # Case B: Price has not reached limit yet (below limit for Short)
        conf_below, rsn_below, _ = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="SHORT", limit_price=limit_short, current_price=0.03220
        )
        self.assertFalse(conf_below, "Price below short limit must not trigger fill")

        # Case C: Price has blown past limit (+0.80% above limit into green rocket)
        price_rocket = limit_short * 1.0080 # 0.03270
        conf_rocket, rsn_rocket, tel_rocket = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="SHORT", limit_price=limit_short, current_price=price_rocket
        )
        self.assertFalse(conf_rocket, "Price surging +0.80% past short limit must defer fill")
        self.assertEqual(tel_rocket.get("fill_state"), "ADVERSE_PENETRATION_DEFERRED")
        self.assertIn("Adverse price surge", rsn_rocket)

        # Case D: Symmetric check for LONG (red waterfall dump -0.80% below Long limit)
        limit_long = 100.0
        price_dump = 99.20
        conf_dump, rsn_dump, tel_dump = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="LONG", limit_price=limit_long, current_price=price_dump
        )
        self.assertFalse(conf_dump, "Price dumping -0.80% through long limit must defer fill")
        self.assertEqual(tel_dump.get("fill_state"), "ADVERSE_PENETRATION_DEFERRED")
        self.assertIn("Adverse price dump", rsn_dump)

        # 2. Dynamic Blowout Guard in PaperTradingBot
        import tempfile
        import shutil
        from datetime import datetime, timezone
        tmp_dir = tempfile.mkdtemp()
        try:
            ledger_path = os.path.join(tmp_dir, "test_ledger_blowout.json")
            bot = PaperTradingBot(ledger_file=ledger_path)
            pos_susdt = {
                "trade_id": "TEST_SUSDT_SHORT",
                "symbol": "S/USDT",
                "desk": "scalp",
                "direction": "SHORT",
                "horizon": "15M",
                "entry_price": 0.03244,
                "optimal_entry_limit": 0.03244,
                "sl_price": 0.033006, # SL distance = 1.74%
                "tp1_price": 0.031167,
                "status": "RESTING_LIMIT",
                "is_limit_resting": True,
                "placed_at_utc": datetime.now(timezone.utc).isoformat(),
                "opened_at_utc": datetime.now(timezone.utc).isoformat()
            }
            bot.data["open_positions"] = [pos_susdt]

            # Price surges to 0.03272 (+0.86% through limit, > 45% of 1.74% SL distance = 0.78% blowout gate)
            bot.on_tick(live_prices={"S/USDT": 0.03272})

            # Position must be cancelled for blowout, NOT filled
            self.assertEqual(len(bot.data["open_positions"]), 0, "Blown-out resting limit must be cancelled")
            canc_list = bot.data.get("cancelled_orders", [])
            self.assertEqual(len(canc_list), 1)
            self.assertEqual(canc_list[0]["cancellation_reason"], "CANCELLED_EXTREME_MACRO_BLOWOUT")
            self.assertIn("Price rallied", canc_list[0]["cancellation_detail"])
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # 3. Volatility noise floor: >= 1.40x ATR and >= 1.80% SL distance
        df_15m_s = pd.DataFrame({
            "open": [0.0322, 0.0323, 0.0321, 0.0322, 0.0324, 0.0322],
            "high": [0.0326, 0.0325, 0.0324, 0.0326, 0.0326, 0.0324],
            "low": [0.0318, 0.0319, 0.0318, 0.0317, 0.0319, 0.0318],
            "close": [0.0323, 0.0321, 0.0322, 0.0324, 0.0322, 0.0322],
            "volume": [1000, 1000, 1000, 1000, 1000, 1000]
        })
        res_short = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
            df_15m=df_15m_s,
            lh_pivot_price=0.03244,
            current_price=0.0322,
            spread_bps=5.0
        )
        sl_dist_short = (res_short["sl_price"] - res_short["entry_price"]) / res_short["entry_price"]
        self.assertGreaterEqual(sl_dist_short, 0.0180, f"SL distance must be at least 1.80%, got {sl_dist_short:.4%}")
        self.assertGreaterEqual(res_short["risk_reward_ratio"], 2.0, "1:2 R:R must be preserved")

    def test_15_adverse_penetration_smart_stabilization_and_continuous_oos_eval(self):
        """
        Comprehensive Verification for:
        1. Smart Penetration Stabilization: No sacrificed fills when price thrusts past limit
           and stabilizes via microstructure absorption (OBI/CVD) or candlestick exhaustion wicks.
        2. PaperTradingBot Multi-Tick Velocity Stall: Fills orders at superior price improvement
           when adverse velocity stalls before blowout.
        3. Continuous Out-of-Sample Forward Edge Evaluator:
           Verifies that V16ShadowValidationEngine.run_continuous_forward_edge_evaluation
           produces authoritative forward validation reports across scan cycles.
        """
        # 1. Smart Penetration Stabilization on SHORT
        limit_short = 100.0
        price_overshoot_short = 100.60 # +0.60% above limit

        # Case A: Overshoot with aggressive seller absorption (Ask wall depth + negative CVD)
        depth_seller_absorb = {
            "bids": [[100.59, 1.0]],
            "asks": [[100.61, 5.0]], # Ask wall 5x larger than bid
            "has_depth": True
        }
        cvd_seller_absorb = {"cvd_surge": -0.25} # Aggressive market selling into the bounce
        conf_short_stab, rsn_short_stab, tel_short_stab = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="SHORT",
            limit_price=limit_short,
            current_price=price_overshoot_short,
            depth_data=depth_seller_absorb,
            cvd_metrics=cvd_seller_absorb
        )
        self.assertTrue(conf_short_stab, "Seller absorption must confirm fill at superior short price")
        self.assertEqual(tel_short_stab.get("fill_state"), "STABILIZED_PENETRATION_CONFIRMED")
        self.assertEqual(tel_short_stab.get("fill_confirmation_type"), "STABILIZED_ABSORPTION_FILL")
        self.assertEqual(tel_short_stab.get("execution_price"), 100.60)

        # Case B: Smart Penetration Stabilization on LONG
        limit_long = 100.0
        price_overshoot_long = 99.40 # -0.60% below limit
        depth_buyer_absorb = {
            "bids": [[99.39, 5.0]], # Bid support wall 5x larger than ask
            "asks": [[99.41, 1.0]],
            "has_depth": True
        }
        cvd_buyer_absorb = {"cvd_surge": +0.25} # Aggressive market buying into the dip
        conf_long_stab, rsn_long_stab, tel_long_stab = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="LONG",
            limit_price=limit_long,
            current_price=price_overshoot_long,
            depth_data=depth_buyer_absorb,
            cvd_metrics=cvd_buyer_absorb
        )
        self.assertTrue(conf_long_stab, "Buyer absorption must confirm fill at superior long price")
        self.assertEqual(tel_long_stab.get("fill_state"), "STABILIZED_PENETRATION_CONFIRMED")
        self.assertEqual(tel_long_stab.get("fill_confirmation_type"), "STABILIZED_ABSORPTION_FILL")
        self.assertEqual(tel_long_stab.get("execution_price"), 99.40)

        # 2. PaperTradingBot Multi-Tick Velocity Stall Execution
        import tempfile
        import shutil
        from datetime import datetime, timezone
        tmp_dir = tempfile.mkdtemp()
        try:
            ledger_path = os.path.join(tmp_dir, "test_ledger_stall.json")
            bot = PaperTradingBot(ledger_file=ledger_path)
            pos_stall = {
                "trade_id": "TEST_STALL_FILL",
                "symbol": "BTC/USDT",
                "desk": "scalp",
                "direction": "SHORT",
                "horizon": "15M",
                "entry_price": 60000.0,
                "optimal_entry_limit": 60000.0,
                "sl_price": 61500.0, # 2.5% SL
                "tp1_price": 57000.0, # 5.0% TP1 (R:R = 1:2.0)
                "status": "RESTING_LIMIT",
                "is_limit_resting": True,
                "placed_at_utc": datetime.now(timezone.utc).isoformat(),
                "opened_at_utc": datetime.now(timezone.utc).isoformat()
            }
            bot.data["open_positions"] = [pos_stall]

            # Tick 1: Price surges +0.50% past limit without depth -> Defer
            bot.on_tick(live_prices={"BTC/USDT": 60300.0})
            self.assertEqual(pos_stall["status"], "RESTING_LIMIT")
            self.assertTrue(pos_stall.get("awaiting_microstructure_inflow"))
            self.assertEqual(pos_stall.get("microstructure_deferral_count"), 1)

            # Tick 2: Price velocity stalls at 60310.0 (delta = 0.016% < 0.08%) -> Confirmed fill at superior price!
            bot.on_tick(live_prices={"BTC/USDT": 60310.0})
            self.assertEqual(pos_stall["status"], "OPEN", "Stalled momentum must confirm fill at superior price")
            self.assertEqual(pos_stall["entry_price"], 60310.0)
            self.assertTrue(pos_stall.get("price_improved"))
            self.assertEqual(pos_stall.get("fill_confirmation_type"), "STABILIZED_VELOCITY_STALL_FILL")

            # 3. Continuous Out-of-Sample Forward Edge Evaluator
            from app.quant_v16.validation_engine import V16ShadowValidationEngine
            oos_res = V16ShadowValidationEngine.run_continuous_forward_edge_evaluation(export_dir=tmp_dir)
            self.assertIn("experiment_id", oos_res)
            self.assertIn("brier_score", oos_res)
            self.assertIn("expected_calibration_error", oos_res)
            self.assertIn("promotion_gates", oos_res)

            # Verify exported files exist and are valid JSON
            val_path = os.path.join(tmp_dir, "v16_validation_report.json")
            cal_path = os.path.join(tmp_dir, "v16_calibration_metrics.json")
            edge_path = os.path.join(tmp_dir, "live_forward_edge_metrics.json")
            self.assertTrue(os.path.exists(val_path), "v16_validation_report.json must be generated")
            self.assertTrue(os.path.exists(cal_path), "v16_calibration_metrics.json must be generated")
            self.assertTrue(os.path.exists(edge_path), "live_forward_edge_metrics.json must be generated")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)



if __name__ == "__main__":
    unittest.main()
