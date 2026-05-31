from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.demo import DEMO_STORE_ID
from app.models import Store
from app.openapi_examples import (
    STORE_NOT_FOUND_RESPONSE,
    STORE_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)
from app.routers.utils import get_store_or_404
from app.schemas.store import StoreCreate, StoreRead, StoreUpdate

router = APIRouter(prefix="/stores", tags=["stores"])


@router.post(
    "",
    response_model=StoreRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: STORE_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
def create_store(payload: StoreCreate, db: Session = Depends(get_db)) -> Store:
    """로컬 MVP에서 사용하는 고정 데모 가게를 생성하거나 갱신합니다."""

    values = payload.model_dump()
    store = db.get(Store, DEMO_STORE_ID)
    if store is None:
        store = Store(id=DEMO_STORE_ID, **values)
        db.add(store)
    else:
        for field, value in values.items():
            setattr(store, field, value)
    db.commit()
    db.refresh(store)
    return store


@router.get(
    "/{store_id}",
    response_model=StoreRead,
    responses={
        status.HTTP_200_OK: STORE_RESPONSE,
        status.HTTP_404_NOT_FOUND: STORE_NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
def read_store(store_id: int, db: Session = Depends(get_db)) -> Store:
    """가게 1건을 반환하거나 공통 404 응답을 발생시킵니다."""

    return get_store_or_404(db, store_id)


@router.put(
    "/{store_id}",
    response_model=StoreRead,
    responses={
        status.HTTP_200_OK: STORE_RESPONSE,
        status.HTTP_404_NOT_FOUND: STORE_NOT_FOUND_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
def update_store(store_id: int, payload: StoreUpdate, db: Session = Depends(get_db)) -> Store:
    """데모 설정 화면에서 수정 가능한 가게 필드를 교체합니다."""

    store = get_store_or_404(db, store_id)
    for field, value in payload.model_dump().items():
        setattr(store, field, value)
    db.commit()
    db.refresh(store)
    return store
