from sqlalchemy import func, select

from app.database import SessionLocal
from app.demo import DEMO_STORE_ID
from app.models import Review, ReviewStatus, RiskLevel, Sentiment
from app.seed.seeder import seed_database


def test_seed_database_uses_json_store_id_and_pending_reviews():
    with SessionLocal() as db:
        store = seed_database(db)

        assert store.id == DEMO_STORE_ID
        assert db.scalar(select(func.count()).select_from(Review)) == 30
        assert db.scalar(select(func.count()).select_from(Review).where(Review.status != ReviewStatus.PENDING)) == 0


def test_seed_database_resets_existing_review_analysis_state():
    with SessionLocal() as db:
        store = seed_database(db)
        review = db.scalar(select(Review).where(Review.store_id == store.id).limit(1))
        review.sentiment = Sentiment.NEGATIVE
        review.sub_type = "배달지연"
        review.risk_level = RiskLevel.MEDIUM
        review.interpretation = '{"core_issue":"배달 지연"}'
        review.reply_tone = "사과"
        review.reply_text = "죄송합니다."
        review.rag_references = "[]"
        review.status = ReviewStatus.NEEDS_APPROVAL
        db.commit()

        seed_database(db)
        db.refresh(review)

        assert review.sentiment is None
        assert review.sub_type is None
        assert review.risk_level is None
        assert review.interpretation is None
        assert review.reply_tone is None
        assert review.reply_text is None
        assert review.rag_references is None
        assert review.status == ReviewStatus.PENDING
