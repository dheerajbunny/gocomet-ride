from fastapi import APIRouter, HTTPException
from app.core.database import get_db_pool
from app.schemas.schemas import RiderCreate

router = APIRouter(prefix="/v1/riders", tags=["Riders"])


@router.post("", status_code=201)
async def create_rider(payload: RiderCreate):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO riders (name, phone, email)
            VALUES ($1, $2, $3)
            ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
            RETURNING *
        """, payload.name, payload.phone, payload.email)
    return dict(row)


@router.get("/{rider_id}")
async def get_rider(rider_id: str):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM riders WHERE id = $1", rider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rider not found")
    return dict(row)
