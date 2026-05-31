"""Swagger 문서에서 사용하는 요청/응답 예시입니다."""

STORE_EXAMPLE = {
    "id": 1,
    "store_name": "민트치킨 성수점",
    "origin_info": "닭고기: 국내산",
    "is_dine_in": True,
    "is_takeout": True,
    "is_delivery": True,
    "created_at": "2026-05-31T10:00:00",
}

STORE_REQUEST_EXAMPLE = {
    "store_name": "민트치킨 성수점",
    "origin_info": "닭고기: 국내산",
    "is_dine_in": True,
    "is_takeout": True,
    "is_delivery": True,
}

REVIEW_LIST_ITEM_EXAMPLE = {
    "id": 3,
    "review_text": "배달이 1시간 넘게 걸렸고 감자가 식어 있었어요.",
    "reviewer_name": "기다림끝",
    "rating": 2,
    "order_type": "delivery",
    "sentiment": "negative",
    "sub_type": "배달지연",
    "risk_level": "medium",
    "status": "analyzed",
    "reply_text": None,
    "created_at": "2026-05-31T12:05:00",
}

REVIEW_LIST_EXAMPLE = {
    "total": 30,
    "page": 1,
    "size": 20,
    "reviews": [REVIEW_LIST_ITEM_EXAMPLE],
}

INTERPRETATION_EXAMPLE = {
    "core_issue": "배달 지연으로 인한 음식 품질 저하",
    "action_direction": "사과와 배달 동선 점검 약속",
    "reply_tone": "사과",
}

RAG_REFERENCE_EXAMPLE = {
    "review": "배달이 늦고 음식이 식어 있었습니다.",
    "reply": "불편을 드려 죄송합니다. 배달 동선을 다시 점검하겠습니다.",
    "similarity": 0.87,
}

REVIEW_DETAIL_EXAMPLE = {
    **REVIEW_LIST_ITEM_EXAMPLE,
    "store_id": 1,
    "interpretation": INTERPRETATION_EXAMPLE,
    "reply_text": "안녕하세요, 민트치킨 성수점입니다. 배달 지연으로 불편을 드려 죄송합니다.",
    "status": "needs_approval",
    "rag_references": [RAG_REFERENCE_EXAMPLE],
    "updated_at": "2026-05-31T12:16:00",
}

REVIEW_STATS_EXAMPLE = {
    "total_reviews": 30,
    "sentiment_distribution": {"positive": 10, "negative": 18, "malicious": 2},
    "risk_distribution": {"low": 10, "medium": 15, "high": 5},
    "status_distribution": {
        "pending": 0,
        "analyzing": 0,
        "analyzed": 12,
        "generating": 0,
        "auto_replied": 10,
        "needs_approval": 8,
        "approved": 0,
        "on_hold": 0,
    },
    "sub_type_distribution": {"배달지연": 7, "음식맛": 5, "이물질": 2},
}

BATCH_REVIEW_REQUEST_EXAMPLE = {"review_ids": [2, 3, 4]}

ANALYSIS_TASK_EXAMPLE = {
    "task_id": "task_a1b2c3d4e5f6",
    "message": "분석이 시작되었습니다. WebSocket으로 진행 상황을 확인하세요.",
    "total": 3,
}

GENERATION_TASK_EXAMPLE = {
    "task_id": "task_b2c3d4e5f6a7",
    "message": "답변 생성이 시작되었습니다. WebSocket으로 진행 상황을 확인하세요.",
    "total": 3,
}

REGENERATE_TASK_EXAMPLE = {
    "task_id": "task_c3d4e5f6a7b8",
    "message": "답변을 다시 생성합니다.",
}

APPROVE_ACTION_EXAMPLE = {
    "id": 3,
    "status": "approved",
    "message": "답변이 승인되었습니다.",
}

REJECT_ACTION_EXAMPLE = {
    "id": 3,
    "status": "on_hold",
    "message": "답변이 보류 처리되었습니다.",
}

NOT_FOUND_STORE_EXAMPLE = {"detail": "가게를 찾을 수 없습니다."}
NOT_FOUND_REVIEW_EXAMPLE = {"detail": "리뷰를 찾을 수 없습니다."}
BATCH_NOT_FOUND_EXAMPLE = {
    "detail": {"message": "리뷰를 찾을 수 없습니다.", "review_ids": [99]}
}

ANALYSIS_CONFLICT_EXAMPLE = {
    "detail": {
        "message": "분석 시작 가능한 상태가 아닌 리뷰가 포함되어 있습니다.",
        "invalid_reviews": [{"id": 3, "status": "analyzed"}],
        "allowed_statuses": ["pending"],
    }
}

GENERATION_CONFLICT_EXAMPLE = {
    "detail": {
        "message": "답변 생성 가능한 상태가 아닌 리뷰가 포함되어 있습니다.",
        "invalid_reviews": [{"id": 2, "status": "pending"}],
        "allowed_statuses": ["analyzed"],
    }
}

ACTION_CONFLICT_EXAMPLE = {
    "detail": {
        "message": "승인 가능한 상태가 아닙니다.",
        "current_status": "analyzed",
        "allowed_statuses": ["needs_approval"],
    }
}

REGENERATE_CONFLICT_EXAMPLE = {
    "detail": {
        "message": "답변 재생성 가능한 상태가 아닙니다.",
        "current_status": "needs_approval",
        "allowed_statuses": ["on_hold"],
    }
}

VALIDATION_ERROR_EXAMPLE = {
    "detail": [
        {
            "type": "greater_than_equal",
            "loc": ["query", "page"],
            "msg": "Input should be greater than or equal to 1",
            "input": 0,
            "ctx": {"ge": 1},
        }
    ]
}


def json_response(description: str, example: dict) -> dict:
    """OpenAPI responses 항목에 넣을 JSON 예시 응답을 만듭니다."""

    return {
        "description": description,
        "content": {"application/json": {"example": example}},
    }


STORE_RESPONSE = json_response("가게 정보", STORE_EXAMPLE)
STORE_NOT_FOUND_RESPONSE = json_response("가게를 찾을 수 없음", NOT_FOUND_STORE_EXAMPLE)
REVIEW_NOT_FOUND_RESPONSE = json_response("리뷰를 찾을 수 없음", NOT_FOUND_REVIEW_EXAMPLE)
BATCH_REVIEW_NOT_FOUND_RESPONSE = json_response("요청한 리뷰 중 일부가 없음", BATCH_NOT_FOUND_EXAMPLE)
VALIDATION_ERROR_RESPONSE = json_response("요청 validation 실패", VALIDATION_ERROR_EXAMPLE)
REVIEW_LIST_RESPONSE = json_response("리뷰 목록", REVIEW_LIST_EXAMPLE)
REVIEW_DETAIL_RESPONSE = json_response("리뷰 상세", REVIEW_DETAIL_EXAMPLE)
REVIEW_STATS_RESPONSE = json_response("리뷰 통계", REVIEW_STATS_EXAMPLE)
ANALYSIS_TASK_RESPONSE = json_response("분석 작업 시작", ANALYSIS_TASK_EXAMPLE)
GENERATION_TASK_RESPONSE = json_response("답변 생성 작업 시작", GENERATION_TASK_EXAMPLE)
REGENERATE_TASK_RESPONSE = json_response("답변 재생성 작업 시작", REGENERATE_TASK_EXAMPLE)
APPROVE_ACTION_RESPONSE = json_response("답변 승인 완료", APPROVE_ACTION_EXAMPLE)
REJECT_ACTION_RESPONSE = json_response("답변 보류 완료", REJECT_ACTION_EXAMPLE)
ANALYSIS_CONFLICT_RESPONSE = json_response("분석 가능한 상태가 아님", ANALYSIS_CONFLICT_EXAMPLE)
GENERATION_CONFLICT_RESPONSE = json_response("답변 생성 가능한 상태가 아님", GENERATION_CONFLICT_EXAMPLE)
ACTION_CONFLICT_RESPONSE = json_response("상태 전이 불가", ACTION_CONFLICT_EXAMPLE)
REGENERATE_CONFLICT_RESPONSE = json_response("재생성 가능한 상태가 아님", REGENERATE_CONFLICT_EXAMPLE)
