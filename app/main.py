import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.services.db_sync import migrate_files_to_db, init_db
from app.services.websocket_manager import ws_manager
from app.routers import signals_router, forecast_router, portfolio_router, health_router, models_router, websocket_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database schema & run initial migration from CSV/JSON asynchronously
    print("[BACKEND ⚡] Starting Quantitative Crypto FastAPI Backend...")
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)
    watcher_task = asyncio.create_task(ws_manager.start_background_watcher(settings.EXPORT_DIR))
    try:
        init_db()
    except Exception as e:
        print(f"[BACKEND ⚠️] init_db notice: {e}")
    try:
        import threading
        threading.Thread(target=migrate_files_to_db, daemon=True).start()
    except Exception as e:
        print(f"[BACKEND ⚠️] migrate_files_to_db notice: {e}")
    yield
    print("[BACKEND 🛑] Shutting down Quantitative Crypto Backend...")
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass

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

# Include API Routers
app.include_router(signals_router)
app.include_router(forecast_router)
app.include_router(portfolio_router)
app.include_router(health_router)
app.include_router(models_router)
app.include_router(websocket_router)

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
