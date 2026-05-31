"""생성된 리뷰 답변의 승인 필요 여부를 결정합니다."""

from __future__ import annotations

from typing import Optional


def determine_approval(risk_level: Optional[str], sentiment: Optional[str]) -> str:
    """답변 생성 후 리뷰가 자동 답변 가능한지, 사장님 승인이 필요한지 결정합니다."""
    normalized_risk = (risk_level or "").strip().lower()
    normalized_sentiment = (sentiment or "").strip().lower()

    if normalized_risk == "low" and normalized_sentiment == "positive":
        return "auto_replied"
    if normalized_risk in ("medium", "high"):
        return "needs_approval"
    if normalized_sentiment == "malicious":
        return "needs_approval"
    return "needs_approval"
