from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import OrderType, ReviewStatus, RiskLevel, Sentiment


class BatchReviewRequest(BaseModel):
    review_ids: list[int] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "BatchReviewRequest":
        if len(self.review_ids) != len(set(self.review_ids)):
            raise ValueError("review_ids must not contain duplicates")
        return self


class ReviewListItem(BaseModel):
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

    model_config = ConfigDict(from_attributes=True)


class ReviewListResponse(BaseModel):
    total: int
    page: int
    size: int
    reviews: list[ReviewListItem]


class Interpretation(BaseModel):
    core_issue: Optional[str] = None
    action_direction: Optional[str] = None
    reply_tone: Optional[str] = None


class RagReference(BaseModel):
    review: str
    reply: str
    similarity: Optional[float] = None


class ReviewDetail(BaseModel):
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


class ReviewStats(BaseModel):
    total_reviews: int
    sentiment_distribution: dict[str, int]
    risk_distribution: dict[str, int]
    status_distribution: dict[str, int]
    sub_type_distribution: dict[str, int]


class AnalysisTaskResponse(BaseModel):
    task_id: str
    message: str
    total: int


class RegenerateTaskResponse(BaseModel):
    task_id: str
    message: str


class ActionResponse(BaseModel):
    id: int
    status: ReviewStatus
    message: str
