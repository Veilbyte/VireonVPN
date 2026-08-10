from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VIREON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+aiosqlite:///./vireon.db"
    public_base_url: str = "http://localhost:8000"

    telegram_bot_token: str | None = None
    telegram_bot_username: str | None = None
    support_url: str | None = None

    jwt_secret: str = "change-me-in-production"
    bootstrap_owner_username: str | None = None
    bootstrap_owner_password: str | None = None

    trial_days: int = 3
    trial_device_limit: int = 1
    payment_mode: Literal["mock", "disabled"] = "mock"

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.environment == "production" and self.jwt_secret == "change-me-in-production":
            raise ValueError("VIREON_JWT_SECRET must be changed in production")
        if self.trial_days < 1:
            raise ValueError("VIREON_TRIAL_DAYS must be positive")
        if self.trial_device_limit < 1:
            raise ValueError("VIREON_TRIAL_DEVICE_LIMIT must be positive")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
