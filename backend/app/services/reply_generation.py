"""Reply generation service and generation-stage pipeline helper."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from ..llm.client import AIClientProtocol, LLMResponseParseError, create_ai_client
from ..llm.prompts import REPLY_GENERATION_SYSTEM_PROMPT
from ..llm.types import ReplyGenerationResult
from .approval_gate import determine_approval
from .interpretation import normalize_interpretation
from .rag_service import RAGService


def generate_reply(
    review_text: str,
    interpretation: Mapping[str, Any],
    store_info: Mapping[str, Any],
    *,
    rag_references: Optional[Sequence[Mapping[str, Any]]] = None,
    client: Optional[AIClientProtocol] = None,
) -> Dict[str, Any]:
    """
    Generate a reply draft.

    If JSON parsing still fails after the client's one retry, this returns an
    empty draft per SPEC so routers can keep the review in analyzed state.
    Timeout/API errors are allowed to propagate.
    """

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
            system_prompt=REPLY_GENERATION_SYSTEM_PROMPT,
            user_payload={
                "review_text": review_text,
                "interpretation": normalized_interpretation,
                "store_info": dict(store_info),
                "rag_references": references,
            },
        )
    except LLMResponseParseError:
        return ReplyGenerationResult(
            reply_text="",
            rag_references=references,
        ).to_dict()

    reply_text = str(raw.get("reply_text") or "").strip()[:500]
    return ReplyGenerationResult(
        reply_text=reply_text,
        rag_references=references,
    ).to_dict()


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
    """
    Run RAG search, reply generation, and approval gate for one analyzed review.

    Return shape is ready for a router to persist:
    {
      "reply_text": str,
      "status": "auto_replied" | "needs_approval" | "analyzed",
      "rag_references": [...]
    }
    """

    ai_client = client or create_ai_client()
    rag = rag_service or RAGService(client=ai_client)
    references = rag.search(
        review_text,
        top_k=top_k,
        sub_type=classification.get("sub_type"),
        risk_level=classification.get("risk_level"),
        order_type=order_type,
    )
    generated = generate_reply(
        review_text,
        interpretation,
        store_info,
        rag_references=references,
        client=ai_client,
    )
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
