from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost/ridedb"
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "dev-secret-key"
    app_env: str = "development"
    new_relic_license_key: str = ""
    new_relic_app_name: str = "GoComet-RideHailing"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()
