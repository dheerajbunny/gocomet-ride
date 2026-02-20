import math
import asyncio
from datetime import datetime


async def _get_redis():
    from app.core.database import get_redis
    return await get_redis()

# Base fares per tier (INR)
BASE_FARE = {"standard": 30, "premium": 60, "xl": 80}
RATE_PER_KM = {"standard": 12, "premium": 20, "xl": 18}
RATE_PER_MIN = {"standard": 1.5, "premium": 2.5, "xl": 2.0}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate straight-line distance in km between two coordinates."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def get_surge_multiplier(pickup_lat: float, pickup_lng: float) -> float:
    """
    Dynamic surge pricing based on demand in grid cell.
    Grid cell = rounded to 2 decimal places (~1.1km resolution).
    """
    redis = await _get_redis()
    cell = f"{round(pickup_lat, 2)}:{round(pickup_lng, 2)}"
    key = f"demand:{cell}"

    # Increment demand counter with 5-min expiry
    count = await redis.incr(key)
    await redis.expire(key, 300)

    # Surge tiers
    if count < 5:
        return 1.0
    elif count < 10:
        return 1.2
    elif count < 20:
        return 1.5
    elif count < 40:
        return 1.8
    else:
        return 2.0


def calculate_fare(tier: str, distance_km: float, duration_minutes: float, surge: float) -> float:
    """Calculate trip fare."""
    fare = (
        BASE_FARE.get(tier, 30)
        + RATE_PER_KM.get(tier, 12) * distance_km
        + RATE_PER_MIN.get(tier, 1.5) * duration_minutes
    )
    return round(fare * surge, 2)


def estimate_fare(tier: str, pickup_lat: float, pickup_lng: float,
                  dest_lat: float, dest_lng: float, surge: float) -> float:
    """Estimate fare before trip starts."""
    dist = haversine_km(pickup_lat, pickup_lng, dest_lat, dest_lng)
    # Estimate ~30 km/h average speed
    duration = (dist / 30) * 60
    return calculate_fare(tier, dist, duration, surge)
