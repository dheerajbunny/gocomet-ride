import json
import asyncio
from typing import Optional
from app.core.database import get_db_pool, get_redis


async def update_driver_location_cache(driver_id: str, lat: float, lng: float, tier: str, status: str):
    """Cache driver location in Redis for fast geo-lookup."""
    redis = await get_redis()
    key = f"driver:loc:{driver_id}"
    data = {"lat": lat, "lng": lng, "tier": tier, "status": status}
    await redis.setex(key, 30, json.dumps(data))  # 30-second TTL


async def find_nearest_driver(pickup_lat: float, pickup_lng: float, tier: str, radius_km: float = 5.0) -> Optional[dict]:
    """
    Find nearest available driver using Postgres distance query.
    Uses the Haversine formula via SQL for accuracy.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, phone, latitude, longitude,
                   (6371 * acos(
                       cos(radians($1)) * cos(radians(latitude)) *
                       cos(radians(longitude) - radians($2)) +
                       sin(radians($1)) * sin(radians(latitude))
                   )) AS distance_km
            FROM drivers
            WHERE status = 'available'
              AND tier = $3
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
              AND (6371 * acos(
                      cos(radians($1)) * cos(radians(latitude)) *
                      cos(radians(longitude) - radians($2)) +
                      sin(radians($1)) * sin(radians(latitude))
                   )) < $4
            ORDER BY distance_km ASC
            LIMIT 1
        """, pickup_lat, pickup_lng, tier, radius_km)

        if row:
            return dict(row)

    # Fallback: expand radius
    if radius_km < 20:
        return await find_nearest_driver(pickup_lat, pickup_lng, tier, radius_km * 2)

    return None


async def assign_driver_to_ride(ride_id: str, driver_id: str):
    """Atomically assign a driver to a ride using a transaction."""
    pool = await get_db_pool()
    redis = await get_redis()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Lock the driver row to prevent double assignment
            driver = await conn.fetchrow(
                "SELECT id, status FROM drivers WHERE id = $1 FOR UPDATE", driver_id
            )
            if not driver or driver["status"] != "available":
                raise Exception("Driver no longer available")

            await conn.execute(
                "UPDATE drivers SET status = 'on_trip' WHERE id = $1", driver_id
            )
            await conn.execute(
                """UPDATE rides SET driver_id = $1, status = 'matched', updated_at = NOW()
                   WHERE id = $2""",
                driver_id, ride_id
            )

    # Invalidate cache
    await redis.delete(f"driver:loc:{driver_id}")
    await redis.delete(f"ride:{ride_id}")
