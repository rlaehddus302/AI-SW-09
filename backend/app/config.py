from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """루트와 백엔드 env 파일에서 읽어오는 애플리케이션 설정입니다."""
    app_name: str = "Review Helper API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = Field(
        default="mysql+pymysql://root:password@localhost:3306/review_helper?charset=utf8mb4",
        validation_alias="DATABASE_URL",
    )
    create_tables_on_startup: bool = Field(default=True, validation_alias="CREATE_TABLES_ON_STARTUP")
    reset_database_on_startup: bool = Field(default=True, validation_alias="RESET_DATABASE_ON_STARTUP")
    seed_on_startup: bool = Field(default=True, validation_alias="SEED_ON_STARTUP")
    seed_rag_on_startup: bool = Field(default=True, validation_alias="SEED_RAG_ON_STARTUP")
    cors_origins: str = Field(default="http://localhost:5173", validation_alias="CORS_ORIGINS")
    # AI_MODE는 의도적으로 명시값만 허용합니다:
    # - mock: 외부 호출 없는 deterministic 로컬 AI
    # - live: 실제 Upstage API 호출, UPSTAGE_API_KEY 필수
    ai_mode: str = Field(default="mock", validation_alias="AI_MODE")
    upstage_api_key: Optional[str] = Field(default=None, validation_alias="UPSTAGE_API_KEY")
    upstage_base_url: str = Field(default="https://api.upstage.ai/v1", validation_alias="UPSTAGE_BASE_URL")
    upstage_chat_model: str = Field(
        default="solar-pro3",
        validation_alias=AliasChoices("UPSTAGE_CHAT_MODEL", "UPSTAGE_SOLAR_MODEL"),
    )
    upstage_embedding_url: str = Field(
        default="https://api.upstage.ai/v1/solar/embeddings",
        validation_alias="UPSTAGE_EMBEDDING_URL",
    )
    upstage_embedding_model: str = Field(
        default="solar-embedding-1-large-query",
        validation_alias="UPSTAGE_EMBEDDING_MODEL",
    )
    upstage_embedding_query_model: Optional[str] = Field(
        default=None,
        validation_alias="UPSTAGE_EMBEDDING_QUERY_MODEL",
    )
    upstage_embedding_passage_model: Optional[str] = Field(
        default=None,
        validation_alias="UPSTAGE_EMBEDDING_PASSAGE_MODEL",
    )
    ai_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("AI_TIMEOUT_SECONDS", "UPSTAGE_TIMEOUT_SECONDS"),
    )
    chroma_persist_dir: str = Field(
        default=".chroma/review_helper",
        validation_alias=AliasChoices("CHROMA_PERSIST_DIR", "CHROMA_PERSIST_PATH"),
    )
    rag_collection_name: str = Field(
        default="review_reply_examples",
        validation_alias=AliasChoices("RAG_COLLECTION_NAME", "CHROMA_COLLECTION"),
    )

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """쉼표로 구분된 CORS_ORIGINS 값을 FastAPI가 받는 리스트 형태로 변환합니다."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """설정 객체를 프로세스 안에서 재사용하도록 캐시해서 반환합니다."""
    return Settings()
