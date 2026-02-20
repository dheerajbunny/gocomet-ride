import uuid
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.core.database import get_db_pool, get_redis
from app.schemas.schemas import RideCreate, RideResponse
from app.services.pricing import get_surge_multiplier, estimate_fare
from app.services.matching import find_nearest_driver, assign_driver_to_ride
import json

router = APIRouter(prefix="/v1/rides", tags=["Rides"])


async def _search_and_match(ride_id: str, pickup_lat: float, pickup_lng: float, tier: str):
    """Background task: find driver and assign."""
    pool = await get_db_pool()
    redis = await get_redis()

    # Update ride to searching
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE rides SET status = 'searching', updated_at = NOW() WHERE id = $1", ride_id
        )

    driver = await find_nearest_driver(pickup_lat, pickup_lng, tier)

    if not driver:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE rides SET status = 'cancelled', updated_at = NOW() WHERE id = $1", ride_id
            )
        await redis.delete(f"ride:{ride_id}")
        return

    try:
        await assign_driver_to_ride(ride_id, str(driver["id"]))
    except Exception:
        # Driver grabbed by someone else, retry once
        await asyncio.sleep(0.5)
        driver2 = await find_nearest_driver(pickup_lat, pickup_lng, tier)
        if driver2:
            await assign_driver_to_ride(ride_id, str(driver2["id"]))

    await redis.delete(f"ride:{ride_id}")


@router.post("", status_code=201)
async def create_ride(payload: RideCreate, background_tasks: BackgroundTasks):
    """
    Create a ride request. Idempotent via idempotency_key.
    Triggers background driver matching.
    """
    pool = await get_db_pool()
    redis = await get_redis()

    # Idempotency check
    if payload.idempotency_key:
        cached = await redis.get(f"idem:ride:{payload.idempotency_key}")
        if cached:
            return json.loads(cached)

    surge = await get_surge_multiplier(payload.pickup_lat, payload.pickup_lng)
    est_fare = estimate_fare(
        payload.tier, payload.pickup_lat, payload.pickup_lng,
        payload.dest_lat, payload.dest_lng, surge
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO rides (rider_id, pickup_lat, pickup_lng, dest_lat, dest_lng,
                               pickup_address, dest_address, tier, payment_method,
                               surge_multiplier, estimated_fare, idempotency_key)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
            RETURNING *
        """, payload.rider_id, payload.pickup_lat, payload.pickup_lng,
            payload.dest_lat, payload.dest_lng, payload.pickup_address,
            payload.dest_address, payload.tier, payload.payment_method,
            surge, est_fare, payload.idempotency_key)

    result = dict(row)
    result["id"] = str(result["id"])

    if payload.idempotency_key:
        await redis.setex(f"idem:ride:{payload.idempotency_key}", 86400, json.dumps(result, default=str))

    # Start matching in background (non-blocking)
    background_tasks.add_task(
        _search_and_match, result["id"], payload.pickup_lat, payload.pickup_lng, payload.tier
    )

    return result


@router.get("/{ride_id}")
async def get_ride(ride_id: str):
    """Get ride status. Cached in Redis for 5s to reduce DB load."""
    redis = await get_redis()

    cached = await redis.get(f"ride:{ride_id}")
    if cached:
        return json.loads(cached)

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT r.*, d.name as driver_name, d.phone as driver_phone,
                   d.latitude as driver_lat, d.longitude as driver_lng
            FROM rides r
            LEFT JOIN drivers d ON r.driver_id = d.id
            WHERE r.id = $1
        """, ride_id)

    if not row:
        raise HTTPException(status_code=404, detail="Ride not found")

    result = {k: str(v) if hasattr(v, 'hex') else v for k, v in dict(row).items()}

    await redis.setex(f"ride:{ride_id}", 5, json.dumps(result, default=str))

    return result
