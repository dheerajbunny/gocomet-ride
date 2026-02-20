from fastapi import APIRouter, HTTPException
from app.core.database import get_db_pool, get_redis
from app.schemas.schemas import TripEndRequest
from app.services.pricing import calculate_fare

router = APIRouter(prefix="/v1/trips", tags=["Trips"])


@router.post("/{trip_id}/start", status_code=200)
async def start_trip(trip_id: str):
    pool = await get_db_pool()
    redis = await get_redis()

    async with pool.acquire() as conn:
        async with conn.transaction():
            trip = await conn.fetchrow(
                "SELECT * FROM trips WHERE id = $1 FOR UPDATE", trip_id
            )
            if not trip:
                raise HTTPException(status_code=404, detail="Trip not found")

            ride = await conn.fetchrow(
                "SELECT * FROM rides WHERE id = $1", str(trip["ride_id"])
            )
            if ride["status"] not in ("accepted",):
                raise HTTPException(status_code=409, detail=f"Cannot start trip in ride state '{ride['status']}'")

            await conn.execute(
                "UPDATE trips SET started_at = NOW() WHERE id = $1", trip_id
            )
            await conn.execute(
                "UPDATE rides SET status = 'in_progress', updated_at = NOW() WHERE id = $1",
                str(trip["ride_id"])
            )

    await redis.delete(f"ride:{str(trip['ride_id'])}")
    return {"status": "in_progress", "trip_id": trip_id}


@router.post("/{trip_id}/pause", status_code=200)
async def pause_trip(trip_id: str):
    pool = await get_db_pool()
    redis = await get_redis()

    async with pool.acquire() as conn:
        async with conn.transaction():
            trip = await conn.fetchrow("SELECT * FROM trips WHERE id = $1 FOR UPDATE", trip_id)
            if not trip:
                raise HTTPException(status_code=404, detail="Trip not found")

            await conn.execute("UPDATE trips SET paused_at = NOW() WHERE id = $1", trip_id)
            await conn.execute(
                "UPDATE rides SET status = 'paused', updated_at = NOW() WHERE id = $1",
                str(trip["ride_id"])
            )

    await redis.delete(f"ride:{str(trip['ride_id'])}")
    return {"status": "paused", "trip_id": trip_id}


@router.post("/{trip_id}/end", status_code=200)
async def end_trip(trip_id: str, payload: TripEndRequest):
    """
    End trip, calculate fare, update driver status.
    Atomic transaction to ensure consistency.
    """
    pool = await get_db_pool()
    redis = await get_redis()

    async with pool.acquire() as conn:
        async with conn.transaction():
            trip = await conn.fetchrow("SELECT * FROM trips WHERE id = $1 FOR UPDATE", trip_id)
            if not trip:
                raise HTTPException(status_code=404, detail="Trip not found")

            ride = await conn.fetchrow(
                "SELECT * FROM rides WHERE id = $1 FOR UPDATE", str(trip["ride_id"])
            )
            if ride["status"] not in ("in_progress", "paused"):
                raise HTTPException(status_code=409, detail=f"Cannot end trip in ride state '{ride['status']}'")

            fare = calculate_fare(
                ride["tier"], payload.distance_km,
                payload.duration_minutes, float(ride["surge_multiplier"])
            )

            await conn.execute("""
                UPDATE trips SET ended_at = NOW(), distance_km = $1,
                                 duration_minutes = $2, fare = $3
                WHERE id = $4
            """, payload.distance_km, payload.duration_minutes, fare, trip_id)

            await conn.execute("""
                UPDATE rides SET status = 'completed', final_fare = $1, updated_at = NOW()
                WHERE id = $2
            """, fare, str(trip["ride_id"]))

            # Free up driver
            await conn.execute(
                "UPDATE drivers SET status = 'available' WHERE id = $1",
                str(ride["driver_id"])
            )

    await redis.delete(f"ride:{str(trip['ride_id'])}")
    return {
        "status": "completed",
        "trip_id": trip_id,
        "fare": fare,
        "distance_km": payload.distance_km,
        "duration_minutes": payload.duration_minutes
    }


@router.get("/{trip_id}")
async def get_trip(trip_id: str):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM trips WHERE id = $1", trip_id)
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")
    return {k: str(v) if hasattr(v, 'hex') else v for k, v in dict(row).items()}
