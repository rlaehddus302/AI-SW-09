from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.openapi_examples import STORE_EXAMPLE, STORE_REQUEST_EXAMPLE


class StoreBase(BaseModel):
    """가게 생성/수정 요청에서 공통으로 사용하는 필드입니다."""

    store_name: str = Field(min_length=1, max_length=100)
    origin_info: Optional[str] = None
    is_dine_in: bool = False
    is_takeout: bool = False
    is_delivery: bool = False
    reply_tone_style: Literal["friendly", "formal", "neutral"] = "neutral"
    reply_opening: Optional[str] = Field(default=None, max_length=200)
    reply_closing: Optional[str] = Field(default=None, max_length=200)
    reply_emphasis: Optional[str] = Field(default=None, max_length=300)
    reply_forbidden: Optional[str] = Field(default=None, max_length=300)

    model_config = ConfigDict(json_schema_extra={"example": STORE_REQUEST_EXAMPLE})


class StoreCreate(StoreBase):
    """가게 등록 요청 스키마입니다."""

    pass


class StoreUpdate(StoreBase):
    """가게 정보 수정 요청 스키마입니다."""

    pass


class StoreRead(StoreBase):
    """가게 조회 응답 스키마입니다."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, json_schema_extra={"example": STORE_EXAMPLE})
