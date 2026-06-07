from __future__ import annotations

import inspect
from importlib import import_module
from typing import Any, Optional


class AIServiceUnavailable(RuntimeError):
    """선택형 AI 서비스 어댑터를 불러오지 못했을 때 사용하는 예외입니다."""
    pass


async def _maybe_await(value: Any) -> Any:
    """일반 값은 그대로 돌려주고 코루틴이면 await 처리합니다."""
    if inspect.isawaitable(value):
        return await value
    return value


def _load_callable(module_name: str, function_name: str):
    """테스트에서 교체하기 쉽도록 서비스 함수를 지연 import합니다."""
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AIServiceUnavailable(f"{module_name}.{function_name} is not available") from exc
    func = getattr(module, function_name, None)
    if func is None or not callable(func):
        raise AIServiceUnavailable(f"{module_name}.{function_name} is not callable")
    return func


async def classify_review(review_text: str) -> dict[str, Any]:
    """설정된 분류 서비스로 리뷰 1건을 분류합니다."""
    func = _load_callable("app.services.classification", "classify_review")
    return await _maybe_await(func(review_text=review_text))


async def interpret_review(review_text: str, classification: dict[str, Any]) -> dict[str, Any]:
    """분류 결과를 바탕으로 리뷰의 핵심 이슈와 답변 방향을 해석합니다."""
    func = _load_callable("app.services.interpretation", "interpret_review")
    return await _maybe_await(func(review_text=review_text, classification=classification))

async def analyze_review(review_text: str) -> dict[str, Any]:
    """설정된 분류 및 해석 서비스로 리뷰 1건을 분류 및 해석합니다."""
    func = _load_callable("app.services.analyzation", "analyze_review")
    return await _maybe_await(func(review_text=review_text))

async def search_rag_references(
    *,
    review_text: str,
    store_id: int,
    sub_type: Optional[str],
    order_type: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """답변 생성에 사용할 유사 승인 답변 사례를 검색합니다."""
    func = _load_callable("app.services.rag_service", "search_similar_reviews")
    return await _maybe_await(
        func(
            review_text=review_text,
            store_id=store_id,
            sub_type=sub_type,
            order_type=order_type,
            limit=limit,
        )
    )


async def generate_reply(
    *,
    review_text: str,
    interpretation: dict[str, Any],
    store_info: dict[str, Any],
    rag_references: list[dict[str, Any]],
    sentiment: Optional[str] = None,
) -> dict[str, Any]:
    """분석된 리뷰 1건에 대한 사장님 답변 초안을 생성합니다."""
    func = _load_callable("app.services.reply_generation", "generate_reply")
    return await _maybe_await(
        func(
            review_text=review_text,
            interpretation=interpretation,
            store_info=store_info,
            rag_references=rag_references,
            sentiment=sentiment,
        )
    )


async def self_review(
    *,
    reply_text: str,
    sentiment: Optional[str] = None,
    forbidden: Optional[str] = None,
) -> dict[str, Any]:
    """생성된 답변을 LLM이 스스로 점검하고 통과/실패 결과를 반환합니다."""
    func = _load_callable("app.services.reply_generation", "self_review")
    return await _maybe_await(
        func(reply_text=reply_text, sentiment=sentiment, forbidden=forbidden)
    )


async def save_approved_reply(
    *,
    review: str,
    reply: str,
    store_id: int,
    sub_type: Optional[str],
    risk_level: Optional[str],
    order_type: str,
) -> None:
    """승인된 답변을 이후 RAG 검색에 재사용할 수 있도록 저장합니다."""
    func = _load_callable("app.services.rag_service", "save_approved_reply")
    await _maybe_await(
        func(
            review=review,
            reply=reply,
            store_id=store_id,
            sub_type=sub_type,
            risk_level=risk_level,
            order_type=order_type,
        )
    )


async def seed_rag_pairs(pairs: list[dict[str, Any]], store_id: int) -> None:
    """데모 스토어의 초기 RAG 예시 데이터를 저장합니다."""
    func = _load_callable("app.services.rag_service", "seed_rag_pairs")
    await _maybe_await(func(pairs=pairs, store_id=store_id))
