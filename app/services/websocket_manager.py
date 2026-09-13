import asyncio
import os
import json
import time
import logging
from typing import Set, Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("websocket_manager")

class WebSocketManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = asyncio.Lock()
        self._last_forecast_mtime: float = 0.0
        self._last_shield_payload: Dict[str, Any] = {}
        self._last_leaderboard_fingerprints: Dict[str, str] = {}
        self._watcher_task: Optional[asyncio.Task] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"[WS 🟢] Client connected. Total active connections: {len(self.active_connections)}")
        
        # Send instant welcome handshake
        try:
            await websocket.send_text(json.dumps({
                "type": "connection_ack",
                "message": "Connected to QuantEdge Real-Time Multi-Horizon Stream",
                "timestamp": time.time()
            }))
        except Exception:
            pass

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"[WS 🔴] Client disconnected. Total active connections: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Asynchronously broadcast JSON payload to all connected clients."""
        if not self.active_connections:
            return

        payload_str = json.dumps(message, default=str)
        dead_connections = []

        async with self._lock:
            connections = list(self.active_connections)

        for connection in connections:
            try:
                await connection.send_text(payload_str)
            except Exception:
                dead_connections.append(connection)

        if dead_connections:
            async with self._lock:
                for dead in dead_connections:
                    self.active_connections.discard(dead)

    def broadcast_threadsafe(self, message: Dict[str, Any]):
        """Thread-safe synchronous helper called from background threads."""
        if not self.active_connections:
            return
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)

    async def start_background_watcher(self, export_dir: str = "/app/export_app_data"):
        """High-frequency watcher that detects engine predictions & broadcasts deltas to clients."""
        logger.info(f"[WS 🛰️] Starting background forecast watcher on {export_dir}...")
        forecast_path = os.path.join(export_dir, "live_market_forecast.json")
        last_ping_ts = time.time()

        while True:
            try:
                now_ts = time.time()

                # 1. Periodic Ping to keep WebSocket channels open across cloud firewalls
                if (now_ts - last_ping_ts) >= 15.0:
                    last_ping_ts = now_ts
                    if self.active_connections:
                        await self.broadcast({"type": "ping", "ts": now_ts})

                # 2. Check for live forecast file updates
                if os.path.exists(forecast_path):
                    mtime = os.path.getmtime(forecast_path)
                    if mtime > self._last_forecast_mtime:
                        self._last_forecast_mtime = mtime
                        try:
                            with open(forecast_path, "r", encoding="utf-8") as f:
                                data = json.load(f)

                            # A. Check and broadcast BTC Shield Updates
                            shield = data.get("btc_market_shield", {})
                            if shield and shield != self._last_shield_payload:
                                self._last_shield_payload = shield
                                if self.active_connections:
                                    await self.broadcast({
                                        "type": "shield_tick",
                                        "timestamp": data.get("timestamp"),
                                        "data": shield
                                    })

                            # B. Check and broadcast individual asset delta updates
                            leaderboard = data.get("scanner_leaderboard", [])
                            updated_assets = []
                            for item in leaderboard:
                                if not isinstance(item, dict) or "symbol" not in item:
                                    continue
                                sym = item["symbol"]
                                # Fingerprint based on price, server_prediction_time, and horizons
                                fp = f"{item.get('current_price')}_{item.get('server_prediction_time')}_{item.get('overall_score')}"
                                if self._last_leaderboard_fingerprints.get(sym) != fp:
                                    self._last_leaderboard_fingerprints[sym] = fp
                                    updated_assets.append(item)

                            if updated_assets and self.active_connections:
                                if len(updated_assets) <= 5:
                                    # Send granular per-asset deltas for smooth UI row updates
                                    for asset in updated_assets:
                                        await self.broadcast({
                                            "type": "asset_update",
                                            "symbol": asset.get("symbol"),
                                            "data": asset
                                        })
                                else:
                                    # Batch update
                                    await self.broadcast({
                                        "type": "batch_assets_update",
                                        "count": len(updated_assets),
                                        "data": updated_assets
                                    })

                            # C. Check and broadcast top round signals
                            top_signals = data.get("top_round_signals", [])
                            signals_by_h = data.get("signals_by_horizon", {})
                            if self.active_connections:
                                await self.broadcast({
                                    "type": "signals_sync",
                                    "timestamp": data.get("timestamp"),
                                    "top_signals": top_signals,
                                    "signals_by_horizon": signals_by_h
                                })

                        except Exception as e:
                            logger.error(f"[WS Watcher Read Error] {e}")

                await asyncio.sleep(0.15)  # 150ms micro-polling loop for sub-second push latency
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WS Watcher Loop Error] {e}")
                await asyncio.sleep(1.0)

ws_manager = WebSocketManager()
