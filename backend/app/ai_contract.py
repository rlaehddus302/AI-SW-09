from __future__ import annotations

import inspect
from importlib import import_module
from typing import Any


class AIServiceUnavailable(RuntimeError):
    pass


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _load_callable(module_name: str, function_name: str):
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AIServiceUnavailable(f"{module_name}.{function_name} is not available") from exc
    func = getattr(module, function_name, None)
    if func is None or not callable(func):
        raise AIServiceUnavailable(f"{module_name}.{function_name} is not callable")
    return func


async def classify_review(review_text: str) -> dict[str, Any]:
    func = _load_callable("app.services.classification", "classify_review")
    return await _maybe_await(func(review_text=review_text))


async def interpret_review(review_text: str, classification: dict[str, Any]) -> dict[str, Any]:
    func = _load_callable("app.services.interpretation", "interpret_review")
    return await _maybe_await(func(review_text=review_text, classification=classification))


async def search_rag_references(
    *,
    review_text: str,
    store_id: int,
    sub_type: str | None,
    order_type: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
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
) -> dict[str, Any]:
    func = _load_callable("app.services.reply_generation", "generate_reply")
    return await _maybe_await(
        func(
            review_text=review_text,
            interpretation=interpretation,
            store_info=store_info,
            rag_references=rag_references,
        )
    )


async def save_approved_reply(
    *,
    review: str,
    reply: str,
    store_id: int,
    sub_type: str | None,
    risk_level: str | None,
    order_type: str,
) -> None:
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
    func = _load_callable("app.services.rag_service", "seed_rag_pairs")
    await _maybe_await(func(pairs=pairs, store_id=store_id))
