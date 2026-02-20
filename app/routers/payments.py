import uuid
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.core.database import get_db_pool, get_redis
from app.schemas.schemas import PaymentCreate
import json

router = APIRouter(prefix="/v1/payments", tags=["Payments"])


async def _process_payment(payment_id: str, ride_id: str, amount: float, method: str):
    """
    Simulate external PSP call (Stripe/Razorpay).
    In production, replace with actual PSP SDK call.
    """
    await asyncio.sleep(0.5)  # Simulate PSP latency

    pool = await get_db_pool()
    redis = await get_redis()

    # Simulate 95% success rate
    import random
    success = random.random() < 0.95
    psp_ref = f"psp_{uuid.uuid4().hex[:12]}" if success else None
    status = "success" if success else "failed"

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE payments SET status = $1, psp_ref = $2 WHERE id = $3
        """, status, psp_ref, payment_id)

    await redis.delete(f"payment:{ride_id}")


@router.post("", status_code=201)
async def create_payment(payload: PaymentCreate, background_tasks: BackgroundTasks):
    """
    Trigger payment for a completed ride. Idempotent.
    """
    pool = await get_db_pool()
    redis = await get_redis()

    # Idempotency check
    if payload.idempotency_key:
        cached = await redis.get(f"idem:pay:{payload.idempotency_key}")
        if cached:
            return json.loads(cached)

    # Get ride details
    async with pool.acquire() as conn:
        ride = await conn.fetchrow("SELECT * FROM rides WHERE id = $1", payload.ride_id)

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["status"] != "completed":
        raise HTTPException(status_code=409, detail="Ride must be completed before payment")

    amount = float(ride["final_fare"] or ride["estimated_fare"] or 0)

    async with pool.acquire() as conn:
        payment = await conn.fetchrow("""
            INSERT INTO payments (ride_id, rider_id, amount, method, idempotency_key)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
            RETURNING *
        """, payload.ride_id, str(ride["rider_id"]), amount,
            ride["payment_method"], payload.idempotency_key)

    result = {k: str(v) if hasattr(v, 'hex') else v for k, v in dict(payment).items()}

    if payload.idempotency_key:
        await redis.setex(f"idem:pay:{payload.idempotency_key}", 86400, json.dumps(result, default=str))

    # Async PSP call
    background_tasks.add_task(
        _process_payment, str(payment["id"]), payload.ride_id, amount, ride["payment_method"]
    )

    return result


@router.get("/{ride_id}")
async def get_payment_status(ride_id: str):
    """Get payment status for a ride."""
    redis = await get_redis()
    cached = await redis.get(f"payment:{ride_id}")
    if cached:
        return json.loads(cached)

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM payments WHERE ride_id = $1 ORDER BY created_at DESC LIMIT 1", ride_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="No payment found for this ride")

    result = {k: str(v) if hasattr(v, 'hex') else v for k, v in dict(row).items()}
    await redis.setex(f"payment:{ride_id}", 10, json.dumps(result, default=str))
    return result
