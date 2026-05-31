import json
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["CREATE_TABLES_ON_STARTUP"] = "false"
os.environ["RESET_DATABASE_ON_STARTUP"] = "false"
os.environ["SEED_ON_STARTUP"] = "false"
os.environ["AI_MODE"] = "mock"

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import OrderType, Review, ReviewStatus, RiskLevel, Sentiment, Store  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database() -> Generator:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded_store() -> int:
    with SessionLocal() as db:
        store = Store(
            store_name="테스트 치킨집",
            origin_info="닭고기: 국내산",
            is_dine_in=True,
            is_takeout=True,
            is_delivery=True,
        )
        db.add(store)
        db.flush()
        reviews = [
            Review(
                store_id=store.id,
                review_text="맛있고 빨리 왔어요.",
                reviewer_name="긍정",
                rating=5,
                order_type=OrderType.DELIVERY,
                sentiment=Sentiment.POSITIVE,
                risk_level=RiskLevel.LOW,
                status=ReviewStatus.AUTO_REPLIED,
                reply_text="감사합니다.",
            ),
            Review(
                store_id=store.id,
                review_text="분석 대기 리뷰입니다.",
                reviewer_name="대기",
                rating=3,
                order_type=OrderType.TAKEOUT,
                status=ReviewStatus.PENDING,
            ),
            Review(
                store_id=store.id,
                review_text="답변 생성 대기 리뷰입니다.",
                reviewer_name="분석됨",
                rating=2,
                order_type=OrderType.DELIVERY,
                sentiment=Sentiment.NEGATIVE,
                sub_type="배달지연",
                risk_level=RiskLevel.MEDIUM,
                interpretation=json.dumps(
                    {
                        "core_issue": "배달 지연",
                        "action_direction": "사과와 개선",
                        "reply_tone": "사과",
                    },
                    ensure_ascii=False,
                ),
                reply_tone="사과",
                status=ReviewStatus.ANALYZED,
            ),
            Review(
                store_id=store.id,
                review_text="승인 필요 리뷰입니다.",
                reviewer_name="승인",
                rating=1,
                order_type=OrderType.DINE_IN,
                sentiment=Sentiment.NEGATIVE,
                sub_type="이물질",
                risk_level=RiskLevel.HIGH,
                interpretation=json.dumps(
                    {
                        "core_issue": "위생 이슈",
                        "action_direction": "사과와 점검",
                        "reply_tone": "사과",
                    },
                    ensure_ascii=False,
                ),
                reply_text="불편을 드려 죄송합니다.",
                rag_references=json.dumps(
                    [{"review": "이물질", "reply": "죄송합니다.", "similarity": 0.9}],
                    ensure_ascii=False,
                ),
                status=ReviewStatus.NEEDS_APPROVAL,
            ),
            Review(
                store_id=store.id,
                review_text="보류 리뷰입니다.",
                reviewer_name="보류",
                rating=1,
                order_type=OrderType.DELIVERY,
                sentiment=Sentiment.MALICIOUS,
                sub_type="악성",
                risk_level=RiskLevel.HIGH,
                reply_text="이전 답변",
                status=ReviewStatus.ON_HOLD,
            ),
        ]
        db.add_all(reviews)
        db.commit()
        return store.id
