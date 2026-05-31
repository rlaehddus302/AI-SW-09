from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """모든 SQLAlchemy ORM 모델이 상속하는 기준 클래스입니다."""
    pass


def _engine_kwargs(database_url: str) -> dict:
    """SQLite 테스트와 MySQL 런타임에 맞는 엔진 옵션을 선택합니다."""
    if database_url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if database_url.endswith(":memory:") or database_url == "sqlite://":
            kwargs["poolclass"] = StaticPool
        return kwargs
    return {"pool_pre_ping": True}


settings = get_settings()
engine = create_engine(settings.database_url, future=True, **_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator:
    """요청 단위 DB 세션을 제공하고 사용 후 항상 닫습니다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
