import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_contract
from app.config import get_settings
from app.demo import DEMO_STORE_ID
from app.models import OrderType, Review, ReviewStatus, Store

SEED_DATA_PATH = Path(__file__).with_name("seed_data.json")


def load_seed_data(path: Path = SEED_DATA_PATH) -> dict:
    """지정된 JSON 파일에서 데모 시드 데이터를 읽어옵니다."""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def seed_database(db: Session) -> Store:
    """데모 가게와 리뷰를 idempotent하게 초기화하고 리뷰 상태를 미분석으로 되돌립니다."""

    data = load_seed_data()
    store_payload = data["store"]
    store_id = int(store_payload.get("id", DEMO_STORE_ID))
    store_values = {key: value for key, value in store_payload.items() if key != "id"}
    review_defaults = data.get("review_defaults", {})

    store = db.get(Store, store_id)
    if store is None:
        store = Store(id=store_id, **store_values)
        db.add(store)
        db.flush()
    else:
        for field, value in store_values.items():
            setattr(store, field, value)

    existing_reviews = {
        review.review_text: review
        for review in db.scalars(select(Review).where(Review.store_id == store.id)).all()
    }
    for item in data.get("reviews", []):
        review = existing_reviews.get(item["review_text"])
        if review is None:
            review = Review(store_id=store.id, review_text=item["review_text"])
            db.add(review)
        else:
            review.review_text = item["review_text"]

        review.reviewer_name = item.get("reviewer_name")
        review.rating = item.get("rating")
        review.order_type = OrderType(item["order_type"])
        review.sentiment = None
        review.sub_type = None
        review.risk_level = None
        review.interpretation = None
        review.reply_tone = None
        review.reply_text = None
        review.rag_references = None
        status = item.get("status", review_defaults.get("status", ReviewStatus.PENDING.value))
        review.status = ReviewStatus(status)
    db.commit()
    db.refresh(store)
    return store


async def seed_rag_if_enabled(store_id: int) -> None:
    """설정이 켜져 있으면 데모 RAG 예시 데이터를 해당 가게에 저장합니다."""

    settings = get_settings()
    if not settings.seed_rag_on_startup:
        return
    data = load_seed_data()
    await ai_contract.seed_rag_pairs(data.get("rag_seed_pairs", []), store_id)
