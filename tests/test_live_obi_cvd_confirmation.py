import unittest
import time
from datetime import datetime, timezone
from app.quant_v16.entry_confirmation import EntryConfirmationEngine
from app.engine.execution.paper_trading_bot import PaperTradingBot

class TestLiveObiCvdConfirmation(unittest.TestCase):
    def setUp(self):
        self.bot = PaperTradingBot(ledger_file="scratch/test_paper_ledger_obi_cvd.json")
        self.bot.data = {
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

    def test_calculate_top5_obi_empty(self):
        """Empty or invalid depth inputs return safe default zeroes."""
        res_none = EntryConfirmationEngine.calculate_top5_obi(None)
        self.assertEqual(res_none["obi_5"], 0.0)
        self.assertEqual(res_none["has_depth"], False)

        res_empty = EntryConfirmationEngine.calculate_top5_obi({"bids": [], "asks": []})
        self.assertEqual(res_empty["obi_5"], 0.0)
        self.assertEqual(res_empty["has_depth"], False)

    def test_calculate_top5_obi_synthetic(self):
        """Verifies exact level-5 OBI, USD depth, spread, and micro-price calculation."""
        # 5 Bids: 100 @ 2, 99 @ 2, 98 @ 2, 97 @ 2, 96 @ 2 -> total bid USD = 200 + 198 + 196 + 194 + 192 = 980
        # 5 Asks: 101 @ 1, 102 @ 1, 103 @ 1, 104 @ 1, 105 @ 1 -> total ask USD = 101 + 102 + 103 + 104 + 105 = 515
        depth_data = {
            "bids": [[100, 2], [99, 2], [98, 2], [97, 2], [96, 2]],
            "asks": [[101, 1], [102, 1], [103, 1], [104, 1], [105, 1]]
        }
        res = EntryConfirmationEngine.calculate_top5_obi(depth_data)
        self.assertTrue(res["has_depth"])
        self.assertEqual(res["best_bid"], 100.0)
        self.assertEqual(res["best_ask"], 101.0)
        self.assertEqual(res["bid_depth_usd"], 980.0)
        self.assertEqual(res["ask_depth_usd"], 515.0)

        expected_obi = round((980.0 - 515.0) / (980.0 + 515.0), 4) # 465 / 1495 = 0.3110
        self.assertEqual(res["obi_5"], expected_obi)
        self.assertGreater(res["spread_bps"], 0.0)
        self.assertGreater(res["micro_price"], 100.0)

    def test_long_limit_fill_confirmed_supportive_obi(self):
        """Long resting limit order fills when top-5 book confirms buyer absorption."""
        pos = {
            "trade_id": "TEST_LONG_CONFIRMED",
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 50000.0,
            "optimal_entry_limit": 50000.0,
            "tp1_price": 51500.0,
            "sl_price": 49000.0,
            "current_price": 50200.0,
            "desk": "day",
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "metrics": {"cvd_surge_5": 0.10}
        }
        self.bot.data["open_positions"] = [pos]

        # Supportive order book: heavy bids, thin asks (OBI ~ +0.50)
        depths = {
            "BTC/USDT": {
                "bids": [[49995.0, 3.0], [49990.0, 2.0]],
                "asks": [[50000.0, 0.5], [50005.0, 0.5]]
            }
        }

        # Market touches limit price at $49,995
        self.bot.on_tick(
            live_prices={"BTC/USDT": 49995.0},
            order_book_depths=depths,
            cvd_metrics={"BTC/USDT": {"cvd_surge": 0.15}}
        )

        pos_after = self.bot.data["open_positions"][0]
        self.assertEqual(pos_after["status"], "OPEN")
        self.assertFalse(pos_after["is_limit_resting"])
        self.assertEqual(pos_after["fill_confirmation_type"], "LIVE_OBI_CVD_CONFIRMED")
        self.assertGreater(pos_after["fill_obi"], 0.0)
        self.assertFalse(pos_after["awaiting_microstructure_inflow"])

    def test_long_limit_fill_deferred_adverse_ask_wall(self):
        """Long resting limit order fill is deferred when book has adverse ask wall pressure."""
        pos = {
            "trade_id": "TEST_LONG_DEFERRED",
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 50000.0,
            "optimal_entry_limit": 50000.0,
            "tp1_price": 51500.0,
            "sl_price": 49000.0,
            "current_price": 50100.0,
            "desk": "day",
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "metrics": {}
        }
        self.bot.data["open_positions"] = [pos]

        # Toxic ask cascade: heavy asks, thin bids (OBI = -0.70) + negative CVD dump (-0.35)
        depths = {
            "BTC/USDT": {
                "bids": [[49990.0, 0.2], [49980.0, 0.2]],
                "asks": [[50000.0, 4.0], [50010.0, 4.0]]
            }
        }

        # Price touches limit price at $49,990
        self.bot.on_tick(
            live_prices={"BTC/USDT": 49990.0},
            order_book_depths=depths,
            cvd_metrics={"BTC/USDT": {"cvd_surge": -0.35}}
        )

        # Order must NOT be filled into the falling knife
        pos_after = self.bot.data["open_positions"][0]
        self.assertEqual(pos_after["status"], "RESTING_LIMIT")
        self.assertTrue(pos_after["is_limit_resting"])
        self.assertTrue(pos_after["awaiting_microstructure_inflow"])
        self.assertGreaterEqual(pos_after["microstructure_deferral_count"], 1)

    def test_long_limit_adverse_blowout_cancellation(self):
        """If deferred resting limit order penetrates >1.20% blowout gate, it cancels automatically."""
        pos = {
            "trade_id": "TEST_LONG_BLOWOUT",
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 50000.0,
            "optimal_entry_limit": 50000.0,
            "current_price": 50000.0,
            "desk": "day",
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "metrics": {}
        }
        self.bot.data["open_positions"] = [pos]

        # Adverse price dump to 49,300 (-1.40% penetration through 50,000 limit)
        self.bot.on_tick(live_prices={"BTC/USDT": 49300.0})

        # Must be removed from open_positions and added to cancelled_orders
        self.assertEqual(len(self.bot.data["open_positions"]), 0)
        self.assertEqual(len(self.bot.data["cancelled_orders"]), 1)
        canc = self.bot.data["cancelled_orders"][0]
        self.assertEqual(canc["cancellation_reason"], "CANCELLED_EXTREME_MACRO_BLOWOUT")

    def test_short_limit_fill_confirmed_and_deferred(self):
        """Verifies short limit fill deferral under bid squeeze and confirmation under ask resistance."""
        pos = {
            "trade_id": "TEST_SHORT",
            "symbol": "ETH/USDT",
            "direction": "SHORT",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 3000.0,
            "optimal_entry_limit": 3000.0,
            "tp1_price": 2900.0,
            "sl_price": 3050.0,
            "current_price": 2980.0,
            "desk": "scalp",
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "metrics": {}
        }
        self.bot.data["open_positions"] = [pos]

        # Toxic squeeze: heavy bids pushing up (OBI = +0.70) and positive CVD (+0.30)
        squeeze_depths = {
            "ETH/USDT": {
                "bids": [[3005.0, 10.0], [3000.0, 10.0]],
                "asks": [[3010.0, 1.0], [3015.0, 1.0]]
            }
        }
        # Price touches short limit at 3005
        self.bot.on_tick(
            live_prices={"ETH/USDT": 3005.0},
            order_book_depths=squeeze_depths,
            cvd_metrics={"ETH/USDT": {"cvd_surge": 0.30}}
        )

        # Must be deferred
        pos_after = self.bot.data["open_positions"][0]
        self.assertEqual(pos_after["status"], "RESTING_LIMIT")
        self.assertTrue(pos_after["awaiting_microstructure_inflow"])

        # Now book flips to seller resistance: heavy asks (OBI = -0.60) and negative CVD (-0.15)
        resist_depths = {
            "ETH/USDT": {
                "bids": [[3000.0, 1.0], [2995.0, 1.0]],
                "asks": [[3005.0, 10.0], [3010.0, 10.0]]
            }
        }
        self.bot.on_tick(
            live_prices={"ETH/USDT": 3002.0},
            order_book_depths=resist_depths,
            cvd_metrics={"ETH/USDT": {"cvd_surge": -0.15}}
        )

        # Now fill is confirmed
        pos_filled = self.bot.data["open_positions"][0]
        self.assertEqual(pos_filled["status"], "OPEN")
        self.assertEqual(pos_filled["fill_confirmation_type"], "LIVE_OBI_CVD_CONFIRMED")
        self.assertLess(pos_filled["fill_obi"], 0.0)

    def test_backward_compatibility_fallback_without_depth(self):
        """When depth is absent, execution falls back cleanly to price touch without raising errors."""
        pos = {
            "trade_id": "TEST_FALLBACK",
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "entry_price": 180.0,
            "optimal_entry_limit": 180.0,
            "tp1_price": 190.0,
            "sl_price": 175.0,
            "current_price": 182.0,
            "desk": "swing",
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "metrics": {}
        }
        self.bot.data["open_positions"] = [pos]

        # Call on_tick without depth or cvd arguments
        self.bot.on_tick(live_prices={"SOL/USDT": 179.90})

        pos_after = self.bot.data["open_positions"][0]
        self.assertEqual(pos_after["status"], "OPEN")
        self.assertEqual(pos_after["fill_confirmation_type"], "PRICE_TOUCH_FALLBACK")

    def test_microstructure_offline_conservative_taker_buy_volume_fallback(self):
        """In local test environments without live WebSockets or Redis, orderbook depth and CVD fall back to taker-buy estimates."""
        # 1. Supportive taker-buy ratio on Long (tb_ratio = 0.65 -> positive synth OBI and CVD)
        candle_metrics_support = {"taker_buy_ratio": 0.65}
        confirmed, reason, telemetry = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="LONG",
            limit_price=100.0,
            current_price=99.95,
            depth_data=None,
            cvd_metrics=None,
            candle_metrics=candle_metrics_support
        )
        self.assertTrue(confirmed, "Supportive taker-buy volume ratio must confirm long limit fill")
        self.assertEqual(telemetry["fill_confirmation_type"], "SYNTHETIC_MICROSTRUCTURE_CONFIRMED")
        self.assertTrue(telemetry["is_synthetic"])
        self.assertGreater(telemetry["obi_5"], 0.0)
        self.assertGreater(telemetry["cvd_surge"], 0.0)

        # 2. Adverse taker-buy ratio on Long (tb_ratio = 0.20 -> toxic sell flow: OBI < -0.25, CVD < -0.20)
        candle_metrics_adverse = {"taker_buy_ratio": 0.20}
        confirmed_adv, reason_adv, telemetry_adv = EntryConfirmationEngine.validate_resting_limit_fill(
            direction="LONG",
            limit_price=100.0,
            current_price=99.95,
            depth_data=None,
            cvd_metrics=None,
            candle_metrics=candle_metrics_adverse
        )
        self.assertFalse(confirmed_adv, "Adverse taker-buy volume ratio must defer long limit fill")
        self.assertEqual(telemetry_adv["fill_state"], "AWAITING_INFLOW")
        self.assertIn("Adverse ask wall pressure", reason_adv)

    def test_data_loader_offline_depth_and_cvd_conservative_fallback(self):
        """MultiHorizonDataLoader synthesizes conservative orderbook depth and CVD when feeds are offline."""
        from app.engine.scanner.data_loader import MultiHorizonDataLoader
        from unittest.mock import patch
        import pandas as pd

        loader = MultiHorizonDataLoader()
        # Seed cache with known 15m candle possessing taker-buy volume
        df_candle = pd.DataFrame([{
            "timestamp": 1700000000000,
            "open": 100.0,
            "high": 101.0,
            "low": 99.5,
            "close": 100.5,
            "volume": 1000.0,
            "taker_buy_vol": 650.0  # 65% taker buy ratio
        }])
        loader._candle_cache["TEST/USDT_15m"] = (df_candle, time.time())

        # When exchange depth endpoints return None
        with patch.object(loader, "_fetch_raw_depth_from_exchanges", return_value=None):
            depth = loader.fetch_top5_depth("TEST/USDT")
            self.assertIsNotNone(depth)
            self.assertTrue(depth["is_synthetic"])
            self.assertEqual(depth["venue"], "conservative_taker_buy_estimate")
            self.assertEqual(len(depth["bids"]), 5)
            self.assertEqual(len(depth["asks"]), 5)
            # OBI should reflect (0.65 - 0.50) * 2.0 = +0.30
            self.assertAlmostEqual(depth["obi_5"], 0.30, places=2)

            cvd = loader.fetch_cvd_metrics("TEST/USDT")
            self.assertIsNotNone(cvd)
            self.assertTrue(cvd["is_synthetic"])
            self.assertEqual(cvd["source"], "conservative_taker_buy_estimate")
            # CVD surge = 2 * 0.65 - 1.0 = +0.30
            self.assertAlmostEqual(cvd["cvd_surge"], 0.30, places=2)

    def test_signal_generator_offline_cvd_and_obi_taker_buy_fallback(self):
        """SignalGenerationSystem microstructure features fall back to taker-buy estimates when live feeds are offline."""
        from app.engine.signals.signal_generator import SignalGenerationSystem
        import pandas as pd
        import numpy as np

        sig_sys = SignalGenerationSystem()
        n = 30
        df = pd.DataFrame({
            "timestamp": np.arange(1700000000, 1700000000 + n * 900, 900),
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [100.2 + i * 0.1 for i in range(n)],
            "low": [99.8 + i * 0.1 for i in range(n)],
            "close": [100.1 + i * 0.1 for i in range(n)],
            "volume": [1000.0] * n,
            "taker_buy_vol": [600.0] * n
        })
        dfs_9 = {tf: df.copy() for tf in ["5m", "15m", "1h", "4h", "12h", "1d", "1w", "15d", "1M"]}
        btc_shield = {"status_code": "NORMAL", "altcoin_longs_allowed": True, "regime": "NEUTRAL"}

        sig = sig_sys._build_single_horizon_signal(
            symbol="BTC/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="LONG",
            current_price=103.0,
            dfs_9=dfs_9,
            horizon_prediction={"predicted_change_pct": 1.5, "predicted_target_price": 104.5, "consensus_probability": 0.70},
            btc_shield_state=btc_shield,
            aligned_horizons=["5m", "15m", "1h", "4h", "12h", "1d"]
        )
        self.assertIsNotNone(sig)
        m_feats = sig["microstructure_features"]
        self.assertIn("f_cvd_divergence", m_feats)
        self.assertIn("f_order_book_imbalance", m_feats)
        self.assertFalse(np.isnan(m_feats["f_cvd_divergence"]))
        self.assertFalse(np.isnan(m_feats["f_order_book_imbalance"]))

    def test_test_py_crypto_data_loader_offline_orderbook_and_cvd_fallback(self):
        """CryptoDataLoader in test.py falls back to taker-buy volume estimates when offline."""
        from test import CryptoDataLoader
        import pandas as pd

        loader = CryptoDataLoader()
        df = pd.DataFrame({
            "timestamp": [1700000000000 + i * 900000 for i in range(10)],
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.5] * 10,
            "volume": [1000.0] * 10,
            "taker_buy_vol": [700.0] * 10  # 70% taker-buy ratio
        })
        loader._cache["SOL/USDT_15m_2000"] = df

        # Force exchange failure by pointing session to closed endpoint
        loader.session.get = lambda *args, **kwargs: type("Resp", (), {"status_code": 500, "json": lambda: {}})()

        imbalance = loader.fetch_orderbook_imbalance("SOL/USDT", limit=5)
        # Expected: (0.70 - 0.50) * 2.0 = +0.40
        self.assertAlmostEqual(imbalance, 0.40, places=2)

        cvd = loader.fetch_cvd_metrics("SOL/USDT")
        self.assertEqual(cvd["source"], "conservative_taker_buy_estimate")
        self.assertTrue(cvd["is_synthetic"])
        # Expected: 2 * 0.70 - 1.0 = +0.40
        self.assertAlmostEqual(cvd["cvd_surge"], 0.40, places=2)


if __name__ == "__main__":
    unittest.main()

