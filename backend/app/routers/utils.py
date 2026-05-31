from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Review, ReviewStatus, Store
from app.schemas.review import RagReference, ReviewDetail


def get_store_or_404(db: Session, store_id: int) -> Store:
    """가게를 조회하거나 API 표준 가게 404를 발생시킵니다."""

    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="가게를 찾을 수 없습니다.")
    return store


def get_review_or_404(db: Session, store_id: int, review_id: int) -> Review:
    """가게 범위 안의 리뷰 1건을 조회하거나 표준 리뷰 404를 발생시킵니다."""

    review = db.scalar(select(Review).where(Review.id == review_id, Review.store_id == store_id))
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="리뷰를 찾을 수 없습니다.")
    return review


def get_reviews_or_404(db: Session, store_id: int, review_ids: list[int]) -> list[Review]:
    """리뷰 묶음을 조회하고 요청된 id 순서를 유지합니다."""

    rows = db.scalars(select(Review).where(Review.store_id == store_id, Review.id.in_(review_ids))).all()
    by_id = {review.id: review for review in rows}
    missing = [review_id for review_id in review_ids if review_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "리뷰를 찾을 수 없습니다.", "review_ids": missing},
        )
    return [by_id[review_id] for review_id in review_ids]


def require_status(review: Review, allowed: set[ReviewStatus], action: str) -> None:
    """단일 리뷰 상태 전이를 검증하고 맞지 않으면 409를 발생시킵니다."""

    if review.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{action} 가능한 상태가 아닙니다.",
                "current_status": review.status.value,
                "allowed_statuses": [item.value for item in allowed],
            },
        )


def require_batch_status(reviews: list[Review], allowed: set[ReviewStatus], action: str) -> None:
    """배치 상태 전이를 검증하고 잘못된 id를 409 상세에 포함합니다."""

    invalid = [
        {"id": review.id, "status": review.status.value}
        for review in reviews
        if review.status not in allowed
    ]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{action} 가능한 상태가 아닌 리뷰가 포함되어 있습니다.",
                "invalid_reviews": invalid,
                "allowed_statuses": [item.value for item in allowed],
            },
        )


def parse_json_object(value: Optional[str]) -> Optional[dict[str, Any]]:
    """JSON 객체 문자열을 파싱하고 비었거나 잘못된 값이면 None을 반환합니다."""

    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_rag_references(value: Optional[str]) -> list[RagReference]:
    """저장된 RAG JSON을 검증된 응답 reference 모델로 파싱합니다."""

    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    references: list[RagReference] = []
    for item in parsed:
        if isinstance(item, dict) and item.get("review") and item.get("reply"):
            references.append(RagReference.model_validate(item))
    return references


def review_detail_from_model(review: Review) -> ReviewDetail:
    """ORM 리뷰 row를 API 상세 응답 모델로 변환합니다."""

    return ReviewDetail(
        id=review.id,
        store_id=review.store_id,
        review_text=review.review_text,
        reviewer_name=review.reviewer_name,
        rating=review.rating,
        order_type=review.order_type,
        sentiment=review.sentiment,
        sub_type=review.sub_type,
        risk_level=review.risk_level,
        interpretation=parse_json_object(review.interpretation),
        reply_text=review.reply_text,
        status=review.status,
        rag_references=parse_rag_references(review.rag_references),
        created_at=review.created_at,
        updated_at=review.updated_at,
    )
