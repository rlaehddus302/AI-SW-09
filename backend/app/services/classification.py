"""리뷰 분류 서비스입니다."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from ..llm.client import AIClientProtocol, create_ai_client
from ..llm.prompts import CLASSIFICATION_SYSTEM_PROMPT
from ..llm.types import ClassificationResult


ALLOWED_SENTIMENTS = {"positive", "negative", "malicious"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
ALLOWED_SUB_TYPES = {
    "배달지연",
    "이물질",
    "음식맛",
    "불친절",
    "가격불만",
    "포장불량",
    "환불요청",
    "기타",
}


def classify_review(
    review_text: str,
    *,
    client: Optional[AIClientProtocol] = None,
) -> Dict[str, Any]:
    """리뷰 텍스트를 감정, 세부 유형, 위험도로 분류합니다."""
    _require_review_text(review_text)
    ai_client = client or create_ai_client()
    raw = ai_client.complete_json(
        task="classification",
        system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
        user_payload={"review_text": review_text},
        RouteDecision=ClassificationResult
    )
    return raw

def normalize_classification(raw: Mapping[str, Any]) -> ClassificationResult:
    """모델 출력값을 허용된 enum 후보와 안전한 기본값으로 정규화합니다."""
    sentiment = str(raw.get("sentiment") or "").strip().lower()
    if sentiment not in ALLOWED_SENTIMENTS:
        sentiment = "negative"

    risk_level = str(raw.get("risk_level") or "").strip().lower()
    if risk_level not in ALLOWED_RISK_LEVELS:
        risk_level = "medium"

    raw_sub_type = raw.get("sub_type")
    sub_type = str(raw_sub_type).strip() if raw_sub_type not in (None, "") else None

    if sentiment == "positive":
        sub_type = None
        risk_level = "low" if risk_level not in ("medium", "high") else risk_level
    elif sub_type not in ALLOWED_SUB_TYPES:
        sub_type = "기타"

    if sentiment == "malicious" and risk_level == "low":
        risk_level = "high"

    return ClassificationResult(
        sentiment=sentiment,
        sub_type=sub_type,
        risk_level=risk_level,
    )

def _require_review_text(review_text: str) -> None:
    """AI 호출 전 빈 리뷰 텍스트를 차단합니다."""
    if not isinstance(review_text, str) or not review_text.strip():
        raise ValueError("review_text must not be empty")
