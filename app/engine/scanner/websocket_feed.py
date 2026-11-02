"""
QUANT EDGE V16: High-Performance Real-Time WebSocket Market Data Feed
Provides sub-second price ticks with automated keep-alive ping/pong,
instant reconnect with exponential backoff, and latency tracking.
"""

import asyncio
import json
import threading
import time
from typing import Dict, Optional, Tuple


class WebSocketFeedManager:
    """
    Decoupled sub-second market data streaming manager.
    Connects to Binance Futures / Spot multi-ticker mini streams.
    Provides sub-second in-memory price snapshots to the paper trading bot
    and data loader, eliminating REST API queueing latency.
    """

    PRIMARY_WS = "wss://data-stream.binance.vision/ws/!miniTicker@arr"
    FALLBACK_WS = "wss://stream.binance.com:9443/ws/!miniTicker@arr"

    def __init__(self, ping_interval: float = 20.0, ping_timeout: float = 10.0):
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout

        self._prices: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._last_received_ts: float = 0.0
        self._last_ping_ts: float = 0.0
        self._is_running: bool = False
        self._connected: bool = False
        self._worker_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active_stream_url: str = self.PRIMARY_WS
        self._reconnect_count: int = 0
        self._total_packets_received: int = 0

    @property
    def last_update_ts(self) -> float:
        with self._lock:
            return self._last_received_ts

    def is_healthy(self, max_staleness_seconds: float = 3.5) -> bool:
        """Returns True if the WebSocket connection is active and received ticks recently."""
        with self._lock:
            if not self._connected or not self._prices:
                return False
            return (time.time() - self._last_received_ts) <= max_staleness_seconds

    def get_latency_ms(self) -> float:
        """Returns the latency in milliseconds since the last received ticker packet."""
        with self._lock:
            if self._last_received_ts <= 0:
                return 9999.0
            return max(0.0, round((time.time() - self._last_received_ts) * 1000.0, 1))

    def get_prices(self) -> Dict[str, float]:
        """Returns an atomic copy of current live prices."""
        with self._lock:
            return self._prices.copy()

    def get_ticker(self, symbol: str) -> Optional[float]:
        """Returns the live price for a specific symbol."""
        with self._lock:
            return self._prices.get(symbol) or self._prices.get(symbol.replace("/", "").replace(":USDT", ""))

    def start(self):
        """Starts the background WebSocket ingestion worker thread."""
        if self._is_running:
            return
        self._is_running = True
        self._worker_thread = threading.Thread(
            target=self._run_event_loop,
            daemon=True,
            name="quant_v16_ws_feed"
        )
        self._worker_thread.start()

    def stop(self):
        """Stops the WebSocket worker thread and closes connection cleanly."""
        self._is_running = False
        if self._loop and self._loop.is_running():
            def _cancel_all():
                if hasattr(self, "_main_task") and self._main_task and not self._main_task.done():
                    self._main_task.cancel()
            self._loop.call_soon_threadsafe(_cancel_all)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        with self._lock:
            self._connected = False

    def _run_event_loop(self):
        """Worker thread entry point with dedicated asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._main_task = self._loop.create_task(self._connection_supervisor())
            self._loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                for t in pending:
                    t.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self._loop.close()

    async def _connection_supervisor(self):
        """Supervises the WebSocket lifecycle with keep-alive ping/pong and backoff."""
        import websockets

        backoff = 1.0
        while self._is_running:
            try:
                # Alternate between Binance Vision and Binance Spot mirrors
                stream_url = self.PRIMARY_WS if (self._reconnect_count % 2 == 0) else self.FALLBACK_WS
                self._active_stream_url = stream_url

                async with websockets.connect(
                    stream_url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    close_timeout=5.0,
                    max_size=10 * 1024 * 1024
                ) as ws:
                    with self._lock:
                        self._connected = True
                    backoff = 1.0

                    async for message in ws:
                        if not self._is_running:
                            break
                        self._process_raw_message(message)

            except Exception:
                with self._lock:
                    self._connected = False
                self._reconnect_count += 1
                await asyncio.sleep(backoff)
                backoff = min(8.0, backoff * 1.5)

    def _process_raw_message(self, message: str):
        """Parses Binance miniTicker stream array and updates in-memory price dict."""
        try:
            data = json.loads(message)
            if not isinstance(data, list):
                return

            now = time.time()
            updated_ticks: Dict[str, float] = {}

            for item in data:
                s = item.get("s")  # Symbol, e.g. "BTCUSDT"
                c = item.get("c")  # Close price
                if s and c:
                    p = float(c)
                    updated_ticks[s] = p
                    if s.endswith("USDT"):
                        base = s[:-4]
                        updated_ticks[f"{base}/USDT"] = p

            if updated_ticks:
                with self._lock:
                    self._prices.update(updated_ticks)
                    self._last_received_ts = now
                    self._total_packets_received += 1
        except Exception:
            pass


# Global singleton WebSocket feed instance
ws_feed_manager = WebSocketFeedManager()
