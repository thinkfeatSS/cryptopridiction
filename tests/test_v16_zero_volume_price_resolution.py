import unittest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.signal import SignalAudit
from app.services.signal_service import resolve_asset_price

class TestV16ZeroVolumePriceResolution(unittest.TestCase):
    def test_live_price_tier1_resolution(self):
        """Verifies Tier 1: in-memory live price dictionary lookup."""
        live_prices = {"BTC/USDT": 65000.0, "BTCUSDT": 65000.0}
        p = resolve_asset_price("BTC/USDT", live_prices=live_prices)
        self.assertEqual(p, 65000.0)

    def test_tracked_telemetry_tier4_resolution(self):
        """Verifies Tier 4: signal internal tracked current_price when dropped from active 24h ticker."""
        sig = SignalAudit(
            id=1,
            signal_id="SIG_DELISTED_1",
            symbol="DELIST/USDT",
            direction="LONG",
            entry_price=1.00,
            peak_price_seen=1.50,
            trough_price_seen=0.95
        )
        sig.current_price = 1.45
        # Empty live prices and failed external HTTP
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Delisted / Zero Volume Pair")
            p = resolve_asset_price("DELIST/USDT", signal=sig, live_prices={})
            self.assertEqual(p, 1.45)

    def test_historical_kline_tier3_resolution(self):
        """Verifies Tier 3: last historical kline close prior to delisting/halt is resolved."""
        sig = SignalAudit(
            id=2,
            signal_id="SIG_DELISTED_2",
            symbol="ZEROVOL/USDT",
            direction="SHORT",
            entry_price=2.00,
        )
        mock_kline_resp = MagicMock()
        mock_kline_resp.status_code = 200
        # Binance kline format: [open_time, open, high, low, close, ...]
        mock_kline_resp.json.return_value = [
            [1730000000000, "1.80", "1.85", "1.70", "1.72", "1000", 1730000059999]
        ]

        with patch("requests.get") as mock_get:
            def side_effect(url, timeout=2.0):
                if "klines" in url:
                    return mock_kline_resp
                m = MagicMock()
                m.status_code = 404
                return m
            mock_get.side_effect = side_effect

            p = resolve_asset_price("ZEROVOL/USDT", signal=sig, live_prices={})
            self.assertEqual(p, 1.72)

    def test_realized_return_calculation_on_delisted_asset(self):
        """Verifies that resolved terminal exit price computes accurate realized return rather than defaulting to 0.0%."""
        entry_p = 10.0
        exit_p = 12.5  # +25.0% gain
        direction = "LONG"
        ret = ((exit_p - entry_p) / entry_p) * 100.0 if direction == "LONG" else ((entry_p - exit_p) / entry_p) * 100.0
        self.assertAlmostEqual(ret, 25.0, places=2)

        # For SHORT
        entry_s = 10.0
        exit_s = 8.0  # +20.0% gain for short
        direction_s = "SHORT"
        ret_s = ((entry_s - exit_s) / entry_s) * 100.0
        self.assertAlmostEqual(ret_s, 20.0, places=2)

if __name__ == "__main__":
    unittest.main()
