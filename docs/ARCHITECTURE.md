# GoComet Ride Hailing — Architecture Documentation

## High Level Design (HLD)

### System Overview

A multi-tenant, multi-region ride-hailing platform supporting:
- ~100,000 concurrent drivers
- ~10,000 ride requests/minute
- ~200,000 driver location updates/second

---

### Architecture Diagram

```
Clients (Rider App / Driver App / Web UI)
          │
          ▼
    [Load Balancer]  ─── SSL Termination, Rate Limiting
          │
          ▼
   [FastAPI Instances]  ◄─── Stateless, horizontally scalable
    ┌─────┴──────┐
    │            │
    ▼            ▼
[Postgres]    [Redis]
 (Neon.tech)  (Upstash)
 Primary DB   Cache + Location
              + Idempotency
              + Demand counters
```

### Key Design Decisions

1. **Stateless API servers**: All state lives in Postgres/Redis, allowing any instance to serve any request. Scales horizontally behind a load balancer.

2. **Async background matching**: `POST /v1/rides` returns immediately (< 50ms). Driver matching runs in a background task, updating ride status. Clients poll `GET /v1/rides/{id}` every 2 seconds.

3. **Redis for hot data**: Driver locations (30s TTL), ride status cache (5s TTL), idempotency keys (24h TTL), demand counters for surge (5min TTL). Reduces DB reads by ~70%.

4. **Region-local writes**: Writes go to the nearest Postgres primary. No blocking on cross-region replication. Eventual consistency for reads across regions is acceptable for this use case.

---

## Low Level Design (LLD)

### Database Schema

```sql
drivers    — id, name, phone, tier, status, lat, lng, last_update
riders     — id, name, phone, email
rides      — id, rider_id, driver_id, pickup/dest coords, tier, status,
             surge_multiplier, estimated_fare, final_fare, idempotency_key
trips      — id, ride_id, started_at, paused_at, ended_at, distance_km,
             duration_minutes, fare
payments   — id, ride_id, rider_id, amount, method, status, psp_ref, idempotency_key
```

### Ride State Machine

```
requested → searching → matched → accepted → in_progress → completed
                                                 │
                                               paused (resumes to in_progress)
                                                 
Any state → cancelled (timeout / no drivers / explicit cancel)
```

### Driver Matching Algorithm

1. Query Postgres for nearest `available` driver of the correct `tier` within 5km using Haversine SQL:
   ```sql
   ORDER BY (6371 * acos(cos(radians(pickup_lat)) * cos(radians(lat)) * ...)) ASC
   ```
2. If no driver found, double the radius (up to 20km), retry once.
3. On match, use `SELECT FOR UPDATE` transaction to atomically:
   - Lock the driver row
   - Verify still `available`
   - Set driver → `on_trip`
   - Set ride → `matched`
4. Invalidate Redis cache for the ride.

### Surge Pricing

- Grid-based: each ~1.1km cell tracked with a demand counter in Redis
- Counter increments on each ride request, expires in 5 minutes
- Surge tiers: 1x (< 5 requests), 1.2x, 1.5x, 1.8x, 2.0x (40+ requests)

### Fare Calculation

```
fare = (base_fare[tier] + rate_per_km[tier] * distance + rate_per_min[tier] * duration) * surge
```

| Tier     | Base | /km  | /min |
|----------|------|------|------|
| standard | ₹30  | ₹12  | ₹1.5 |
| premium  | ₹60  | ₹20  | ₹2.5 |
| xl       | ₹80  | ₹18  | ₹2.0 |

### Idempotency

Both `POST /v1/rides` and `POST /v1/payments` accept an `idempotency_key`. On duplicate requests:
- Redis is checked first (O(1))
- If found, return the cached response
- If not, execute and cache the result for 24 hours
- DB has a `UNIQUE` constraint on `idempotency_key` as a safety net

### Concurrency & Atomicity

- Driver assignment uses `SELECT FOR UPDATE` inside a Postgres transaction to prevent double-booking
- All state transitions use atomic `UPDATE ... WHERE id = $1 AND status = 'expected_status'`
- Connection pool (5–20 connections per instance) managed by asyncpg

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/riders` | Register a rider |
| POST | `/v1/drivers` | Register a driver |
| PATCH | `/v1/drivers/{id}/status` | Go online/offline |
| POST | `/v1/drivers/{id}/location` | Update location (1-2/sec) |
| POST | `/v1/drivers/{id}/accept` | Accept a matched ride |
| POST | `/v1/rides` | Create ride request |
| GET | `/v1/rides/{id}` | Get ride status |
| POST | `/v1/trips/{id}/start` | Start a trip |
| POST | `/v1/trips/{id}/pause` | Pause a trip |
| POST | `/v1/trips/{id}/end` | End trip + calculate fare |
| GET | `/v1/trips/{id}` | Get trip details |
| POST | `/v1/payments` | Trigger payment |
| GET | `/v1/payments/{ride_id}` | Get payment status |

---

## Scalability Analysis

### Location Updates (200k/sec target)

- At 100k drivers × 2 updates/sec = 200k writes/sec
- Each update: 1 DB write + 1 Redis write
- **Solution**: Use Redis as write buffer; batch-flush to Postgres every 500ms using a background worker (not yet implemented; stub in place)
- Neon.tech serverless Postgres auto-scales; Upstash Redis handles millions of ops/sec

### Ride Requests (10k/min)

- ~167 req/sec — well within FastAPI + asyncio + asyncpg capacity
- Idempotency keys prevent double-processing
- Background matching decouples request latency from matching latency

### Driver Matching (< 1s p95)

- Geospatial SQL query with `INDEX ON (latitude, longitude)`
- Redis-cached driver locations for "hot" lookups
- In production: use a geospatial index (PostGIS or Redis GEOSEARCH) for O(log n) lookups

---

## Monitoring (New Relic)

1. Install agent: `pip install newrelic`
2. Generate config: `newrelic-admin generate-config LICENSE_KEY newrelic.ini`
3. Run app: `NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program uvicorn app.main:app`

**Key metrics to track:**
- API response time per endpoint (target: p95 < 200ms)
- DB query time (alert if > 100ms)
- Redis hit rate (target > 80%)
- Error rate per endpoint (alert if > 1%)
- `/v1/drivers/{id}/location` throughput (should handle 200k/sec in aggregate)

---

## Setup Instructions

```bash
# 1. Clone and install
git clone <repo>
cd gocomet-ride
pip install -r requirements.txt

# 2. Configure env
cp .env.example .env
# Fill in DATABASE_URL (Neon.tech) and REDIS_URL (Upstash)

# 3. Run
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 4. Open http://localhost:8000 for the UI
# 5. API docs at http://localhost:8000/docs

# 6. Run tests
pytest tests/ -v
```

---

## Edge Cases Handled

- **Driver disappears after match**: `SELECT FOR UPDATE` detects stale state; retry with next nearest driver
- **Duplicate ride requests**: Idempotency key returns same response
- **Payment retries**: Idempotency key on payments prevents double charging
- **No drivers available**: Ride auto-cancelled after exhausting 20km radius search
- **Concurrency**: All critical writes use Postgres transactions with row-level locking
- **Cache staleness**: 5s TTL on ride status; invalidated on every write
