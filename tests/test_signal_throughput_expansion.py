import unittest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from app.engine.config import TOP_N_UNIVERSE
from app.engine.scanner.filters import UniverseFilter
from app.quant_v16.no_trade_zone import NoTradeZoneEngine, NoTradeZoneReason, no_trade_zone_engine
from app.engine.signals.signal_generator import SignalGenerationSystem, map_canonical_strategy
from app.quant_v16.strategies import StrategyArchetype


class TestSignalThroughputExpansion(unittest.TestCase):
    """
    Verifies the accuracy-first throughput expansion:
    1. Dynamic universe size parameterization.
    2. Institutional Order Block and SMC setup exemption from middle chop.
    3. Intraday (15M/1H) desk decoupling from 1D macro middle-chop.
    4. Preservation of capital against generic 50/50 unconfirmed chop.
    """

    def setUp(self):
        np.random.seed(42)
        n = 30
        close = np.linspace(100.0, 100.5, n) + np.random.normal(0, 0.05, n)
        high = close + 0.10
        low = close - 0.10
        open_ = close - 0.02
        vol = np.full(n, 1000.0)

        self.df_chop = pd.DataFrame({
            'open': open_,
            'high': high,
            'low': low,
            'close': close,
            'volume': vol
        })

    def test_dynamic_universe_top_n_parameterization(self):
        """Verifies UniverseFilter.get_top_40_universe respects dynamic top_n argument."""
        custom_n = 20
        clean_coins = [
            "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "SUI", "LINK", "NEAR",
            "APT", "DOT", "TIA", "INJ", "RENDER", "FET", "OP", "LTC", "UNI", "ICP",
            "FIL", "STX", "TAO", "SEI", "ATOM", "AAVE", "WLD", "RUNE", "POL", "PYTH"
        ]
        mock_raw = [{"symbol": f"{c}USDT", "lastPrice": "10.0", "highPrice": "11.0", "lowPrice": "9.0", "quoteVolume": "50000000.0", "priceChangePercent": "2.0"} for c in clean_coins]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_raw
        
        mock_info_resp = MagicMock()
        mock_info_resp.status_code = 200
        mock_info_resp.json.return_value = {"symbols": [{"symbol": f"{c}USDT", "status": "TRADING", "isSpotTradingAllowed": True} for c in clean_coins]}

        mock_session = MagicMock()
        mock_session.get.side_effect = [mock_info_resp, mock_resp]

        res = UniverseFilter.get_top_40_universe(session=mock_session, top_n=custom_n)
        self.assertEqual(len(res), custom_n)

    def test_generic_chop_without_trigger_still_vetoed(self):
        """Verifies that generic dead middle chop WITHOUT an institutional setup is strictly vetoed."""
        ntz = NoTradeZoneEngine()
        res = ntz.evaluate_asset_ntz(
            df=self.df_chop,
            current_price=100.25,
            anchor_tf="1h",
            ob_setup=None,
            direction="LONG",
            decision="LONG"
        )
        self.assertTrue(res["is_ntz"], "Generic unconfirmed chop must still trigger NTZ")
        self.assertIn("NO TRADE ZONE", res["label"])

    def test_order_block_touch_exempt_from_middle_chop(self):
        """Verifies that a verified Order Block touch is NOT vetoed by middle chop."""
        ntz = NoTradeZoneEngine()
        ob_setup = {
            "setup_detected": True,
            "in_order_block_zone": True,
            "is_touching": True,
            "state": "TESTING",
            "zeiierman_rank": 2,
            "direction": "LONG",
            "mitigated": False
        }
        res = ntz.evaluate_asset_ntz(
            df=self.df_chop,
            current_price=100.25,
            anchor_tf="15m",
            ob_setup=ob_setup,
            alignment_score=65.0,
            meta_win_prob=0.72,
            direction="LONG",
            decision="ORDER_BLOCK_LONG"
        )
        self.assertFalse(res["is_ntz"], "Confirmed Order Block touch must NOT be vetoed by middle chop")

    def test_range_bounce_strategy_exempt_from_middle_chop(self):
        """Verifies that RANGE_BOUNCE_LONG strategy is exempt from middle chop veto."""
        ntz = NoTradeZoneEngine()
        res = ntz.evaluate_asset_ntz(
            df=self.df_chop,
            current_price=100.25,
            anchor_tf="15m",
            ob_setup=None,
            alignment_score=60.0,
            meta_win_prob=0.68,
            direction="LONG",
            decision="RANGE_BOUNCE_LONG"
        )
        self.assertFalse(res["is_ntz"], "Institutional RANGE_BOUNCE strategy must not be vetoed by middle chop")

    def test_15m_desk_decoupling_with_local_confluence(self):
        """Verifies that 15M gate qualifies when 15M/5M/1H desk confluence exists even if 1D has middle-chop veto."""
        sig_sys = SignalGenerationSystem()
        trend_matrix = {
            "5m": "BULLISH",
            "15m": "BULLISH",
            "1h": "BULLISH",
            "4h": "CONSOLIDATION",
            "12h": "CONSOLIDATION",
            "1d": "CONSOLIDATION",
            "1w": "CONSOLIDATION",
            "15d": "CONSOLIDATION",
            "1M": "CONSOLIDATION"
        }
        matrix_eval = {
            "archetype": "ARCHETYPE_C_RANGE_ROTATION",
            "strategy": "CAPITAL_PRESERVATION_MIDDLE_CHOP_VETO",
            "trade_permitted": True,
            "dominant_direction": "LONG"
        }
        horizon_preds = {
            "5m": {"is_cold_start": False, "candle_count": 50},
            "15m": {"is_cold_start": False, "candle_count": 50},
            "1h": {"is_cold_start": False, "candle_count": 50},
            "4h": {"is_cold_start": False, "candle_count": 50},
            "12h": {"is_cold_start": False, "candle_count": 50},
            "1d": {"is_cold_start": False, "candle_count": 50},
        }

        q_15m, q_1h, q_24h = sig_sys.evaluate_multi_horizon_gates(
            trend_matrix=trend_matrix,
            horizon_predictions=horizon_preds,
            matrix_eval=matrix_eval,
            ob_setup_15m=None,
            ob_setup_1h=None,
            ob_setup_24h=None,
            has_smc_15m=False,
            smc_dir_15m=None
        )

        self.assertTrue(q_15m["qualified"], "15M Scalp must qualify with 3/3 intraday desk confluence despite 1D chop")
        self.assertEqual(q_15m["direction"], "LONG")
        self.assertFalse(q_24h["qualified"], "24H Macro swing must remain blocked by 1D middle chop")

    def test_short_signal_without_fundamental_matrix_no_unbound_error(self):
        """Verifies SHORT signal generation safely handles None fundamental_matrix without UnboundLocalError."""
        from app.engine.signals.signal_generator import SignalGenerationSystem
        import numpy as np

        sig_sys = SignalGenerationSystem()
        # Build dummy df with 30 candles
        dates = pd.date_range("2026-01-01", periods=30, freq="15min")
        df_15m = pd.DataFrame({
            "open": np.linspace(100, 90, 30),
            "high": np.linspace(101, 91, 30),
            "low": np.linspace(99, 89, 30),
            "close": np.linspace(99.5, 89.5, 30),
            "volume": [1000.0] * 30
        }, index=dates)

        dfs = {"15m": df_15m, "1d": df_15m}
        btc_shield = {
            "altcoin_longs_allowed": True,
            "altcoin_shorts_allowed": True,
            "active": False,
            "status_code": "CLEAR"
        }

        # Should complete without throwing UnboundLocalError: local variable 'has_severe_positive_news' referenced before assignment
        sig = sig_sys._build_single_horizon_signal(
            symbol="BTC/USDT",
            horizon_label="15M",
            tf_key="15m",
            direction="SHORT",
            current_price=90.0,
            dfs_9=dfs,
            horizon_prediction=None,
            btc_shield_state=btc_shield,
            aligned_horizons=["5m", "15m", "1h"],
            fundamental_matrix=None # explicitly None
        )
        self.assertIsNotNone(sig)
        self.assertIn("signal_status", sig)
        self.assertEqual(sig["direction"], "SHORT")


if __name__ == "__main__":
    unittest.main()
