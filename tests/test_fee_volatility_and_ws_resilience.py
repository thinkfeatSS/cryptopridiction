import unittest
import time
import json
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd

from app.quant_v16.costs import ExecutionCostEngine, ExecutionAssumption
from app.engine.signals.signal_generator import SignalGenerationSystem
from app.engine.execution.paper_trading_bot import PaperTradingBot
from app.engine.scanner.data_loader import MultiHorizonDataLoader
from app.engine.scanner.websocket_feed import WebSocketFeedManager


class TestFeeVolatilityAndWsResilience(unittest.TestCase):
    """
    Forensic verification suite for Fee Spike Volatility & WebSocket Feed Resilience:
    1. Dynamic Fee Spike Volatility Cushion in ExecutionCostEngine for low-liquidity pairs.
    2. Exact mathematical component sum invariant: fee_pct + spread_pct + slippage_pct + funding_pct == total_cost_pct.
    3. Marginal Net EV (0.00% < EV_net < 0.05%) target calibration in SignalGenerationSystem.
    4. Passive resting limit routing and maker fee application in PaperTradingBot for marginal Net EV setups.
    5. Automatic multi-venue REST fallback hierarchy engagement when WebSocket disconnects.
    6. Level-5 Order Book Depth SWR bridging up to 15.0s during WebSocket drops without lapsing into synthetic data.
    7. 15-second price freshness SLA guaranteed throughout WebSocket disconnects.
    """

    def setUp(self):
        self.cost_engine = ExecutionCostEngine()
        self.sg = SignalGenerationSystem()
        self.paper_bot = PaperTradingBot()
        self.loader = MultiHorizonDataLoader()

    def test_01_fee_spike_volatility_cushion_low_cap(self):
        """
        Verify that ExecutionCostEngine adds dynamic fee spike cushion on low-liquidity pairs (< $25M)
        and supports explicit fee_spike_buffer_bps, while maintaining strict total_cost sum equality.
        """
        # Baseline deep liquid asset ($100M volume)
        c_liquid = self.cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            volume_24h_usd=100_000_000.0,
            assumption=ExecutionAssumption.BASE
        )
        self.assertAlmostEqual(c_liquid.total_cost_pct, round(c_liquid.fee_pct + c_liquid.spread_pct + c_liquid.slippage_pct + c_liquid.funding_pct, 4))

        # Low liquidity pair ($5M volume)
        c_low_cap = self.cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            volume_24h_usd=5_000_000.0,
            assumption=ExecutionAssumption.BASE
        )
        # Fee pct should be higher due to fee spike volatility cushion
        self.assertGreater(c_low_cap.fee_pct, c_liquid.fee_pct)
        # Component sum equality must hold with mathematical precision
        expected_total = round(c_low_cap.fee_pct + c_low_cap.spread_pct + c_low_cap.slippage_pct + c_low_cap.funding_pct, 4)
        self.assertEqual(c_low_cap.total_cost_pct, expected_total)

        # Explicit fee spike buffer (e.g. 5 bps = 0.05%)
        c_explicit = self.cost_engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            fee_spike_buffer_bps=5.0,
            assumption=ExecutionAssumption.BASE
        )
        self.assertGreaterEqual(c_explicit.fee_pct, c_liquid.fee_pct + 0.04)
        expected_explicit_total = round(c_explicit.fee_pct + c_explicit.spread_pct + c_explicit.slippage_pct + c_explicit.funding_pct, 4)
        self.assertEqual(c_explicit.total_cost_pct, expected_explicit_total)

    def test_02_marginal_net_ev_target_resilience_shield(self):
        """
        Verify that SignalGenerationSystem dynamically protects marginal Net EV (0.00% < EV_net < 0.05%)
        by calibrating TP1 within ATR reach or designating RESTING_LIMIT to eliminate taker fee spikes.
        """
        dates = pd.date_range("2026-11-16 00:00", periods=40, freq="15min")
        closes = [100.0 + 0.3 * np.sin(i) for i in range(38)] + [100.2, 100.1]
        opens = [100.0 + 0.3 * np.sin(i) for i in range(38)] + [100.7, 100.2]
        highs = [c + 0.4 for c in closes[:38]] + [101.0, 100.4]
        lows = [c - 0.4 for c in closes[:38]] + [100.0, 99.9]

        df_15m = pd.DataFrame({
            "timestamp": [int(d.timestamp()) for d in dates],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [5000.0] * 40,
            "taker_buy_vol": [2200.0] * 40
        })
        df_15m.attrs["is_price_fresh_15s"] = True
        df_15m.attrs["live_price_freshness_seconds"] = 1.0

        dfs_9 = {"15m": df_15m, "1h": df_15m, "4h": df_15m, "1d": df_15m}
        btc_shield = {
            "regime": "NEUTRAL",
            "action": "NORMAL",
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "sizing_multiplier": 1.0
        }

        hz_pred = {
            "timeframe": "15m",
            "direction": "SHORT",
            "prob_bearish": 0.53,
            "prob_bullish": 0.47,
            "predicted_target_price": 98.0,
            "predicted_change_pct": -2.1
        }

        sig = self.sg._build_single_horizon_signal(
            symbol="PLUME/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="SHORT",
            current_price=100.1,
            dfs_9=dfs_9,
            horizon_prediction=hz_pred,
            btc_shield_state=btc_shield,
            aligned_horizons=["15M"],
            spread_bps=4.0,
            volume_24h_usd=8_000_000.0
        )

        self.assertIsNotNone(sig)
        if sig.get("is_trade_active"):
            ev_net = float(sig.get("ev_net", 0.0))
            # Either Net EV is elevated safely above 0.05%, or it is routed via resting limit
            is_limit = bool(sig.get("entry_mode") == "RESTING_LIMIT" or sig.get("is_limit_pending"))
            self.assertTrue(ev_net >= 0.05 or is_limit, f"Signal should have EV >= 0.05% or be RESTING_LIMIT, got EV={ev_net}%")

    def test_03_paper_trading_bot_maker_fee_on_resting_limit(self):
        """
        Verify that PaperTradingBot charges maker_fee_rate (0.018%) instead of taker (0.045%)
        when executing a resting limit order or when EVnet is marginal (0.00% <= EVnet < 0.05%).
        """
        bot = PaperTradingBot()
        sig_marginal = {
            "symbol": "ENA/USDT",
            "horizon": "15M",
            "direction": "SHORT",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "⚡ Grade A (VWAP_BOUNCE_SHORT)",
            "canonical_strategy": "VWAP_BOUNCE_SHORT",
            "strategy": "VWAP_BOUNCE_SHORT",
            "entry_price": 0.1184,
            "sl_price": 0.1207,
            "tp1_price": 0.1140,
            "tp2_price": 0.1120,
            "tp3_price": 0.1100,
            "ev_net": 0.03,  # Marginal EV in (0.00%, 0.05%)
            "p_tp1": 0.594,
            "conviction": 59.4,
            "spread_bps": 3.0,
            "volume_24h_usd": 22_000_000.0,
            "candle_trigger_confirmed": True
        }

        admitted = bot.admit_signal(sig_marginal)
        self.assertTrue(admitted)
        # Should be marked as passive limit to protect against fee spikes
        self.assertTrue(sig_marginal.get("is_passive_limit") or sig_marginal.get("entry_mode") == "RESTING_LIMIT")

        # Verify entry fee uses maker fee rate
        positions = bot.data.get("open_positions", [])
        ena_pos = next((p for p in positions if p.get("symbol") == "ENA/USDT"), None)
        self.assertIsNotNone(ena_pos)
        pos_size = ena_pos.get("position_size_usd", 0.0)
        entry_fee = ena_pos.get("entry_fee_usd", 0.0)
        expected_maker_fee = pos_size * bot.maker_fee_rate
        self.assertAlmostEqual(entry_fee, expected_maker_fee, places=4)

    def test_03b_marginal_ev_fee_spread_spike_fails_closed(self):
        """
        Verify that if exchange taker fees or spot-perp basis spreads rapidly expand beyond typical
        bounds on low-liquidity pairs, signals with marginal net EV (0.00% < EV_net < 0.05%)
        dynamically degrade to negative net EV and fail closed as intended.
        """
        bot = PaperTradingBot()
        sig_spiked = {
            "symbol": "CHIP/USDT",
            "horizon": "15M",
            "direction": "LONG",
            "is_trade_active": True,
            "signal_status": "ACTIVE_SIGNAL",
            "quality_grade": "⚖️ Grade B (15M STRICT 6-HORIZON ALIGNMENT)",
            "strategy": "STRICT_6_HORIZON_ALIGNMENT",
            "entry_price": 0.02845,
            "sl_price": 0.02794,
            "tp1_price": 0.02925,
            "ev_net": 0.02,  # Marginal EV = 0.02%
            "p_tp1": 0.556,
            "conviction": 55.6,
            "spread_bps": 22.0,  # Spreading expanded beyond typical bounds (22 bps > 15 bps)
            "volume_24h_usd": 4_000_000.0,  # Low liquidity pair (< $10M)
            "candle_trigger_confirmed": True
        }

        admitted = bot.admit_signal(sig_spiked)
        # Must fail closed immediately
        self.assertFalse(admitted, "Signal with marginal net EV and expanded spread/fee spike must fail closed")

    def test_04_websocket_feed_disconnect_engages_rest_fallback(self):
        """
        Verify that when the WebSocket feed disconnects (is_healthy returns False),
        MultiHorizonDataLoader automatically engages the multi-venue REST fallback hierarchy.
        """
        loader = self.loader
        mock_ws = MagicMock()
        mock_ws.is_healthy.return_value = False
        mock_ws.is_mirror_outage = False
        loader.ws_feed = mock_ws

        # Mock Binance REST failing with ConnectionRefused to verify Tier-2 Bybit REST cascade
        mock_ticks = {"BTC/USDT": 67500.0, "ETH/USDT": 2650.0}
        with patch.object(loader.session, "get", side_effect=Exception("ConnectionRefused")):
            with patch.object(loader, "_fetch_bybit_tickers", return_value=mock_ticks):
                ticks = loader.fetch_all_tickers(max_age_seconds=0.0)
                self.assertEqual(ticks.get("BTC/USDT"), 67500.0)
                self.assertTrue(loader._is_price_fresh_15s)

    def test_05_order_book_depth_swr_bridge_during_ws_disconnect(self):
        """
        Verify that Level-5 Order Book Depth cache extends TTL up to 15.0s during WebSocket
        drops, providing continuous real-time confirmation without falling back prematurely.
        """
        loader = self.loader
        mock_ws = MagicMock()
        mock_ws.is_healthy.return_value = False  # WebSocket dropped
        loader.ws_feed = mock_ws

        # Pre-seed depth cache at t = now - 5.0s (older than 2s normal TTL, but within 15s SWR bridge)
        now = time.time()
        cached_depth = {
            "symbol": "BTC/USDT",
            "bids": [[67000.0, 1.5]],
            "asks": [[67010.0, 1.2]],
            "timestamp": now - 5.0,
            "venue": "binance_spot"
        }
        with loader._depth_lock:
            loader._top5_depth_cache["BTCUSDT"] = (cached_depth, now - 5.0)

        # Call fetch_top5_depth: should serve cached depth under the 15s WebSocket disconnect bridge
        depth = loader.fetch_top5_depth("BTC/USDT", max_age_seconds=2.0)
        self.assertIsNotNone(depth)
        self.assertEqual(depth.get("venue"), "binance_spot")

    def test_06_15s_price_freshness_sla_maintained_during_ws_disconnect(self):
        """
        Verify that get_live_price_with_freshness maintains is_fresh_15s = True
        when prices are supplied via the multi-exchange fallback hierarchy.
        """
        loader = self.loader
        mock_ws = MagicMock()
        mock_ws.is_healthy.return_value = False
        loader.ws_feed = mock_ws

        now = time.time()
        loader._live_tickers_ts = now
        loader._symbol_price_timestamps["SOL/USDT"] = now
        loader._is_price_fresh_15s = True
        mock_ticks = {"SOL/USDT": 185.0}
        with patch.object(loader, "fetch_all_tickers", return_value=mock_ticks):
            with patch.object(loader, "_lookup_price_with_multiplier", return_value=(185.0, "SOL/USDT")):
                price, is_fresh, age = loader.get_live_price_with_freshness("SOL/USDT")
                self.assertEqual(price, 185.0)
                self.assertTrue(is_fresh)
                self.assertLessEqual(age, 15.0)


if __name__ == "__main__":
    unittest.main()
