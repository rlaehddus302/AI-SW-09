from __future__ import annotations

import json
from typing import Any, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app import ai_contract
from app.database import SessionLocal, get_db
from app.models import OrderType, Review, ReviewStatus, RiskLevel, Sentiment
from app.routers.utils import (
    get_review_or_404,
    get_reviews_or_404,
    get_store_or_404,
    parse_json_object,
    require_batch_status,
    require_status,
)
from app.schemas.review import (
    ActionResponse,
    AnalysisTaskResponse,
    BatchReviewRequest,
    RegenerateTaskResponse,
)
from app.websocket import manager

router = APIRouter(prefix="/stores/{store_id}/reviews", tags=["analysis"])


def _task_id() -> str:
    return f"task_{uuid4().hex[:12]}"


def _progress(current: int, total: int) -> dict[str, int]:
    return {
        "current": current,
        "total": total,
        "percentage": int(current / total * 100) if total else 100,
    }


def _enum_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def determine_approval(
    risk_level: Optional[Union[RiskLevel, str]],
    sentiment: Optional[Union[Sentiment, str]],
) -> ReviewStatus:
    risk = _enum_value(risk_level)
    sent = _enum_value(sentiment)
    if risk == RiskLevel.LOW.value and sent == Sentiment.POSITIVE.value:
        return ReviewStatus.AUTO_REPLIED
    if risk in (RiskLevel.MEDIUM.value, RiskLevel.HIGH.value):
        return ReviewStatus.NEEDS_APPROVAL
    if sent == Sentiment.MALICIOUS.value:
        return ReviewStatus.NEEDS_APPROVAL
    return ReviewStatus.NEEDS_APPROVAL


def _classification_payload(result: dict[str, Any]) -> dict[str, Any]:
    sentiment = result.get("sentiment")
    risk_level = result.get("risk_level")
    sub_type = result.get("sub_type")

    if sentiment not in {item.value for item in Sentiment}:
        sentiment = Sentiment.NEGATIVE.value
    if risk_level not in {item.value for item in RiskLevel}:
        risk_level = RiskLevel.MEDIUM.value
    if sentiment == Sentiment.POSITIVE.value:
        sub_type = None
    elif sentiment == Sentiment.MALICIOUS.value and not sub_type:
        sub_type = "악성"
    elif not sub_type:
        sub_type = "기타"

    return {"sentiment": sentiment, "sub_type": sub_type, "risk_level": risk_level}


def _interpretation_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "core_issue": result.get("core_issue"),
        "action_direction": result.get("action_direction"),
        "reply_tone": result.get("reply_tone"),
    }


def _normalize_rag_references(result: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for item in result or []:
        if not isinstance(item, dict) or not item.get("review") or not item.get("reply"):
            continue
        normalized = {"review": item["review"], "reply": item["reply"]}
        if item.get("similarity") is not None:
            normalized["similarity"] = float(item["similarity"])
        references.append(normalized)
    return references


async def _call_with_retry(func, *args, **kwargs):
    last_error: Optional[Exception] = None
    for _ in range(2):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - task error is reported through WebSocket.
            last_error = exc
    raise last_error or RuntimeError("AI task failed")


async def _broadcast_progress(
    store_id: int,
    *,
    message_type: str,
    task_id: str,
    review_id: int,
    step: str,
    step_status: str,
    current: int,
    total: int,
) -> None:
    await manager.broadcast(
        store_id,
        {
            "type": message_type,
            "task_id": task_id,
            "review_id": review_id,
            "step": step,
            "status": step_status,
            "progress": _progress(current, total),
        },
    )


async def run_analysis_task(task_id: str, store_id: int, review_ids: list[int]) -> None:
    success = 0
    failed = 0
    total = len(review_ids)
    with SessionLocal() as db:
        for index, review_id in enumerate(review_ids, start=1):
            review = db.get(Review, review_id)
            if review is None or review.store_id != store_id:
                failed += 1
                continue
            try:
                await _broadcast_progress(
                    store_id,
                    message_type="analysis_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="classification",
                    step_status="started",
                    current=index,
                    total=total,
                )
                raw_classification = await _call_with_retry(ai_contract.classify_review, review.review_text)
                classification = _classification_payload(raw_classification)
                review.sentiment = Sentiment(classification["sentiment"])
                review.sub_type = classification["sub_type"]
                review.risk_level = RiskLevel(classification["risk_level"])
                db.commit()
                await _broadcast_progress(
                    store_id,
                    message_type="analysis_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="classification",
                    step_status="completed",
                    current=index,
                    total=total,
                )

                await _broadcast_progress(
                    store_id,
                    message_type="analysis_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="interpretation",
                    step_status="started",
                    current=index,
                    total=total,
                )
                raw_interpretation = await _call_with_retry(
                    ai_contract.interpret_review,
                    review.review_text,
                    classification,
                )
                interpretation = _interpretation_payload(raw_interpretation)
                review.interpretation = json.dumps(interpretation, ensure_ascii=False)
                review.reply_tone = interpretation.get("reply_tone")
                review.status = ReviewStatus.ANALYZED
                db.commit()
                success += 1
                await _broadcast_progress(
                    store_id,
                    message_type="analysis_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="interpretation",
                    step_status="completed",
                    current=index,
                    total=total,
                )
            except Exception as exc:  # noqa: BLE001 - task error is reported through WebSocket.
                db.rollback()
                review = db.get(Review, review_id)
                if review is not None:
                    review.status = ReviewStatus.PENDING
                    db.commit()
                failed += 1
                await manager.broadcast(
                    store_id,
                    {
                        "type": "error",
                        "task_id": task_id,
                        "review_id": review_id,
                        "error": str(exc),
                        "fallback_action": "status를 pending으로 되돌렸습니다.",
                    },
                )
    await manager.broadcast(
        store_id,
        {
            "type": "task_complete",
            "task_id": task_id,
            "result": "success" if failed == 0 else "partial_failure",
            "summary": {"total": total, "success": success, "failed": failed},
        },
    )


async def run_generation_task(
    task_id: str,
    store_id: int,
    review_ids: list[int],
    restore_status: ReviewStatus = ReviewStatus.ANALYZED,
) -> None:
    success = 0
    failed = 0
    total = len(review_ids)
    with SessionLocal() as db:
        store = get_store_or_404(db, store_id)
        for index, review_id in enumerate(review_ids, start=1):
            review = db.get(Review, review_id)
            if review is None or review.store_id != store_id:
                failed += 1
                continue
            try:
                await _broadcast_progress(
                    store_id,
                    message_type="generation_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="rag_search",
                    step_status="started",
                    current=index,
                    total=total,
                )
                rag_references = _normalize_rag_references(
                    await ai_contract.search_rag_references(
                        review_text=review.review_text,
                        store_id=store_id,
                        sub_type=review.sub_type,
                        order_type=review.order_type.value,
                        limit=3,
                    )
                )
                review.rag_references = json.dumps(rag_references, ensure_ascii=False)
                db.commit()
                await _broadcast_progress(
                    store_id,
                    message_type="generation_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="rag_search",
                    step_status="completed",
                    current=index,
                    total=total,
                )

                await _broadcast_progress(
                    store_id,
                    message_type="generation_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="reply_generation",
                    step_status="started",
                    current=index,
                    total=total,
                )
                raw_reply = await _call_with_retry(
                    ai_contract.generate_reply,
                    review_text=review.review_text,
                    interpretation=parse_json_object(review.interpretation) or {},
                    store_info={"store_name": store.store_name, "origin_info": store.origin_info},
                    rag_references=rag_references,
                )
                reply_text = raw_reply.get("reply_text") if isinstance(raw_reply, dict) else None
                if not reply_text:
                    raise ValueError("reply_text is empty")
                review.reply_text = str(reply_text)[:500]
                db.commit()
                await _broadcast_progress(
                    store_id,
                    message_type="generation_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="reply_generation",
                    step_status="completed",
                    current=index,
                    total=total,
                )

                await _broadcast_progress(
                    store_id,
                    message_type="generation_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="approval_gate",
                    step_status="started",
                    current=index,
                    total=total,
                )
                review.status = determine_approval(review.risk_level, review.sentiment)
                db.commit()
                success += 1
                await _broadcast_progress(
                    store_id,
                    message_type="generation_progress",
                    task_id=task_id,
                    review_id=review.id,
                    step="approval_gate",
                    step_status="completed",
                    current=index,
                    total=total,
                )
            except Exception as exc:  # noqa: BLE001 - task error is reported through WebSocket.
                db.rollback()
                review = db.get(Review, review_id)
                if review is not None:
                    review.status = restore_status
                    if restore_status == ReviewStatus.ANALYZED:
                        review.reply_text = review.reply_text or ""
                    db.commit()
                failed += 1
                await manager.broadcast(
                    store_id,
                    {
                        "type": "error",
                        "task_id": task_id,
                        "review_id": review_id,
                        "error": str(exc),
                        "fallback_action": f"status를 {restore_status.value}로 되돌렸습니다.",
                    },
                )
    await manager.broadcast(
        store_id,
        {
            "type": "task_complete",
            "task_id": task_id,
            "result": "success" if failed == 0 else "partial_failure",
            "summary": {"total": total, "success": success, "failed": failed},
        },
    )


async def save_approved_reply_task(store_id: int, review_id: int) -> None:
    with SessionLocal() as db:
        review = db.get(Review, review_id)
        if review is None or review.store_id != store_id or not review.reply_text:
            return
        try:
            await ai_contract.save_approved_reply(
                review=review.review_text,
                reply=review.reply_text,
                store_id=store_id,
                sub_type=review.sub_type,
                risk_level=review.risk_level.value if review.risk_level else None,
                order_type=review.order_type.value,
            )
        except ai_contract.AIServiceUnavailable:
            return


@router.post("/analyze", response_model=AnalysisTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def analyze_reviews(
    store_id: int,
    payload: BatchReviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AnalysisTaskResponse:
    get_store_or_404(db, store_id)
    reviews = get_reviews_or_404(db, store_id, payload.review_ids)
    require_batch_status(reviews, {ReviewStatus.PENDING}, "분석 시작")
    for review in reviews:
        review.status = ReviewStatus.ANALYZING
    db.commit()
    task_id = _task_id()
    background_tasks.add_task(run_analysis_task, task_id, store_id, payload.review_ids)
    return AnalysisTaskResponse(
        task_id=task_id,
        message="분석이 시작되었습니다. WebSocket으로 진행 상황을 확인하세요.",
        total=len(payload.review_ids),
    )


@router.post("/generate-replies", response_model=AnalysisTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_replies(
    store_id: int,
    payload: BatchReviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AnalysisTaskResponse:
    get_store_or_404(db, store_id)
    reviews = get_reviews_or_404(db, store_id, payload.review_ids)
    require_batch_status(reviews, {ReviewStatus.ANALYZED}, "답변 생성")
    for review in reviews:
        review.status = ReviewStatus.GENERATING
    db.commit()
    task_id = _task_id()
    background_tasks.add_task(run_generation_task, task_id, store_id, payload.review_ids, ReviewStatus.ANALYZED)
    return AnalysisTaskResponse(
        task_id=task_id,
        message="답변 생성이 시작되었습니다. WebSocket으로 진행 상황을 확인하세요.",
        total=len(payload.review_ids),
    )


@router.post("/{review_id}/approve", response_model=ActionResponse)
def approve_review(
    store_id: int,
    review_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ActionResponse:
    review = get_review_or_404(db, store_id, review_id)
    require_status(review, {ReviewStatus.NEEDS_APPROVAL}, "승인")
    review.status = ReviewStatus.APPROVED
    db.commit()
    background_tasks.add_task(save_approved_reply_task, store_id, review_id)
    return ActionResponse(id=review.id, status=review.status, message="답변이 승인되었습니다.")


@router.post("/{review_id}/reject", response_model=ActionResponse)
def reject_review(store_id: int, review_id: int, db: Session = Depends(get_db)) -> ActionResponse:
    review = get_review_or_404(db, store_id, review_id)
    require_status(review, {ReviewStatus.NEEDS_APPROVAL}, "반려")
    review.status = ReviewStatus.ON_HOLD
    db.commit()
    return ActionResponse(id=review.id, status=review.status, message="답변이 보류 처리되었습니다.")


@router.post("/{review_id}/regenerate", response_model=RegenerateTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def regenerate_reply(
    store_id: int,
    review_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RegenerateTaskResponse:
    review = get_review_or_404(db, store_id, review_id)
    require_status(review, {ReviewStatus.ON_HOLD}, "답변 재생성")
    review.status = ReviewStatus.GENERATING
    db.commit()
    task_id = _task_id()
    background_tasks.add_task(run_generation_task, task_id, store_id, [review_id], ReviewStatus.ON_HOLD)
    return RegenerateTaskResponse(task_id=task_id, message="답변을 다시 생성합니다.")
