import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.services.db_sync import migrate_files_to_db, init_db
from app.services.websocket_manager import ws_manager
from app.routers import signals_router, forecast_router, portfolio_router, health_router, models_router, websocket_router, whatsapp_router, v16_router, fundamentals_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database schema & run initial migration from CSV/JSON asynchronously
    print("[BACKEND ⚡] Starting Quantitative Crypto FastAPI Backend...")
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)
    watcher_task = asyncio.create_task(ws_manager.start_background_watcher(settings.EXPORT_DIR))
    
    # Start decoupled sub-second WebSocket feed for zero-latency price ticks
    try:
        from app.database import is_test_environment
        if not is_test_environment() or os.environ.get("WS_TEST_CONNECT") == "1":
            from app.engine.scanner.websocket_feed import ws_feed_manager
            ws_feed_manager.start()
            print("[BACKEND ⚡] Global WebSocket Feed Manager active.")
        else:
            print("[BACKEND ℹ️] Test environment detected: Outbound WebSocket price stream deferred.")
    except Exception as e:
        print(f"[BACKEND ⚠️] WebSocket Feed Manager startup error: {e}")

    import threading
    def _bg_startup():
        try:
            init_db()
        except Exception as e:
            print(f"[BACKEND ⚠️] init_db notice: {e}")
        try:
            migrate_files_to_db()
        except Exception as e:
            print(f"[BACKEND ⚠️] migrate_files_to_db notice: {e}")

    threading.Thread(target=_bg_startup, daemon=True, name="db_startup_thread").start()
    yield
    print("[BACKEND 🛑] Shutting down Quantitative Crypto Backend...")
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass
    try:
        from app.database import is_test_environment
        if not is_test_environment() or os.environ.get("WS_TEST_CONNECT") == "1":
            from app.engine.scanner.websocket_feed import ws_feed_manager
            ws_feed_manager.stop()
            print("[BACKEND 🛑] Global WebSocket Feed Manager stopped.")
    except Exception as e:
        print(f"[BACKEND ⚠️] WebSocket Feed Manager stop error: {e}")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

# GZip Compression Middleware (Compresses ~1.5MB JSON down to ~65KB, reducing latency by 95%+)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS Configuration for Next.js Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows Next.js (http://localhost:3000) and any deployment domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enforce No-Cache on API Endpoints to prevent browser stale in-memory cache
@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, no-cache, no-store, must-revalidate, proxy-revalidate, max-age=0, s-maxage=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
        response.headers["Surrogate-Control"] = "no-store"
    return response

# Include API Routers
app.include_router(signals_router)
app.include_router(forecast_router)
app.include_router(portfolio_router)
app.include_router(health_router)
app.include_router(models_router)
app.include_router(websocket_router)
app.include_router(whatsapp_router)
app.include_router(v16_router)
app.include_router(fundamentals_router)


from app.services.signal_service import signal_service

@app.get("/api/prices")
def get_live_prices():
    """Direct real-time Binance prices endpoint for instant frontend ticker sync."""
    return signal_service.get_all_live_prices()

@app.get("/")
def root():
    return {
        "message": "Quantitative Crypto Trading Engine API is Running",
        "docs": "/api/docs",
        "status_endpoint": "/api/status",
        "prices_endpoint": "/api/prices",
        "kpi_endpoint": "/api/signals/kpi",
    }
