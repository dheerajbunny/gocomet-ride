import newrelic.agent
newrelic.agent.initialize('newrelic.ini')
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import time
import logging

from app.core.database import connect, disconnect
from app.routers import rides, drivers, trips, payments, riders

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — connecting to DB and Redis...")
    await connect()
    logger.info("Connected successfully.")
    yield
    logger.info("Shutting down...")
    await disconnect()


app = FastAPI(
    title="GoComet Ride Hailing API",
    description="Multi-tenant ride hailing platform with real-time matching, surge pricing, and payments.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Latency tracking middleware ──────────────────────────────────────────────
@app.middleware("http")
async def add_latency_header(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-Ms"] = f"{latency_ms:.2f}"
    if latency_ms > 500:
        logger.warning(f"SLOW REQUEST: {request.method} {request.url.path} — {latency_ms:.0f}ms")
    return response


# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(rides.router)
app.include_router(drivers.router)
app.include_router(trips.router)
app.include_router(payments.router)
app.include_router(riders.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "GoComet Ride Hailing"}


# Serve frontend
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse("frontend/index.html")
