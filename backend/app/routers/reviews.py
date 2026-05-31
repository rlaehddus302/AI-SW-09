from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OrderType, Review, ReviewStatus, RiskLevel, Sentiment
from app.routers.utils import get_review_or_404, get_store_or_404, review_detail_from_model
from app.schemas.review import ReviewDetail, ReviewListResponse, ReviewStats

router = APIRouter(prefix="/stores/{store_id}/reviews", tags=["reviews"])


@router.get("", response_model=ReviewListResponse)
def list_reviews(
    store_id: int,
    order_type: Optional[OrderType] = None,
    status: Optional[ReviewStatus] = None,
    sentiment: Optional[Sentiment] = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ReviewListResponse:
    get_store_or_404(db, store_id)
    filters = [Review.store_id == store_id]
    if order_type is not None:
        filters.append(Review.order_type == order_type)
    if status is not None:
        filters.append(Review.status == status)
    if sentiment is not None:
        filters.append(Review.sentiment == sentiment)

    total = db.scalar(select(func.count()).select_from(Review).where(*filters)) or 0
    reviews = db.scalars(
        select(Review)
        .where(*filters)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return ReviewListResponse(total=total, page=page, size=size, reviews=reviews)


@router.get("/stats", response_model=ReviewStats)
def review_stats(
    store_id: int,
    order_type: Optional[OrderType] = None,
    db: Session = Depends(get_db),
) -> ReviewStats:
    get_store_or_404(db, store_id)
    filters = [Review.store_id == store_id]
    if order_type is not None:
        filters.append(Review.order_type == order_type)

    total = db.scalar(select(func.count()).select_from(Review).where(*filters)) or 0

    def enum_distribution(column, enum_type) -> dict[str, int]:
        rows = db.execute(select(column, func.count()).where(*filters).group_by(column)).all()
        counts = {item.value: 0 for item in enum_type}
        for key, count in rows:
            if key is not None:
                counts[key.value if hasattr(key, "value") else str(key)] = count
        return counts

    sub_type_rows = db.execute(
        select(Review.sub_type, func.count())
        .where(*filters, Review.sub_type.is_not(None))
        .group_by(Review.sub_type)
    ).all()

    return ReviewStats(
        total_reviews=total,
        sentiment_distribution=enum_distribution(Review.sentiment, Sentiment),
        risk_distribution=enum_distribution(Review.risk_level, RiskLevel),
        status_distribution=enum_distribution(Review.status, ReviewStatus),
        sub_type_distribution={sub_type: count for sub_type, count in sub_type_rows},
    )


@router.get("/{review_id}", response_model=ReviewDetail)
def read_review(store_id: int, review_id: int, db: Session = Depends(get_db)) -> ReviewDetail:
    review = get_review_or_404(db, store_id, review_id)
    return review_detail_from_model(review)
