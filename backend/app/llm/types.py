"""AI 파이프라인에서 내부적으로 사용하는 타입 객체입니다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ClassificationResult:
    """리뷰 분류 단계의 정규화된 결과입니다."""
    sentiment: str
    sub_type: Optional[str]
    risk_level: str

    def to_dict(self) -> Dict[str, Any]:
        """라우터와 테스트가 사용하는 dict 계약으로 변환합니다."""
        return asdict(self)


@dataclass(frozen=True)
class InterpretationResult:
    """리뷰 해석 단계의 정규화된 결과입니다."""
    core_issue: str
    action_direction: str
    reply_tone: str

    def to_dict(self) -> Dict[str, Any]:
        """라우터와 테스트가 사용하는 dict 계약으로 변환합니다."""
        return asdict(self)


@dataclass(frozen=True)
class RAGReference:
    """RAG 검색에서 반환하는 유사 리뷰-답변 사례 1건입니다."""
    review: str
    reply: str
    sub_type: Optional[str] = None
    risk_level: Optional[str] = None
    order_type: Optional[str] = None
    similarity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """JSON 응답에 바로 사용할 수 있는 dict로 변환합니다."""
        return asdict(self)


@dataclass(frozen=True)
class ReplyGenerationResult:
    """답변 생성 결과와 생성에 사용된 RAG 참고 사례입니다."""
    reply_text: str
    rag_references: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        """라우터와 테스트가 사용하는 dict 계약으로 변환합니다."""
        return asdict(self)
