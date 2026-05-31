from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import OrderType, ReviewStatus, RiskLevel, Sentiment
from app.openapi_examples import (
    ANALYSIS_TASK_EXAMPLE,
    APPROVE_ACTION_EXAMPLE,
    BATCH_REVIEW_REQUEST_EXAMPLE,
    INTERPRETATION_EXAMPLE,
    RAG_REFERENCE_EXAMPLE,
    REGENERATE_TASK_EXAMPLE,
    REVIEW_DETAIL_EXAMPLE,
    REVIEW_LIST_EXAMPLE,
    REVIEW_LIST_ITEM_EXAMPLE,
    REVIEW_STATS_EXAMPLE,
)


class BatchReviewRequest(BaseModel):
    """여러 리뷰를 한 번에 처리할 때 받는 리뷰 id 목록입니다."""

    review_ids: list[int] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(json_schema_extra={"example": BATCH_REVIEW_REQUEST_EXAMPLE})

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "BatchReviewRequest":
        """같은 리뷰 id가 중복 요청되는 것을 validation 단계에서 차단합니다."""

        if len(self.review_ids) != len(set(self.review_ids)):
            raise ValueError("review_ids must not contain duplicates")
        return self


class ReviewListItem(BaseModel):
    """리뷰 목록 화면에서 필요한 요약 응답 필드입니다."""

    id: int
    review_text: str
    reviewer_name: Optional[str]
    rating: Optional[int]
    order_type: OrderType
    sentiment: Optional[Sentiment]
    sub_type: Optional[str]
    risk_level: Optional[RiskLevel]
    status: ReviewStatus
    reply_text: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, json_schema_extra={"example": REVIEW_LIST_ITEM_EXAMPLE})


class ReviewListResponse(BaseModel):
    """페이지네이션된 리뷰 목록 응답입니다."""

    total: int
    page: int
    size: int
    reviews: list[ReviewListItem]

    model_config = ConfigDict(json_schema_extra={"example": REVIEW_LIST_EXAMPLE})


class Interpretation(BaseModel):
    """AI 해석 결과의 핵심 이슈, 답변 방향, 답변 톤입니다."""

    core_issue: Optional[str] = None
    action_direction: Optional[str] = None
    reply_tone: Optional[str] = None

    model_config = ConfigDict(json_schema_extra={"example": INTERPRETATION_EXAMPLE})


class RagReference(BaseModel):
    """답변 생성에 참고한 유사 리뷰-답변 사례입니다."""

    review: str
    reply: str
    similarity: Optional[float] = None

    model_config = ConfigDict(json_schema_extra={"example": RAG_REFERENCE_EXAMPLE})


class ReviewDetail(BaseModel):
    """리뷰 상세 패널에서 사용하는 전체 리뷰 응답입니다."""

    id: int
    store_id: int
    review_text: str
    reviewer_name: Optional[str]
    rating: Optional[int]
    order_type: OrderType
    sentiment: Optional[Sentiment]
    sub_type: Optional[str]
    risk_level: Optional[RiskLevel]
    interpretation: Optional[dict[str, Any]]
    reply_text: Optional[str]
    status: ReviewStatus
    rag_references: list[RagReference] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(json_schema_extra={"example": REVIEW_DETAIL_EXAMPLE})


class ReviewStats(BaseModel):
    """리뷰 대시보드 통계 카드와 분포 차트에 쓰는 집계 응답입니다."""

    total_reviews: int
    sentiment_distribution: dict[str, int]
    risk_distribution: dict[str, int]
    status_distribution: dict[str, int]
    sub_type_distribution: dict[str, int]

    model_config = ConfigDict(json_schema_extra={"example": REVIEW_STATS_EXAMPLE})


class AnalysisTaskResponse(BaseModel):
    """분석/답변 생성 배치 작업 시작 응답입니다."""

    task_id: str
    message: str
    total: int

    model_config = ConfigDict(json_schema_extra={"example": ANALYSIS_TASK_EXAMPLE})


class RegenerateTaskResponse(BaseModel):
    """답변 재생성 작업 시작 응답입니다."""

    task_id: str
    message: str

    model_config = ConfigDict(json_schema_extra={"example": REGENERATE_TASK_EXAMPLE})


class ActionResponse(BaseModel):
    """승인, 반려 같은 단일 리뷰 상태 변경 응답입니다."""

    id: int
    status: ReviewStatus
    message: str

    model_config = ConfigDict(json_schema_extra={"example": APPROVE_ACTION_EXAMPLE})
