import pytest
from app.services.pricing import haversine_km, calculate_fare, estimate_fare


class TestHaversine:
    def test_same_point(self):
        assert haversine_km(12.97, 77.59, 12.97, 77.59) == 0.0

    def test_known_distance(self):
        # Bangalore to roughly 5km north
        dist = haversine_km(12.9716, 77.5946, 13.0166, 77.5946)
        assert 4.5 < dist < 5.5

    def test_symmetry(self):
        d1 = haversine_km(12.97, 77.59, 13.02, 77.64)
        d2 = haversine_km(13.02, 77.64, 12.97, 77.59)
        assert abs(d1 - d2) < 0.001


class TestFareCalculation:
    def test_standard_fare(self):
        fare = calculate_fare("standard", distance_km=5.0, duration_minutes=15.0, surge=1.0)
        # base 30 + 5*12 + 15*1.5 = 30+60+22.5 = 112.5
        assert fare == 112.5

    def test_surge_doubles_fare(self):
        fare_normal = calculate_fare("standard", 5.0, 15.0, 1.0)
        fare_surge = calculate_fare("standard", 5.0, 15.0, 2.0)
        assert abs(fare_surge - 2 * fare_normal) < 0.01

    def test_premium_higher_than_standard(self):
        fare_std = calculate_fare("standard", 10.0, 20.0, 1.0)
        fare_prem = calculate_fare("premium", 10.0, 20.0, 1.0)
        assert fare_prem > fare_std

    def test_zero_distance(self):
        fare = calculate_fare("standard", 0.0, 0.0, 1.0)
        assert fare == 30.0  # just base fare

    def test_xl_tier(self):
        fare = calculate_fare("xl", 5.0, 10.0, 1.0)
        # base 80 + 5*18 + 10*2 = 80+90+20 = 190
        assert fare == 190.0


class TestEstimateFare:
    def test_returns_positive(self):
        fare = estimate_fare("standard", 12.97, 77.59, 13.02, 77.64, 1.0)
        assert fare > 0

    def test_surge_increases_estimate(self):
        fare1 = estimate_fare("standard", 12.97, 77.59, 13.02, 77.64, 1.0)
        fare2 = estimate_fare("standard", 12.97, 77.59, 13.02, 77.64, 1.5)
        assert fare2 > fare1
