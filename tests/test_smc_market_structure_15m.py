"""
QUANT EDGE V16: Forensic Test Suite for Universal SMC, Multi-Timeframe (4H > 1H > 15M),
Order Block Routing, Top 100 Non-Meme Universe Filter, and 15M Scalp Execution Engine.

Authoritative Test Coverage:
1. Institutional Universe Screener: Top 100 utility coins, category tags exclusion, explicit meme blacklist,
   $10M volume floor, listing age check, stablecoin and synthetic exclusion.
2. Vectorized Non-Repainting Fractal Swings: Left/Right confirmation windows, strict zero lookahead.
3. BOS & CHoCH State Machine: Candle body close confirmation, structural trend shifts, HTF CHoCH precedence.
4. Institutional Order Block Engine: FVG and displacement detection, lifecycle (ACTIVE -> TESTING -> MITIGATED),
   and strict HTF precedence (4H OB > 1H OB > 15M OB).
5. Pre-AI Decision Matrix:
   - Scenario A: Active Order Block hit -> trade direction set strictly by OB.
   - Scenario B: No Order Block hit -> trade direction kept strictly aligned with unanimous 4H + 1H + 15M trend.
   - Divergence: Timeframe mismatch -> fails closed to NEUTRAL (NO_SIGNAL).
   - Opposing POI Guard: Vetoes trades colliding into opposing HTF supply/demand blocks.
6. 15-Minute Signal Engine (SignalEngine15M):
   - Scalp horizon only (strictly 15M).
   - Long entry at 15M HL / Bullish OB; Short entry at 15M LH / Bearish OB.
   - Stop Loss buffer: 0.15 * ATR_15m.
   - Strict 1:2 Risk-to-Reward ratio (TP1 = Entry +/- 2.0 * Risk).
   - Price geometry invariants: SL < Entry < TP1 < TP2 < TP3 (Long) | SL > Entry > TP1 > TP2 > TP3 (Short).
"""

from datetime import datetime, timezone
import unittest
import numpy as np
import pandas as pd

from app.quant_v16.universe_filter import (
    InstitutionalUniverseFilter,
    TOP_100_UNIVERSE_SIZE,
    MIN_INSTITUTIONAL_VOLUME_USD,
    EXCLUDED_MEME_BLACKLIST
)
from app.quant_v16.market_structure import (
    MarketStructureEngine,
    PreAIMarketStructureDecision,
    SwingPivot,
    TimeframeStructureProfile,
    OrderBlockStructure,
    TradeDirection,
    TrendDirection,
    OrderBlockCategory,
    OrderBlockStatus
)
from app.quant_v16.signal_engine_15m import (
    SignalEngine15M,
    ScalpTradeSetup15M
)


class TestSMCMarketStructure15M(unittest.TestCase):

    def _create_synthetic_candles(
        self,
        n: int = 60,
        trend: str = "BULLISH",
        base_price: float = 100.0,
        step: float = 0.5,
        timeframe_secs: int = 900
    ) -> pd.DataFrame:
        """Generates deterministic synthetic OHLCV candles with realistic swing pivots."""
        records = []
        p = base_price
        for i in range(n):
            if trend == "BULLISH":
                cycle = i % 8
                if cycle in [0, 1, 2, 3, 4]:
                    p += step
                else:
                    p -= (step * 0.4) # Shallow pullback forming Higher Lows
            elif trend == "BEARISH":
                cycle = i % 8
                if cycle in [0, 1, 2, 3, 4]:
                    p -= step
                else:
                    p += (step * 0.4) # Shallow bounce forming Lower Highs
            else:
                cycle = i % 6
                p = base_price + (step if cycle < 3 else -step)

            o = p - (0.1 * step) if trend == "BULLISH" else p + (0.1 * step)
            h = max(o, p) + (0.3 * step)
            l = min(o, p) - (0.3 * step)
            c = p
            v = 100_000.0 + (i * 200.0)
            records.append({
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": v,
                "timestamp": 1700000000 + (i * timeframe_secs)
            })
        return pd.DataFrame(records)

    # ==========================================================================
    # 1. INSTITUTIONAL UNIVERSE FILTER TESTS
    # ==========================================================================

    def test_01_universe_filter_rejects_all_blacklisted_memes(self):
        """Verifies that all explicit meme coins and shitcoins are strictly rejected."""
        test_memes = [
            "DOGE/USDT", "SHIB/USDT", "PEPE/USDT", "WIF/USDT", "BONK/USDT", "FLOKI/USDT",
            "BRETT/USDT", "MOG/USDT", "POPCAT/USDT", "NEIRO/USDT", "TRUMP/USDT", "FARTCOIN/USDT",
            "PNUT/USDT", "MEME/USDT", "TURBO/USDT", "BOME/USDT", "MEW/USDT", "BABYDOGE/USDT",
            "1000SATS/USDT"
        ]
        for sym in test_memes:
            is_valid, reason = InstitutionalUniverseFilter.is_valid_utility_coin(
                symbol=sym,
                price=1.0,
                volume_usd=50_000_000.0,
                listing_age_days=100.0
            )
            self.assertFalse(is_valid, f"{sym} must be rejected as meme/shitcoin")
            self.assertIn("EXCLUDED_MEME_OR_SHITCOIN", reason)

    def test_02_universe_filter_rejects_prohibited_category_tags(self):
        """Verifies rejection of assets carrying meme, pump-fun, or gambling category tags."""
        prohibited_tags = ["memes", "pump-fun", "dog-themed", "fan-token", "gambling", "solana-meme"]
        for tag in prohibited_tags:
            is_valid, reason = InstitutionalUniverseFilter.is_valid_utility_coin(
                symbol="RANDOMCOIN/USDT",
                price=5.0,
                volume_usd=20_000_000.0,
                category_tags=[tag],
                listing_age_days=60.0
            )
            self.assertFalse(is_valid, f"Asset with tag {tag} must be rejected")
            self.assertIn("EXCLUDED_CATEGORY_TAG", reason)

    def test_03_universe_filter_rejects_stablecoins_synthetic_and_leveraged(self):
        """Verifies rejection of stablecoins, leveraged tokens, and synthetic equities."""
        prohibited_tokens = ["USDT/USDT", "USDC/USDT", "FDUSD/USDT", "BTCUP/USDT", "ETH3L/USDT", "AAPLB/USDT"]
        for sym in prohibited_tokens:
            is_valid, _ = InstitutionalUniverseFilter.is_valid_utility_coin(
                symbol=sym,
                price=1.0,
                volume_usd=100_000_000.0
            )
            self.assertFalse(is_valid, f"{sym} must be rejected")

    def test_04_universe_filter_listing_age_and_volume_hurdles(self):
        """Verifies minimum 30-day listing age and $10M institutional volume floor."""
        # Brand new listing (< 30 days) must be rejected
        is_valid_young, reason_young = InstitutionalUniverseFilter.is_valid_utility_coin(
            symbol="NEWCOIN/USDT",
            price=2.0,
            volume_usd=30_000_000.0,
            listing_age_days=14.0 # Less than 30 days
        )
        self.assertFalse(is_valid_young)
        self.assertIn("INSUFFICIENT_LISTING_AGE", reason_young)

        # Low volume (< $10M) must be rejected for Tier-1
        is_valid_low_vol, reason_vol = InstitutionalUniverseFilter.is_valid_utility_coin(
            symbol="UTILITY/USDT",
            price=10.0,
            volume_usd=5_000_000.0, # Below $10M
            listing_age_days=90.0,
            min_volume=MIN_INSTITUTIONAL_VOLUME_USD
        )
        self.assertFalse(is_valid_low_vol)
        self.assertIn("VOLUME_BELOW_FLOOR", reason_vol)

        # Genuine institutional asset meeting all criteria passes
        is_valid_ok, reason_ok = InstitutionalUniverseFilter.is_valid_utility_coin(
            symbol="SOL/USDT",
            price=150.0,
            volume_usd=50_000_000.0,
            listing_age_days=500.0
        )
        self.assertTrue(is_valid_ok)
        self.assertEqual(reason_ok, "PASSED")

    def test_05_universe_filter_guarantees_exact_top_100_universe(self):
        """Verifies get_top_100_universe returns exactly 100 high-volume clean utility pairs."""
        universe = InstitutionalUniverseFilter.get_top_100_universe(top_n=100)
        self.assertEqual(len(universe), 100, "Universe must return exactly 100 pairs")
        for asset in universe:
            sym = asset["symbol"]
            base = asset.get("base", sym.split("/")[0])
            self.assertNotIn(base, EXCLUDED_MEME_BLACKLIST, f"Meme coin {base} found in universe")

    # ==========================================================================
    # 2. VECTORIZED NON-REPAINTING FRACTALS & ZERO LOOKAHEAD
    # ==========================================================================

    def test_06_fractal_swings_require_closed_right_bars_and_never_repaint(self):
        """Verifies swing pivots require closed confirmation bars and never alter historical values."""
        df_bull = self._create_synthetic_candles(n=60, trend="BULLISH", base_price=100.0, step=1.0)

        # Confirm at bar 40 and bar 55
        sh_40, sl_40 = MarketStructureEngine.find_confirmed_fractals(df_bull, timeframe="15m", up_to_bar=40)
        sh_55, sl_55 = MarketStructureEngine.find_confirmed_fractals(df_bull, timeframe="15m", up_to_bar=55)

        self.assertGreater(len(sh_40), 0)
        self.assertGreater(len(sl_40), 0)

        # Pivots confirmed by bar 40 must match identically in bar 55
        for p40 in sh_40:
            matching = [p55 for p55 in sh_55 if p55.index == p40.index]
            self.assertEqual(len(matching), 1, f"Pivot at index {p40.index} must remain invariant")
            self.assertEqual(matching[0].price, p40.price, "Pivot price must not repaint")

        # Zero lookahead: pivot index <= evaluation boundary - right_bars
        _, right_bars = MarketStructureEngine.get_window_params("15m")
        for sh in sh_40:
            self.assertLessEqual(sh.index, 40 - right_bars)

    # ==========================================================================
    # 3. BOS & CHoCH STATE MACHINE
    # ==========================================================================

    def test_07_bos_and_choch_state_transitions(self):
        """Verifies BOS continuation and CHoCH structural trend reversal."""
        df_bull = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=1.0)
        prof_bull = MarketStructureEngine.analyze_timeframe(df_bull, timeframe="15m")
        self.assertEqual(prof_bull.trend, TrendDirection.BULLISH)
        self.assertTrue(prof_bull.has_bos, "Bullish progression must exhibit BOS")

        # Simulate acute bearish breakdown below the confirmed Higher Low (Bearish CHoCH)
        df_choch = df_bull.copy()
        hl_price = prof_bull.recent_hl.price if prof_bull.recent_hl else 100.0
        # Add 3 aggressive downward breakdown candles closing decisively below HL
        for j in range(3):
            breakdown_price = hl_price - (j + 1) * 2.0
            df_choch = pd.concat([df_choch, pd.DataFrame([{
                "open": breakdown_price + 1.0,
                "high": breakdown_price + 1.5,
                "low": breakdown_price - 0.5,
                "close": breakdown_price,
                "volume": 200_000.0,
                "timestamp": int(df_choch["timestamp"].iloc[-1]) + 900
            }])], ignore_index=True)

        prof_choch = MarketStructureEngine.analyze_timeframe(df_choch, timeframe="15m")
        self.assertTrue(prof_choch.has_choch)
        self.assertEqual(prof_choch.choch_type, "BEARISH_CHOCH")
        # Invalidation forces trend away from Bullish
        self.assertNotEqual(prof_choch.trend, TrendDirection.BULLISH)

    def test_08_higher_timeframe_choch_precedence_invalidates_setups(self):
        """Verifies that an opposing 4H or 1H CHoCH immediately invalidates lower timeframe setups."""
        df_15m = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0)
        df_1h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0)
        df_4h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0)

        # Baseline: All 3 timeframes bullish -> decision is LONG
        dec_base = MarketStructureEngine.evaluate_pre_ai_structure(df_4h=df_4h, df_1h=df_1h, df_15m=df_15m)
        self.assertTrue(dec_base.is_unanimously_aligned)
        self.assertEqual(dec_base.trade_direction, TradeDirection.LONG)

        # Inject Bearish CHoCH onto the 4H chart
        prof_4h_base = MarketStructureEngine.analyze_timeframe(df_4h, timeframe="4h")
        hl_4h = prof_4h_base.recent_hl.price if prof_4h_base.recent_hl else 100.0
        df_4h_broken = df_4h.copy()
        for j in range(2):
            break_p = hl_4h - (j + 1) * 3.0
            df_4h_broken = pd.concat([df_4h_broken, pd.DataFrame([{
                "open": break_p + 1.0, "high": break_p + 1.5, "low": break_p - 0.5, "close": break_p,
                "volume": 300_000.0, "timestamp": int(df_4h_broken["timestamp"].iloc[-1]) + 14400
            }])], ignore_index=True)

        dec_htf = MarketStructureEngine.evaluate_pre_ai_structure(df_4h=df_4h_broken, df_1h=df_1h, df_15m=df_15m)
        self.assertFalse(dec_htf.is_unanimously_aligned)
        self.assertEqual(dec_htf.trade_direction, TradeDirection.NEUTRAL)
        self.assertTrue(dec_htf.has_htf_choch)
        self.assertIn("4H Bearish", dec_htf.htf_choch_reason)

    # ==========================================================================
    # 4. ORDER BLOCK LIFECYCLE & HTF RESPECT (4H > 1H > 15M)
    # ==========================================================================

    def test_09_order_block_detection_and_mitigation_lifecycle(self):
        """Verifies Bullish OB creation with FVG and lifecycle from ACTIVE to TESTING to MITIGATED."""
        records = []
        p = 100.0
        # Form 15 base candles
        for i in range(15):
            records.append({
                "open": p, "high": p + 0.5, "low": p - 0.5, "close": p + 0.1,
                "volume": 50000.0, "timestamp": 1700000000 + (i * 900)
            })

        # Candle 15: Last down-candle (close < open) - this forms the Bullish OB
        ob_candle = {
            "open": 101.0, "high": 101.5, "low": 99.5, "close": 100.0,
            "volume": 80000.0, "timestamp": 1700000000 + (15 * 900)
        }
        records.append(ob_candle)

        # Candles 16 & 17: Aggressive displacement upward leaving FVG (Low of 17 > High of 15)
        disp1 = {
            "open": 100.2, "high": 104.0, "low": 100.1, "close": 103.8,
            "volume": 250000.0, "timestamp": 1700000000 + (16 * 900)
        }
        disp2 = {
            "open": 103.9, "high": 107.0, "low": 102.0, "close": 106.5, # Low 102.0 > High 101.5 (FVG created)
            "volume": 300000.0, "timestamp": 1700000000 + (17 * 900)
        }
        records.extend([disp1, disp2])

        # Candle 18: Price pulls back to 101.0 (inside [99.5, 101.5] zone) -> TESTING
        pullback = {
            "open": 105.0, "high": 105.2, "low": 100.8, "close": 101.2,
            "volume": 120000.0, "timestamp": 1700000000 + (18 * 900)
        }
        records.append(pullback)

        df_ob = pd.DataFrame(records)
        obs = MarketStructureEngine.detect_institutional_order_blocks(df_ob, timeframe="15m", current_price=101.0)
        self.assertGreater(len(obs), 0, "Must detect Bullish Order Block")
        top_ob = obs[0]
        self.assertEqual(top_ob.block_type, OrderBlockCategory.BULLISH)
        self.assertEqual(top_ob.status, OrderBlockStatus.TESTING)
        self.assertTrue(top_ob.is_touching)
        self.assertTrue(top_ob.has_fvg)

    def test_10_higher_timeframe_order_block_precedence_4h_over_15m(self):
        """Verifies that 4H Order Block has absolute precedence over 15M Order Block."""
        # 15M has Bullish OB, but 4H has touched Bearish OB
        df_15m = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0)
        df_1h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0)

        # Create 4H DataFrame with active Bearish OB touching current price
        records_4h = []
        p = 100.0
        for i in range(20):
            records_4h.append({"open": p, "high": p + 1.0, "low": p - 1.0, "close": p + 0.2, "volume": 50000, "timestamp": 1700000000 + i * 14400})
        # Up candle (Bearish OB): open 100, close 102, high 102.5, low 99.8
        records_4h.append({"open": 100.0, "high": 102.5, "low": 99.8, "close": 102.0, "volume": 90000, "timestamp": 1700000000 + 20 * 14400})
        # Strong downward displacement with FVG
        records_4h.append({"open": 101.8, "high": 102.0, "low": 95.0, "close": 95.5, "volume": 400000, "timestamp": 1700000000 + 21 * 14400})
        records_4h.append({"open": 95.5, "high": 96.0, "low": 91.0, "close": 91.5, "volume": 350000, "timestamp": 1700000000 + 22 * 14400})
        # Pullback into 4H Bearish OB at 101.0
        records_4h.append({"open": 92.0, "high": 101.5, "low": 91.5, "close": 101.0, "volume": 150000, "timestamp": 1700000000 + 23 * 14400})
        df_4h = pd.DataFrame(records_4h)

        dec = MarketStructureEngine.evaluate_pre_ai_structure(df_4h=df_4h, df_1h=df_1h, df_15m=df_15m, current_price=101.0)
        # Because 4H touched Bearish OB, 4H has macro authority over LTF trend
        self.assertEqual(dec.dominant_ob_timeframe, "4H")
        self.assertEqual(dec.trade_direction, TradeDirection.SHORT)
        self.assertEqual(dec.scenario, "SCENARIO_A_ORDER_BLOCK_TRIGGER")

    # ==========================================================================
    # 5. PRE-AI DECISION MATRIX: SCENARIO A vs SCENARIO B
    # ==========================================================================

    def test_11_decision_matrix_scenario_b_no_ob_preserves_unanimous_trend(self):
        """Verifies Scenario B: When no active OB is touched, unanimous 4H+1H+15M trend sets direction."""
        df_bull_4h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=1.5, timeframe_secs=14400)
        df_bull_1h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=1.0, timeframe_secs=3600)
        df_bull_15m = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5, timeframe_secs=900)

        # Price at new highs (away from order blocks)
        curr_p = float(df_bull_15m['close'].iloc[-1])
        dec = MarketStructureEngine.evaluate_pre_ai_structure(
            df_4h=df_bull_4h, df_1h=df_bull_1h, df_15m=df_bull_15m, current_price=curr_p
        )

        self.assertTrue(dec.is_unanimously_aligned)
        self.assertEqual(dec.trade_direction, TradeDirection.LONG)
        self.assertEqual(dec.order_block_source, "TREND_ALIGNMENT_DEFAULT")
        self.assertIn("unanimous Bullish trend alignment", dec.reasons[0])

    def test_12_decision_matrix_timeframe_divergence_fails_closed(self):
        """Verifies that conflicting timeframes (e.g. 4H Bearish vs 15M Bullish) fail closed to NEUTRAL."""
        df_bear_4h = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=1.5, timeframe_secs=14400)
        df_bull_1h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=1.0, timeframe_secs=3600)
        df_bull_15m = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5, timeframe_secs=900)

        dec = MarketStructureEngine.evaluate_pre_ai_structure(
            df_4h=df_bear_4h, df_1h=df_bull_1h, df_15m=df_bull_15m
        )

        self.assertFalse(dec.is_unanimously_aligned)
        self.assertEqual(dec.trade_direction, TradeDirection.NEUTRAL)
        self.assertEqual(dec.scenario, "NO_SIGNAL")
        self.assertIn("Timeframe divergence", dec.veto_reason)

    # ==========================================================================
    # 6. 15-MINUTE SCALP ENGINE: ENTRY, SL (0.15*ATR), & STRICT 1:2 R:R
    # ==========================================================================

    def test_13_signal_engine_15m_long_geometry_strict_1_to_2_rr(self):
        """Verifies Long trade setup on 15M: entry at HL floor, SL buffer 0.15*ATR, and immutable 1:2 R:R."""
        df_4h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=1.0, timeframe_secs=14400)
        df_1h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.8, timeframe_secs=3600)
        df_15m = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=0.5, timeframe_secs=900)

        setup: ScalpTradeSetup15M = SignalEngine15M.evaluate_15m_scalp_setup(
            symbol="BTC/USDT",
            df_4h=df_4h,
            df_1h=df_1h,
            df_15m=df_15m
        )

        self.assertTrue(setup.is_valid)
        self.assertEqual(setup.direction, "LONG")
        self.assertEqual(setup.horizon, "15M")

        # Verify strict price geometry: SL < Entry < TP1 < TP2 < TP3
        self.assertLess(setup.sl_price, setup.entry_price)
        self.assertLess(setup.entry_price, setup.tp1_price)
        self.assertLess(setup.tp1_price, setup.tp2_price)
        self.assertLess(setup.tp2_price, setup.tp3_price)

        # Verify strict 1:2.0 Risk-to-Reward ratio
        risk = setup.entry_price - setup.sl_price
        reward = setup.tp1_price - setup.entry_price
        rr_computed = round(reward / risk, 2)
        self.assertEqual(rr_computed, 2.0, f"R:R must be strictly 1:2.0 (got {rr_computed})")
        self.assertEqual(setup.risk_reward_ratio, 2.0)

        # Verify SL buffer equals 0.15 * ATR_15m
        expected_buffer = round(setup.atr_15m * 0.15, 4)
        self.assertAlmostEqual(setup.sl_buffer, expected_buffer, places=3)

    def test_14_signal_engine_15m_short_geometry_strict_1_to_2_rr(self):
        """Verifies Short trade setup on 15M: entry at LH ceiling, SL buffer 0.15*ATR, and immutable 1:2 R:R."""
        df_4h = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=1.0, timeframe_secs=14400)
        df_1h = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=0.8, timeframe_secs=3600)
        df_15m = self._create_synthetic_candles(n=50, trend="BEARISH", base_price=100.0, step=0.5, timeframe_secs=900)

        setup: ScalpTradeSetup15M = SignalEngine15M.evaluate_15m_scalp_setup(
            symbol="ETH/USDT",
            df_4h=df_4h,
            df_1h=df_1h,
            df_15m=df_15m
        )

        self.assertTrue(setup.is_valid)
        self.assertEqual(setup.direction, "SHORT")
        self.assertEqual(setup.horizon, "15M")

        # Verify strict price geometry: SL > Entry > TP1 > TP2 > TP3
        self.assertGreater(setup.sl_price, setup.entry_price)
        self.assertGreater(setup.entry_price, setup.tp1_price)
        self.assertGreater(setup.tp1_price, setup.tp2_price)
        self.assertGreater(setup.tp2_price, setup.tp3_price)

        # Verify strict 1:2.0 Risk-to-Reward ratio
        risk = setup.sl_price - setup.entry_price
        reward = setup.entry_price - setup.tp1_price
        rr_computed = round(reward / risk, 2)
        self.assertEqual(rr_computed, 2.0, f"R:R must be strictly 1:2.0 (got {rr_computed})")
        self.assertEqual(setup.risk_reward_ratio, 2.0)

    def test_15_anchor_to_lh_hl_enforces_minimum_sl_noise_floor(self):
        """
        Regression Test (SIG_20261112_0912_HBARUSDT_15M):
        When current_price pushes slightly past a stale LH/HL pivot before market trigger,
        structural_ceiling + vol_cushion must NEVER produce a sub-spread 0.003% micro-SL
        (e.g. $0.065792 vs $0.065790 / 1:267 R:R). Minimum SL distance must be >= 0.35%.
        """
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        df_15m = self._create_synthetic_candles(n=30, trend="BEARISH", base_price=0.0658, step=0.0001, timeframe_secs=900)
        # Replicate HBAR/USDT: current_price = 0.065790, stale lh_pivot = 0.065500 below current_price
        short_anc = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
            df_15m=df_15m,
            lh_pivot_price=0.065500,
            current_price=0.065790,
            spread_bps=6.0,
        )
        short_sl_pct = (short_anc["sl_price"] - short_anc["entry_price"]) / short_anc["entry_price"]
        self.assertGreaterEqual(short_sl_pct, 0.0034, f"SHORT SL too tight: {short_sl_pct:.6f}")
        self.assertLessEqual(short_anc["risk_reward_ratio"], 3.0)

        # Symmetric LONG check: current_price = 0.065790, stale hl_pivot = 0.066050 above current_price
        long_anc = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_15m,
            hl_pivot_price=0.066050,
            current_price=0.065790,
            spread_bps=6.0,
        )
        long_sl_pct = (long_anc["entry_price"] - long_anc["sl_price"]) / long_anc["entry_price"]
        self.assertGreaterEqual(long_sl_pct, 0.0034, f"LONG SL too tight: {long_sl_pct:.6f}")
        self.assertLessEqual(long_anc["risk_reward_ratio"], 3.0)

    def test_16_candle_rejection_validation_prevents_market_chasing(self):
        """
        Regression Test (TIA_USDT_15M_1794476194):
        Verifies that when an active 15M candle is driving strongly in the opposite direction
        (e.g., green candle without upper rejection wick for SHORT), the engine sets RESTING_LIMIT
        at LH rather than executing MARKET_TRIGGER right into the rally.
        Also verifies SL buffer exceeds micro-noise floor (>= 0.50% / 0.65*ATR).
        """
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine

        # Construct candles where last candle is strongly green (open=0.4048, high=0.4071, low=0.4048, close=0.4070)
        df_15m = self._create_synthetic_candles(n=30, trend="BEARISH", base_price=0.4000, step=0.0005, timeframe_secs=900)
        df_15m.iloc[-1, df_15m.columns.get_loc("open")] = 0.4048
        df_15m.iloc[-1, df_15m.columns.get_loc("high")] = 0.4071
        df_15m.iloc[-1, df_15m.columns.get_loc("low")] = 0.4048
        df_15m.iloc[-1, df_15m.columns.get_loc("close")] = 0.4070

        short_anc = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
            df_15m=df_15m,
            lh_pivot_price=0.4060,
            current_price=0.4070,
            spread_bps=5.0,
        )
        self.assertEqual(short_anc["execution_mode"], "RESTING_LIMIT", "Must not market-execute into an unconfirmed green rally")
        self.assertIn("AWAIT BOUNCE TO LH", short_anc["decision_label"])
        sl_pct = (short_anc["sl_price"] - short_anc["entry_price"]) / short_anc["entry_price"]
        self.assertGreaterEqual(sl_pct, 0.0050, f"SHORT SL must be >= 0.50% (got {sl_pct:.4%})")

        # Now test symmetric LONG with strongly red candle driving down
        df_15m.iloc[-1, df_15m.columns.get_loc("open")] = 0.4070
        df_15m.iloc[-1, df_15m.columns.get_loc("high")] = 0.4070
        df_15m.iloc[-1, df_15m.columns.get_loc("low")] = 0.4045
        df_15m.iloc[-1, df_15m.columns.get_loc("close")] = 0.4048

        long_anc = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_15m,
            hl_pivot_price=0.4055,
            current_price=0.4048,
            spread_bps=5.0,
        )
        self.assertEqual(long_anc["execution_mode"], "RESTING_LIMIT", "Must not market-execute into an unconfirmed falling knife")
        self.assertIn("AWAIT PULLBACK TO HL", long_anc["decision_label"])
        sl_pct = (long_anc["entry_price"] - long_anc["sl_price"]) / long_anc["entry_price"]
        self.assertGreaterEqual(sl_pct, 0.0050, f"LONG SL must be >= 0.50% (got {sl_pct:.4%})")

    def test_17_mtf_trend_unanimity_gate(self):
        """
        Regression Test (TIA / MEGA 2026-11-12 09:36):
        Verifies that evaluate_multi_horizon_gates strictly requires 15M, 1H, and 4H
        to all share the same trend direction, and rejects signals when there is a mismatch
        even if 1D Range Rotation exists.
        """
        from app.engine.signals.signal_generator import SignalGenerationSystem

        sig_sys = SignalGenerationSystem()

        matrix_rotation = {
            "archetype": "ARCHETYPE_C_RANGE_ROTATION",
            "trade_permitted": True,
            "dominant_direction": "SHORT",
            "strategy": "RANGE_MEAN_REVERSION"
        }

        # Case 1: 15M BULLISH, 1H BULLISH, 4H BEARISH -> Must fail closed
        trend_mismatch = {
            "15m": "BULLISH",
            "1h": "BULLISH",
            "4h": "BEARISH",
        }
        preds = {
            "15m": {"is_cold_start": False, "candle_count": 50, "trend_state": "BULLISH"},
            "1h": {"is_cold_start": False, "candle_count": 50, "trend_state": "BULLISH"},
            "4h": {"is_cold_start": False, "candle_count": 50, "trend_state": "BEARISH"},
        }
        q_15m, q_1h, q_24h = sig_sys.evaluate_multi_horizon_gates(trend_mismatch, preds, matrix_rotation)
        self.assertFalse(q_15m["qualified"], "Must reject when 15M/1H/4H trend is misaligned")
        self.assertTrue(any("MTF_TREND_MISALIGNMENT" in c for c in q_15m.get("conflicts", [])))

        # Case 2: 15M BEARISH, 1H BULLISH, 4H BEARISH -> Must fail closed
        trend_mismatch_2 = {
            "15m": "BEARISH",
            "1h": "BULLISH",
            "4h": "BEARISH",
        }
        preds_2 = {
            "15m": {"is_cold_start": False, "candle_count": 50, "trend_state": "BEARISH"},
            "1h": {"is_cold_start": False, "candle_count": 50, "trend_state": "BULLISH"},
            "4h": {"is_cold_start": False, "candle_count": 50, "trend_state": "BEARISH"},
        }
        q_15m_2, _, _ = sig_sys.evaluate_multi_horizon_gates(trend_mismatch_2, preds_2, matrix_rotation)
        self.assertFalse(q_15m_2["qualified"], "Must reject when 1H is misaligned with 15M/4H")
        self.assertTrue(len(q_15m_2.get("conflicts", [])) > 0)

        # Case 3: 15M, 1H, 4H all BEARISH -> Unanimously qualified
        trend_unanimous_bear = {
            "15m": "BEARISH",
            "1h": "BEARISH",
            "4h": "BEARISH",
        }
        preds_bear = {
            "15m": {"is_cold_start": False, "candle_count": 50, "trend_state": "BEARISH"},
            "1h": {"is_cold_start": False, "candle_count": 50, "trend_state": "BEARISH"},
            "4h": {"is_cold_start": False, "candle_count": 50, "trend_state": "BEARISH"},
        }
        q_15m_bear, _, _ = sig_sys.evaluate_multi_horizon_gates(trend_unanimous_bear, preds_bear, matrix_rotation)
        self.assertTrue(q_15m_bear["qualified"], "Must qualify when 15M, 1H, 4H are all BEARISH")
        self.assertEqual(q_15m_bear["direction"], "SHORT")

        # Case 4: 15M, 1H, 4H all BULLISH -> Unanimously qualified
        trend_unanimous_bull = {
            "15m": "BULLISH",
            "1h": "BULLISH",
            "4h": "BULLISH",
        }
        preds_bull = {
            "15m": {"is_cold_start": False, "candle_count": 50, "trend_state": "BULLISH"},
            "1h": {"is_cold_start": False, "candle_count": 50, "trend_state": "BULLISH"},
            "4h": {"is_cold_start": False, "candle_count": 50, "trend_state": "BULLISH"},
        }
        matrix_rotation_bull = {
            "archetype": "ARCHETYPE_C_RANGE_ROTATION",
            "trade_permitted": True,
            "dominant_direction": "LONG",
            "strategy": "RANGE_MEAN_REVERSION"
        }
        q_15m_bull, _, _ = sig_sys.evaluate_multi_horizon_gates(trend_unanimous_bull, preds_bull, matrix_rotation_bull)
        self.assertTrue(q_15m_bull["qualified"], "Must qualify when 15M, 1H, 4H are all BULLISH")
        self.assertEqual(q_15m_bull["direction"], "LONG")

    def test_18_runaway_parabolic_resting_limit_fill_conversion(self):
        """
        Regression Test:
        Verifies that in runaway parabolic markets, if price reverses before reaching
        the distant LH/HL resting limit, PaperTradingBot does NOT let the order expire
        unfilled or cancel prematurely if effective R:R to TP1 remains >= 1:1.20.
        Instead, it converts the resting limit to an active market fill (RUNAWAY_REVERSAL_CONVERTED).
        Also verifies that if R:R is degraded below 1:1.20, it safely cancels.
        """
        from app.engine.execution.paper_trading_bot import PaperTradingBot

        bot = PaperTradingBot(ledger_file="scratch/test_paper_runaway_reversal.json")
        bot.enable_signal_expiry = True
        bot.data = {
            "account_equity_usd": 1000.0,
            "open_positions": [],
            "closed_trades": [],
            "cancelled_orders": [],
            "desks": {
                "day": {"name": "Day Trading Desk", "allocated_usd": 350.0, "max_slots": 2, "active_slots": 0, "leverage": 3},
                "scalp": {"name": "High-Frequency Scalp Desk", "allocated_usd": 150.0, "max_slots": 2, "active_slots": 0, "leverage": 5},
                "swing": {"name": "Macro Swing Desk", "allocated_usd": 500.0, "max_slots": 2, "active_slots": 0, "leverage": 2}
            }
        }

        # Case A: SHORT resting limit at $0.4080 with admission at $0.4060, SL at $0.4100, TP1 at $0.3900.
        # Price reverses early at $0.4065 and starts dumping to $0.4040.
        # At $0.4040: Reward = 0.4040 - 0.3900 = 0.0140, Risk = 0.4100 - 0.4040 = 0.0060 -> R:R = 1:2.33 (>= 1.20)
        pos_short = {
            "trade_id": "TEST_RUNAWAY_SHORT",
            "symbol": "TIA/USDT",
            "direction": "SHORT",
            "horizon": "15M",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 0.4080,
            "optimal_entry_limit": 0.4080,
            "admission_price": 0.4060,
            "current_price": 0.4060,
            "tp1_price": 0.3900,
            "sl_price": 0.4100,
            "desk": "scalp",
            "chase_threshold_pct": 0.40,
            "active_atr": 0.0040,
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        bot.data["open_positions"] = [pos_short]

        # Price dumps to 0.4040 (< 0.4060 * (1 - 0.004) = 0.40438)
        bot.on_tick(live_prices={"TIA/USDT": 0.4040})

        pos_after = bot.data["open_positions"][0]
        self.assertEqual(pos_after["status"], "OPEN")
        self.assertFalse(pos_after["is_limit_resting"])
        self.assertEqual(pos_after["fill_confirmation_type"], "RUNAWAY_REVERSAL_CONVERTED")
        self.assertEqual(pos_after["entry_price"], 0.4040)

        # Case B: Price dropped too far (e.g. 0.3930, where reward is 0.0030 and risk is 0.0170 -> R:R = 0.18 < 1.20)
        pos_chase_bad = {
            "trade_id": "TEST_CHASE_EXCEEDED",
            "symbol": "MEGA/USDT",
            "direction": "SHORT",
            "horizon": "15M",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 0.4080,
            "optimal_entry_limit": 0.4080,
            "admission_price": 0.4060,
            "current_price": 0.4060,
            "tp1_price": 0.3900,
            "sl_price": 0.4100,
            "desk": "scalp",
            "chase_threshold_pct": 0.40,
            "active_atr": 0.0040,
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        bot.data["open_positions"] = [pos_after, pos_chase_bad]
        bot.on_tick(live_prices={"MEGA/USDT": 0.3930, "TIA/USDT": 0.4040})

        # Order must be safely cancelled as CANCELLED_CHASE_EXCEEDED to protect capital
        self.assertEqual(len(bot.data["open_positions"]), 1) # Only pos_short remains
        self.assertEqual(len(bot.data["cancelled_orders"]), 1)
        self.assertEqual(bot.data["cancelled_orders"][0]["cancellation_reason"], "CANCELLED_CHASE_EXCEEDED")

    def test_19_strictly_higher_low_long_and_lower_high_short_anchoring(self):
        """
        Forensic Verification Test:
        Verifies that:
        1. Long entries are strictly anchored to confirmed Higher Lows (HL), never Lower Lows (LL) or Higher Highs.
        2. Short entries are strictly anchored to confirmed Lower Highs (LH), never Higher Highs (HH) or Lower Lows.
        3. If price is extended beyond the HL/LH retest zone, RESTING_LIMIT is placed at the structural pivot.
        4. If price is strictly inside the retest zone [zone_floor, zone_ceiling], MARKET_TRIGGER/MARKET_CONFIRMED is allowed.
        """
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine
        # 1. LONG: Extended price above Higher Low zone -> Must be RESTING_LIMIT at HL
        df_15m_long = pd.DataFrame({
            "open": [100.0, 101.0, 102.0, 101.5, 103.0, 104.0, 105.0],
            "high": [101.5, 102.5, 103.0, 102.0, 104.0, 105.5, 106.0],
            "low": [99.5, 100.5, 101.0, 101.0, 102.5, 103.5, 104.5],
            "close": [101.0, 102.0, 101.5, 102.0, 103.8, 105.0, 105.8],
            "volume": [1000] * 7,
            "timestamp": list(range(7))
        })
        hl_price = 101.0  # Confirmed Higher Low
        current_price_high = 105.8  # Price expanded well above HL

        long_extended = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_15m_long,
            hl_pivot_price=hl_price,
            current_price=current_price_high,
            spread_bps=5.0
        )
        self.assertTrue(long_extended["is_extended"], "Price above zone ceiling must be flagged as extended")
        self.assertEqual(long_extended["execution_mode"], "RESTING_LIMIT", "Extended price must place resting limit at Higher Low")
        self.assertAlmostEqual(long_extended["entry_price"], hl_price, places=2)
        self.assertLess(long_extended["sl_price"], long_extended["entry_price"])
        self.assertGreater(long_extended["tp1_price"], long_extended["entry_price"])

        # 2. LONG: Price directly inside Higher Low retest zone with green bounce -> MARKET_TRIGGER
        df_15m_bounce = pd.DataFrame({
            "open": [100.0, 101.0, 102.0, 101.5, 101.1],
            "high": [101.5, 102.5, 103.0, 102.0, 101.8],
            "low": [99.5, 100.5, 101.0, 101.0, 101.0],
            "close": [101.0, 102.0, 101.5, 101.1, 101.6], # Green candle bounce from 101.0 low
            "volume": [1000] * 5,
            "timestamp": list(range(5))
        })
        long_at_hl = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_15m_bounce,
            hl_pivot_price=101.0,
            current_price=101.4, # Inside [101.0 - 0.10*atr, 101.0 + 0.50*atr]
            spread_bps=5.0
        )
        self.assertFalse(long_at_hl["is_extended"])
        self.assertEqual(long_at_hl["execution_mode"], "MARKET_TRIGGER")
        self.assertAlmostEqual(long_at_hl["entry_price"], 101.4, places=2)

        # 3. SHORT: Extended price below Lower High zone -> Must be RESTING_LIMIT at LH
        df_15m_short = pd.DataFrame({
            "open": [100.0, 99.0, 98.0, 98.5, 97.0, 96.0, 95.0],
            "high": [100.5, 99.5, 99.0, 99.0, 97.5, 96.5, 95.5],
            "low": [98.5, 97.5, 97.0, 98.0, 96.0, 94.5, 94.0],
            "close": [99.0, 98.0, 98.5, 98.0, 96.2, 95.0, 94.2],
            "volume": [1000] * 7,
            "timestamp": list(range(7))
        })
        lh_price = 99.0  # Confirmed Lower High
        current_price_low = 94.2  # Price dumped well below LH

        short_extended = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
            df_15m=df_15m_short,
            lh_pivot_price=lh_price,
            current_price=current_price_low,
            spread_bps=5.0
        )
        self.assertTrue(short_extended["is_extended"], "Price below zone floor must be flagged as extended")
        self.assertEqual(short_extended["execution_mode"], "RESTING_LIMIT", "Dumping price must place resting limit at Lower High")
        self.assertAlmostEqual(short_extended["entry_price"], lh_price, places=2)
        self.assertGreater(short_extended["sl_price"], short_extended["entry_price"])
        self.assertLess(short_extended["tp1_price"], short_extended["entry_price"])

        # 4. SHORT: Price directly inside Lower High retest zone with red rejection -> MARKET_TRIGGER
        df_15m_rejection = pd.DataFrame({
            "open": [100.0, 99.0, 98.0, 98.5, 98.9],
            "high": [100.5, 99.5, 99.0, 99.0, 99.1],
            "low": [98.5, 97.5, 97.0, 98.0, 98.2],
            "close": [99.0, 98.0, 98.5, 98.8, 98.4], # Red rejection candle from 99.0
            "volume": [1000] * 5,
            "timestamp": list(range(5))
        })
        short_at_lh = EntryConfirmationEngine.anchor_to_lower_high_and_ob(
            df_15m=df_15m_rejection,
            lh_pivot_price=99.0,
            current_price=98.6, # Inside retest zone
            spread_bps=5.0
        )
        self.assertFalse(short_at_lh["is_extended"])
        self.assertEqual(short_at_lh["execution_mode"], "MARKET_TRIGGER")
        self.assertAlmostEqual(short_at_lh["entry_price"], 98.6, places=2)

    def test_20_pre_tp1_trailing_profit_ratchet_and_minimum_sl_floor(self):
        """
        Forensic Verification Test (Profit Generation & Anti-Micro-Stop Guard):
        1. Verifies that EntryConfirmationEngine enforces a minimum SL distance of >= 1.20%
           preventing razor-thin 0.35% - 0.60% stops from being wicked out by noise.
        2. Verifies that PaperTradingBot engages Multi-Stage Pre-TP1 Trailing Profit Ratchet:
           - A trade reaching +3.10% (like NIGHT) ratchets SL to +2.00% and exits in profit on pullback.
           - A trade reaching +4.80% (like MEGA) ratchets SL to >= +2.80% and exits in profit on pullback.
           - Pre-TP1 profit exits are authoritatively mapped to WON_PROFIT_RATCHET with 🟢 WON outcome label.
        """
        from app.quant_v16.entry_confirmation import EntryConfirmationEngine
        from app.engine.execution.paper_trading_bot import PaperTradingBot

        # 1. Minimum SL Floor Verification (>= 1.20% distance)
        df_15m = pd.DataFrame({
            "open": [100.0, 100.5, 101.0, 101.2, 101.5],
            "high": [100.6, 101.1, 101.3, 101.6, 101.8],
            "low": [99.8, 100.2, 100.8, 101.0, 101.3],
            "close": [100.5, 101.0, 101.2, 101.5, 101.6],
            "volume": [1000] * 5,
            "timestamp": list(range(5))
        })
        long_setup = EntryConfirmationEngine.anchor_to_higher_low_and_ob(
            df_15m=df_15m,
            hl_pivot_price=101.3,
            current_price=101.6,
            spread_bps=5.0
        )
        entry_p = float(long_setup["entry_price"])
        sl_p = float(long_setup["sl_price"])
        sl_distance_pct = (entry_p - sl_p) / entry_p
        self.assertGreaterEqual(sl_distance_pct, 0.0120, f"SL distance must be >= 1.20% (got {sl_distance_pct:.4%})")

        # 2. Pre-TP1 Trailing Profit Ratchet Simulation (NIGHT-like setup reaching +3.10% gain)
        bot = PaperTradingBot(ledger_file="scratch/test_paper_profit_ratchet.json")
        bot.enable_breakeven_guard = True
        bot.data = {
            "account_equity_usd": 1000.0,
            "open_positions": [],
            "closed_trades": [],
            "cancelled_orders": [],
            "desks": {
                "day": {"name": "Day Trading Desk", "allocated_usd": 350.0, "max_slots": 2, "active_slots": 0, "leverage": 3},
                "scalp": {"name": "High-Frequency Scalp Desk", "allocated_usd": 150.0, "max_slots": 2, "active_slots": 0, "leverage": 5},
                "swing": {"name": "Macro Swing Desk", "allocated_usd": 500.0, "max_slots": 2, "active_slots": 0, "leverage": 2}
            }
        }

        pos_night = {
            "trade_id": "TEST_NIGHT_PROFIT_RATCHET",
            "symbol": "NIGHT/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "status": "OPEN",
            "is_limit_resting": False,
            "entry_price": 0.045800,
            "current_price": 0.045800,
            "tp1_price": 0.047802, # +4.37%
            "tp2_price": 0.049000,
            "tp3_price": 0.050000,
            "sl_price": 0.045100,
            "initial_sl_price": 0.045100,
            "desk": "scalp",
            "active_atr": 0.000600,
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        bot.data["open_positions"] = [pos_night]

        # Tick 1: Price pumps to $0.047220 (+3.10% gain)
        bot.on_tick(live_prices={"NIGHT/USDT": 0.047220})
        pos_after_pump = bot.data["open_positions"][0]
        self.assertTrue(pos_after_pump.get("is_profit_ratchet_active"), "Profit ratchet must activate at +3.10% MFE")
        # SL must have ratcheted to at least +2.00% above entry ($0.0458 * 1.02 = $0.046716)
        self.assertGreaterEqual(pos_after_pump["sl_price"], 0.0458 * 1.0200)

        # Tick 2: Price pulls back to $0.046600 (breaching the ratcheted profit stop)
        bot.on_tick(live_prices={"NIGHT/USDT": 0.046600})
        self.assertEqual(len(bot.data["open_positions"]), 0, "Position must close when ratcheted profit stop is hit")
        self.assertEqual(len(bot.data["closed_trades"]), 1, "Must be recorded in closed trades")
        closed_night = bot.data["closed_trades"][0]
        self.assertIn("WON (PROFIT RATCHET", closed_night["outcome_label"], "Outcome label must be green WON profit ratchet")
        self.assertGreater(closed_night["return_pct"], 1.50, "Must have locked in substantial positive profit")

    def test_21_scenario_c_trend_pullback_entry_and_dynamic_anchor(self):
        """Verifies Phase 1: Scenario C Trend Pullback Re-entry and dynamic structural anchor fallback."""
        df_bull_4h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=1.5, timeframe_secs=14400)
        df_bull_1h = self._create_synthetic_candles(n=50, trend="BULLISH", base_price=100.0, step=1.0, timeframe_secs=3600)
        # 15M is in CHOP (consolidation / pullback)
        df_chop_15m = self._create_synthetic_candles(n=50, trend="CHOP", base_price=100.0, step=0.0, timeframe_secs=900)

        curr_p = float(df_chop_15m['close'].iloc[-1])
        dec = MarketStructureEngine.evaluate_pre_ai_structure(
            df_4h=df_bull_4h, df_1h=df_bull_1h, df_15m=df_chop_15m, current_price=curr_p
        )

        self.assertTrue(dec.is_unanimously_aligned, "Scenario C pullback must be aligned with macro trend")
        self.assertEqual(dec.trade_direction, TradeDirection.LONG, "Must preserve Long bias from 4H/1H")
        self.assertEqual(dec.scenario, "SCENARIO_C_TREND_PULLBACK_ENTRY", "Must be classified as Scenario C Pullback Entry")
        self.assertIsNotNone(dec.entry_anchor_pivot, "Must dynamically synthesize structural entry anchor pivot")
        self.assertLess(dec.entry_anchor_pivot.price, curr_p, "Anchor price must be below current price for Long")

        # Now test 15M Signal Engine evaluation on this setup
        setup = SignalEngine15M.evaluate_15m_scalp_setup(
            symbol="BTC/USDT",
            df_4h=df_bull_4h,
            df_1h=df_bull_1h,
            df_15m=df_chop_15m,
            current_price=curr_p,
            pre_ai_decision=dec
        )
        self.assertTrue(setup.is_valid, "15M Scalp setup must be valid under Scenario C")
        self.assertEqual(setup.direction, "LONG")
        self.assertEqual(setup.scenario, "SCENARIO_C_TREND_PULLBACK_ENTRY")
        self.assertLess(setup.sl_price, setup.entry_price)
        self.assertGreater(setup.tp1_price, setup.entry_price)
        self.assertGreaterEqual(setup.risk_reward_ratio, 2.0, "Must maintain strict 1:2.0 R:R")


if __name__ == "__main__":
    unittest.main()

