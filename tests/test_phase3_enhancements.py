"""
Unit and Integration Tests for Phase 3 Institutional Trading Enhancements:
- EXT-02: Non-Linear Liquidity Market Impact Slippage Model
- NWS-01: Macro Economic Calendar & High-Impact Volatility Blackout Filter
- SIG-02: Volatility-Conditioned Dynamic Timeframe TTL
"""

import unittest
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from app.quant_v16.costs import ExecutionCostEngine, ExecutionAssumption, CostBreakdown
from app.services.fundamental_service import fundamental_service
from app.engine.signals.signal_generator import SignalGenerationSystem
from app.engine.execution.paper_trading_bot import PaperTradingBot


class TestPhase3Enhancements(unittest.TestCase):

    # -------------------------------------------------------------------------
    # EXT-02: Non-Linear Liquidity Slippage Model
    # -------------------------------------------------------------------------
    def test_ext02_non_linear_liquidity_slippage_model(self):
        """Verifies that slippage scales non-linearly using square-root order book impact."""
        engine = ExecutionCostEngine()

        # 1. Baseline: No liquidity parameters passed -> identity scalar 1.0
        c_base = engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            historical_slippage_bps=6.0,
            est_holding_hours=1.0,
            assumption=ExecutionAssumption.BASE
        )
        self.assertEqual(c_base.liquidity_impact_mult, 1.0)
        self.assertEqual(c_base.slippage_pct, 0.06)
        # Mathematical integrity: total cost must exactly equal sum of components
        expected_total = round(c_base.fee_pct + c_base.spread_pct + c_base.slippage_pct + c_base.funding_pct, 4)
        self.assertEqual(c_base.total_cost_pct, expected_total)

        # 2. Thin Altcoin: Large order relative to daily volume ($50,000 size on $500,000 volume)
        # depth_proxy = max(10000, 500000 * 0.001) = 10000
        # impact_ratio = sqrt(50000 / 10000) = sqrt(5) ~= 2.236
        c_thin = engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            historical_slippage_bps=6.0,
            est_holding_hours=1.0,
            assumption=ExecutionAssumption.BASE,
            position_size_usd=50000.0,
            volume_24h_usd=500000.0
        )
        self.assertGreater(c_thin.liquidity_impact_mult, 2.0)
        self.assertGreater(c_thin.slippage_pct, c_base.slippage_pct)
        self.assertGreater(c_thin.total_cost_pct, c_base.total_cost_pct)
        expected_thin_total = round(c_thin.fee_pct + c_thin.spread_pct + c_thin.slippage_pct + c_thin.funding_pct, 4)
        self.assertEqual(c_thin.total_cost_pct, expected_thin_total)

        # 3. High-Liquidity Large Cap: Small order on deep liquidity ($500 size on $100M volume)
        # depth_proxy = 100M * 0.001 = 100,000
        # impact_ratio = sqrt(500 / 100000) = 0.07 -> clamped to lower bound 0.70
        c_liquid = engine.estimate_costs(
            market_type="futures",
            observed_spread_bps=4.0,
            historical_slippage_bps=6.0,
            est_holding_hours=1.0,
            assumption=ExecutionAssumption.BASE,
            position_size_usd=500.0,
            volume_24h_usd=100000000.0
        )
        self.assertAlmostEqual(c_liquid.liquidity_impact_mult, 0.70)
        self.assertLess(c_liquid.slippage_pct, c_base.slippage_pct)
        self.assertLess(c_liquid.total_cost_pct, c_base.total_cost_pct)
        expected_liq_total = round(c_liquid.fee_pct + c_liquid.spread_pct + c_liquid.slippage_pct + c_liquid.funding_pct, 4)
        self.assertEqual(c_liquid.total_cost_pct, expected_liq_total)

    # -------------------------------------------------------------------------
    # NWS-01: Macro Economic Calendar & Volatility Blackout Filter
    # -------------------------------------------------------------------------
    def test_nws01_macro_economic_calendar_projection_and_blackout(self):
        """Verifies perpetual calendar date arithmetic and [-30m, +15m] macro blackout gating."""
        now = datetime.now(timezone.utc)

        # 1. Verification of calendar projection: events must exist
        cal = fundamental_service.get_macro_economic_calendar(now_utc=now)
        self.assertTrue(cal["has_macro_event"])
        self.assertIsNotNone(cal["event_name"])
        self.assertIsNotNone(cal["minutes_until_event"])

        # 2. Simulated event: Target time 10 minutes in the future (inside blackout window)
        target_event_time = now + timedelta(minutes=10)
        cal_blackout = fundamental_service.get_macro_economic_calendar(now_utc=target_event_time - timedelta(minutes=10))
        # When evaluating right next to an event date:
        test_event_dt = datetime(2026, 11, 6, 12, 30, tzinfo=timezone.utc) # First Friday NFP
        # Test 10m before event
        eval_before = fundamental_service.get_macro_economic_calendar(now_utc=test_event_dt - timedelta(minutes=10))
        self.assertTrue(eval_before["is_volatility_pause_active"])
        self.assertIn("US Macro Volatility Blackout", eval_before["pause_reason"])

        # Test 10m after event (still inside +15m post-release buffer)
        eval_after = fundamental_service.get_macro_economic_calendar(now_utc=test_event_dt + timedelta(minutes=10))
        self.assertTrue(eval_after["is_volatility_pause_active"])

        # Test 60m before event (safely outside -30m window)
        eval_clear = fundamental_service.get_macro_economic_calendar(now_utc=test_event_dt - timedelta(minutes=60))
        self.assertFalse(eval_clear["is_volatility_pause_active"])

        # 3. Test PaperTradingBot admission rejection on macro blackout
        bot = PaperTradingBot()
        sig_macro_blackout = {
            "symbol": "BTC/USDT",
            "direction": "LONG",
            "horizon": "15M",
            "is_trade_active": True,
            "signal_status": "HOLD_VETOED_BY_MACRO_BLACKOUT",
            "is_macro_blackout": True,
            "entry_price": 70000.0,
            "sl_price": 68000.0,
            "tp1_price": 72000.0,
            "tp2_price": 74000.0,
            "tp3_price": 76000.0,
            "fundamental_matrix": {
                "macro_economic_event": {
                    "event_name": "FOMC Interest Rate Decision",
                    "is_volatility_pause_active": True,
                    "pause_reason": "US Macro Volatility Blackout: FOMC Interest Rate Decision (10.0m until release)"
                }
            }
        }
        admitted = bot.admit_signal(sig_macro_blackout)
        self.assertFalse(admitted, "Paper bot must reject trade entry when macro blackout is active")

    # -------------------------------------------------------------------------
    # SIG-02: Volatility-Conditioned Dynamic Timeframe TTL
    # -------------------------------------------------------------------------
    def test_sig02_volatility_conditioned_dynamic_timeframe_ttl(self):
        """Verifies that signal TTL dynamically compresses during high volatility and expands during calm periods."""
        sig_sys = SignalGenerationSystem()

        # Baseline 15M TTL: 240 seconds
        base_15m_ttl = sig_sys._get_timeframe_ttl("15m")
        self.assertEqual(base_15m_ttl, 240.0)

        # Baseline 1H TTL: 1200 seconds
        base_1h_ttl = sig_sys._get_timeframe_ttl("1h")
        self.assertEqual(base_1h_ttl, 1200.0)

        # Case A: Acute Volatility Expansion (Coin ATR% = 4.5% vs baseline 1.5%)
        # Multiplier = clamp(1.5 / 4.5, 0.40, 1.25) = 0.333 -> clamped to 0.40
        # 15M TTL must compress from 240s down to 240 * 0.40 = 96.0s
        high_vol_ttl = sig_sys._get_timeframe_ttl("15m", active_atr_pct=4.5)
        self.assertEqual(high_vol_ttl, 96.0)
        self.assertLess(high_vol_ttl, base_15m_ttl)

        # Case B: Calm Low-Volatility Consolidation (Coin ATR% = 0.6% vs baseline 1.5%)
        # Multiplier = clamp(1.5 / 0.6, 0.40, 1.25) = 2.5 -> clamped to 1.25
        # 15M TTL can safely expand up to 240 * 1.25 = 300.0s
        low_vol_ttl = sig_sys._get_timeframe_ttl("15m", active_atr_pct=0.6)
        self.assertEqual(low_vol_ttl, 300.0)
        self.assertGreater(low_vol_ttl, base_15m_ttl)


if __name__ == "__main__":
    unittest.main()
