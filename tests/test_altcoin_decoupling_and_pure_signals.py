import os
import unittest
import numpy as np
import pandas as pd
from typing import Dict, Any

from app.engine.signals.signal_generator import SignalGenerationSystem
from app.quant_v16.strategies import StrategyRegistry, StrategyArchetype


class TestAltcoinDecouplingAndPureSignals(unittest.TestCase):
    """
    Forensic test suite for Altcoin Idiosyncratic Decoupling during BTC consolidation/low volume
    and Pure Institutional Signal Generation.
    """

    def setUp(self):
        self.signal_system = SignalGenerationSystem()
        self.strategy_registry = StrategyRegistry()

        # Build synthetic DataFrame with an uptrend (ADX >= 20, EMA20 > EMA50)
        dates = pd.date_range("2026-11-01", periods=50, freq="15min")
        base_price = 100.0
        prices = [base_price + i * 0.5 + (0.2 if i % 2 == 0 else -0.2) for i in range(50)]
        highs = [p + 0.6 for p in prices]
        lows = [p - 0.4 for p in prices]
        volumes = [1000.0 + i * 50.0 for i in range(50)]

        self.df_trending_bull = pd.DataFrame({
            "timestamp": [int(d.timestamp() * 1000) for d in dates],
            "open": prices,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": volumes
        })

        # Build synthetic DataFrame with flat dead chop (ADX < 14)
        flat_prices = [100.0 + (0.05 if i % 2 == 0 else -0.05) for i in range(50)]
        self.df_flat_chop = pd.DataFrame({
            "timestamp": [int(d.timestamp() * 1000) for d in dates],
            "open": flat_prices,
            "high": [p + 0.08 for p in flat_prices],
            "low": [p - 0.08 for p in flat_prices],
            "close": flat_prices,
            "volume": [100.0 for _ in range(50)]
        })

    def test_01_altcoin_idiosyncratic_trend_detection_during_btc_squeeze(self):
        """When BTC is in low volume or consolidation squeeze, trending altcoins qualify as decoupled."""
        btc_shield_squeeze = {
            "status_code": "NO_TRADE_ZONE",
            "regime": "RANGE_SQUEEZE",
            "altcoin_posture": "NO_TRADE_ZONE_CAPITAL_PRESERVATION",
            "is_ntz_active": True,
            "ret_1h": 0.001,
            "ret_24h": 0.002
        }

        is_decoupled, reason = self.signal_system.detect_altcoin_idiosyncratic_trend(
            symbol="SOL/USDT",
            direction="LONG",
            tf_key="15m",
            df_active=self.df_trending_bull,
            current_price=125.0,
            btc_shield_state=btc_shield_squeeze
        )

        self.assertTrue(is_decoupled, f"Expected decoupled altcoin trend, got: {reason}")
        self.assertIn("Decoupled LONG trend on SOL/USDT", reason)

    def test_02_middle_chop_altcoin_remains_safely_filtered(self):
        """When BTC is consolidating, an altcoin that is also flat chop without trend remains filtered."""
        btc_shield_squeeze = {
            "status_code": "NO_TRADE_ZONE",
            "regime": "RANGE_SQUEEZE",
            "altcoin_posture": "NO_TRADE_ZONE_CAPITAL_PRESERVATION",
            "is_ntz_active": True,
            "ret_1h": 0.0,
            "ret_24h": 0.0
        }

        is_decoupled, reason = self.signal_system.detect_altcoin_idiosyncratic_trend(
            symbol="DORMANT/USDT",
            direction="LONG",
            tf_key="15m",
            df_active=self.df_flat_chop,
            current_price=100.0,
            btc_shield_state=btc_shield_squeeze
        )

        self.assertFalse(is_decoupled)
        self.assertIn("Middle chop", reason)

    def test_03_btc_flash_dump_fails_closed_even_for_trending_alts(self):
        """When BTC is in FLASH_DUMP / acute cascade, all altcoins fail closed to protect capital."""
        btc_shield_dump = {
            "status_code": "BEAR_CASCADE_BLACKOUT",
            "regime": "FLASH_DUMP",
            "altcoin_posture": "DEFENSIVE_CASH_ONLY",
            "is_ntz_active": True
        }

        is_decoupled, reason = self.signal_system.detect_altcoin_idiosyncratic_trend(
            symbol="SOL/USDT",
            direction="LONG",
            tf_key="15m",
            df_active=self.df_trending_bull,
            current_price=125.0,
            btc_shield_state=btc_shield_dump
        )

        self.assertFalse(is_decoupled)
        self.assertIn("flash dump", reason.lower())

    def test_04_strategy_registry_allows_trend_when_decoupled(self):
        """StrategyRegistry allows trend strategies during RANGE only when is_decoupled_trend is True."""
        strat = StrategyArchetype.MOMENTUM_LONG.value

        # Case A: Standard RANGE without decoupling -> Strictly PAUSED
        allowed_normal, reason_normal = self.strategy_registry.is_strategy_allowed(strat, current_regime="RANGE", is_decoupled_trend=False)
        self.assertFalse(allowed_normal)
        self.assertIn("PAUSED", reason_normal)

        # Case B: Decoupled independent altcoin trend -> Allowed
        allowed_decoupled, reason_decoupled = self.strategy_registry.is_strategy_allowed(strat, current_regime="RANGE", is_decoupled_trend=True)
        self.assertTrue(allowed_decoupled)
        self.assertIn("Decoupled", reason_decoupled)

    def test_05_pure_signals_unbounded_by_paper_trading_slots(self):
        """Pure signals architecture admits signals and clusters theses without paper trading slot caps."""
        from app.quant_v16.thesis import TradeThesisEngine
        engine = TradeThesisEngine()

        t1, is_new1 = engine.register_or_update(
            symbol="ETH/USDT",
            direction="LONG",
            horizon="15M",
            strategy="MOMENTUM_LONG",
            regime="RANGE",
            expected_net_return=0.85,
            signal_id="SIG_01"
        )
        self.assertTrue(is_new1)
        self.assertEqual(t1.symbol, "ETH/USDT")

        # Second signal on 1H clusters into same thesis without being blocked by paper bot slots
        t2, is_new2 = engine.register_or_update(
            symbol="ETH/USDT",
            direction="LONG",
            horizon="1H",
            strategy="MOMENTUM_LONG",
            regime="RANGE",
            expected_net_return=1.15,
            signal_id="SIG_02"
        )
        self.assertFalse(is_new2)
        self.assertEqual(t2.thesis_id, t1.thesis_id)
        self.assertEqual(t2.active_signals_count, 2)


if __name__ == "__main__":
    unittest.main()
