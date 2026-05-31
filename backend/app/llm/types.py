"""Typed result objects for the AI pipeline.

The services expose dict-shaped payloads for FastAPI routers, while these
dataclasses give tests and internal code a stable contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ClassificationResult:
    sentiment: str
    sub_type: Optional[str]
    risk_level: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InterpretationResult:
    core_issue: str
    action_direction: str
    reply_tone: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RAGReference:
    review: str
    reply: str
    sub_type: Optional[str] = None
    risk_level: Optional[str] = None
    order_type: Optional[str] = None
    similarity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReplyGenerationResult:
    reply_text: str
    rag_references: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
