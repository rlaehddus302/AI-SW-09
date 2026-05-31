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
    try:
        await asyncio.to_thread(lambda: asyncio.run(seed_rag_if_enabled(store_id)))
    except Exception:
        logger.exception("RAG seed failed after startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        # RAG seeding may call the live embedding API. Keep server readiness independent
        # from external AI latency or failures.
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
    return {"status": "ok"}


@app.websocket("/ws/{store_id}")
async def websocket_endpoint(websocket: WebSocket, store_id: int) -> None:
    await manager.connect(store_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(store_id, websocket)
