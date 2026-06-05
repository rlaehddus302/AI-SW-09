from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from ..llm.client import AIClientProtocol, create_ai_client
from ..llm.prompts import ANALYSIS_SYSTEM_PROMPT
from ..llm.types import AnalysisResult

def analyze_review(
    review_text: str,
    *,
    client: Optional[AIClientProtocol] = None,
) -> Dict[str, Any]:
    """리뷰 텍스트를 감정, 세부 유형, 위험도로 분류합니다."""
    _require_review_text(review_text)
    ai_client = client or create_ai_client()
    raw = ai_client.complete_json(
        task="analysis",
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        user_payload={"review_text": review_text},
        RouteDecision=AnalysisResult
    )
    return raw


def _require_review_text(review_text: str) -> None:
    """AI 호출 전 빈 리뷰 텍스트를 차단합니다."""
    if not isinstance(review_text, str) or not review_text.strip():
        raise ValueError("review_text must not be empty")