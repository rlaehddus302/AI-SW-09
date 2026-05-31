from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


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
    cors_origins: str = Field(default="http://localhost:5173", validation_alias="CORS_ORIGINS")

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
