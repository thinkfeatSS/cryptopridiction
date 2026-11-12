import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.quant_v16.no_trade_zone import no_trade_zone_engine, NoTradeZoneEngine, NoTradeZoneReason


class TestExtremeVolatilityBlowouts(unittest.TestCase):
    """
    Test suite verifying protections against Extreme Volatility Blowouts:
    1. Dynamic Slippage Dampener & Effective R:R degradation in flash liquidity voids.
    2. PaperTradingBot rejection of trade entries when spread widening degrades effective R:R below 1:1.20.
    3. PaperTradingBot cancellation of resting limit orders when live spread degrades effective R:R below 1:1.20.
    4. PaperTradingBot cancellation of resting limit orders during macro news blackout windows (CPI / FOMC).
    5. NoTradeZoneEngine news blackout circuit breakers during high-impact US macro prints.
    6. NoTradeZoneEngine cascade circuit breakers during acute exchange liquidation cascades.
    """

    def setUp(self):
        self.tmp_ledger = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp_ledger.close()
        self.bot = PaperTradingBot(ledger_file=self.tmp_ledger.name)

    def tearDown(self):
        if os.path.exists(self.tmp_ledger.name):
            try:
                os.remove(self.tmp_ledger.name)
            except Exception:
                pass

    def test_effective_rr_calculation_and_spread_degradation(self):
        """
        Verify that in a flash liquidity void, spread widening degrades effective R:R
        below 1:1.20 even when gross price geometry appears profitable (e.g. gross 1:1.35).
        """
        entry_p = 100.0
        tp1_p = 102.70   # Gross reward = 2.70
        sl_p = 98.00     # Gross risk = 2.00
        gross_rr = (tp1_p - entry_p) / (entry_p - sl_p)
        self.assertAlmostEqual(gross_rr, 1.35, places=2)

        # Case A: Normal market conditions (tight spread = 4.0 bps, deep liquidity = $50M)
        normal_rr, normal_reward, normal_risk = self.bot.calculate_effective_rr(
            entry_p=entry_p,
            tp1_p=tp1_p,
            sl_p=sl_p,
            spread_bps=4.0,
            volume_24h_usd=50_000_000.0,
            tick_latency_ms=50.0,
            is_limit=False
        )
        self.assertGreaterEqual(normal_rr, 1.20, "Normal market conditions must maintain effective R:R >= 1.20")

        # Case B: Flash liquidity void (spread widened to 50.0 bps due to news/cascade)
        void_rr, void_reward, void_risk = self.bot.calculate_effective_rr(
            entry_p=entry_p,
            tp1_p=tp1_p,
            sl_p=sl_p,
            spread_bps=50.0,
            volume_24h_usd=50_000_000.0,
            tick_latency_ms=150.0,
            is_limit=False
        )
        self.assertLess(void_rr, 1.20, f"Flash void spread blowout must degrade effective R:R below 1:1.20 (got {void_rr})")
        self.assertLess(void_reward, normal_reward)
        self.assertGreater(void_risk, normal_risk)

    def test_paper_trading_bot_admit_signal_rejects_spread_degraded_rr(self):
        """
        Verify that PaperTradingBot.admit_signal strictly rejects trade entry
        when spread widening degrades effective R:R below 1:1.20.
        """
        signal_base = {
            "signal_id": "TEST_SIG_BLOWOUT_01",
            "symbol": "SOL/USDT",
            "direction": "LONG",
            "dominant_direction": "LONG",
            "horizon": "1H",
            "signal_status": "ACTIVE_SIGNAL",
            "is_trade_active": True,
            "entry_price": 150.0,
            "tp1_price": 153.80,  # Gross reward = 3.80
            "sl_price": 147.0,    # Gross risk = 3.00 (gross R:R = 1.27)
            "quality_grade": "Grade A",
            "conviction": 85.0,
            "ev_net": 0.45,
            "meta_passed": True,
            "volume_24h_usd": 20_000_000.0,
            "is_limit_pending": False
        }

        # Sub-case 1: Flash spread blowout (spread_bps = 55.0 bps)
        blowout_signal = dict(signal_base)
        blowout_signal["spread_bps"] = 55.0
        admitted = self.bot.admit_signal(blowout_signal)
        self.assertFalse(admitted, "PaperTradingBot must strictly reject signals where spread widening degrades effective R:R < 1:1.20")
        self.assertEqual(len(self.bot.data["open_positions"]), 0)

        # Sub-case 2: Clean tight spread (spread_bps = 3.5 bps) with healthy gross R:R (1:1.60)
        clean_signal = dict(signal_base)
        clean_signal["tp1_price"] = 154.80  # Gross reward = 4.80, gross risk = 3.00 (gross R:R = 1.60)
        clean_signal["spread_bps"] = 3.5
        admitted_clean = self.bot.admit_signal(clean_signal)
        self.assertTrue(admitted_clean, "PaperTradingBot must admit pristine signals with tight spreads")
        self.assertEqual(len(self.bot.data["open_positions"]), 1)
        self.assertGreaterEqual(self.bot.data["open_positions"][0]["effective_rr"], 1.20)

    def test_resting_limit_cancelled_on_live_spread_blowout_at_touch(self):
        """
        Verify that when price touches a resting limit order, if live bid/ask spread
        has widened (degrading effective R:R below 1:1.20), the order cancels safely
        with CANCELLED_SPREAD_BLOWOUT_RR_DEGRADED rather than executing into a toxic void.
        """
        limit_order = {
            "trade_id": "LIMIT_BLOWOUT_TEST_01",
            "symbol": "AVAX/USDT",
            "desk": "day",
            "desk_name": "Day Desk",
            "direction": "LONG",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "optimal_entry_limit": 30.0,
            "entry_price": 30.0,
            "admission_price": 30.20,
            "current_price": 30.20,
            "tp1_price": 30.80,   # Gross reward = 0.80
            "sl_price": 29.35,    # Gross risk = 0.65 (gross R:R = 1.23)
            "spread_bps": 4.0,
            "volume_24h_usd": 15_000_000.0,
            "opened_at_utc": datetime.now(timezone.utc).isoformat()
        }
        self.bot.data["open_positions"] = [limit_order]
        self.bot.data["cancelled_orders"] = []

        # Price touches limit (curr_p = 29.98 <= 30.00), but live ask/bid spread has blown out to 60 bps:
        # live_bid = 29.90, live_ask = 30.08 (spread = 0.18 on 30.0 = 60 bps)
        live_prices = {
            "AVAX/USDT": 29.98,
            "AVAX/USDT:bid": 29.90,
            "AVAX/USDT:ask": 30.08
        }
        self.bot.on_tick(live_prices=live_prices)

        # Order must not have filled into status OPEN; must be cancelled
        self.assertEqual(len(self.bot.data["open_positions"]), 0)
        self.assertEqual(len(self.bot.data["cancelled_orders"]), 1)
        cancelled = self.bot.data["cancelled_orders"][0]
        self.assertEqual(cancelled["cancellation_reason"], "CANCELLED_SPREAD_BLOWOUT_RR_DEGRADED")
        self.assertIn("1.20", cancelled["cancellation_detail"])

    def test_resting_limit_cancelled_on_macro_news_blackout(self):
        """
        Verify that when a high-impact US macro event (e.g. CPI print or FOMC release)
        enters the volatility pause window, resting limit orders are cancelled pre-emptively
        with CANCELLED_MACRO_EVENT_BLACKOUT to eliminate news spike blowout risk.
        """
        limit_order = {
            "trade_id": "LIMIT_MACRO_TEST_01",
            "symbol": "BTC/USDT",
            "desk": "day",
            "desk_name": "Day Desk",
            "direction": "LONG",
            "status": "RESTING_LIMIT",
            "is_limit_resting": True,
            "optimal_entry_limit": 60000.0,
            "entry_price": 60000.0,
            "admission_price": 60500.0,
            "current_price": 60400.0,
            "tp1_price": 62500.0,
            "sl_price": 58500.0,
            "spread_bps": 2.0,
            "volume_24h_usd": 500_000_000.0,
            "opened_at_utc": datetime.now(timezone.utc).isoformat()
        }
        self.bot.data["open_positions"] = [limit_order]
        self.bot.data["cancelled_orders"] = []

        mock_macro_cal = {
            "has_macro_event": True,
            "event_name": "US CPI YoY Release",
            "is_volatility_pause_active": True,
            "pause_reason": "US Macro Volatility Blackout: US CPI YoY (15.0m until release)"
        }

        with patch("app.services.institutional_intelligence_service.institutional_intelligence_service.get_macro_economic_calendar", return_value=mock_macro_cal):
            self.bot.on_tick(live_prices={"BTC/USDT": 60400.0})

        self.assertEqual(len(self.bot.data["open_positions"]), 0)
        self.assertEqual(len(self.bot.data["cancelled_orders"]), 1)
        cancelled = self.bot.data["cancelled_orders"][0]
        self.assertEqual(cancelled["cancellation_reason"], "CANCELLED_MACRO_EVENT_BLACKOUT")
        self.assertIn("CPI", cancelled["cancellation_detail"])

    def test_no_trade_zone_engine_pre_event_news_blackout(self):
        """
        Verify that NoTradeZoneEngine triggers PRE_EVENT_BLACKOUT during
        high-impact US macroeconomic release windows (CPI, FOMC, NFP).
        """
        df = pd.DataFrame({
            "open": [100.0] * 30,
            "high": [102.0] * 30,
            "low": [98.0] * 30,
            "close": [100.5] * 30,
            "volume": [1000.0] * 30
        })

        # Sub-case 1: Active macro economic event blackout via fund_matrix
        fund_matrix = {
            "macro_economic_event": {
                "event_name": "FOMC Rate Decision",
                "is_volatility_pause_active": True,
                "pause_reason": "US Macro Volatility Blackout: FOMC Rate Decision (10.0m until release)"
            }
        }
        ntz_res = no_trade_zone_engine.evaluate_asset_ntz(
            df=df,
            current_price=100.5,
            anchor_tf="1h",
            fund_matrix=fund_matrix
        )
        self.assertTrue(ntz_res["is_ntz"], "Macro event blackout must trigger is_ntz = True")
        self.assertEqual(ntz_res["code"], NoTradeZoneReason.PRE_EVENT_BLACKOUT.value)
        self.assertFalse(ntz_res["allowed_to_trade"])

        # Sub-case 2: Active macro event blackout via institutional_intelligence_service
        mock_cal = {
            "is_volatility_pause_active": True,
            "pause_reason": "US Macro Volatility Blackout: US CPI YoY"
        }
        with patch("app.services.institutional_intelligence_service.institutional_intelligence_service.get_macro_economic_calendar", return_value=mock_cal):
            ntz_cal_res = no_trade_zone_engine.evaluate_asset_ntz(
                df=df,
                current_price=100.5,
                anchor_tf="1h",
                fund_matrix=None
            )
            self.assertTrue(ntz_cal_res["is_ntz"])
            self.assertEqual(ntz_cal_res["code"], NoTradeZoneReason.PRE_EVENT_BLACKOUT.value)

    def test_no_trade_zone_engine_liquidation_cascade_and_spread_blowout(self):
        """
        Verify that NoTradeZoneEngine triggers MACRO_BTC_CASCADE during acute
        liquidation cascades (e.g. FLASH_DUMP / BEAR_CASCADE_BLACKOUT), and
        DRY_VOLUME_ILLIQUID when effective R:R is degraded below 1:1.20 by spread widening.
        """
        df = pd.DataFrame({
            "open": [100.0] * 30,
            "high": [102.0] * 30,
            "low": [98.0] * 30,
            "close": [100.5] * 30,
            "volume": [1000.0] * 30
        })

        # Sub-case 1: Acute liquidation cascade protects both Long and Short entries
        cascade_shield = {
            "is_active": True,
            "status_code": "FLASH_DUMP",
            "regime": "FLASH_DUMP",
            "reason": "BTC Liquidation Cascade - Acute Flush"
        }
        short_ntz = no_trade_zone_engine.evaluate_asset_ntz(
            df=df,
            current_price=100.5,
            direction="SHORT",
            btc_shield_info=cascade_shield
        )
        self.assertTrue(short_ntz["is_ntz"], "Acute liquidation cascade must halt SHORT entries to prevent void slippage")
        self.assertEqual(short_ntz["code"], NoTradeZoneReason.MACRO_BTC_CASCADE.value)

        # Sub-case 2: Spread blowout degrades effective R:R below 1:1.20
        spread_blowout_ntz = no_trade_zone_engine.evaluate_asset_ntz(
            df=df,
            current_price=100.5,
            spread_bps=45.0,
            effective_rr=1.12  # Degraded below 1.20
        )
        self.assertTrue(spread_blowout_ntz["is_ntz"])
        self.assertEqual(spread_blowout_ntz["code"], NoTradeZoneReason.DRY_VOLUME_ILLIQUID.value)
        self.assertTrue(any("Spread widening" in r for r in spread_blowout_ntz["reasons"]))

    def test_signal_generator_vetoes_spread_degraded_effective_rr(self):
        """
        Verify that SignalGenerationSystem vetoes trades where spread widening
        degrades effective R:R below 1:1.20, assigning HOLD_SPREAD_DEGRADED_RR.
        """
        from app.engine.signals.signal_generator import SignalGenerationSystem

        sig_sys = SignalGenerationSystem()
        df = pd.DataFrame({
            "open": [100.0 + i * 0.1 for i in range(50)],
            "high": [101.0 + i * 0.1 for i in range(50)],
            "low": [99.5 + i * 0.1 for i in range(50)],
            "close": [100.8 + i * 0.1 for i in range(50)],
            "volume": [10000.0] * 50
        })
        dfs_9 = {"15m": df, "1h": df, "4h": df, "1d": df}

        horizon_pred = {
            "consensus_probability": 0.70,
            "classifier_votes": "3/5 LONG",
            "regressor_votes": "3/5 LONG"
        }
        btc_shield = {
            "is_active": False,
            "regime": "BALANCED_VOLATILITY",
            "status_code": "BALANCED",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True
        }

        # Sub-case: Extreme spread blowout (spread_bps = 50.0 bps)
        sig = sig_sys._build_single_horizon_signal(
            symbol="ETH/USDT",
            horizon_label="1H",
            tf_key="1h",
            direction="LONG",
            current_price=105.0,
            dfs_9=dfs_9,
            horizon_prediction=horizon_pred,
            btc_shield_state=btc_shield,
            aligned_horizons=["15M", "1H", "4H"],
            volume_24h_usd=50_000_000.0,
            spread_bps=50.0
        )

        self.assertIsNotNone(sig)
        self.assertFalse(sig["is_trade_active"])
        # Either vetoed by spread degraded RR, flash liquidity drain, excessive spread, or NTZ
        self.assertIn(sig["signal_status"], [
            "HOLD_SPREAD_DEGRADED_RR",
            "HOLD_VETOED_BY_FLASH_LIQUIDITY_DRAIN",
            "HOLD_FILTERED_BY_EXCESSIVE_SPREAD",
            "HOLD_VETOED_BY_BREAKOUT_SPREAD_ASYMMETRY",
            "HOLD_VETOED_BY_NO_TRADE_ZONE"
        ])
        self.assertLess(sig.get("effective_rr", 0.0), 1.20)


if __name__ == "__main__":
    unittest.main()
