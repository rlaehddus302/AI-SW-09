import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_contract
from app.config import get_settings
from app.models import OrderType, Review, Store

SEED_DATA_PATH = Path(__file__).with_name("seed_data.json")


def load_seed_data(path: Path = SEED_DATA_PATH) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def seed_database(db: Session) -> Store:
    data = load_seed_data()
    store_payload = data["store"]
    store = db.scalar(select(Store).where(Store.store_name == store_payload["store_name"]))
    if store is None:
        store = Store(**store_payload)
        db.add(store)
        db.flush()

    existing_review_texts = set(
        db.scalars(select(Review.review_text).where(Review.store_id == store.id)).all()
    )
    for item in data.get("reviews", []):
        if item["review_text"] in existing_review_texts:
            continue
        db.add(
            Review(
                store_id=store.id,
                review_text=item["review_text"],
                reviewer_name=item.get("reviewer_name"),
                rating=item.get("rating"),
                order_type=OrderType(item["order_type"]),
            )
        )
    db.commit()
    db.refresh(store)
    return store


async def seed_rag_if_enabled(store_id: int) -> None:
    settings = get_settings()
    if not settings.seed_rag_on_startup:
        return
    data = load_seed_data()
    await ai_contract.seed_rag_pairs(data.get("rag_seed_pairs", []), store_id)

