from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.websocket_manager import ws_manager
import logging

logger = logging.getLogger("websocket_router")
router = APIRouter(tags=["WebSocket Stream"])

@router.websocket("/ws/live")
async def websocket_live_stream(websocket: WebSocket):
    """
    Real-Time WebSocket Stream for Multi-Horizon Matrix deltas, BTC Market Shield ticks,
    and Institutional Trade Signals.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep receiving client heartbeats or messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"[WS Exception] {e}")
        await ws_manager.disconnect(websocket)
