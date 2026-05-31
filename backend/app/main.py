from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import Review, Store  # noqa: F401 - imported so metadata includes all tables.
from app.routers import analysis, reviews, stores
from app.seed.seeder import seed_database, seed_rag_if_enabled
from app.websocket import manager

logger = logging.getLogger(__name__)


async def seed_rag_after_startup(store_id: int) -> None:
    """헬스체크가 외부 AI 지연에 막히지 않도록 RAG 시드를 서버 시작 후 비동기로 실행합니다."""
    try:
        await asyncio.to_thread(lambda: asyncio.run(seed_rag_if_enabled(store_id)))
    except Exception:
        logger.exception("RAG seed failed after startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """스키마 초기화, 데모 데이터 시드, 비동기 RAG 시드 예약까지 담당하는 FastAPI lifespan입니다."""
    settings = get_settings()
    seeded_store_id: Optional[int] = None
    if settings.reset_database_on_startup:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    elif settings.create_tables_on_startup:
        Base.metadata.create_all(bind=engine)
    if settings.seed_on_startup:
        with SessionLocal() as db:
            store = seed_database(db)
            seeded_store_id = store.id
    if seeded_store_id is not None:
        # live 임베딩 API 호출 지연/실패가 서버 준비 상태를 막지 않도록 분리합니다.
        asyncio.create_task(seed_rag_after_startup(seeded_store_id))
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router, prefix=settings.api_v1_prefix)
app.include_router(stores.router, prefix=settings.api_v1_prefix)
app.include_router(reviews.router, prefix=settings.api_v1_prefix)


@app.get("/health")
def health_check() -> dict[str, str]:
    """로컬 실행과 테스트에서 서버 준비 상태를 확인하는 가벼운 엔드포인트입니다."""
    return {"status": "ok"}


@app.websocket("/ws/{store_id}")
async def websocket_endpoint(websocket: WebSocket, store_id: int) -> None:
    """특정 가게의 작업 진행률 브로드캐스트 채널에 클라이언트를 연결합니다."""
    await manager.connect(store_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(store_id, websocket)
