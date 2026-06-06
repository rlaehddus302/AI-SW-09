from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app import ai_contract
from app.database import SessionLocal, get_db
from app.models import OrderType, Review, ReviewStatus, RiskLevel, Sentiment
from app.openapi_examples import (
    ACTION_CONFLICT_RESPONSE,
    ANALYSIS_CONFLICT_RESPONSE,
    ANALYSIS_TASK_RESPONSE,
    APPROVE_ACTION_RESPONSE,
    BATCH_REVIEW_NOT_FOUND_RESPONSE,
    GENERATION_CONFLICT_RESPONSE,
    GENERATION_TASK_RESPONSE,
    REGENERATE_CONFLICT_RESPONSE,
    REGENERATE_TASK_RESPONSE,
    REJECT_ACTION_RESPONSE,
    REVIEW_NOT_FOUND_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)
from app.routers.utils import (
    get_review_or_404,
    get_reviews_or_404,
    get_store_or_404,
    parse_json_object,
    require_batch_status,
    require_status,
    review_detail_from_model,
)
from app.schemas.review import (
    ActionResponse,
    AnalysisTaskResponse,
    BatchReviewRequest,
    RegenerateTaskResponse,
)
from app.websocket import manager

router = APIRouter(prefix="/stores/{store_id}/reviews", tags=["analysis"])
MAX_CONCURRENT_REVIEW_TASKS = 4
_MAX_SELF_REVIEW_RETRIES = 2


def _task_id() -> str:
    """클라이언트에 전달할 짧은 백그라운드 작업 id를 생성합니다."""

    return f"task_{uuid4().hex[:12]}"


def _progress(current: int, total: int) -> dict[str, int]:
    """WebSocket으로 보내는 공통 진행률 payload를 생성합니다."""

    return {
        "current": current,
        "total": total,
        "percentage": int(current / total * 100) if total else 100,
    }


def _enum_value(value: Any) -> Optional[str]:
    """enum 또는 문자열 값을 일반 문자열로 바꾸고 None은 그대로 둡니다."""

    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def determine_approval(
    risk_level: Optional[Union[RiskLevel, str]],
    sentiment: Optional[Union[Sentiment, str]],
) -> ReviewStatus:
    """생성된 답변을 자동 답변 처리할지 승인 필요 상태로 둘지 결정합니다."""

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
    """AI 분류 결과를 DB enum 컬럼에 저장 가능한 값으로 정규화합니다."""

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
    """리뷰 모델에 저장하는 해석 필드만 추려냅니다."""

    return {
        "core_issue": result.get("core_issue"),
        "action_direction": result.get("action_direction"),
        "reply_tone": result.get("reply_tone"),
    }


def _normalize_rag_references(result: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """RAG 참고 사례를 직렬화 가능한 리뷰/답변 쌍으로 정리합니다."""

    references: list[dict[str, Any]] = []
    for item in result or []:
        if not isinstance(item, dict) or not item.get("review") or not item.get("reply"):
            continue
        normalized = {"review": item["review"], "reply": item["reply"]}
        if item.get("similarity") is not None:
            normalized["similarity"] = float(item["similarity"])
        references.append(normalized)
    return references


def _call_in_thread(func, *args, **kwargs):
    """동기 또는 비동기 AI 함수를 워커 스레드 안에서 실행합니다."""

    value = func(*args, **kwargs)
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


async def _call_with_retry(func, *args, **kwargs):
    """AI 단계 하나를 최대 한 번 재시도하고 이벤트 루프 블로킹을 피합니다."""

    last_error: Optional[Exception] = None
    for _ in range(2):
        try:
            return await asyncio.to_thread(_call_in_thread, func, *args, **kwargs)
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
    """리뷰 작업의 단계별 진행 이벤트를 브로드캐스트합니다."""

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


async def _broadcast_review_updated(
    store_id: int,
    *,
    task_id: str,
    review: Review,
    event: str,
    step: str,
    step_status: str,
    current: int,
    total: int,
    error: Optional[str] = None,
) -> None:
    """단계가 DB 데이터를 바꾼 뒤 최신 리뷰 스냅샷을 브로드캐스트합니다."""

    message = {
        "type": "review_updated",
        "task_id": task_id,
        "event": event,
        "step": step,
        "status": step_status,
        "review_id": review.id,
        "review": review_detail_from_model(review).model_dump(mode="json"),
        "progress": _progress(current, total),
    }
    if error:
        message["error"] = error
    await manager.broadcast(store_id, message)


async def _record_completion(summary: dict[str, int], lock: asyncio.Lock, *, succeeded: bool) -> int:
    """공유 작업 카운터를 안전하게 갱신하고 완료 수를 반환합니다."""

    async with lock:
        summary["completed"] += 1
        if succeeded:
            summary["success"] += 1
        else:
            summary["failed"] += 1
        return summary["completed"]


async def run_analysis_task(task_id: str, store_id: int, review_ids: list[int]) -> None:
    """선택한 리뷰를 동시에 분석하고 리뷰별 변경사항을 실시간 전송합니다."""

    total = len(review_ids)
    summary = {"completed": 0, "success": 0, "failed": 0}
    summary_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REVIEW_TASKS)

    async def process_review(review_id: int) -> None:
        """리뷰 id 하나에 대해 분류와 해석 단계를 실행합니다."""

        async with semaphore:
            with SessionLocal() as db:
                review = db.get(Review, review_id)
                if review is None or review.store_id != store_id:
                    await _record_completion(summary, summary_lock, succeeded=False)
                    return
                try:
                    await _broadcast_progress(
                        store_id,
                        message_type="analysis_progress",
                        task_id=task_id,
                        review_id=review.id,
                        step="analyzation",
                        step_status="started",
                        current=summary["completed"],
                        total=total,
                    )

                    raw_analysis = await _call_with_retry(ai_contract.analyze_review, review.review_text)
                    classification = _classification_payload(raw_analysis)
                    review.sentiment = Sentiment(classification["sentiment"])
                    review.sub_type = classification["sub_type"]
                    review.risk_level = RiskLevel(classification["risk_level"])
                    db.commit()
                    db.refresh(review)
                    await _broadcast_review_updated(
                        store_id,
                        task_id=task_id,
                        review=review,
                        event="classification_completed",
                        step="classification",
                        step_status="completed",
                        current=summary["completed"],
                        total=total,
                    )
                    interpretation = _interpretation_payload(raw_analysis)
                    review.interpretation = json.dumps(interpretation, ensure_ascii=False)
                    review.reply_tone = interpretation.get("reply_tone")
                    review.status = ReviewStatus.ANALYZED
                    db.commit()
                    db.refresh(review)
                    current = await _record_completion(summary, summary_lock, succeeded=True)
                    await _broadcast_review_updated(
                        store_id,
                        task_id=task_id,
                        review=review,
                        event="analysis_completed",
                        step="interpretation",
                        step_status="completed",
                        current=current,
                        total=total,
                    )
                except Exception as exc:  # noqa: BLE001 - task error is reported through WebSocket.
                    db.rollback()
                    review = db.get(Review, review_id)
                    current = await _record_completion(summary, summary_lock, succeeded=False)
                    if review is not None:
                        review.status = ReviewStatus.PENDING
                        db.commit()
                        db.refresh(review)
                        await _broadcast_review_updated(
                            store_id,
                            task_id=task_id,
                            review=review,
                            event="analysis_failed",
                            step="analysis",
                            step_status="failed",
                            current=current,
                            total=total,
                            error=str(exc),
                        )
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

    await asyncio.gather(*(process_review(review_id) for review_id in review_ids))

    async with summary_lock:
        success = summary["success"]
        failed = summary["failed"]
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
    """답변을 동시에 생성하고 RAG, 답변, 승인 게이트 변경사항을 실시간 전송합니다."""

    total = len(review_ids)
    summary = {"completed": 0, "success": 0, "failed": 0}
    summary_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REVIEW_TASKS)
    with SessionLocal() as db:
        store = get_store_or_404(db, store_id)
        store_info = {
            "store_name": store.store_name,
            "origin_info": store.origin_info,
            "reply_tone_style": store.reply_tone_style,
            "reply_opening": store.reply_opening,
            "reply_closing": store.reply_closing,
            "reply_emphasis": store.reply_emphasis,
            "reply_forbidden": store.reply_forbidden,
        }

    async def process_review(review_id: int) -> None:
        """리뷰 하나에 대해 RAG 검색, 답변 생성, 승인 게이트를 실행합니다."""

        async with semaphore:
            with SessionLocal() as db:
                review = db.get(Review, review_id)
                if review is None or review.store_id != store_id:
                    await _record_completion(summary, summary_lock, succeeded=False)
                    return
                try:
                    await _broadcast_progress(
                        store_id,
                        message_type="generation_progress",
                        task_id=task_id,
                        review_id=review.id,
                        step="rag_search",
                        step_status="started",
                        current=summary["completed"],
                        total=total,
                    )
                    rag_references = _normalize_rag_references(
                        await _call_with_retry(
                            ai_contract.search_rag_references,
                            review_text=review.review_text,
                            store_id=store_id,
                            sub_type=review.sub_type,
                            order_type=review.order_type.value,
                            limit=3,
                        )
                    )
                    review.rag_references = json.dumps(rag_references, ensure_ascii=False)
                    db.commit()
                    db.refresh(review)
                    await _broadcast_review_updated(
                        store_id,
                        task_id=task_id,
                        review=review,
                        event="rag_search_completed",
                        step="rag_search",
                        step_status="completed",
                        current=summary["completed"],
                        total=total,
                    )

                    _sr_forbidden = (store_info.get("reply_forbidden") or "").strip() or None
                    for _attempt in range(_MAX_SELF_REVIEW_RETRIES + 1):
                        await _broadcast_progress(
                            store_id,
                            message_type="generation_progress",
                            task_id=task_id,
                            review_id=review.id,
                            step="reply_generation",
                            step_status="started",
                            current=summary["completed"],
                            total=total,
                        )
                        raw_reply = await _call_with_retry(
                            ai_contract.generate_reply,
                            review_text=review.review_text,
                            interpretation=parse_json_object(review.interpretation) or {},
                            store_info=store_info,
                            rag_references=rag_references,
                            sentiment=review.sentiment.value if review.sentiment else None,
                        )
                        reply_text = raw_reply.get("reply_text") if isinstance(raw_reply, dict) else None
                        if not reply_text:
                            raise ValueError("reply_text is empty")
                        review.reply_text = str(reply_text)[:500]
                        db.commit()
                        db.refresh(review)
                        await _broadcast_review_updated(
                            store_id,
                            task_id=task_id,
                            review=review,
                            event="reply_generation_completed",
                            step="reply_generation",
                            step_status="completed",
                            current=summary["completed"],
                            total=total,
                        )
                        await _broadcast_progress(
                            store_id,
                            message_type="generation_progress",
                            task_id=task_id,
                            review_id=review.id,
                            step="self_review",
                            step_status="started",
                            current=_attempt,
                            total=_MAX_SELF_REVIEW_RETRIES + 1,
                        )
                        _sr_result = await _call_with_retry(
                            ai_contract.self_review,
                            reply_text=review.reply_text,
                            sentiment=review.sentiment.value if review.sentiment else None,
                            forbidden=_sr_forbidden,
                        )
                        _sr_passed = bool(_sr_result.get("passed", True))
                        await manager.broadcast(
                            store_id,
                            {
                                "type": "generation_progress",
                                "task_id": task_id,
                                "review_id": review.id,
                                "step": "self_review",
                                "status": "passed" if _sr_passed else "failed",
                                "reason": _sr_result.get("reason"),
                                "attempt": _attempt + 1,
                                "progress": _progress(summary["completed"], total),
                            },
                        )
                        if _sr_passed or _attempt == _MAX_SELF_REVIEW_RETRIES:
                            break

                    await _broadcast_progress(
                        store_id,
                        message_type="generation_progress",
                        task_id=task_id,
                        review_id=review.id,
                        step="approval_gate",
                        step_status="started",
                        current=summary["completed"],
                        total=total,
                    )
                    review.status = determine_approval(review.risk_level, review.sentiment)
                    db.commit()
                    db.refresh(review)
                    current = await _record_completion(summary, summary_lock, succeeded=True)
                    await _broadcast_review_updated(
                        store_id,
                        task_id=task_id,
                        review=review,
                        event="generation_completed",
                        step="approval_gate",
                        step_status="completed",
                        current=current,
                        total=total,
                    )
                except Exception as exc:  # noqa: BLE001 - task error is reported through WebSocket.
                    db.rollback()
                    review = db.get(Review, review_id)
                    current = await _record_completion(summary, summary_lock, succeeded=False)
                    if review is not None:
                        review.status = restore_status
                        if restore_status == ReviewStatus.ANALYZED:
                            review.reply_text = review.reply_text or ""
                        db.commit()
                        db.refresh(review)
                        await _broadcast_review_updated(
                            store_id,
                            task_id=task_id,
                            review=review,
                            event="generation_failed",
                            step="generation",
                            step_status="failed",
                            current=current,
                            total=total,
                            error=str(exc),
                        )
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
    await asyncio.gather(*(process_review(review_id) for review_id in review_ids))

    async with summary_lock:
        success = summary["success"]
        failed = summary["failed"]
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
    """API 응답을 막지 않고 승인된 답변을 RAG 저장소에 저장합니다."""

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


@router.post(
    "/analyze",
    response_model=AnalysisTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_202_ACCEPTED: ANALYSIS_TASK_RESPONSE,
        status.HTTP_404_NOT_FOUND: BATCH_REVIEW_NOT_FOUND_RESPONSE,
        status.HTTP_409_CONFLICT: ANALYSIS_CONFLICT_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
def analyze_reviews(
    store_id: int,
    payload: BatchReviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AnalysisTaskResponse:
    """미분석 리뷰의 비동기 분석 작업을 시작합니다."""

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


@router.post(
    "/generate-replies",
    response_model=AnalysisTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_202_ACCEPTED: GENERATION_TASK_RESPONSE,
        status.HTTP_404_NOT_FOUND: BATCH_REVIEW_NOT_FOUND_RESPONSE,
        status.HTTP_409_CONFLICT: GENERATION_CONFLICT_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
def generate_replies(
    store_id: int,
    payload: BatchReviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AnalysisTaskResponse:
    """분석 완료 리뷰의 비동기 답변 생성 작업을 시작합니다."""

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


@router.post(
    "/{review_id}/approve",
    response_model=ActionResponse,
    responses={
        status.HTTP_200_OK: APPROVE_ACTION_RESPONSE,
        status.HTTP_404_NOT_FOUND: REVIEW_NOT_FOUND_RESPONSE,
        status.HTTP_409_CONFLICT: ACTION_CONFLICT_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
def approve_review(
    store_id: int,
    review_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ActionResponse:
    """생성된 답변을 승인하고 향후 RAG 재사용 저장을 예약합니다."""

    review = get_review_or_404(db, store_id, review_id)
    require_status(review, {ReviewStatus.NEEDS_APPROVAL}, "승인")
    review.status = ReviewStatus.APPROVED
    db.commit()
    background_tasks.add_task(save_approved_reply_task, store_id, review_id)
    return ActionResponse(id=review.id, status=review.status, message="답변이 승인되었습니다.")


@router.post(
    "/{review_id}/reject",
    response_model=ActionResponse,
    responses={
        status.HTTP_200_OK: REJECT_ACTION_RESPONSE,
        status.HTTP_404_NOT_FOUND: REVIEW_NOT_FOUND_RESPONSE,
        status.HTTP_409_CONFLICT: ACTION_CONFLICT_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
def reject_review(store_id: int, review_id: int, db: Session = Depends(get_db)) -> ActionResponse:
    """승인 필요 답변을 보류 상태로 바꿔 재생성할 수 있게 합니다."""

    review = get_review_or_404(db, store_id, review_id)
    require_status(review, {ReviewStatus.NEEDS_APPROVAL}, "반려")
    review.status = ReviewStatus.ON_HOLD
    db.commit()
    return ActionResponse(id=review.id, status=review.status, message="답변이 보류 처리되었습니다.")


@router.post(
    "/{review_id}/regenerate",
    response_model=RegenerateTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_202_ACCEPTED: REGENERATE_TASK_RESPONSE,
        status.HTTP_404_NOT_FOUND: REVIEW_NOT_FOUND_RESPONSE,
        status.HTTP_409_CONFLICT: REGENERATE_CONFLICT_RESPONSE,
        422: VALIDATION_ERROR_RESPONSE,
    },
)
def regenerate_reply(
    store_id: int,
    review_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RegenerateTaskResponse:
    """보류된 리뷰의 답변 재생성 작업을 시작합니다."""

    review = get_review_or_404(db, store_id, review_id)
    require_status(review, {ReviewStatus.ON_HOLD}, "답변 재생성")
    review.status = ReviewStatus.GENERATING
    db.commit()
    task_id = _task_id()
    background_tasks.add_task(run_generation_task, task_id, store_id, [review_id], ReviewStatus.ON_HOLD)
    return RegenerateTaskResponse(task_id=task_id, message="답변을 다시 생성합니다.")
