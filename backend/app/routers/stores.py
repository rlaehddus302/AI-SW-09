from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.demo import DEMO_STORE_ID
from app.models import Store
from app.routers.utils import get_store_or_404
from app.schemas.store import StoreCreate, StoreRead, StoreUpdate

router = APIRouter(prefix="/stores", tags=["stores"])


@router.post("", response_model=StoreRead, status_code=status.HTTP_201_CREATED)
def create_store(payload: StoreCreate, db: Session = Depends(get_db)) -> Store:
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


@router.get("/{store_id}", response_model=StoreRead)
def read_store(store_id: int, db: Session = Depends(get_db)) -> Store:
    return get_store_or_404(db, store_id)


@router.put("/{store_id}", response_model=StoreRead)
def update_store(store_id: int, payload: StoreUpdate, db: Session = Depends(get_db)) -> Store:
    store = get_store_or_404(db, store_id)
    for field, value in payload.model_dump().items():
        setattr(store, field, value)
    db.commit()
    db.refresh(store)
    return store
