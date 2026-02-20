from fastapi import APIRouter, HTTPException
from app.core.database import get_db_pool, get_redis
from app.schemas.schemas import DriverCreate, DriverLocationUpdate, DriverAcceptRide
from app.services.matching import update_driver_location_cache
import json

router = APIRouter(prefix="/v1/drivers", tags=["Drivers"])


@router.post("", status_code=201)
async def create_driver(payload: DriverCreate):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO drivers (name, phone, tier)
            VALUES ($1, $2, $3)
            ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
            RETURNING *
        """, payload.name, payload.phone, payload.tier)
    return dict(row)


@router.get("/{driver_id}")
async def get_driver(driver_id: str):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM drivers WHERE id = $1", driver_id)
    if not row:
        raise HTTPException(status_code=404, detail="Driver not found")
    return dict(row)


@router.post("/{driver_id}/location", status_code=200)
async def update_location(driver_id: str, payload: DriverLocationUpdate):
    """
    High-frequency endpoint (~2/sec per driver).
    Writes to DB and caches in Redis. Uses upsert for efficiency.
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE drivers
            SET latitude = $1, longitude = $2, last_location_update = NOW()
            WHERE id = $3
            RETURNING id, status, tier
        """, payload.latitude, payload.longitude, driver_id)

    if not row:
        raise HTTPException(status_code=404, detail="Driver not found")

    # Update Redis cache
    await update_driver_location_cache(
        driver_id, payload.latitude, payload.longitude,
        row["tier"], row["status"]
    )

    return {"status": "ok", "driver_id": driver_id}


@router.post("/{driver_id}/accept", status_code=200)
async def accept_ride(driver_id: str, payload: DriverAcceptRide):
    """
    Driver accepts a matched ride — transitions ride to 'accepted'
    and creates a trip record atomically.
    """
    pool = await get_db_pool()
    redis = await get_redis()

    async with pool.acquire() as conn:
        async with conn.transaction():
            ride = await conn.fetchrow(
                "SELECT * FROM rides WHERE id = $1 AND driver_id = $2 FOR UPDATE",
                payload.ride_id, driver_id
            )
            if not ride:
                raise HTTPException(status_code=404, detail="Ride not found or not assigned to you")
            if ride["status"] not in ("matched",):
                raise HTTPException(status_code=409, detail=f"Cannot accept ride in '{ride['status']}' state")

            await conn.execute(
                "UPDATE rides SET status = 'accepted', updated_at = NOW() WHERE id = $1",
                payload.ride_id
            )
            trip = await conn.fetchrow("""
                INSERT INTO trips (ride_id, started_at)
                VALUES ($1, NOW())
                RETURNING *
            """, payload.ride_id)

    await redis.delete(f"ride:{payload.ride_id}")
    return {"status": "accepted", "trip_id": str(trip["id"]), "ride_id": payload.ride_id}


@router.patch("/{driver_id}/status", status_code=200)
async def update_driver_status(driver_id: str, body: dict):
    """Set driver online/offline."""
    status = body.get("status")
    if status not in ("available", "offline"):
        raise HTTPException(status_code=400, detail="Status must be 'available' or 'offline'")

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE drivers SET status = $1 WHERE id = $2 RETURNING id, status",
            status, driver_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Driver not found")

    return {"driver_id": driver_id, "status": status}
