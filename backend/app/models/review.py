from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import OrderType, ReviewStatus, RiskLevel, Sentiment


def enum_values(enum_type: type) -> list[str]:
    """SQLAlchemy Enum 컬럼에 Python Enum 값 문자열만 저장하도록 변환합니다."""

    return [item.value for item in enum_type]


class Review(Base):
    """고객 리뷰와 AI 분석/답변 생성 상태를 저장하는 ORM 모델입니다."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="ck_reviews_rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False)
    review_text: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(nullable=True)
    order_type: Mapped[OrderType] = mapped_column(
        SAEnum(OrderType, values_callable=enum_values, native_enum=False, length=20),
        nullable=False,
    )
    sentiment: Mapped[Optional[Sentiment]] = mapped_column(
        SAEnum(Sentiment, values_callable=enum_values, native_enum=False, length=20),
        nullable=True,
    )
    sub_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    risk_level: Mapped[Optional[RiskLevel]] = mapped_column(
        SAEnum(RiskLevel, values_callable=enum_values, native_enum=False, length=20),
        nullable=True,
    )
    interpretation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reply_tone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rag_references: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(ReviewStatus, values_callable=enum_values, native_enum=False, length=30),
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    store: Mapped["Store"] = relationship("Store", back_populates="reviews")
