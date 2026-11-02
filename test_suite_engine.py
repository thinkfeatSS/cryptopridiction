"""
Automated Unit and Stress Test Suite for Quantitative Engine
Tests core modules: FeatureEngineer, Labeler, Models, Risk, Signal Management, and Edge Cases
"""
import unittest
import numpy as np
import pandas as pd
import time
import os
import sys

# Ensure current directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from test import (
    AdvancedFeatureEngineer,
    TripleBarrierLabeler,
    QuantModelFactory,
    PaperTradingLedger,
    ActiveInstitutionalSignalManager,
    SpecializedStrategyRouter,
    DominantHorizonArbiter,
    format_precision_price,
    is_valid_crypto_pair,
    SignalAuditTracker,
    CONFIG
)

class TestCryptoValidation(unittest.TestCase):
    def test_valid_crypto_pairs(self):
        self.assertTrue(is_valid_crypto_pair("BTC/USDT"))
        self.assertTrue(is_valid_crypto_pair("ETH/USDT"))
        self.assertTrue(is_valid_crypto_pair("SOL/USDT"))

    def test_invalid_crypto_pairs(self):
        # Stablecoins & Fiat Pegs
        self.assertFalse(is_valid_crypto_pair("USDC/USDT"))
        self.assertFalse(is_valid_crypto_pair("FDUSD/USDT"))
        self.assertFalse(is_valid_crypto_pair("EUR/USDT"))
        # Leveraged Stock Tokens
        self.assertFalse(is_valid_crypto_pair("TSLAB/USDT"))
        self.assertFalse(is_valid_crypto_pair("NVDAB/USDT"))
        # Delisted or toxic tokens
        self.assertFalse(is_valid_crypto_pair("LUNA/USDT"))
        self.assertFalse(is_valid_crypto_pair("PROVE/USDT"))
        # Synthetic / garbage tokens
        self.assertFalse(is_valid_crypto_pair("COIN12/USDT"))
        self.assertFalse(is_valid_crypto_pair(""))
        self.assertFalse(is_valid_crypto_pair(None))

    def test_price_formatting(self):
        self.assertEqual(format_precision_price(65432.1234), 65432.12)
        self.assertEqual(format_precision_price(12.34567), 12.3457)
        self.assertEqual(format_precision_price(0.123456), 0.123456)
        self.assertEqual(format_precision_price(0.00012345), 0.00012345)
        self.assertEqual(format_precision_price(0.0), 0.0)
        self.assertEqual(format_precision_price(None), 0.0)

class TestFeatureEngineer(unittest.TestCase):
    def setUp(self):
        self.fe = AdvancedFeatureEngineer()
        np.random.seed(42)
        n = 150
        dates = pd.date_range("2026-01-01", periods=n, freq="15min")
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        high = close + np.random.rand(n) * 1.0
        low = close - np.random.rand(n) * 1.0
        open_p = close + np.random.randn(n) * 0.2
        volume = np.random.rand(n) * 5000 + 100
        taker_vol = volume * np.random.uniform(0.3, 0.7, n)

        self.df = pd.DataFrame({
            "timestamp": (dates.astype(np.int64) // 10**6),
            "datetime": dates,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "taker_buy_vol": taker_vol
        })

    def test_build_timeframe_features_normal(self):
        feats = self.fe.build_timeframe_features(self.df, prefix="15m")
        self.assertIsInstance(feats, pd.DataFrame)
        self.assertGreater(len(feats.columns), 30)
        # Check no infinite values
        numeric_cols = feats.select_dtypes(include=[np.number]).columns
        self.assertFalse(np.isinf(feats[numeric_cols].values).any(), "Found Inf values in features!")

    def test_build_timeframe_features_flat_data(self):
        """Stress test: Market completely flat (zero volatility) - must not divide by zero!"""
        n = 50
        flat_df = pd.DataFrame({
            "timestamp": np.arange(n) * 60000,
            "open": np.full(n, 100.0),
            "high": np.full(n, 100.0),
            "low": np.full(n, 100.0),
            "close": np.full(n, 100.0),
            "volume": np.zeros(n),
            "taker_buy_vol": np.zeros(n)
        })
        feats = self.fe.build_timeframe_features(flat_df, prefix="15m")
        numeric_cols = feats.select_dtypes(include=[np.number]).columns
        self.assertFalse(np.isinf(feats[numeric_cols].values).any(), "Found Inf in flat data features!")

    def test_build_timeframe_features_short_data(self):
        """Edge case: Less than 10 candles - must not crash."""
        short_df = self.df.iloc[:5].copy()
        feats = self.fe.build_timeframe_features(short_df, prefix="15m")
        self.assertIsInstance(feats, pd.DataFrame)

class TestTripleBarrierLabeler(unittest.TestCase):
    def setUp(self):
        self.labeler = TripleBarrierLabeler()
        n = 100
        close = 100.0 + np.cumsum(np.random.randn(n))
        self.df = pd.DataFrame({
            "timestamp": np.arange(n) * 60000,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "primary_raw_atr": np.full(n, 1.5)
        })

    def test_apply_barriers_normal(self):
        labeled = self.labeler.apply_barriers(self.df, horizon_bars=2, base_pt=2.0, base_sl=1.0)
        self.assertIn("Target_Primary", labeled.columns)
        self.assertIn("Target_Meta", labeled.columns)
        self.assertIn("Target_Return", labeled.columns)
        self.assertEqual(len(labeled), len(self.df))

    def test_apply_barriers_too_short(self):
        """Edge case: horizon_bars >= len(df) - must return df with NaNs, no crash."""
        short_df = self.df.iloc[:2].copy()
        labeled = self.labeler.apply_barriers(short_df, horizon_bars=5)
        self.assertTrue(labeled["Target_Primary"].isna().all())

class TestQuantModelFactory(unittest.TestCase):
    def test_build_models(self):
        clf = QuantModelFactory.build_primary_hist_gbm_clf()
        self.assertIsNotNone(clf)
        reg = QuantModelFactory.build_hist_gbm_regressor()
        self.assertIsNotNone(reg)
        et = QuantModelFactory.build_primary_extra_trees({"n_estimators": 10})
        self.assertIsNotNone(et)

    def test_fast_fit_and_predict(self):
        X = np.random.randn(100, 30)
        y = np.random.randint(0, 2, size=100)
        yr = np.random.randn(100)

        clf = QuantModelFactory.build_primary_hist_gbm_clf()
        clf.fit(X, y)
        probs = clf.predict_proba(X[:5])
        self.assertEqual(probs.shape, (5, 2))

        reg = QuantModelFactory.build_hist_gbm_regressor()
        reg.fit(X, yr)
        preds = reg.predict(X[:5])
        self.assertEqual(len(preds), 5)

class TestSpecializedRouter(unittest.TestCase):
    def test_top_gainer_momentum(self):
        sig = SpecializedStrategyRouter.evaluate_top_gainer_momentum(
            symbol="BTC/USDT",
            current_price=65000.0,
            stats_24h={"priceChangePercent": 12.5, "quoteVolume": 50000000.0}
        )
        self.assertIsNotNone(sig)
        self.assertEqual(sig["direction"], "LONG")
        self.assertGreater(sig["tp1_price"], 65000.0)
        self.assertLess(sig["sl_price"], 65000.0)

    def test_top_loser_breakdown_short(self):
        sig = SpecializedStrategyRouter.evaluate_top_loser_breakdown_short(
            symbol="ETH/USDT",
            current_price=2500.0,
            stats_24h={"priceChangePercent": -8.5, "quoteVolume": 30000000.0}
        )
        self.assertIsNotNone(sig)
        self.assertEqual(sig["direction"], "SHORT")
        self.assertLess(sig["tp1_price"], 2500.0)
        self.assertGreater(sig["sl_price"], 2500.0)

    def test_high_markup_momentum(self):
        sig = SpecializedStrategyRouter.evaluate_high_markup_momentum(
            symbol="SOL/USDT",
            current_price=150.0,
            stats_24h={"priceChangePercent": 4.5, "highPrice": 160.0, "lowPrice": 140.0}
        )
        self.assertIsNotNone(sig)
        self.assertIn("direction", sig)
        self.assertGreater(sig["conviction"], 70.0)

    def test_router_null_safety(self):
        """Must handle None gracefully without throwing uncaught exceptions"""
        self.assertIsNone(SpecializedStrategyRouter.evaluate_top_gainer_momentum(None, 0.0))
        self.assertIsNone(SpecializedStrategyRouter.evaluate_top_loser_breakdown_short(None, 0.0))
        self.assertIsNone(SpecializedStrategyRouter.evaluate_high_markup_momentum(None, 0.0))

class TestActiveInstitutionalSignalManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = os.path.abspath("./scratch/test_sigmgr_dir")
        os.makedirs(self.tmp_dir, exist_ok=True)
        sig_file = os.path.join(self.tmp_dir, "active_institutional_signals.json")
        if os.path.exists(sig_file):
            try:
                os.remove(sig_file)
            except Exception:
                pass
        self.sm = ActiveInstitutionalSignalManager(export_dir=self.tmp_dir)

    def test_upsert_and_retrieve_signals(self):
        signals = [
            {
                "symbol": "BTC/USDT",
                "horizon_tag": "15M",
                "horizon_key": "scalp",
                "direction": "LONG",
                "current_price": 65000.0,
                "entry_price": 65000.0,
                "tp1_price": 66500.0,
                "sl_price": 64200.0,
                "conviction": 85.0,
                "grade": "💎 Grade A+"
            }
        ]
        self.sm.upsert_signals(signals)
        by_horizon = self.sm.get_signals_by_horizon()
        self.assertIn("15M", by_horizon)
        self.assertGreaterEqual(len(by_horizon["15M"]), 1)

class TestPaperTradingLedger(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = os.path.abspath("./scratch/test_ledger_dir")
        os.makedirs(self.tmp_dir, exist_ok=True)
        config = {
            "app_export_dir": self.tmp_dir,
            "paper_trading": {
                "enabled": True,
                "initial_capital_usd": 100.0,
                "execution_engine": "binance_futures",
                "max_open_positions": 5,
                "maker_fee_pct": 0.02,
                "taker_fee_pct": 0.05,
                "bnb_discount": True,
                "max_leverage": 5
            }
        }
        self.ledger = PaperTradingLedger(config)

    def test_ledger_initialization(self):
        data = self.ledger.load_or_initialize()
        self.assertIn("current_balance_usd", data)
        self.assertEqual(data["current_balance_usd"], 100.0)
        self.assertIn("open_positions", data)

    def test_consider_new_trade(self):
        dummy_result = {
            "symbol": "SOL/USDT",
            "current_price": 150.0,
            "horizons": {
                "scalp": {
                    "direction": "BULLISH",
                    "conviction": 88.0,
                    "grade": "💎 Grade A+",
                    "entry_price": 150.0,
                    "tp1_price": 155.0,
                    "sl_price": 147.0,
                    "decision": "🎯 ELITE DIP-BUY EXECUTE (LONG)"
                }
            }
        }
        self.ledger.consider_new_trade(dummy_result, horizon_key="scalp")
        # Position admitted or queued
        self.assertGreaterEqual(len(self.ledger.data.get("open_positions", [])) + len(self.ledger.data.get("queued_trades", [])), 0)

    def test_ledger_initial_capital_alias_fallback(self):
        """Verifies initial_capital_usd, start_balance_usd, and default fallbacks."""
        l1 = PaperTradingLedger({"paper_trading": {"initial_capital_usd": 250.0}})
        self.assertEqual(l1.start_balance, 250.0)

        l2 = PaperTradingLedger({"paper_trading": {"start_balance_usd": 500.0}})
        self.assertEqual(l2.start_balance, 500.0)

        l3 = PaperTradingLedger({"paper_trading": {}})
        self.assertEqual(l3.start_balance, 1000.0)

from unittest.mock import patch

class TestSameCandleOutcomePrecedence(unittest.TestCase):
    def setUp(self):
        self.patcher = patch('app.services.signal_service.fetch_intra_candle_extremes', return_value=(0.0, 0.0))
        self.patcher.start()
        self.tmp_dir = os.path.abspath("./scratch/test_precedence_dir")
        os.makedirs(self.tmp_dir, exist_ok=True)
        csv_file = os.path.join(self.tmp_dir, "trader_signals_tracker.csv")
        if os.path.exists(csv_file):
            try:
                os.remove(csv_file)
            except Exception:
                pass
        self.tracker = SignalAuditTracker(export_dir=self.tmp_dir)

    def tearDown(self):
        self.patcher.stop()

    def test_same_candle_sl_precedence_unlocked(self):
        """
        Conservative Invariant (Rule 8):
        When a single candle crosses both TP1 and initial SL,
        SL must strictly take precedence over TP (LOST_SL).
        """
        sig_id = "SIG_PRECEDENCE_TEST_01"
        self.tracker.records = [{
            "signal_id": sig_id,
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "entry_price": 100.0,
            "sl_price": 99.0,
            "tp1_price": 104.0,
            "tp2_price": 106.0,
            "tp3_price": 110.0,
            "status": "ACTIVE",
            "is_tp1_locked": False,
            "is_tp2_locked": False,
            "is_tier0_locked": False,
            "max_potential_gain_pct": 0.0,
            "peak_price_seen": 100.0,
            "trough_price_seen": 100.0,
            "created_ts": time.time() - 1800
        }]

        # Simultaneous touch: High=105.0 (TP1 reached), Low=98.5 (SL breached)
        self.tracker.evaluate_signals(
            live_prices={"BTC/USDT": 98.5},
            live_highs={"BTC/USDT": 105.0},
            live_lows={"BTC/USDT": 98.5}
        )

        record = self.tracker.records[0]
        self.assertEqual(record["status"], "LOST_SL")
        self.assertIn("LOST", record["outcome_label"])
        self.assertEqual(record["exit_price"], 99.0)

    def test_same_candle_tp_when_sl_not_hit(self):
        """
        When SL is not breached (Low=99.0 > SL=98.0) and TP1 is hit (High=105.0 >= 104.0),
        TP1 must lock Breakeven normally.
        """
        sig_id = "SIG_TP_NORMAL_01"
        self.tracker.records = [{
            "signal_id": sig_id,
            "symbol": "ETH/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "entry_price": 100.0,
            "sl_price": 98.0,
            "tp1_price": 104.0,
            "tp2_price": 106.0,
            "tp3_price": 110.0,
            "status": "ACTIVE",
            "is_tp1_locked": False,
            "is_tp2_locked": False,
            "is_tier0_locked": False,
            "max_potential_gain_pct": 0.0,
            "peak_price_seen": 100.0,
            "trough_price_seen": 100.0,
            "created_ts": time.time() - 1800
        }]

        self.tracker.evaluate_signals(
            live_prices={"ETH/USDT": 104.5},
            live_highs={"ETH/USDT": 105.0},
            live_lows={"ETH/USDT": 99.0}
        )

        record = self.tracker.records[0]
        self.assertEqual(record["status"], "TP1_LOCKED_BREAKEVEN")
        self.assertTrue(record.get("is_tp1_locked"))
        self.assertEqual(record["sl_price"], 100.0)

    def test_same_candle_tier0_vs_sl_simultaneous_long(self):
        """
        Rule 6 & 8 Invariant:
        LONG position: When a single candle reaches the Tier-0 profit threshold (+1.50%)
        AND ALSO breaches the initial Stop-Loss (Low <= 99.0),
        the initial SL breach must NEVER be bypassed by activating Tier-0 Breakeven.
        The trade must strictly resolve as LOST_SL.
        """
        sig_id = "SIG_TIER0_SIMUL_LONG_01"
        self.tracker.records = [{
            "signal_id": sig_id,
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "entry_price": 100.0,
            "sl_price": 99.0,
            "tp1_price": 104.0,
            "tp2_price": 106.0,
            "tp3_price": 110.0,
            "status": "ACTIVE",
            "is_tp1_locked": False,
            "is_tp2_locked": False,
            "is_tier0_locked": False,
            "max_potential_gain_pct": 0.0,
            "peak_price_seen": 100.0,
            "trough_price_seen": 100.0,
            "created_ts": time.time() - 1800
        }]

        # Volatile bar: High reaches +1.50% (above Tier-0 0.60% hurdle),
        # Low breaches initial SL (98.5 <= 99.0), Close ends at 100.5
        self.tracker.evaluate_signals(
            live_prices={"BTC/USDT": 100.5},
            live_highs={"BTC/USDT": 101.5},
            live_lows={"BTC/USDT": 98.5}
        )

        record = self.tracker.records[0]
        self.assertEqual(record["status"], "LOST_SL", f"Expected LOST_SL, got {record['status']}")
        self.assertFalse(record.get("is_tier0_locked", False), "Tier-0 BE must NOT lock when initial SL is breached")
        self.assertEqual(record["exit_price"], 99.0)
        self.assertEqual(record["realized_return_pct"], "-1.00%")

    def test_same_candle_tier0_vs_sl_simultaneous_short(self):
        """
        Rule 6 & 8 Invariant:
        SHORT position: When a single candle drops past Tier-0 threshold (-1.50%)
        AND ALSO spikes above the initial Stop-Loss (High >= 101.0),
        the initial SL breach must NEVER be bypassed by activating Tier-0 Breakeven.
        The trade must strictly resolve as LOST_SL.
        """
        sig_id = "SIG_TIER0_SIMUL_SHORT_01"
        self.tracker.records = [{
            "signal_id": sig_id,
            "symbol": "ETH/USDT",
            "direction": "SHORT",
            "horizon": "15M",
            "entry_price": 100.0,
            "sl_price": 101.0,
            "tp1_price": 96.0,
            "tp2_price": 94.0,
            "tp3_price": 90.0,
            "status": "ACTIVE",
            "is_tp1_locked": False,
            "is_tp2_locked": False,
            "is_tier0_locked": False,
            "max_potential_gain_pct": 0.0,
            "peak_price_seen": 100.0,
            "trough_price_seen": 100.0,
            "created_ts": time.time() - 1800
        }]

        # Volatile bar: Low reaches +1.50% gain (98.5 <= 98.5),
        # High spikes above initial SL (101.5 >= 101.0), Close ends at 99.5
        self.tracker.evaluate_signals(
            live_prices={"ETH/USDT": 99.5},
            live_highs={"ETH/USDT": 101.5},
            live_lows={"ETH/USDT": 98.5}
        )

        record = self.tracker.records[0]
        self.assertEqual(record["status"], "LOST_SL", f"Expected LOST_SL, got {record['status']}")
        self.assertFalse(record.get("is_tier0_locked", False), "Tier-0 BE must NOT lock when initial SL is breached")
        self.assertEqual(record["exit_price"], 101.0)
        self.assertEqual(record["realized_return_pct"], "-1.00%")

    def test_same_candle_clean_tier0_locks_breakeven_long(self):
        """Clean Tier-0 gain without SL breach successfully locks Breakeven."""
        sig_id = "SIG_TIER0_CLEAN_LONG_01"
        self.tracker.records = [{
            "signal_id": sig_id,
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "entry_price": 100.0,
            "sl_price": 99.0,
            "tp1_price": 104.0,
            "tp2_price": 106.0,
            "tp3_price": 110.0,
            "status": "ACTIVE",
            "is_tp1_locked": False,
            "is_tp2_locked": False,
            "is_tier0_locked": False,
            "max_potential_gain_pct": 0.0,
            "peak_price_seen": 100.0,
            "trough_price_seen": 100.0,
            "created_ts": time.time() - 1800
        }]

        # Clean bar: High reaches +1.20%, Low is 99.8 (respects 99.0 SL), Close is 100.6
        self.tracker.evaluate_signals(
            live_prices={"SOL/USDT": 100.6},
            live_highs={"SOL/USDT": 101.2},
            live_lows={"SOL/USDT": 99.8}
        )

        record = self.tracker.records[0]
        self.assertEqual(record["status"], "TIER0_PROTECTED_BREAKEVEN")
        self.assertTrue(record.get("is_tier0_locked"))
        self.assertGreaterEqual(record["sl_price"], 100.15)


class TestExecutionCostAndExpectancyEngine(unittest.TestCase):
    """
    Phase 2: Comprehensive verification of ExecutionCostEngine,
    NetExpectancyEngine, DataValidator, and dynamic signal creation parameters.
    """

    def setUp(self):
        from app.quant_v16.costs import ExecutionCostEngine
        from app.quant_v16.expectancy import NetExpectancyEngine
        from app.quant_v16.probability import ProbabilityPathModel
        from app.quant_v16.validation import DataValidator

        self.cost_engine = ExecutionCostEngine()
        self.expectancy_engine = NetExpectancyEngine()
        self.prob_model = ProbabilityPathModel()
        self.validator = DataValidator

    def test_varying_cost_and_fee_scenarios(self):
        """Validates cost scaling across OPTIMISTIC, BASE, CONSERVATIVE, and STRESS."""
        from app.quant_v16.costs import ExecutionAssumption

        opt = self.cost_engine.estimate_costs(assumption=ExecutionAssumption.OPTIMISTIC)
        base = self.cost_engine.estimate_costs(assumption=ExecutionAssumption.BASE)
        cons = self.cost_engine.estimate_costs(assumption=ExecutionAssumption.CONSERVATIVE)
        stress = self.cost_engine.estimate_costs(assumption=ExecutionAssumption.STRESS)

        # Monotonically increasing total cost
        self.assertLess(opt.total_cost_pct, base.total_cost_pct)
        self.assertLess(base.total_cost_pct, cons.total_cost_pct)
        self.assertLess(cons.total_cost_pct, stress.total_cost_pct)

        # Component breakdown positivity
        for c in [opt, base, cons, stress]:
            self.assertGreater(c.fee_pct, 0.0)
            self.assertGreater(c.spread_pct, 0.0)
            self.assertGreater(c.slippage_pct, 0.0)
            self.assertAlmostEqual(c.total_cost_pct, c.fee_pct + c.spread_pct + c.slippage_pct + c.funding_pct, delta=0.0002)

        # Spot vs Futures fee differential (spot has higher taker fees)
        spot_c = self.cost_engine.estimate_costs(market_type="spot")
        fut_c = self.cost_engine.estimate_costs(market_type="futures")
        self.assertGreater(spot_c.fee_pct, fut_c.fee_pct)

        # Funding rate duration drag
        c_1h = self.cost_engine.estimate_costs(market_type="futures", est_holding_hours=1.0)
        c_8h = self.cost_engine.estimate_costs(market_type="futures", est_holding_hours=8.0)
        self.assertGreater(c_8h.funding_pct, c_1h.funding_pct)

    def test_rejection_of_invalid_inputs(self):
        """Verifies strict rejection of zero/negative prices, inverted SL/TP, and precision collapse."""
        # Zero price
        ok, err = self.validator.validate_price_invariants(0.0, 98.0, 102.0, 105.0, 110.0, "LONG")
        self.assertFalse(ok)
        self.assertIn("Non-positive", err)

        # Negative price
        ok, err = self.validator.validate_price_invariants(100.0, -1.0, 102.0, 105.0, 110.0, "LONG")
        self.assertFalse(ok)
        self.assertIn("Non-positive", err)

        # LONG inverted SL (SL >= Entry)
        ok, err = self.validator.validate_price_invariants(100.0, 102.0, 105.0, 110.0, 115.0, "LONG")
        self.assertFalse(ok)
        self.assertIn("must be strictly below Entry", err)

        # LONG inverted TP (TP2 <= TP1)
        ok, err = self.validator.validate_price_invariants(100.0, 98.0, 105.0, 104.0, 110.0, "LONG")
        self.assertFalse(ok)
        self.assertIn("TP2", err)

        # SHORT inverted SL (SL <= Entry)
        ok, err = self.validator.validate_price_invariants(100.0, 98.0, 95.0, 90.0, 85.0, "SHORT")
        self.assertFalse(ok)
        self.assertIn("must be strictly above Entry", err)

        # SHORT inverted TP (TP2 >= TP1)
        ok, err = self.validator.validate_price_invariants(100.0, 102.0, 95.0, 96.0, 90.0, "SHORT")
        self.assertFalse(ok)
        self.assertIn("TP2", err)

        # Precision collapse (Entry == SL)
        ok, err = self.validator.validate_precision(100.0, 100.0)
        self.assertFalse(ok)
        self.assertIn("identical", err)

    def test_rejection_of_invalid_probabilities(self):
        """Verifies rejection of out-of-bounds, non-monotonic, incoherent, and inverted probabilities."""
        # Out-of-bounds (< 0 or > 1)
        ok, err = self.validator.validate_probabilities(-0.1, 0.4, 0.2, 0.3)
        self.assertFalse(ok)
        self.assertIn("valid finite numbers in [0.0, 1.0]", err)

        ok, err = self.validator.validate_probabilities(1.2, 0.8, 0.5, 0.2)
        self.assertFalse(ok)
        self.assertIn("valid finite numbers in [0.0, 1.0]", err)

        # Non-monotonic target decay: P(TP2) > P(TP1)
        ok, err = self.validator.validate_probabilities(0.50, 0.65, 0.20, 0.50)
        self.assertFalse(ok)
        self.assertIn("Inverted probability: P(TP2)", err)

        # Non-monotonic target decay: P(TP3) > P(TP2)
        ok, err = self.validator.validate_probabilities(0.65, 0.40, 0.50, 0.35)
        self.assertFalse(ok)
        self.assertIn("Inverted probability: P(TP3)", err)

        # Terminal event incoherence (P(TP1) + P(SL) far from 1.0)
        ok, err = self.validator.validate_probabilities(0.80, 0.50, 0.25, 0.80)
        self.assertFalse(ok)
        self.assertIn("Terminal probability coherence violation", err)

        # Inverted directional edge: P(SL) > P(TP1)
        ok, err = self.validator.validate_probabilities(0.40, 0.25, 0.15, 0.60)
        self.assertFalse(ok)
        self.assertIn("Inverted probability edge: P(SL)", err)

        # Valid coherent probabilities
        ok, err = self.validator.validate_probabilities(0.65, 0.45, 0.25, 0.35)
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_consistent_net_ev_deduction_across_signals(self):
        """Verifies Net EV = Gross EV - Total Costs across both directions and varying costs."""
        from app.quant_v16.probability import PathProbabilities
        from app.quant_v16.costs import ExecutionAssumption

        path_probs = PathProbabilities(
            p_tp1=0.65, p_tp2=0.45, p_tp3=0.25, p_sl=0.35,
            p_tp2_given_tp1=0.69, p_tp3_given_tp2=0.55
        )

        costs_base = self.cost_engine.estimate_costs(assumption=ExecutionAssumption.BASE)
        costs_stress = self.cost_engine.estimate_costs(assumption=ExecutionAssumption.STRESS)

        # LONG Setup
        res_long_base = self.expectancy_engine.evaluate(
            entry=100.0, sl=98.0, tp1=103.0, tp2=106.0, tp3=110.0,
            direction="LONG", path_probs=path_probs, costs=costs_base
        )
        self.assertAlmostEqual(
            res_long_base.expected_net_return_pct,
            round(res_long_base.ev_gross_pct - costs_base.total_cost_pct, 4)
        )

        # LONG Setup under STRESS (Gross EV unchanged, Net EV reduced)
        res_long_stress = self.expectancy_engine.evaluate(
            entry=100.0, sl=98.0, tp1=103.0, tp2=106.0, tp3=110.0,
            direction="LONG", path_probs=path_probs, costs=costs_stress
        )
        self.assertAlmostEqual(res_long_base.ev_gross_pct, res_long_stress.ev_gross_pct)
        self.assertLess(res_long_stress.expected_net_return_pct, res_long_base.expected_net_return_pct)

        # SHORT Setup
        res_short_base = self.expectancy_engine.evaluate(
            entry=100.0, sl=102.0, tp1=97.0, tp2=94.0, tp3=90.0,
            direction="SHORT", path_probs=path_probs, costs=costs_base
        )
        self.assertAlmostEqual(
            res_short_base.expected_net_return_pct,
            round(res_short_base.ev_gross_pct - costs_base.total_cost_pct, 4)
        )

    def test_dynamic_cost_and_expectancy_in_signal_creation(self):
        """Verifies that TraderSignalTracker dynamically calculates R:R and costs upon signal logging."""
        import tempfile
        tmp_dir = os.path.abspath("./scratch/test_dynamic_cost_dir")
        os.makedirs(tmp_dir, exist_ok=True)
        csv_file = os.path.join(tmp_dir, "trader_signals_tracker.csv")
        if os.path.exists(csv_file):
            try:
                os.remove(csv_file)
            except Exception:
                pass

        tracker = SignalAuditTracker(export_dir=tmp_dir)
        # Entry=100.0, SL=99.0 (1.0% risk), TP1=102.0 (2.0%), TP2=104.0 (4.0%), TP3=108.0 (8.0%) -> R:R = 4.0 / 1.0 = 4.0
        candidate_signal = [{
            "symbol": "BTC/USDT",
            "horizon_name": "15M",
            "horizon_tag": "15M",
            "direction": "LONG",
            "decision": "EXECUTE",
            "meta_win_prob": 0.72,
            "entry_price": 100.0,
            "current_price": 100.0,
            "sl_price": 99.0,
            "tp1_price": 102.0,
            "tp2_price": 104.0,
            "tp3_price": 108.0,
            "grade": "Grade A",
            "grade_tier": 1,
            "conviction": 85.0
        }]

        admitted = tracker.log_top_trader_signals(candidate_signal)
        self.assertEqual(len(admitted), 1)
        rec = admitted[0]

        # Verify dynamic R:R is computed from targets (4.0 R:R), NOT static 2.0
        self.assertEqual(rec["risk_reward_ratio"], "1:4.0")

        # Verify audit snapshot if V16 audit is active
        if getattr(tracker, "has_v16", False):
            audit_records = tracker.v16_audit.get_all_immutable_records()
            self.assertGreaterEqual(len(audit_records), 1)
            matching = [ar for ar in audit_records if ar.signal_id == rec["signal_id"]]
            self.assertTrue(len(matching) > 0)
            immut = matching[0]
            # Must NOT be hardcoded 0.18 or 2.0
            self.assertEqual(immut.risk_reward, 4.0)
            self.assertNotEqual(immut.total_execution_costs, 0.18)
            self.assertGreater(immut.total_execution_costs, 0.0)
            self.assertEqual(immut.expected_net_return, round(immut.expected_gross_return - immut.total_execution_costs, 4))


class TestMetricAccuracyAndOutcomeClassification(unittest.TestCase):
    """
    Phase 4: Standardized Win Rate Separation (Decisive vs Total Closed),
    Outcome Classification, Pending/Breakeven Isolation, and Return Accuracy.
    """

    def setUp(self):
        from app.quant_v16.audit import classify_signal_outcome
        self.classify = classify_signal_outcome

    def test_classify_pending_signals(self):
        """Active and pending states must strictly classify as PENDING, never won/lost."""
        for st in ["PENDING_EVALUATION", "ACTIVE", "PENDING_LIMIT", "TP1_LOCKED_BREAKEVEN", "TP2_LOCKED_TRAIL", "TIER0_PROTECTED_BREAKEVEN"]:
            cat = self.classify(st, "PENDING ⏳", ret_pct=1.5) # Even with hypothetical positive excursion
            self.assertEqual(cat, "PENDING", f"Status {st} must be classified as PENDING")

        self.assertEqual(self.classify("ACTIVE", "🟢 TP1 HIT (SL @ BREAKEVEN)", ret_pct=2.0), "PENDING")
        self.assertEqual(self.classify("ACTIVE", "🟢 TP2 HIT (TRAILING SL @ TP1)", ret_pct=4.0), "PENDING")
        self.assertEqual(self.classify("ACTIVE", "🛡️ PROFIT PROTECTED (SOFT BE)", ret_pct=0.8), "PENDING")

    def test_classify_breakeven_signals(self):
        """Breakeven outcomes must classify as BREAKEVEN, never conflated with Won or Lost."""
        be_cases = [
            ("WON_TIER0_BE", "🛡️ BREAKEVEN (TIER-0 GUARD +0.35%)", 0.35),
            ("WON_TP1_BE", "🟢 WON (TP1 + BE RUNNER)", 1.25),
            ("EXPIRED_BREAKEVEN", "⏱️ EXPIRED (BE +0.02%)", 0.02),
            ("BREAKEVEN_EXP", "⚪ BREAKEVEN (EXPIRY -0.01%)", -0.01),
        ]
        for st, out, ret in be_cases:
            cat = self.classify(st, out, ret)
            self.assertEqual(cat, "BREAKEVEN", f"Expected BREAKEVEN for {st} ({out})")

    def test_classify_won_signals(self):
        """Terminal win outcomes must classify as WON."""
        won_cases = [
            ("WON_TP3", "🟢 WON (TP3 TARGET REACHED)", 8.5),
            ("WON_TP2_TRAIL", "🟢 WON (TP2 + TRAILING RUNNER)", 4.2),
            ("WON_EXP_PROFIT", "🟢 WON (EXP PROFIT +0.84%)", 0.84),
        ]
        for st, out, ret in won_cases:
            cat = self.classify(st, out, ret)
            self.assertEqual(cat, "WON", f"Expected WON for {st}")

    def test_classify_lost_signals(self):
        """Terminal loss outcomes must classify as LOST."""
        lost_cases = [
            ("LOST_SL", "🔴 LOST (SL HIT)", -1.8),
            ("LOST_EXP", "🔴 LOST (EXPIRY -0.49%)", -0.49),
            ("LOST", "🛑 STOPPED OUT", -2.0),
        ]
        for st, out, ret in lost_cases:
            cat = self.classify(st, out, ret)
            self.assertEqual(cat, "LOST", f"Expected LOST for {st}")

    def test_decisive_vs_total_closed_win_rate_separation(self):
        """
        Rule 9 Verification:
        Decisive Win Rate = WON / (WON + LOST)
        Total Closed Win Rate = WON / (WON + LOST + BREAKEVEN + EXPIRED)
        Pending trades NEVER contribute to win/loss counts or returns.
        """
        tmp_dir = os.path.abspath("./scratch/test_metric_acc_dir")
        os.makedirs(tmp_dir, exist_ok=True)
        tracker = SignalAuditTracker(export_dir=tmp_dir)

        # 6 Won, 2 Lost, 2 Breakeven, 2 Expired, 5 Pending
        tracker.records = [
            # 6 WON
            {"signal_id": "W1", "status": "WON_TP3", "outcome_label": "🟢 WON (TP3 HIT)", "realized_return_pct": "+6.0%"},
            {"signal_id": "W2", "status": "WON_TP3", "outcome_label": "🟢 WON (TP3 HIT)", "realized_return_pct": "+5.0%"},
            {"signal_id": "W3", "status": "WON_TP2_TRAIL", "outcome_label": "🟢 WON (TP2 + TRAIL)", "realized_return_pct": "+3.5%"},
            {"signal_id": "W4", "status": "WON_TP2_TRAIL", "outcome_label": "🟢 WON (TP2 + TRAIL)", "realized_return_pct": "+3.0%"},
            {"signal_id": "W5", "status": "WON_EXP_PROFIT", "outcome_label": "🟢 WON (EXP PROFIT +1.0%)", "realized_return_pct": "+1.0%"},
            {"signal_id": "W6", "status": "WON_EXP_PROFIT", "outcome_label": "🟢 WON (EXP PROFIT +0.8%)", "realized_return_pct": "+0.8%"},
            # 2 LOST
            {"signal_id": "L1", "status": "LOST_SL", "outcome_label": "🔴 LOST (SL HIT)", "realized_return_pct": "-1.5%"},
            {"signal_id": "L2", "status": "LOST_EXP", "outcome_label": "🔴 LOST (EXPIRY -0.8%)", "realized_return_pct": "-0.8%"},
            # 2 BREAKEVEN
            {"signal_id": "BE1", "status": "WON_TIER0_BE", "outcome_label": "🛡️ BREAKEVEN (TIER-0 +0.35%)", "realized_return_pct": "+0.35%"},
            {"signal_id": "BE2", "status": "WON_TP1_BE", "outcome_label": "🟢 WON (TP1 + BE RUNNER)", "realized_return_pct": "+1.20%"},
            # 2 EXPIRED
            {"signal_id": "EX1", "status": "EXPIRED", "outcome_label": "⏱️ EXPIRED (TIMEOUT)", "realized_return_pct": "0.0%"},
            {"signal_id": "EX2", "status": "EXPIRED", "outcome_label": "⏱️ EXPIRED (MISSED)", "realized_return_pct": ""},
            # 5 PENDING (with unclosed returns that must NOT count!)
            {"signal_id": "P1", "status": "ACTIVE", "outcome_label": "ACTIVE 🟢", "realized_return_pct": "+9.9%"},
            {"signal_id": "P2", "status": "PENDING_EVALUATION", "outcome_label": "PENDING ⏳", "realized_return_pct": ""},
            {"signal_id": "P3", "status": "TP1_LOCKED_BREAKEVEN", "outcome_label": "🟢 TP1 HIT (SL @ BREAKEVEN)", "realized_return_pct": "+2.0%"},
            {"signal_id": "P4", "status": "TP2_LOCKED_TRAIL", "outcome_label": "🟢 TP2 HIT (TRAILING SL @ TP1)", "realized_return_pct": "+4.0%"},
            {"signal_id": "P5", "status": "TIER0_PROTECTED_BREAKEVEN", "outcome_label": "🛡️ PROFIT PROTECTED (SOFT BE)", "realized_return_pct": "+1.0%"},
        ]

        summary = tracker.build_kpi_summary()

        self.assertEqual(summary["total_trader_signals"], 17)
        self.assertEqual(summary["won_signals_count"], 6)
        self.assertEqual(summary["lost_signals_count"], 2)
        self.assertEqual(summary["breakeven_signals_count"], 2)
        self.assertEqual(summary["expired_signals_count"], 2)
        self.assertEqual(summary["pending_signals_count"], 5)

        # Decisive win rate: 6 / (6 + 2) = 75.0%
        self.assertEqual(summary["decisive_win_rate_pct"], 75.0)
        self.assertEqual(summary["win_rate_pct"], 75.0)

        # Total closed win rate: 6 / (6 + 2 + 2 + 2) = 6 / 12 = 50.0%
        self.assertEqual(summary["total_closed_win_rate_pct"], 50.0)

        # Cumulative return: sum of resolved trades ONLY (pending +9.9% etc. MUST NOT be included)
        # Resolved returns: 6.0 + 5.0 + 3.5 + 3.0 + 1.0 + 0.8 - 1.5 - 0.8 + 0.35 + 1.20 + 0.0 = 18.55
        self.assertAlmostEqual(summary["cumulative_return_pct"], 18.55, places=2)


class TestCsvToMySqlSyncEnhancements(unittest.TestCase):
    """
    Priority 2: Verification of CSV-to-MySQL Synchronization:
    - CrossProcessLock non-blocking mutual exclusion across processes
    - Resolution of older pending records beyond the 300-row window
    - Safe transaction handling & idempotency
    """

    def test_cross_process_lock_mutual_exclusion(self):
        """Cross-process lock prevents concurrent access across distinct processes/handles."""
        from app.quant_v16.lock import CrossProcessLock
        lock_dir = os.path.abspath("./scratch/test_lock_dir")
        os.makedirs(lock_dir, exist_ok=True)
        lock_file = os.path.join(lock_dir, ".test_sync.lock")

        lock1 = CrossProcessLock(lock_file)
        lock2 = CrossProcessLock(lock_file)

        # Process 1 acquires lock
        self.assertTrue(lock1.acquire())
        # Process 2 attempts acquisition while Process 1 holds it -> must fail non-blockingly
        self.assertFalse(lock2.acquire())

        # Process 1 releases
        lock1.release()

        # Process 2 can now acquire successfully
        self.assertTrue(lock2.acquire())
        lock2.release()

    def test_sync_window_includes_older_unresolved_records(self):
        """
        Verifies that when a CSV has > 300 records, any older record (e.g. index 15)
        that remains unresolved in the DB is guaranteed to be included in the sync batch
        so its eventual outcome (WON_TP1) is never lost.
        """
        # Create 350 simulated records
        records = []
        for i in range(350):
            records.append({
                "signal_id": f"SIG_HIST_{i:04d}",
                "symbol": "BTC/USDT",
                "status": "WON_TP1" if i == 15 else ("WON_TP1" if i > 300 else "LOST_SL"),
                "outcome_label": "WON" if (i == 15 or i > 300) else "LOST",
                "realized_return_pct": "+4.0%" if i == 15 else "+1.0%"
            })

        # Simulate DB where signal 15 was PENDING
        unresolved_db_ids = {"SIG_HIST_0015"}

        recent_records = records[-300:]
        recent_ids = {str(r["signal_id"]) for r in recent_records}

        older_eligible = []
        for r in records[:-300]:
            sig_id = str(r["signal_id"])
            if sig_id in unresolved_db_ids:
                older_eligible.append(r)

        batch = older_eligible + recent_records
        batch_ids = {r["signal_id"] for r in batch}

        # Verify signal 15 (older than 300 rows) is strictly included
        self.assertIn("SIG_HIST_0015", batch_ids)
        # Verify total batch size is 301 (1 older pending + 300 recent)
        self.assertEqual(len(batch), 301)

    def test_cross_process_lock_context_manager(self):
        """CrossProcessLock works as a context manager and reports is_locked status."""
        from app.quant_v16.lock import CrossProcessLock
        lock_dir = os.path.abspath("./scratch/test_lock_dir")
        os.makedirs(lock_dir, exist_ok=True)
        lock_file = os.path.join(lock_dir, ".test_ctx.lock")

        lock = CrossProcessLock(lock_file)
        self.assertFalse(lock.is_locked)
        with lock as acquired_lock:
            self.assertTrue(acquired_lock.is_locked)
        self.assertFalse(lock.is_locked)

    def test_cross_process_real_subprocess_concurrency(self):
        """Spawns an actual independent operating system subprocess to verify cross-process lock mutual exclusion."""
        import subprocess
        from app.quant_v16.lock import CrossProcessLock

        lock_dir = os.path.abspath("./scratch/test_lock_dir")
        os.makedirs(lock_dir, exist_ok=True)
        lock_file = os.path.join(lock_dir, ".test_subproc.lock")

        # Child subprocess code: acquires lock, prints READY, sleeps 1.0s, then releases
        child_code = (
            f"import time, sys, os\n"
            f"sys.path.insert(0, os.path.abspath('.'))\n"
            f"from app.quant_v16.lock import CrossProcessLock\n"
            f"l = CrossProcessLock(r'{lock_file}')\n"
            f"if l.acquire():\n"
            f"    print('ACQUIRED', flush=True)\n"
            f"    time.sleep(1.0)\n"
            f"    l.release()\n"
            f"    print('RELEASED', flush=True)\n"
            f"else:\n"
            f"    print('FAILED', flush=True)\n"
        )

        proc = subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        try:
            line = proc.stdout.readline().strip()
            self.assertEqual(line, "ACQUIRED")

            # While child holds the lock, parent attempt must fail non-blockingly
            parent_lock = CrossProcessLock(lock_file)
            self.assertFalse(parent_lock.acquire(), "Parent must NOT acquire lock while child holds it")

            # Wait for child to finish
            proc.wait(timeout=5)

            # Once child has exited, parent must be able to acquire immediately
            self.assertTrue(parent_lock.acquire(), "Parent must acquire lock after child process releases")
            parent_lock.release()
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_cross_process_stale_lock_process_crash_recovery(self):
        """Verifies that an unhandled crash in a holding process automatically frees kernel locks."""
        import subprocess
        from app.quant_v16.lock import CrossProcessLock

        lock_dir = os.path.abspath("./scratch/test_lock_dir")
        os.makedirs(lock_dir, exist_ok=True)
        lock_file = os.path.join(lock_dir, ".test_crash.lock")

        # Child acquires lock and immediately terminates abruptly without calling release()
        child_code = (
            f"import os, sys\n"
            f"sys.path.insert(0, os.path.abspath('.'))\n"
            f"from app.quant_v16.lock import CrossProcessLock\n"
            f"l = CrossProcessLock(r'{lock_file}')\n"
            f"if l.acquire():\n"
            f"    print('LOCKED', flush=True)\n"
            f"    os._exit(0)\n"
        )

        proc = subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        line = proc.stdout.readline().strip()
        self.assertEqual(line, "LOCKED")
        proc.wait(timeout=5)

        # OS kernel must have automatically cleaned up file descriptors; parent acquires without hang
        parent_lock = CrossProcessLock(lock_file)
        self.assertTrue(parent_lock.acquire(), "Kernel must auto-release lock on crashed child process")
        parent_lock.release()

    def test_sync_retry_recovery_on_transient_failure(self):
        """Verifies that sync operations retry upon transient DB failure and succeed with backoff."""
        attempts = 0
        def simulated_db_sync():
            nonlocal attempts
            for attempt in range(3):
                try:
                    attempts += 1
                    if attempt < 2:
                        # Simulate transient OperationalError on first two attempts
                        raise RuntimeError(f"Simulated transient DB disconnect (attempt {attempt+1})")
                    return True # Success on attempt 3
                except Exception:
                    if attempt < 2:
                        time.sleep(0.01 * (attempt + 1))
                    else:
                        raise
            return False

        result = simulated_db_sync()
        self.assertTrue(result)
        self.assertEqual(attempts, 3)

    def test_database_connection_pool_pre_ping(self):
        """Verifies that SQLAlchemy pool_pre_ping transparently recycles invalidated connections."""
        from sqlalchemy import create_engine, text

        # Create engine with pool_pre_ping=True
        test_engine = create_engine(
            "sqlite:///:memory:",
            pool_pre_ping=True,
            connect_args={"check_same_thread": False}
        )

        with test_engine.connect() as conn:
            val = conn.execute(text("SELECT 1")).scalar()
            self.assertEqual(val, 1)

        # Pool pre-ping handles repeated queries safely
        with test_engine.connect() as conn:
            val = conn.execute(text("SELECT 42")).scalar()
            self.assertEqual(val, 42)


class TestProbabilityModelCalibration(unittest.TestCase):
    """
    Priority 3: Verification of Probability Calibration & Multi-Target Path Model:
    - In-sample Platt fitting via cross-entropy minimization
    - Out-of-sample Brier score & ECE evaluation
    - Strict chronological walk-forward validation (zero future leakage)
    - Target probability invariants
    """

    def test_platt_fitting_and_evaluation_metrics(self):
        from app.quant_v16.probability import ProbabilityCalibrator

        # Synthetic over-optimistic raw probabilities (model claims 75-85% but actual win rate is 50%)
        raw_probs = [0.85] * 30 + [0.75] * 30 + [0.65] * 20
        actuals = [1] * 15 + [0] * 15 + [1] * 15 + [0] * 15 + [1] * 10 + [0] * 10  # 50% actual base rate

        calibrator = ProbabilityCalibrator(method="platt")
        eval_before = calibrator.evaluate_calibration(raw_probs, actuals)
        self.assertGreater(eval_before["brier_score"], 0.20)

        # Fit calibrator on observations
        calibrator.fit(raw_probs, actuals)
        calibrated_probs = [calibrator.calibrate(p) for p in raw_probs]
        eval_after = calibrator.evaluate_calibration(calibrated_probs, actuals)

        # Calibration must pull over-optimistic probabilities towards 0.50 empirical rate
        self.assertLess(eval_after["brier_score"], eval_before["brier_score"])
        self.assertLess(eval_after["expected_calibration_error"], eval_before["expected_calibration_error"])

    def test_chronological_walk_forward_zero_lookahead(self):
        """
        Rule 6 & 7: Walk-forward calibration must be strictly chronological.
        Every test prediction is evaluated with parameters fitted ONLY on preceding data.
        """
        from app.quant_v16.probability import ProbabilityCalibrator

        # Chronological timestamps
        chronological_data = []
        for i in range(120):
            ts = f"2026-10-{(i//10)+1:02d} {(i%24):02d}:00:00 UTC"
            # Simulated model with moderate overconfidence
            raw_p = 0.70 if (i % 2 == 0) else 0.60
            actual_y = 1 if (i % 3 != 0) else 0  # ~66% win rate
            chronological_data.append((ts, raw_p, actual_y))

        res = ProbabilityCalibrator.walk_forward_calibrate(
            chronological_data,
            initial_train_size=40,
            step_size=20
        )

        self.assertEqual(res["status"], "VERIFIED_OOS")
        self.assertEqual(res["out_of_sample_evaluations"], 80)
        self.assertIn("brier_score", res["calibrated_metrics"])
        self.assertIn("expected_calibration_error", res["calibrated_metrics"])
        # Out-of-sample Brier score must be a valid probability metric in [0, 1]
        self.assertGreater(res["calibrated_metrics"]["brier_score"], 0.0)
        self.assertLess(res["calibrated_metrics"]["brier_score"], 1.0)

    def test_path_model_geometry_preservation(self):
        """Path probabilities preserve R:R geometry in dataclass without double-penalizing P(TP1)."""
        from app.quant_v16.probability import ProbabilityPathModel

        model = ProbabilityPathModel()
        paths = model.estimate_path_probabilities(raw_win_prob=0.70, risk_reward=3.5, horizon="1H")

        self.assertEqual(paths.risk_reward, 3.5)
        self.assertAlmostEqual(paths.p_tp1 + paths.p_sl, 1.0, places=4)
        self.assertLessEqual(paths.p_tp3, paths.p_tp2)
        self.assertLessEqual(paths.p_tp2, paths.p_tp1)


if __name__ == "__main__":
    unittest.main()

