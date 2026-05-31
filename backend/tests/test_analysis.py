import asyncio

from app.database import SessionLocal
from app.models import Review, ReviewStatus
from app import ai_contract
from app.routers import analysis


def _status(review_id: int) -> str:
    with SessionLocal() as db:
        return db.get(Review, review_id).status.value


def test_analyze_accepts_only_pending_reviews(client, seeded_store, monkeypatch):
    monkeypatch.setattr(analysis, "run_analysis_task", lambda *args, **kwargs: None)

    response = client.post(
        f"/api/v1/stores/{seeded_store}/reviews/analyze",
        json={"review_ids": [2]},
    )
    assert response.status_code == 202
    assert response.json()["total"] == 1
    assert _status(2) == "analyzing"

    response = client.post(
        f"/api/v1/stores/{seeded_store}/reviews/analyze",
        json={"review_ids": [3]},
    )
    assert response.status_code == 409


def test_batch_requests_reject_duplicates_and_missing_reviews(client, seeded_store):
    response = client.post(
        f"/api/v1/stores/{seeded_store}/reviews/analyze",
        json={"review_ids": [2, 2]},
    )
    assert response.status_code == 422

    response = client.post(
        f"/api/v1/stores/{seeded_store}/reviews/analyze",
        json={"review_ids": [999]},
    )
    assert response.status_code == 404


def test_generate_accepts_only_analyzed_reviews(client, seeded_store, monkeypatch):
    monkeypatch.setattr(analysis, "run_generation_task", lambda *args, **kwargs: None)

    response = client.post(
        f"/api/v1/stores/{seeded_store}/reviews/generate-replies",
        json={"review_ids": [3]},
    )
    assert response.status_code == 202
    assert _status(3) == "generating"

    response = client.post(
        f"/api/v1/stores/{seeded_store}/reviews/generate-replies",
        json={"review_ids": [2]},
    )
    assert response.status_code == 409


def test_approve_reject_and_regenerate_transitions(client, seeded_store, monkeypatch):
    monkeypatch.setattr(analysis, "run_generation_task", lambda *args, **kwargs: None)

    response = client.post(f"/api/v1/stores/{seeded_store}/reviews/3/approve")
    assert response.status_code == 409

    response = client.post(f"/api/v1/stores/{seeded_store}/reviews/4/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    with SessionLocal() as db:
        review = db.get(Review, 4)
        review.status = ReviewStatus.NEEDS_APPROVAL
        db.commit()

    response = client.post(f"/api/v1/stores/{seeded_store}/reviews/4/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "on_hold"

    response = client.post(f"/api/v1/stores/{seeded_store}/reviews/4/regenerate")
    assert response.status_code == 202
    assert _status(4) == "generating"

    response = client.post(f"/api/v1/stores/{seeded_store}/reviews/3/regenerate")
    assert response.status_code == 409


def test_background_tasks_persist_analysis_and_generation(seeded_store, monkeypatch):
    async def fake_classify_review(review_text: str):
        return {"sentiment": "positive", "sub_type": None, "risk_level": "low"}

    async def fake_interpret_review(review_text: str, classification):
        return {
            "core_issue": "긍정 리뷰",
            "action_direction": "감사 인사",
            "reply_tone": "감사",
        }

    async def fake_search_rag_references(**kwargs):
        return [{"review": "맛있어요", "reply": "감사합니다.", "similarity": 0.95}]

    async def fake_generate_reply(**kwargs):
        return {"reply_text": "방문해 주셔서 감사합니다."}

    monkeypatch.setattr(ai_contract, "classify_review", fake_classify_review)
    monkeypatch.setattr(ai_contract, "interpret_review", fake_interpret_review)
    monkeypatch.setattr(ai_contract, "search_rag_references", fake_search_rag_references)
    monkeypatch.setattr(ai_contract, "generate_reply", fake_generate_reply)

    asyncio.run(analysis.run_analysis_task("task_analysis", seeded_store, [2]))
    with SessionLocal() as db:
        review = db.get(Review, 2)
        assert review.status == ReviewStatus.ANALYZED
        assert review.sentiment.value == "positive"
        assert review.reply_tone == "감사"
        review.status = ReviewStatus.GENERATING
        db.commit()

    asyncio.run(analysis.run_generation_task("task_generation", seeded_store, [2]))
    with SessionLocal() as db:
        review = db.get(Review, 2)
        assert review.status == ReviewStatus.AUTO_REPLIED
        assert review.reply_text == "방문해 주셔서 감사합니다."
        assert "맛있어요" in review.rag_references


def test_analysis_task_broadcasts_each_review_as_it_finishes(seeded_store, monkeypatch):
    async def fake_classify_review(review_text: str):
        if "분석 대기" in review_text:
            await asyncio.sleep(0.03)
        return {"sentiment": "negative", "sub_type": "기타", "risk_level": "medium"}

    async def fake_interpret_review(review_text: str, classification):
        return {
            "core_issue": review_text,
            "action_direction": "개별 처리",
            "reply_tone": "사과",
        }

    messages = []

    async def fake_broadcast(store_id: int, message: dict):
        messages.append(message)

    with SessionLocal() as db:
        review = db.get(Review, 3)
        review.status = ReviewStatus.PENDING
        db.commit()

    monkeypatch.setattr(ai_contract, "classify_review", fake_classify_review)
    monkeypatch.setattr(ai_contract, "interpret_review", fake_interpret_review)
    monkeypatch.setattr(analysis.manager, "broadcast", fake_broadcast)

    asyncio.run(analysis.run_analysis_task("task_realtime", seeded_store, [2, 3]))

    completed_updates = [
        message
        for message in messages
        if message.get("type") == "review_updated" and message.get("event") == "analysis_completed"
    ]
    assert len(completed_updates) == 2
    assert completed_updates[0]["review_id"] == 3
    assert completed_updates[0]["review"]["status"] == "analyzed"
    assert completed_updates[0]["progress"]["current"] == 1
    assert completed_updates[1]["progress"]["current"] == 2
    assert messages[-1]["type"] == "task_complete"
