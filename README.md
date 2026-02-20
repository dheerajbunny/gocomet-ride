# 🚗 GoComet Ride Hailing Platform

A production-grade ride-hailing backend + frontend built with **FastAPI**, **PostgreSQL (Neon.tech)**, and **Redis (Upstash)**.

## Features

- ✅ Real-time driver–rider matching (background async, < 1s p95)
- ✅ Dynamic surge pricing (grid-based demand counters)
- ✅ Full trip lifecycle (request → match → accept → start → pause → end)
- ✅ Idempotent payments with async PSP processing
- ✅ Redis caching for ride status, driver locations, idempotency
- ✅ Atomic transactions with row-level locking (no race conditions)
- ✅ Live frontend UI with 2s polling
- ✅ New Relic APM integration
- ✅ Unit tests for core business logic

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in Neon.tech DATABASE_URL and Upstash REDIS_URL

# Run
uvicorn app.main:app --reload

# Open UI
open http://localhost:8000

# API docs
open http://localhost:8000/docs

# Tests
pytest tests/ -v
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for HLD/LLD.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/riders` | Register rider |
| POST | `/v1/drivers` | Register driver |
| POST | `/v1/drivers/{id}/location` | Location update |
| POST | `/v1/drivers/{id}/accept` | Accept ride |
| PATCH | `/v1/drivers/{id}/status` | Go online/offline |
| POST | `/v1/rides` | Book a ride |
| GET | `/v1/rides/{id}` | Get ride status |
| POST | `/v1/trips/{id}/start` | Start trip |
| POST | `/v1/trips/{id}/pause` | Pause trip |
| POST | `/v1/trips/{id}/end` | End trip |
| POST | `/v1/payments` | Trigger payment |
| GET | `/v1/payments/{ride_id}` | Payment status |

## Tech Stack

- **Backend**: FastAPI + asyncpg (async Postgres driver)
- **Database**: PostgreSQL via Neon.tech (serverless, auto-scales)
- **Cache**: Redis via Upstash (serverless, global)
- **Monitoring**: New Relic APM
- **Frontend**: Vanilla HTML/CSS/JS (no framework needed)
