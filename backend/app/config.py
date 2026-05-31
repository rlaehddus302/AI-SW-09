from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Review Helper API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = Field(
        default="mysql+pymysql://root:password@localhost:3306/review_helper?charset=utf8mb4",
        validation_alias="DATABASE_URL",
    )
    create_tables_on_startup: bool = Field(default=True, validation_alias="CREATE_TABLES_ON_STARTUP")
    seed_on_startup: bool = Field(default=True, validation_alias="SEED_ON_STARTUP")
    seed_rag_on_startup: bool = Field(default=True, validation_alias="SEED_RAG_ON_STARTUP")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
