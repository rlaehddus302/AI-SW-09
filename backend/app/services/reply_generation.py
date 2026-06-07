"""답변 생성 서비스와 생성 단계 파이프라인 헬퍼입니다."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from ..llm.client import AIClientProtocol, LLMResponseParseError, create_ai_client
from ..llm.prompts import SELF_REVIEW_SYSTEM_PROMPT, build_reply_generation_prompt
from ..llm.types import ReplyGenerationResult
from .approval_gate import determine_approval
from .interpretation import normalize_interpretation
from .rag_service import RAGService

REPLY_TEXT_KEYS = ("reply_text", "reply", "answer", "response", "message", "content")
MAX_SELF_REVIEW_RETRIES = 2


def extract_reply_text(raw: Mapping[str, Any]) -> str:
    """live 모델이 스키마를 약간 벗어나도 답변 텍스트 후보를 안전하게 추출합니다."""
    for key in REPLY_TEXT_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return ""


def generate_reply(
    review_text: str,
    interpretation: Mapping[str, Any],
    store_info: Mapping[str, Any],
    *,
    sentiment: Optional[str] = None,
    rag_references: Optional[Sequence[Mapping[str, Any]]] = None,
    client: Optional[AIClientProtocol] = None,
) -> Dict[str, Any]:
    """리뷰 원문, 해석 결과, 가게 정보, RAG 참고 사례로 답변 초안을 생성합니다."""
    if not isinstance(review_text, str) or not review_text.strip():
        raise ValueError("review_text must not be empty")
    if not isinstance(store_info, Mapping):
        raise ValueError("store_info must be a mapping")

    normalized_interpretation = normalize_interpretation(interpretation, {}).to_dict()
    references = [dict(reference) for reference in (rag_references or [])]
    ai_client = client or create_ai_client()

    try:
        raw = ai_client.complete_json(
            task="reply_generation",
            system_prompt=build_reply_generation_prompt(store_info, sentiment),
            user_payload={
                "review_text": review_text,
                "interpretation": normalized_interpretation,
                "store_info": dict(store_info),
                "rag_references": references,
                "output_schema": {"reply_text": "string, 1~500 chars"},
            },
        )
    except LLMResponseParseError as exc:
        raise ValueError("reply generation response must be JSON with non-empty reply_text") from exc

    reply_text = extract_reply_text(raw)
    if not reply_text:
        raise ValueError(
            f"reply generation response must include non-empty reply_text; keys={sorted(raw.keys())}"
        )
    return ReplyGenerationResult(
        reply_text=reply_text,
        rag_references=references,
    ).to_dict()


def self_review(
    reply_text: str,
    sentiment: Optional[str] = None,
    forbidden: Optional[str] = None,
    *,
    client: Optional[AIClientProtocol] = None,
) -> Dict[str, Any]:
    """생성된 답변을 LLM이 4가지 기준으로 스스로 점검합니다.

    점검 실패 시 passed=False와 reason을 반환하고,
    LLM 호출 자체가 실패하면 파이프라인을 막지 않도록 passed=True로 폴백합니다.
    """
    if not isinstance(reply_text, str) or not reply_text.strip():
        return {"passed": False, "reason": "reply_text가 비어 있습니다."}

    ai_client = client or create_ai_client()
    try:
        raw = ai_client.complete_json(
            task="self_review",
            system_prompt=SELF_REVIEW_SYSTEM_PROMPT,
            user_payload={
                "reply_text": reply_text,
                "sentiment": sentiment or "unknown",
                "forbidden_expressions": forbidden or "",
            },
        )
    except Exception:
        return {"passed": True, "reason": None}

    passed = bool(raw.get("passed", True))
    reason = str(raw.get("reason") or "").strip() or None
    return {"passed": passed, "reason": None if passed else reason}


def generate_reply_pipeline(
    review_text: str,
    classification: Mapping[str, Any],
    interpretation: Mapping[str, Any],
    store_info: Mapping[str, Any],
    *,
    order_type: Optional[str] = None,
    rag_service: Optional[RAGService] = None,
    client: Optional[AIClientProtocol] = None,
    top_k: int = 3,
) -> Dict[str, Any]:
    """분석 완료 리뷰 1건에 대해 RAG 검색, 답변 생성, 자기 점검, 승인 게이트를 순서대로 실행합니다."""
    ai_client = client or create_ai_client()
    rag = rag_service or RAGService(client=ai_client)
    references = rag.search(
        review_text,
        top_k=top_k,
        sub_type=classification.get("sub_type"),
        risk_level=classification.get("risk_level"),
        order_type=order_type,
    )
    sentiment = classification.get("sentiment")
    forbidden = (store_info.get("reply_forbidden") or "").strip() or None

    generated: Dict[str, Any] = {}
    for attempt in range(MAX_SELF_REVIEW_RETRIES + 1):
        generated = generate_reply(
            review_text,
            interpretation,
            store_info,
            sentiment=sentiment,
            rag_references=references,
            client=ai_client,
        )
        review_result = self_review(
            generated["reply_text"],
            sentiment=sentiment,
            forbidden=forbidden,
            client=ai_client,
        )
        if review_result["passed"] or attempt == MAX_SELF_REVIEW_RETRIES:
            break

    if not generated["reply_text"]:
        status = "analyzed"
    else:
        status = determine_approval(
            classification.get("risk_level"),
            classification.get("sentiment"),
        )
    return {
        "reply_text": generated["reply_text"],
        "status": status,
        "rag_references": generated["rag_references"],
    }
