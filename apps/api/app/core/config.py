from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Healthcare AI Desk"
    app_env: str = "development"
    app_debug: bool = True
    app_secret_key: str = "development-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    cors_origins: str = "http://localhost:5173"
    database_url: str = "mysql+pymysql://had_app:password@mysql:3306/healthcare_ai_desk"
    redis_url: str = "redis://localhost:6379/0"
    conversation_encryption_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("mysql+pymysql://"):
            raise ValueError("DATABASE_URL must start with mysql+pymysql://")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        if not value.startswith("redis://"):
            raise ValueError("REDIS_URL must start with redis://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
