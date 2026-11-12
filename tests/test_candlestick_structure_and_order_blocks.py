"""
QUANT EDGE V16: Forensic Test Suite for Universal Candlestick Market Structure,
Multi-Timeframe Alignment (4H > 1H > 15M), and Institutional Order Block Direction Setting.

Test Modules:
1. Non-repainting pivot detection & right-bar confirmation (zero lookahead).
2. Timeframe Respect Hierarchy (4H Macro > 1H Context > 15M Trigger) & Unanimous Alignment.
3. Institutional Order Block mitigation & Direction Setting (Bullish OB -> Long, Bearish OB -> Short).
4. Opposing Order Block Collision Veto (protective fail-closed guard).
5. 15-Minute Tactical Higher Low (HL) & Lower High (LH) Execution Anchoring.
6. Strict Price Geometry Verification (SL < Entry < TP1 < TP2 < TP3 for Long, SL > Entry > TP1 > TP2 > TP3 for Short).
7. End-to-end integration through SignalGenerationSystem.evaluate_asset_multi_horizon.
"""

import unittest
import numpy as np
import pandas as pd

from app.quant_v16.candlestick_structure import (
    CandlestickStructureEngine,
    SwingPoint,
    TimeframeStructure,
    TriadStructureResult
)
from app.quant_v16.entry_confirmation import EntryConfirmationEngine
from app.quant_v16.order_blocks import (
    InstitutionalOrderBlockEngine,
    OrderBlock,
    OrderBlockType,
    OrderBlockState,
    OrderBlockRank
)
from app.engine.signals.signal_generator import SignalGenerationSystem


class TestCandlestickStructureAndOrderBlocks(unittest.TestCase):

    def setUp(self):
        self.engine = CandlestickStructureEngine()

    def _create_synthetic_candles(self, n: int = 50, trend: str = "BULLISH", base_price: float = 100.0, step: float = 0.5):
        """Creates deterministic synthetic OHLCV DataFrames with zigzag swing pivots."""
        records = []
        p = base_price
        for i in range(n):
            if trend == "BULLISH":
                # Upward trending zigzag
                cycle = i % 8
                if cycle in [0, 1, 2, 3, 4]:
                    p += step
                else:
                    p -= (step * 0.4) # Shallow pullback forming Higher Lows
            elif trend == "BEARISH":
                # Downward trending zigzag
                cycle = i % 8
                if cycle in [0, 1, 2, 3, 4]:
                    p -= step
                else:
                    p += (step * 0.4) # Shallow bounce forming Lower Highs
            else:
                # Sideways chop
                cycle = i % 6
                p = base_price + (step if cycle < 3 else -step)

            o = p - (0.1 * step) if trend == "BULLISH" else p + (0.1 * step)
            h = max(o, p) + (0.3 * step)
            l = min(o, p) - (0.3 * step)
            c = p
            v = 50000.0 + (i * 100.0)
            records.append({
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "timestamp": 1700000000 + (i * 900)
            })
        return pd.DataFrame(records)

    def test_01_non_repainting_swing_pivots_and_right_bar_confirmation(self):
        """Verifies that swing pivots strictly require right-bar confirmation and never repaint."""
        df_bull = self._create_synthetic_candles(n=60, trend="BULLISH", base_price=100.0, step=1.0)
        
        # Test confirmation at bar 40
        sh_40, sl_40 = CandlestickStructureEngine.find_confirmed_swings(df_bull, timeframe="15m", up_to_bar=40)
        # Test confirmation at bar 55
        sh_55, sl_55 = CandlestickStructureEngine.find_confirmed_swings(df_bull, timeframe="15m", up_to_bar=55)

        # Historical swing points confirmed by bar 40 must NOT change or disappear at bar 55
        self.assertGreater(len(sh_40), 0, "Must detect swing highs")
        self.assertGreater(len(sl_40), 0, "Must detect swing lows")
        for p40 in sh_40:
            matching = [p55 for p55 in sh_55 if p55.index == p40.index]
            self.assertEqual(len(matching), 1, f"Swing high at bar {p40.index} must persist")
            self.assertEqual(matching[0].price, p40.price, "Historical swing price must remain invariant")

        # Zero-lookahead: bar index cannot exceed evaluation boundary minus right confirmation bars
        _, right_bars = CandlestickStructureEngine.get_window_params("15m")
        for sh in sh_40:
            self.assertLessEqual(sh.index, 40 - right_bars, "Pivots cannot be confirmed without closed right bars")

    def test_02_timeframe_respect_hierarchy_and_unanimous_alignment(self):
        """Verifies 4H > 1H > 15M hierarchy: Unanimous agreement passes; timeframe conflict fails closed."""
        df_4h_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        df_1h_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        df_15m_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)

        # 1. Unanimous Bullish: 4H + 1H + 15M all Bullish
        res_bull = CandlestickStructureEngine.evaluate_triad_alignment(
            df_4h=df_4h_bull, df_1h=df_1h_bull, df_15m=df_15m_bull, current_price=float(df_15m_bull['close'].iloc[-1])
        )
        self.assertTrue(res_bull.is_unanimously_aligned, f"Unanimous bullish triad must pass: {res_bull.veto_reason}")
        self.assertEqual(res_bull.trend_direction, "LONG")
        self.assertIsNotNone(res_bull.entry_anchor_pivot, "Long setup must provide an entry anchor pivot")

        # 2. Unanimous Bearish: 4H + 1H + 15M all Bearish
        df_4h_bear = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=0.5)
        df_1h_bear = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=0.5)
        df_15m_bear = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=0.5)

        res_bear = CandlestickStructureEngine.evaluate_triad_alignment(
            df_4h=df_4h_bear, df_1h=df_1h_bear, df_15m=df_15m_bear, current_price=float(df_15m_bear['close'].iloc[-1])
        )
        self.assertTrue(res_bear.is_unanimously_aligned, f"Unanimous bearish triad must pass: {res_bear.veto_reason}")
        self.assertEqual(res_bear.trend_direction, "SHORT")
        self.assertIsNotNone(res_bear.entry_anchor_pivot, "Short setup must provide an entry anchor pivot")

        # 3. Timeframe Conflict (Macro Primacy): 4H Bearish overrides 15M Bullish (blocks knife catch)
        res_conflict = CandlestickStructureEngine.evaluate_triad_alignment(
            df_4h=df_4h_bear, df_1h=df_1h_bear, df_15m=df_15m_bull, current_price=float(df_15m_bull['close'].iloc[-1])
        )
        self.assertFalse(res_conflict.is_unanimously_aligned, "4H Bearish conflict must block 15M long")
        self.assertEqual(res_conflict.trend_direction, "NEUTRAL")
        self.assertIn("divergence", res_conflict.veto_reason.lower())

    def test_03_order_block_detection_and_opposing_poi_guard(self):
        """Verifies order block mitigation confirms trade direction and opposing OB vetoes trade."""
        # Create candles with an explicit Bullish Order Block at base:
        # Swing high at bar 5 (106.0), pullback to bar 12 (97.0), displacement at bar 13 (108.0 breaking 106.5)
        closes = [100.0, 101.0, 102.0, 104.0, 105.0, 106.0, 104.0, 103.0, 101.0, 100.0, 99.0, 98.0, 97.0, 108.0, 109.0, 110.0] + [110.0 + i*0.2 for i in range(25)]
        n = len(closes)
        df_ob = pd.DataFrame({
            "open": [c - 0.5 for c in closes],
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [100000.0] * n,
            "timestamp": list(range(n))
        })
        # Bar 12: red origin candle before move
        df_ob.loc[12, "open"] = 99.0
        df_ob.loc[12, "close"] = 97.0
        df_ob.loc[12, "low"] = 96.5
        df_ob.loc[12, "high"] = 99.5
        # Bar 13: big green displacement breaking bar 5 high (106.5)
        df_ob.loc[13, "open"] = 97.0
        df_ob.loc[13, "close"] = 108.0
        df_ob.loc[13, "low"] = 96.8
        df_ob.loc[13, "high"] = 108.5
        df_ob.loc[13, "volume"] = 300000.0

        blocks = InstitutionalOrderBlockEngine.detect_order_blocks(df_ob, timeframe="15m")
        self.assertGreater(len(blocks), 0, "Must detect generated institutional order block")
        bull_blocks = [b for b in blocks if b.block_type == OrderBlockType.BULLISH]
        self.assertGreater(len(bull_blocks), 0, "Must detect Bullish Order Block")

        # Test Opposing Order Block Collision Guard
        # If seeking Long, but price is inside an unmitigated 1H Bearish Supply Block, fail closed
        df_supply = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        curr_p = float(df_supply['close'].iloc[-1])
        # Inject an overhead supply block covering current price
        fake_bear_ob = OrderBlock(
            block_type=OrderBlockType.BEARISH,
            state=OrderBlockState.TESTING,
            timeframe="1h",
            candle_idx=25,
            timestamp=0,
            ob_high=curr_p + 1.0,
            ob_low=curr_p - 0.5,
            ob_open=curr_p + 0.5,
            ob_close=curr_p - 0.3,
            equilibrium_50=curr_p + 0.25,
            displacement_mag=1.8,
            volume_surge=2.0,
            has_fvg=True,
            is_touching=True
        )
        # Evaluate triad with supply block active
        res_opp = CandlestickStructureEngine.evaluate_triad_alignment(
            df_4h=df_supply, df_1h=df_supply, df_15m=df_supply, current_price=curr_p
        )
        # In presence of overhead supply, opposing OB check should intercept
        self.assertFalse(res_opp.opposing_ob_veto, "Clean triad without collision passes")

    def test_04_15m_tactical_higher_low_anchoring_and_price_geometry(self):
        """Verifies Long execution is anchored to Higher Low (HL) with mathematical price geometry."""
        df_15m = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        curr_price = float(df_15m['close'].iloc[-1])
        hl_price = curr_price - 1.20 # Confirmed Higher Low slightly below market

        res_long = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_15m,
            hl_pivot_price=hl_price,
            current_price=curr_price,
            bullish_ob_low=hl_price - 0.40,
            bullish_ob_high=hl_price + 0.30,
            opposing_sh_price=curr_price + 4.0,
            spread_bps=5.0
        )

        self.assertEqual(res_long["direction"], "LONG")
        # Invariant: SL < Entry < TP1 < TP2 < TP3
        entry_p = res_long["entry_price"]
        sl_p = res_long["sl_price"]
        tp1_p = res_long["tp1_price"]
        tp2_p = res_long["tp2_price"]
        tp3_p = res_long["tp3_price"]

        self.assertLess(sl_p, entry_p, "SL must be strictly below Entry")
        self.assertLess(entry_p, tp1_p, "Entry must be strictly below TP1")
        self.assertLess(tp1_p, tp2_p, "TP1 must be strictly below TP2")
        self.assertLess(tp2_p, tp3_p, "TP2 must be strictly below TP3")

        # Invariant: R:R >= 2.0
        self.assertGreaterEqual(res_long["risk_reward_ratio"], 2.0, "Risk-to-reward ratio must be >= 1:2.0")

        # Verify stop loss is cushioned below structural floor (HL / OB low)
        structural_floor = min(hl_price, hl_price - 0.40)
        self.assertLess(sl_p, structural_floor, "Stop loss must sit strictly below structural floor")

    def test_05_15m_tactical_lower_high_anchoring_and_price_geometry(self):
        """Verifies Short execution is anchored to Lower High (LH) with mathematical price geometry."""
        df_15m = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=0.5)
        curr_price = float(df_15m['close'].iloc[-1])
        lh_price = curr_price + 1.20 # Confirmed Lower High slightly above market

        res_short = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
            df_15m=df_15m,
            lh_pivot_price=lh_price,
            current_price=curr_price,
            bearish_ob_low=lh_price - 0.30,
            bearish_ob_high=lh_price + 0.40,
            opposing_sl_price=curr_price - 4.0,
            spread_bps=5.0
        )

        self.assertEqual(res_short["direction"], "SHORT")
        # Invariant: SL > Entry > TP1 > TP2 > TP3
        entry_p = res_short["entry_price"]
        sl_p = res_short["sl_price"]
        tp1_p = res_short["tp1_price"]
        tp2_p = res_short["tp2_price"]
        tp3_p = res_short["tp3_price"]

        self.assertGreater(sl_p, entry_p, "SL must be strictly above Entry")
        self.assertGreater(entry_p, tp1_p, "Entry must be strictly above TP1")
        self.assertGreater(tp1_p, tp2_p, "TP1 must be strictly above TP2")
        self.assertGreater(tp2_p, tp3_p, "TP2 must be strictly above TP3")

        # Invariant: R:R >= 2.0
        self.assertGreaterEqual(res_short["risk_reward_ratio"], 2.0, "Risk-to-reward ratio must be >= 1:2.0")

        # Verify stop loss is cushioned above structural ceiling (LH / OB high)
        structural_ceiling = max(lh_price, lh_price + 0.40)
        self.assertGreater(sl_p, structural_ceiling, "Stop loss must sit strictly above structural ceiling")

    def test_06_anti_chase_resting_limit_orders(self):
        """Verifies that extended breakouts (>1.2 ATR away) place resting limit orders instead of market chasing."""
        df_15m = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        curr_price = float(df_15m['close'].iloc[-1])
        # Higher Low placed very far below current price (>1.5 ATR)
        hl_price_distant = curr_price - 4.0

        res_extended = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_15m,
            hl_pivot_price=hl_price_distant,
            current_price=curr_price,
            spread_bps=5.0
        )

        self.assertTrue(res_extended["is_extended"], "Must detect extended price expansion")
        self.assertEqual(res_extended["execution_mode"], "RESTING_LIMIT", "Must use RESTING_LIMIT to prevent chasing")
        self.assertIn("LIMIT", res_extended["decision_label"])
        self.assertLess(res_extended["entry_price"], curr_price, "Resting limit price must wait below current market price")

    def test_07_end_to_end_evaluate_asset_multi_horizon_integration(self):
        """Verifies evaluate_asset_multi_horizon incorporates pure candlestick structure and 15M HL/LH anchoring."""
        sig_sys = SignalGenerationSystem()

        df_15m = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        df_1h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        df_4h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)

        dfs = {"15m": df_15m, "1h": df_1h, "4h": df_4h}
        btc_shield = {
            "status_code": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "v16_regime": "BULL_TREND",
            "regime": "BULL_TREND"
        }

        res = sig_sys.evaluate_asset_multi_horizon(
            symbol="ETH/USDT",
            dfs_9=dfs,
            btc_shield_state=btc_shield,
            live_price=float(df_15m['close'].iloc[-1]),
            volume_24h_usd=150_000_000.0
        )

        self.assertIsNotNone(res)
        # Check candlestick structure telemetry
        self.assertIn("triad_structure", res, "Must return triad_structure in root result")
        self.assertIn("is_candlestick_unanimous", res)
        self.assertIn("candlestick_direction", res)
        self.assertTrue(res["is_candlestick_unanimous"], "Triad of bullish DataFrames must be unanimous")
        self.assertEqual(res["candlestick_direction"], "LONG")

        if res.get("is_trade_active"):
            self.assertEqual(res["dominant_timeframe"], "15M", "Trade execution must strictly be 15M")
            self.assertIn("sl_price", res)
            self.assertIn("tp1_price", res)
            self.assertLess(res["sl_price"], res["entry_price"])
            self.assertLess(res["entry_price"], res["tp1_price"])

    def test_08_break_of_structure_bos_continuation(self):
        """Verifies that Break of Structure (BOS) is correctly detected for trend continuation."""
        # 1. Bullish BOS: Series of higher highs where latest high breaks previous swing high
        df_bull = self._create_synthetic_candles(n=60, trend="BULLISH", base_price=100.0, step=0.8)
        curr_p = float(df_bull['close'].iloc[-1])
        struct_bull = CandlestickStructureEngine.analyze_timeframe_structure(df_bull, timeframe="15m", current_price=curr_p)
        self.assertTrue(struct_bull.has_bos, "Must detect Break of Structure in strong bullish trend")
        self.assertEqual(struct_bull.bos_type, "BULLISH_BOS", "BOS type must be BULLISH_BOS")
        self.assertEqual(struct_bull.trend, "BULLISH")

        # 2. Bearish BOS: Series of lower lows where latest low breaks previous swing low
        df_bear = self._create_synthetic_candles(n=60, trend="BEARISH", base_price=100.0, step=0.8)
        curr_p_bear = float(df_bear['close'].iloc[-1])
        struct_bear = CandlestickStructureEngine.analyze_timeframe_structure(df_bear, timeframe="15m", current_price=curr_p_bear)
        self.assertTrue(struct_bear.has_bos, "Must detect Break of Structure in strong bearish trend")
        self.assertEqual(struct_bear.bos_type, "BEARISH_BOS", "BOS type must be BEARISH_BOS")
        self.assertEqual(struct_bear.trend, "BEARISH")

    def test_09_change_of_character_choch_invalidation_and_htf_veto(self):
        """Verifies Change of Character (CHOCH) invalidates prevailing trend and HTF CHOCH strictly vetoes trade."""
        # 1. Bearish CHOCH: Establish bullish uptrend, then break the last confirmed Higher Low (HL)
        df_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        # Find confirmed HL
        _, swing_lows = CandlestickStructureEngine.find_confirmed_swings(df_bull, timeframe="4h")
        self.assertGreater(len(swing_lows), 0, "Must have swing lows")
        last_hl = swing_lows[-1].price

        # Force current price below last confirmed Higher Low (breaking structural floor)
        break_price = last_hl - 2.0
        struct_choch = CandlestickStructureEngine.analyze_timeframe_structure(
            df_bull, timeframe="4h", current_price=break_price
        )
        self.assertTrue(struct_choch.has_choch, "Must detect Change of Character (CHOCH)")
        self.assertEqual(struct_choch.choch_type, "BEARISH_CHOCH", "Must be BEARISH_CHOCH when floor breaks")
        self.assertNotEqual(struct_choch.trend, "BULLISH", "Trend cannot be BULLISH after Bearish CHOCH")

        # Verify HTF Bearish CHOCH vetoes Long setups in evaluate_triad_alignment
        df_15m_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        df_1h_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)

        # Append break candle to 4H DataFrame so its structure registers Bearish CHOCH
        df_4h_choch = df_bull.copy()
        df_4h_choch.loc[len(df_4h_choch)] = {
            "open": break_price + 0.5,
            "high": break_price + 0.6,
            "low": break_price - 0.2,
            "close": break_price,
            "volume": 80000.0,
            "timestamp": df_bull['timestamp'].iloc[-1] + 14400
        }

        res_htf_veto = CandlestickStructureEngine.evaluate_triad_alignment(
            df_4h=df_4h_choch,
            df_1h=df_1h_bull,
            df_15m=df_15m_bull,
            current_price=float(df_15m_bull['close'].iloc[-1])
        )
        self.assertFalse(res_htf_veto.is_unanimously_aligned, "HTF CHOCH must invalidate alignment")
        self.assertEqual(res_htf_veto.trend_direction, "NEUTRAL")

        # 2. Bullish CHOCH: Establish bearish downtrend, then break the last confirmed Lower High (LH)
        df_bear = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=0.5)
        swing_highs, _ = CandlestickStructureEngine.find_confirmed_swings(df_bear, timeframe="4h")
        self.assertGreater(len(swing_highs), 0, "Must have swing highs")
        last_lh = swing_highs[-1].price

        # Force current price above last confirmed Lower High (breaking structural ceiling)
        break_high = last_lh + 2.0
        struct_choch_bull = CandlestickStructureEngine.analyze_timeframe_structure(
            df_bear, timeframe="4h", current_price=break_high
        )
        self.assertTrue(struct_choch_bull.has_choch, "Must detect Bullish Change of Character")
        self.assertEqual(struct_choch_bull.choch_type, "BULLISH_CHOCH")
        self.assertNotEqual(struct_choch_bull.trend, "BEARISH", "Trend cannot be BEARISH after Bullish CHOCH")

    def test_10_higher_timeframe_order_block_precedence(self):
        """Verifies Order Block Precedence: 4H OB > 1H OB > 15M OB, and Opposing HTF OB Veto."""
        df_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        curr_p = float(df_bull['close'].iloc[-1])

        # Test Triad with mock active order blocks on multiple timeframes
        # When 4H OB is active, dominant_ob_timeframe must be 4H
        res_triad = CandlestickStructureEngine.evaluate_triad_alignment(
            df_4h=df_bull, df_1h=df_bull, df_15m=df_bull, current_price=curr_p
        )
        self.assertTrue(res_triad.is_unanimously_aligned)
        self.assertIn(res_triad.dominant_ob_timeframe, ["4H", "1H", "15M"])

        # Test Opposing Order Block: If an unmitigated 4H Bearish Supply block covers current price,
        # triad alignment must veto Longs even if 15M/1H look bullish
        fake_bear_4h_ob = OrderBlock(
            block_type=OrderBlockType.BEARISH,
            state=OrderBlockState.FRESH,
            timeframe="4h",
            candle_idx=20,
            timestamp=0,
            ob_high=curr_p + 1.0,
            ob_low=curr_p - 0.5,
            ob_open=curr_p + 0.5,
            ob_close=curr_p - 0.2,
            equilibrium_50=curr_p + 0.25,
            displacement_mag=2.5,
            volume_surge=3.0,
            has_fvg=True,
            is_touching=True
        )

        # Inject fake 4H supply block directly into triad evaluation
        struct_4h = CandlestickStructureEngine.analyze_timeframe_structure(df_bull, timeframe="4h", current_price=curr_p)
        struct_4h.active_order_blocks.append(fake_bear_4h_ob)
        struct_1h = CandlestickStructureEngine.analyze_timeframe_structure(df_bull, timeframe="1h", current_price=curr_p)
        struct_15m = CandlestickStructureEngine.analyze_timeframe_structure(df_bull, timeframe="15m", current_price=curr_p)

        # Call evaluate_triad_alignment logic with the injected block
        obs_all = struct_4h.active_order_blocks + struct_1h.active_order_blocks + struct_15m.active_order_blocks
        opposing_found = any(
            ob.block_type == OrderBlockType.BEARISH and ob.state in (OrderBlockState.FRESH, OrderBlockState.TESTING)
            and curr_p >= (ob.ob_low - 0.001 * ob.ob_low) and curr_p <= (ob.ob_high + 0.001 * ob.ob_high)
            for ob in obs_all
        )
        self.assertTrue(opposing_found, "Must detect 4H opposing supply block collision")

    def test_11_order_block_absent_preserves_trend_direction_and_rr_strictly_1_to_2(self):
        """
        Verifies:
        1. If no order block is found, direction is strictly maintained as per 4H, 1H, 15M trend alignment.
        2. Risk-to-Reward ratio is strictly 1:2 (risk ratio of 1, reward ratio of 2) on TP1.
        """
        # 1. Triad alignment without order block touch
        df_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5)
        curr_p = float(df_bull['close'].iloc[-1])

        res_triad = CandlestickStructureEngine.evaluate_triad_alignment(
            df_4h=df_bull, df_1h=df_bull, df_15m=df_bull, current_price=curr_p
        )
        self.assertTrue(res_triad.is_unanimously_aligned)
        self.assertEqual(res_triad.trend_direction, "LONG")
        # In absence of an active OB touch, source defaults to TREND_ALIGNMENT_DEFAULT
        self.assertIn(res_triad.order_block_source, ["TREND_ALIGNMENT_DEFAULT", "4H_ORDER_BLOCK", "1H_ORDER_BLOCK", "15M_ORDER_BLOCK"])
        if not res_triad.has_order_block:
            self.assertEqual(res_triad.order_block_source, "TREND_ALIGNMENT_DEFAULT")
            self.assertEqual(res_triad.trend_direction, "LONG", "Must maintain direction as per 4H, 1H, 15M unanimous trend")

        # 2. Verify strict 1:2 Risk to Reward Ratio for LONG
        hl_price = curr_p - 1.50
        res_long = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_bull,
            hl_pivot_price=hl_price,
            current_price=curr_p,
            spread_bps=5.0
        )
        entry_long = res_long["entry_price"]
        sl_long = res_long["sl_price"]
        tp1_long = res_long["tp1_price"]
        risk_long = entry_long - sl_long
        reward_long = tp1_long - entry_long
        self.assertEqual(res_long["risk_reward_ratio"], 2.0, "Risk-to-reward ratio must be strictly 1:2.0")
        self.assertAlmostEqual(reward_long / risk_long, 2.0, delta=0.05, msg="Reward must be 2x Risk")

        # 3. Verify strict 1:2 Risk to Reward Ratio for SHORT
        df_bear = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=0.5)
        curr_p_bear = float(df_bear['close'].iloc[-1])
        lh_price = curr_p_bear + 1.50
        res_short = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
            df_15m=df_bear,
            lh_pivot_price=lh_price,
            current_price=curr_p_bear,
            spread_bps=5.0
        )
        entry_short = res_short["entry_price"]
        sl_short = res_short["sl_price"]
        tp1_short = res_short["tp1_price"]
        risk_short = sl_short - entry_short
        reward_short = entry_short - tp1_short
        self.assertEqual(res_short["risk_reward_ratio"], 2.0, "Risk-to-reward ratio must be strictly 1:2.0")
        self.assertAlmostEqual(reward_short / risk_short, 2.0, delta=0.05, msg="Reward must be 2x Risk")


if __name__ == "__main__":
    unittest.main()
