"""
QUANT EDGE V16: High-Performance Real-Time WebSocket Market Data Feed
Provides sub-second price ticks with automated keep-alive ping/pong,
multi-exchange fallback (Binance Vision -> Binance Data -> Binance Spot -> Bybit v5),
instant reconnect with exponential backoff, and latency tracking.
"""

import asyncio
import json
import ssl
import threading
import time
from typing import Dict, List, Optional, Set, Tuple


class WebSocketFeedManager:
    """
    Decoupled sub-second market data streaming manager.
    Connects to Binance Futures / Spot multi-ticker mini streams with automatic failover
    to Bybit v5 public spot WebSocket stream when Binance endpoints are throttled or partitioned.
    Provides sub-second in-memory price snapshots to the paper trading bot, FastAPI endpoints,
    and data loader, eliminating REST API queueing latency.
    """

    BINANCE_VISION_WS = "wss://data-stream.binance.vision/ws/!miniTicker@arr"
    BINANCE_DATA_WS = "wss://data-stream.binance.com/ws/!miniTicker@arr"
    BINANCE_SPOT_9443 = "wss://stream.binance.com:9443/ws/!miniTicker@arr"
    BINANCE_SPOT_443 = "wss://stream.binance.com:443/ws/!miniTicker@arr"
    BINANCE_SPOT_DEFAULT = "wss://stream.binance.com/ws/!miniTicker@arr"
    BYBIT_WS = "wss://stream.bybit.com/v5/public/spot"
    OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
    OKX_AWS_WS = "wss://wsaws.okx.com:8443/ws/v5/public"

    MIRROR_ENDPOINTS = [
        BINANCE_VISION_WS,
        BINANCE_DATA_WS,
        BINANCE_SPOT_9443,
        BINANCE_SPOT_443,
        BINANCE_SPOT_DEFAULT,
        BYBIT_WS,
        OKX_WS,
        OKX_AWS_WS,
    ]

    DEFAULT_BYBIT_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT",
        "LINKUSDT", "DOTUSDT", "NEARUSDT", "SUIUSDT", "APTUSDT", "OPUSDT", "ARBUSDT",
        "INJUSDT", "TIAUSDT", "FETUSDT", "RENDERUSDT", "ATOMUSDT", "FTMUSDT", "LTCUSDT",
        "BCHUSDT", "UNIUSDT", "XLMUSDT", "ETCUSDT", "ALGOUSDT", "FILUSDT", "ICPUSDT",
        "AAVEUSDT", "CRVUSDT", "MKRUSDT", "SNXUSDT", "DYDXUSDT", "GALAUSDT", "SANDUSDT",
        "MANAUSDT", "AXSUSDT", "THETAUSDT", "EGLDUSDT", "KAVAUSDT", "FLOWUSDT", "CHZUSDT",
        "ENJUSDT", "BLURUSDT", "WLDUSDT", "SEIUSDT", "JTOUSDT", "PYTHUSDT", "JUPUSDT",
        "STRKUSDT", "ONDOUSDT", "ENAUSDT", "NOTUSDT", "IOUSDT", "ZROUSDT", "TONUSDT",
        "TAOUSDT", "PEPEUSDT", "SHIBUSDT", "DOGEUSDT"
    ]

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
        self._active_stream_url: str = self.BINANCE_VISION_WS
        self._reconnect_count: int = 0
        self._total_packets_received: int = 0
        self._is_reconnecting: bool = False
        self._zombie_watchdog_count: int = 0
        self._is_mirror_outage: bool = False
        self._mirror_outage_count: int = 0
        self._active_venue: str = "BINANCE"
        self._venue_cooldowns: Dict[str, float] = {}

    def _get_endpoint_venue(self, endpoint: str) -> str:
        """Identifies the underlying exchange venue for a given WebSocket URL."""
        if "bybit.com" in endpoint:
            return "BYBIT"
        elif "okx.com" in endpoint:
            return "OKX"
        return "BINANCE"

    def _is_venue_throttled(self, venue: str) -> bool:
        """Returns True if the venue is currently under rate-limit or geo-blocking cooldown."""
        with self._lock:
            return time.time() < self._venue_cooldowns.get(venue.upper(), 0.0)

    def _record_venue_throttle(self, venue: str, status_code: int = 429, reason: str = ""):
        """Records an external venue rate-limit or geo-block, triggering fast-fail bypass."""
        now = time.time()
        cooldown = 90.0 if status_code in [403, 451] else 60.0
        with self._lock:
            self._venue_cooldowns[venue.upper()] = now + cooldown
        print(f"[WEBSOCKET FEED [CIRCUIT BREAKER]] Venue {venue.upper()} throttled ({status_code} {reason}). Cooldown: {int(cooldown)}s.", flush=True)

    def _select_next_endpoint(self) -> str:
        """Selects the next available WebSocket mirror endpoint, bypassing venues currently in rate-limit or geo cooldown."""
        with self._lock:
            total = len(self.MIRROR_ENDPOINTS)
            for i in range(total):
                idx = (self._reconnect_count + i) % total
                ep = self.MIRROR_ENDPOINTS[idx]
                v = self._get_endpoint_venue(ep)
                if not self._is_venue_throttled(v):
                    self._reconnect_count = idx
                    return ep

            # If all venues in cooldown, select the one with earliest expiration
            best_ep = self.MIRROR_ENDPOINTS[self._reconnect_count % total]
            earliest_exp = float("inf")
            for ep in self.MIRROR_ENDPOINTS:
                v = self._get_endpoint_venue(ep)
                exp = self._venue_cooldowns.get(v.upper(), 0.0)
                if exp < earliest_exp:
                    earliest_exp = exp
                    best_ep = ep
            return best_ep

    @property
    def active_venue(self) -> str:
        with self._lock:
            return self._active_venue

    @property
    def is_mirror_outage(self) -> bool:
        with self._lock:
            return self._is_mirror_outage

    @property
    def mirror_outage_count(self) -> int:
        with self._lock:
            return self._mirror_outage_count

    @property
    def is_reconnecting(self) -> bool:
        with self._lock:
            return self._is_reconnecting

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def zombie_watchdog_triggers(self) -> int:
        return self._zombie_watchdog_count

    @property
    def last_update_ts(self) -> float:
        with self._lock:
            return self._last_received_ts

    def is_healthy(self, max_staleness_seconds: float = 4.0) -> bool:
        """Returns True if the WebSocket connection is active, healthy, and not experiencing an upstream mirror outage."""
        with self._lock:
            if self._is_mirror_outage or not self._connected or not self._prices:
                return False
            return (time.time() - self._last_received_ts) <= max_staleness_seconds

    def get_latency_ms(self) -> float:
        """Returns the latency in milliseconds since the last received ticker packet."""
        with self._lock:
            if self._last_received_ts <= 0:
                return 9999.0
            return max(0.0, round((time.time() - self._last_received_ts) * 1000.0, 1))

    def is_latency_spike_active(self, threshold_ms: float = 800.0) -> bool:
        """Returns True if WebSocket tick latency exceeds threshold (high-frequency volatility spike)."""
        return self.get_latency_ms() > threshold_ms

    def get_prices(self) -> Dict[str, float]:
        """Returns an atomic copy of current live prices."""
        with self._lock:
            return self._prices.copy()

    def get_ticker(self, symbol: str) -> Optional[float]:
        """Returns the live price for a specific symbol."""
        with self._lock:
            if symbol in self._prices:
                return self._prices[symbol]
            norm = symbol.replace("/", "").replace(":USDT", "").strip().upper()
            if norm in self._prices:
                return self._prices[norm]
            if f"{norm}/USDT" in self._prices:
                return self._prices[f"{norm}/USDT"]
            if norm.endswith("USDT") and norm[:-4] in self._prices:
                return self._prices[norm[:-4]]
            return None

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
        """Supervises the WebSocket lifecycle with keep-alive ping/pong, zombie watchdog, and multi-venue failover."""
        import websockets

        consecutive_fails = 0
        ssl_ctx = None
        try:
            ssl_ctx = ssl.create_default_context()
        except Exception:
            pass

        while self._is_running:
            stream_url = self._select_next_endpoint()
            self._active_stream_url = stream_url
            venue = self._get_endpoint_venue(stream_url)
            is_bybit = (venue == "BYBIT")
            is_okx = (venue == "OKX")

            try:
                connect_kwargs = {
                    "ping_interval": self.ping_interval,
                    "ping_timeout": self.ping_timeout,
                    "close_timeout": 4.0,
                    "max_size": 10 * 1024 * 1024
                }
                if ssl_ctx and stream_url.startswith("wss://"):
                    connect_kwargs["ssl"] = ssl_ctx

                async with websockets.connect(stream_url, **connect_kwargs) as ws:
                    with self._lock:
                        self._connected = True
                        self._is_reconnecting = False
                        self._active_venue = venue
                        if self._is_mirror_outage:
                            self._is_mirror_outage = False
                            print(f"[WEBSOCKET FEED ⚡] Upstream WebSocket connection established via {stream_url} ({venue}). Restored sub-second Tier-0 tick ingestion.", flush=True)

                    consecutive_fails = 0

                    # For Bybit v5: dynamically subscribe to institutional spot universe
                    if is_bybit:
                        symbols_to_sub: Set[str] = set(self.DEFAULT_BYBIT_SYMBOLS)
                        with self._lock:
                            for sym in list(self._prices.keys())[:150]:
                                clean = sym.replace("/", "").replace(":USDT", "").upper()
                                if clean.endswith("USDT") and len(clean) >= 6:
                                    symbols_to_sub.add(clean)

                        sym_list = list(symbols_to_sub)
                        # Subscribe in chunks of 10 (Bybit v5 limit per request)
                        for i in range(0, len(sym_list), 10):
                            chunk = sym_list[i:i + 10]
                            sub_payload = {
                                "op": "subscribe",
                                "args": [f"tickers.{s}" for s in chunk]
                            }
                            await ws.send(json.dumps(sub_payload))

                    # For OKX v5: dynamically subscribe to institutional spot universe
                    if is_okx:
                        symbols_to_sub: Set[str] = set(self.DEFAULT_BYBIT_SYMBOLS)
                        with self._lock:
                            for sym in list(self._prices.keys())[:150]:
                                clean = sym.replace("/", "").replace(":USDT", "").upper()
                                if clean.endswith("USDT") and len(clean) >= 6:
                                    symbols_to_sub.add(clean)

                        sym_list = list(symbols_to_sub)
                        for i in range(0, len(sym_list), 10):
                            chunk = sym_list[i:i + 10]
                            args = []
                            for s in chunk:
                                base = s[:-4] if s.endswith("USDT") else s
                                args.append({"channel": "tickers", "instId": f"{base}-USDT"})
                            sub_payload = {
                                "op": "subscribe",
                                "args": args
                            }
                            await ws.send(json.dumps(sub_payload))

                    last_venue_ping = time.time()

                    while self._is_running:
                        try:
                            # Venue application-level heartbeats every 20 seconds
                            if (time.time() - last_venue_ping) >= 20.0:
                                if is_bybit:
                                    await ws.send(json.dumps({"op": "ping"}))
                                    last_venue_ping = time.time()
                                elif is_okx:
                                    await ws.send("ping")
                                    last_venue_ping = time.time()

                            # Zombie connection watchdog: miniTicker streams emit every 1000ms.
                            # If no packet arrives within 5.0 seconds, force close to trigger immediate reconnect.
                            message = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            self._process_raw_message(message)
                        except asyncio.TimeoutError:
                            self._zombie_watchdog_count += 1
                            break

            except Exception as e:
                err_str = str(e).lower()
                status_code = getattr(e, "status_code", 0)
                if status_code in [403, 418, 429, 451] or any(k in err_str for k in ["429", "403", "451", "rate limit", "too many requests", "banned", "restricted"]):
                    sc = status_code if status_code else (451 if "451" in err_str else (403 if "403" in err_str else 429))
                    self._record_venue_throttle(venue, sc, str(e))
            finally:
                with self._lock:
                    self._connected = False
                    self._is_reconnecting = self._is_running
                self._reconnect_count += 1
                consecutive_fails += 1

                # Track mirror outage when all mirrors have consecutively failed
                if consecutive_fails >= len(self.MIRROR_ENDPOINTS):
                    with self._lock:
                        if not self._is_mirror_outage:
                            self._is_mirror_outage = True
                            self._mirror_outage_count += 1
                            print(f"[WEBSOCKET FEED 🚨] Upstream WebSocket mirror outage active across all {len(self.MIRROR_ENDPOINTS)} mirrors. Instant stepdown to Multi-Venue REST Fallback Hierarchy active.", flush=True)

                # Fast recovery on initial drops (<200ms) to stay within 3.5s freshness SLA
                if consecutive_fails <= 1:
                    sleep_time = 0.15
                elif consecutive_fails == 2:
                    sleep_time = 0.40
                else:
                    sleep_time = min(5.0, 0.4 * (consecutive_fails ** 1.15))

                await asyncio.sleep(sleep_time)

    def _process_raw_message(self, message: str):
        """Parses Binance miniTicker stream array, Bybit v5 ticker dict, or OKX ticker dict and updates in-memory price dict."""
        try:
            data = json.loads(message)
            now = time.time()
            updated_ticks: Dict[str, float] = {}

            # Case 1: Binance miniTicker array format: [{'s': 'BTCUSDT', 'c': '...'}, ...]
            if isinstance(data, list):
                for item in data:
                    s = item.get("s")  # Symbol, e.g. "BTCUSDT"
                    c = item.get("c")  # Close price
                    if s and c:
                        p = float(c)
                        if p > 0:
                            updated_ticks[s] = p
                            if s.endswith("USDT"):
                                base = s[:-4]
                                updated_ticks[f"{base}/USDT"] = p
                                updated_ticks[base] = p

            # Case 2: Bybit v5 public spot ticker snapshot/delta format:
            # {"topic": "tickers.BTCUSDT", "type": "snapshot", "data": {"symbol": "BTCUSDT", "lastPrice": "..."}}
            elif isinstance(data, dict):
                topic = str(data.get("topic", ""))
                if topic.startswith("tickers."):
                    t_data = data.get("data", {})
                    if isinstance(t_data, dict):
                        s = t_data.get("symbol")
                        c = t_data.get("lastPrice")
                        if s and c:
                            p = float(c)
                            if p > 0:
                                updated_ticks[s] = p
                                if s.endswith("USDT"):
                                    base = s[:-4]
                                    updated_ticks[f"{base}/USDT"] = p
                                    updated_ticks[base] = p
                # Case 3: OKX v5 public spot ticker format:
                # {"arg": {"channel": "tickers", "instId": "BTC-USDT"}, "data": [{"instId": "BTC-USDT", "last": "..."}]}
                elif "data" in data and isinstance(data["data"], list):
                    arg = data.get("arg", {})
                    if arg.get("channel") == "tickers" or any("instId" in it for it in data["data"]):
                        for item in data["data"]:
                            inst_id = item.get("instId", "")  # e.g. "BTC-USDT"
                            last_p = item.get("last")
                            if inst_id and last_p:
                                try:
                                    p = float(last_p)
                                    if p > 0:
                                        clean = inst_id.replace("-", "").upper()
                                        updated_ticks[clean] = p
                                        if inst_id.endswith("-USDT"):
                                            base = inst_id[:-5].upper()
                                            updated_ticks[f"{base}/USDT"] = p
                                            updated_ticks[base] = p
                                except (ValueError, TypeError):
                                    continue

            if updated_ticks:
                with self._lock:
                    self._prices.update(updated_ticks)
                    self._last_received_ts = now
                    self._total_packets_received += 1
        except Exception:
            pass


# Global singleton WebSocket feed instance
ws_feed_manager = WebSocketFeedManager()
