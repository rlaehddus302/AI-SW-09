"""리뷰 해석 서비스입니다."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from ..llm.client import AIClientProtocol, create_ai_client
from ..llm.prompts import INTERPRETATION_SYSTEM_PROMPT
from ..llm.types import InterpretationResult
from .classification import classify_review, normalize_classification


ALLOWED_REPLY_TONES = {"감사", "사과", "해명", "단호한 대응"}


def interpret_review(
    review_text: str,
    classification: Mapping[str, Any],
    *,
    client: Optional[AIClientProtocol] = None,
) -> Dict[str, Any]:
    """분류된 리뷰에서 핵심 이슈와 답변 전략을 도출합니다."""
    if not isinstance(review_text, str) or not review_text.strip():
        raise ValueError("review_text must not be empty")

    normalized_classification = normalize_classification(classification).to_dict()
    ai_client = client or create_ai_client()
    raw = ai_client.complete_json(
        task="interpretation",
        system_prompt=INTERPRETATION_SYSTEM_PROMPT,
        user_payload={
            "review_text": review_text,
            "classification": normalized_classification,
        },
        RouteDecision=InterpretationResult
    )
    return raw


def analyze_review(
    review_text: str,
    *,
    client: Optional[AIClientProtocol] = None,
) -> Dict[str, Any]:
    """리뷰 1건에 대해 분류와 해석을 순차 실행합니다."""
    ai_client = client or create_ai_client()
    classification = classify_review(review_text, client=ai_client)
    interpretation = interpret_review(review_text, classification, client=ai_client)
    return {
        "classification": classification,
        "interpretation": interpretation,
    }


def normalize_interpretation(
    raw: Mapping[str, Any],
    classification: Mapping[str, Any],
) -> InterpretationResult:
    """모델 해석 결과의 누락값을 기본 전략으로 보정합니다."""
    core_issue = str(raw.get("core_issue") or "").strip()
    action_direction = str(raw.get("action_direction") or "").strip()
    reply_tone = str(raw.get("reply_tone") or "").strip()

    if not core_issue:
        core_issue = _default_core_issue(classification)
    if not action_direction:
        action_direction = _default_action_direction(classification)
    if reply_tone not in ALLOWED_REPLY_TONES:
        reply_tone = _default_reply_tone(classification)

    return InterpretationResult(
        core_issue=core_issue,
        action_direction=action_direction,
        reply_tone=reply_tone,
    )


def _default_core_issue(classification: Mapping[str, Any]) -> str:
    """감정/세부 유형을 기반으로 기본 핵심 이슈를 선택합니다."""
    sentiment = classification.get("sentiment")
    if sentiment == "positive":
        return "긍정적인 이용 경험"
    return f"{classification.get('sub_type') or '기타'} 관련 고객 불편"


def _default_action_direction(classification: Mapping[str, Any]) -> str:
    """감정을 기반으로 기본 답변 방향을 선택합니다."""
    sentiment = classification.get("sentiment")
    if sentiment == "positive":
        return "감사 인사와 재방문 유도"
    if sentiment == "malicious":
        return "감정적 대응 없이 사실 확인과 공식 문의 채널 안내"
    return "진심 어린 사과와 개선 의지 안내"


def _default_reply_tone(classification: Mapping[str, Any]) -> str:
    """감정을 기반으로 기본 답변 톤을 선택합니다."""
    sentiment = classification.get("sentiment")
    if sentiment == "positive":
        return "감사"
    if sentiment == "malicious":
        return "단호한 대응"
    return "사과"
