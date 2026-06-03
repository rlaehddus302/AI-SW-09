"""AI 파이프라인에서 내부적으로 사용하는 타입 객체입니다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from typing import Annotated, List, Literal

class ClassificationResult(BaseModel):
    """리뷰 분류 단계의 정규화된 결과입니다."""
    model_config = {"frozen": True}
    sentiment: Literal["positive", "negative", "malicious"] = Field(
        description="리뷰의 전반적인 감정 상태를 분류합니다. (긍정, 일반 부정, 악의적 비방/욕설)"
    )
    sub_type: Optional[Literal[
        "배달지연", "이물질", "음식맛", "불친절", "가격불만", "포장불량", "환불요청", "기타"
    ]] = Field(
        default=None,
        description="부정(negative) 또는 악성(malicious) 리뷰인 경우의 구체적인 불만 유형입니다. 긍정(positive) 리뷰인 경우 반드시 null(None)이어야 합니다."
    )
    risk_level: Literal["low", "medium", "high"] = Field(
        description="""리뷰의 위험도를 다음 기준에 따라 엄격히 판단합니다:
                    - low: 긍정적인 리뷰이거나 단순한 한 줄 평 수준의 가벼운 불만
                    - medium: 구체적인 이유가 명시된 일반적인 고객 불만 사항
                    - high: 이물질 발견, 환불 요구나 돈 언급, 욕설/비하 발언, 법적 조치 언급이 포함된 경우"""
    )

    def to_dict(self) -> Dict[str, Any]:
        """라우터와 테스트가 사용하는 dict 계약으로 변환합니다."""
        return self.model_dump()


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
