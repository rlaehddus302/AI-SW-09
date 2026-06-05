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


class InterpretationResult(BaseModel):
    """ 리뷰 해석 단계의 정규화된 결과입니다.
        분류 결과를 바탕으로 리뷰의 핵심 이슈와 사장님이 취해야 할 행동 방향을 도출하고,
        적절한 답변 톤을 결정합니다."""
    model_config = {"frozen": True}
    core_issue: str = Field(
        description="리뷰 원문과 분류 결과를 바탕으로 분석한 고객의 '핵심 이슈' 또는 핵심 불만 사항"
    )
    action_direction: str = Field(
        description="핵심 이슈를 해결하기 위해 사장님이 취해야 할 구체적인 '행동 방향' 또는 대응 전략"
    )
    reply_tone: Literal["감사", "사과", "해명", "단호한 대응"] = Field(
        description="""답변에 사용할 가장 적절한 톤앤매너입니다. 반드시 아래 4가지 선택지 중 하나만 선택해야 합니다:
        - '감사': 긍정적인 리뷰나 칭찬에 대해 고마움을 표현할 때
        - '사과': 서비스나 품질 저하 등 고객의 정당한 불만에 대해 고개를 숙일 때
        - '해명': 오해나 사실과 다른 부분에 대해 정중하고 객관적으로 설명할 때
        - '단호한 대응': 악성 리뷰, 허위 사실, 블랙컨슈머에 대해 엄격하고 단호하게 대처할 때"""
    )

    def to_dict(self) -> Dict[str, Any]:
        """라우터와 테스트가 사용하는 dict 계약으로 변환합니다."""
        return self.model_dump()


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

class AnalysisResult(BaseModel):
    # 분류
    sentiment: Literal["positive", "negative", "malicious"] = Field(
        description="리뷰의 전반적인 감정 상태를 분류합니다. (긍정, 일반 부정, 악의적 비방/욕설)"
    )
    sub_type: Optional[Literal["배달지연", "이물질", "음식맛", "불친절", "가격불만", "포장불량", "환불요청", "기타"]]  = Field(
        default=None,
        description="부정(negative) 또는 악성(malicious) 리뷰인 경우의 구체적인 불만 유형입니다. 긍정(positive) 리뷰인 경우 반드시 null(None)이어야 합니다."
    )
    risk_level: Literal["low", "medium", "high"] = Field(
        description="""리뷰의 위험도를 다음 기준에 따라 엄격히 판단합니다:
                    - low: 긍정적인 리뷰이거나 단순한 한 줄 평 수준의 가벼운 불만
                    - medium: 구체적인 이유가 명시된 일반적인 고객 불만 사항
                    - high: 이물질 발견, 환불 요구나 돈 언급, 욕설/비하 발언, 법적 조치 언급이 포함된 경우"""
    )
    # 해석 
    core_issue: str = Field(
        description="리뷰 원문을 바탕으로 분석한 고객의 '핵심 이슈' 또는 핵심 불만 사항"
    )
    action_direction: str = Field(
        description="핵심 이슈를 해결하기 위해 사장님이 취해야 할 구체적인 '행동 방향' 또는 대응 전략"
    )
    reply_tone: Literal["감사", "사과", "해명", "단호한 대응"] = Field(
        description="""답변에 사용할 가장 적절한 톤앤매너입니다. 반드시 아래 4가지 선택지 중 하나만 선택해야 합니다:
        - '감사': 긍정적인 리뷰나 칭찬에 대해 고마움을 표현할 때
        - '사과': 서비스나 품질 저하 등 고객의 정당한 불만에 대해 고개를 숙일 때
        - '해명': 오해나 사실과 다른 부분에 대해 정중하고 객관적으로 설명할 때
        - '단호한 대응': 악성 리뷰, 허위 사실, 블랙컨슈머에 대해 엄격하고 단호하게 대처할 때"""
    )

    def to_dict(self):
        return self.model_dump()