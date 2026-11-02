import time
import logging
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.engine.scanner.filters import UniverseFilter
from app.engine.scanner.data_loader import MultiHorizonDataLoader
from app.engine.scanner.btc_shield import BtcPredictiveMarketShield
from app.engine.config import TOP_N_UNIVERSE, TIMEFRAMES_9

logger = logging.getLogger("horizon_scanner")

class MultiHorizonScanner:
    """
    Subsystem 1 Coordinator: Multi-Horizon Universe Scanner.
    - Selects Top 40 high-volume pairs, strictly ignoring meme coins.
    - Always fetches and normalizes all 9 charts (5M, 15M, 1H, 4H, 12H, 24H, 7D, 15D, 30D).
    - Computes real-time BTC Market Beta Shield.
    """

    def __init__(self, max_asset_workers: int = 12, top_n: Optional[int] = None):
        self.max_asset_workers = max_asset_workers
        self.top_n = top_n or TOP_N_UNIVERSE
        self.loader = MultiHorizonDataLoader()
        self.btc_shield = BtcPredictiveMarketShield()
        self.last_universe: List[Dict[str, Any]] = []
        self.last_scan_ts: float = 0.0

    def scan_universe(self) -> Dict[str, Any]:
        """
        Executes a complete multi-horizon scan iteration.
        Returns:
            dict containing btc_shield, scanned_assets (each with 9 timeframes), and universe metadata.
        """
        t0 = time.time()
        print(f"[SCANNER 🛰️] Discovering Top {self.top_n} High-Volume Non-Meme Universe...")

        # 1. Discover Top clean institutional pairs
        universe_assets = UniverseFilter.get_top_40_universe(self.loader.session, top_n=self.top_n)
        self.last_universe = universe_assets

        # 2. Preload bulk tickers & funding rates in 1 single call
        self.loader.preload_bulk_funding_rates()
        all_tickers = self.loader.fetch_all_tickers(max_age_seconds=2.0)

        # 3. Evaluate BTC Predictive Market Shield first
        print(f"[SCANNER 🛡️] Evaluating BTC Predictive Market Beta Shield across 9 Horizons...")
        btc_dfs = self.loader.fetch_all_9_timeframes("BTC/USDT")
        btc_live_price = all_tickers.get("BTC/USDT", 0.0)
        shield_state = self.btc_shield.evaluate_regime(btc_dfs, live_btc_price=btc_live_price)

        # 4. Concurrently ingest 9 charts for each of the Top 40 assets
        print(f"[SCANNER ⚡] Parallel Ingestion of 9 Charts across {len(universe_assets)} assets...")
        scanned_results = {}

        def _scan_single_coin(coin_meta):
            sym = coin_meta["symbol"]
            try:
                dfs_9 = self.loader.fetch_all_9_timeframes(sym)
                live_p = all_tickers.get(sym, coin_meta.get("price", 0.0))
                # Sync latest candle close with instantaneous tick price
                if live_p > 0:
                    for tf in dfs_9:
                        if dfs_9[tf] is not None and not dfs_9[tf].empty:
                            dfs_9[tf].at[dfs_9[tf].index[-1], "close"] = live_p

                return sym, {
                    "symbol": sym,
                    "price": live_p,
                    "volume_24h": coin_meta.get("quote_volume_usd", 0.0),
                    "change_24h": coin_meta.get("change_24h_pct", 0.0),
                    "bid_price": coin_meta.get("bid_price", live_p),
                    "ask_price": coin_meta.get("ask_price", live_p),
                    "spread_bps": coin_meta.get("spread_bps", 5.0),
                    "dfs_9": dfs_9
                }
            except Exception as e:
                return sym, None

        with ThreadPoolExecutor(max_workers=self.max_asset_workers) as executor:
            futures = {executor.submit(_scan_single_coin, asset): asset["symbol"] for asset in universe_assets}
            for fut in as_completed(futures):
                sym, res = fut.result()
                if res is not None:
                    scanned_results[sym] = res
                if len(scanned_results) % 10 == 0 or len(scanned_results) == len(universe_assets):
                    print(f"  [INGEST ⚡] Ingested 9 charts for {len(scanned_results)}/{len(universe_assets)} assets...", flush=True)

        elapsed = time.time() - t0
        self.last_scan_ts = time.time()
        print(f"[SCANNER ✅] Completed 9-Chart Ingestion for {len(scanned_results)}/{len(universe_assets)} assets in {elapsed:.2f}s!")

        return {
            "timestamp": time.time(),
            "btc_shield": shield_state,
            "universe_count": len(universe_assets),
            "scanned_count": len(scanned_results),
            "scan_duration_seconds": round(elapsed, 2),
            "assets": scanned_results
        }
