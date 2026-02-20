from pydantic import BaseModel, Field, validator
from typing import Optional
from uuid import UUID
from datetime import datetime


# ─── Driver Schemas ───────────────────────────────────────────────────────────

class DriverCreate(BaseModel):
    name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=10)
    tier: str = Field(default="standard")

    @validator("tier")
    def validate_tier(cls, v):
        if v not in ("standard", "premium", "xl"):
            raise ValueError("tier must be standard, premium, or xl")
        return v


class DriverLocationUpdate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class DriverAcceptRide(BaseModel):
    ride_id: str


class DriverResponse(BaseModel):
    id: UUID
    name: str
    phone: str
    tier: str
    status: str
    latitude: Optional[float]
    longitude: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Rider Schemas ────────────────────────────────────────────────────────────

class RiderCreate(BaseModel):
    name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=10)
    email: Optional[str] = None


# ─── Ride Schemas ─────────────────────────────────────────────────────────────

class RideCreate(BaseModel):
    rider_id: str
    pickup_lat: float = Field(..., ge=-90, le=90)
    pickup_lng: float = Field(..., ge=-180, le=180)
    dest_lat: float = Field(..., ge=-90, le=90)
    dest_lng: float = Field(..., ge=-180, le=180)
    pickup_address: Optional[str] = None
    dest_address: Optional[str] = None
    tier: str = Field(default="standard")
    payment_method: str = Field(default="card")
    idempotency_key: Optional[str] = None

    @validator("tier")
    def validate_tier(cls, v):
        if v not in ("standard", "premium", "xl"):
            raise ValueError("tier must be standard, premium, or xl")
        return v

    @validator("payment_method")
    def validate_payment(cls, v):
        if v not in ("card", "cash", "wallet"):
            raise ValueError("payment_method must be card, cash, or wallet")
        return v


class RideResponse(BaseModel):
    id: UUID
    rider_id: UUID
    driver_id: Optional[UUID]
    pickup_lat: float
    pickup_lng: float
    dest_lat: float
    dest_lng: float
    pickup_address: Optional[str]
    dest_address: Optional[str]
    tier: str
    payment_method: str
    status: str
    surge_multiplier: float
    estimated_fare: Optional[float]
    final_fare: Optional[float]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── Trip Schemas ─────────────────────────────────────────────────────────────

class TripEndRequest(BaseModel):
    distance_km: float = Field(..., ge=0)
    duration_minutes: float = Field(..., ge=0)


class TripResponse(BaseModel):
    id: UUID
    ride_id: UUID
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    distance_km: float
    duration_minutes: float
    fare: Optional[float]

    class Config:
        from_attributes = True


# ─── Payment Schemas ──────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    ride_id: str
    idempotency_key: Optional[str] = None


class PaymentResponse(BaseModel):
    id: UUID
    ride_id: UUID
    amount: float
    method: str
    status: str
    psp_ref: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
