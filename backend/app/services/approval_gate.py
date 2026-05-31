"""Approval gate for generated review replies."""

from __future__ import annotations

from typing import Optional


def determine_approval(risk_level: Optional[str], sentiment: Optional[str]) -> str:
    """
    Return the next review status after reply generation.

    Only low-risk positive reviews can be auto-replied. Every ambiguous or
    risk-bearing case requires owner approval.
    """

    normalized_risk = (risk_level or "").strip().lower()
    normalized_sentiment = (sentiment or "").strip().lower()

    if normalized_risk == "low" and normalized_sentiment == "positive":
        return "auto_replied"
    if normalized_risk in ("medium", "high"):
        return "needs_approval"
    if normalized_sentiment == "malicious":
        return "needs_approval"
    return "needs_approval"
