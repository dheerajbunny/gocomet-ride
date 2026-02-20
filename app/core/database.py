import asyncpg
import redis.asyncio as aioredis
from app.core.config import get_settings

settings = get_settings()

# Global connection pools
db_pool: asyncpg.Pool = None
redis_client: aioredis.Redis = None


async def get_db_pool() -> asyncpg.Pool:
    return db_pool


async def get_redis() -> aioredis.Redis:
    return redis_client


async def init_db(pool: asyncpg.Pool):
    """Create all tables if they don't exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS drivers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                tier TEXT DEFAULT 'standard' CHECK (tier IN ('standard', 'premium', 'xl')),
                status TEXT DEFAULT 'offline' CHECK (status IN ('offline', 'available', 'on_trip')),
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                last_location_update TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS riders (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                email TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS rides (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                rider_id UUID REFERENCES riders(id),
                driver_id UUID REFERENCES drivers(id),
                pickup_lat DOUBLE PRECISION NOT NULL,
                pickup_lng DOUBLE PRECISION NOT NULL,
                dest_lat DOUBLE PRECISION NOT NULL,
                dest_lng DOUBLE PRECISION NOT NULL,
                pickup_address TEXT,
                dest_address TEXT,
                tier TEXT DEFAULT 'standard',
                payment_method TEXT DEFAULT 'card',
                status TEXT DEFAULT 'requested' CHECK (status IN (
                    'requested', 'searching', 'matched', 'accepted',
                    'in_progress', 'paused', 'completed', 'cancelled'
                )),
                surge_multiplier DOUBLE PRECISION DEFAULT 1.0,
                estimated_fare DOUBLE PRECISION,
                final_fare DOUBLE PRECISION,
                idempotency_key TEXT UNIQUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS trips (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ride_id UUID UNIQUE REFERENCES rides(id),
                started_at TIMESTAMPTZ,
                paused_at TIMESTAMPTZ,
                ended_at TIMESTAMPTZ,
                distance_km DOUBLE PRECISION DEFAULT 0,
                duration_minutes DOUBLE PRECISION DEFAULT 0,
                fare DOUBLE PRECISION,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS payments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ride_id UUID REFERENCES rides(id),
                rider_id UUID REFERENCES riders(id),
                amount DOUBLE PRECISION NOT NULL,
                method TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'success', 'failed')),
                psp_ref TEXT,
                idempotency_key TEXT UNIQUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_rides_status ON rides(status);
            CREATE INDEX IF NOT EXISTS idx_rides_rider_id ON rides(rider_id);
            CREATE INDEX IF NOT EXISTS idx_drivers_status ON drivers(status);
            CREATE INDEX IF NOT EXISTS idx_drivers_location ON drivers(latitude, longitude);
            CREATE INDEX IF NOT EXISTS idx_payments_ride_id ON payments(ride_id);
        """)


async def connect():
    global db_pool, redis_client
    raw_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    db_pool = await asyncpg.create_pool(raw_url, min_size=5, max_size=20)
    await init_db(db_pool)
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)


async def disconnect():
    global db_pool, redis_client
    if db_pool:
        await db_pool.close()
    if redis_client:
        await redis_client.close()
