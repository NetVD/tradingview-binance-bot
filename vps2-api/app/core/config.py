from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "staging", "production"] = "development"
    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    log_level: str = "info"

    database_url: str
    redis_url: str

    supabase_url: HttpUrl
    supabase_jwt_jwks_url: HttpUrl
    supabase_jwt_issuer: str
    supabase_jwt_audience: str = "authenticated"
    supabase_service_key: str

    notify_fn_url: HttpUrl

    vps1_base_url: HttpUrl
    service_token: str = Field(min_length=32)

    rate_limit_per_minute: int = 100
    allowed_origins: str = ""

    sentry_dsn: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
