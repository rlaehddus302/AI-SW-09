from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Store(Base):
    """로컬 MVP에서 관리하는 단일 음식점 가게 정보를 저장합니다."""

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    store_name: Mapped[str] = mapped_column(String(100), nullable=False)
    origin_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_dine_in: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_takeout: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_delivery: Mapped[bool] = mapped_column(default=False, nullable=False)
    reply_tone_style: Mapped[str] = mapped_column(
        String(20), default="neutral", server_default="neutral", nullable=False
    )
    reply_opening: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reply_closing: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reply_emphasis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reply_forbidden: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="store",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
