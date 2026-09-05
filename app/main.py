from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.services.db_sync import migrate_files_to_db
from app.routers import signals_router, forecast_router, portfolio_router, health_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database schema & run initial migration from CSV/JSON
    print("[BACKEND ⚡] Starting Quantitative Crypto FastAPI Backend...")
    migrate_files_to_db()
    yield
    print("[BACKEND 🛑] Shutting down Quantitative Crypto Backend...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

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

@app.get("/")
def root():
    return {
        "message": "Quantitative Crypto Trading Engine API is Running",
        "docs": "/api/docs",
        "status_endpoint": "/api/status",
        "kpi_endpoint": "/api/signals/kpi",
    }
