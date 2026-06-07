"""Upstage Solar 연동 클라이언트와 deterministic mock 클라이언트입니다."""

from __future__ import annotations

import hashlib
import json
import math
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Type
from langchain_upstage import ChatUpstage
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from pydantic import BaseModel
from .tools import check_length_N_forbidden

ALLOWED_AI_MODES = {"live", "mock"}
DEFAULT_TIMEOUT_SECONDS = 30.0


class LLMError(RuntimeError):
    """LLM/임베딩 연동 실패에서 공통으로 사용하는 기준 예외입니다."""
    pass


class LLMConfigurationError(LLMError):
    """live 모드에 필요한 설정이 없을 때 발생합니다."""
    pass


class LLMResponseParseError(LLMError):
    """JSON 파싱 재시도까지 실패했을 때 발생합니다."""
    pass


class LLMTimeoutError(LLMError):
    """Upstage 요청이 설정된 timeout을 넘겼을 때 발생합니다."""
    pass


class AIClientProtocol(Protocol):
    """live/mock AI 클라이언트가 공통으로 만족해야 하는 최소 인터페이스입니다."""
    mode: str

    def complete_json(
        self,
        *,
        task: str,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        RouteDecision: Optional[Type[BaseModel]] = None
    ) -> Any:
        """LLM 작업 1건의 결과를 JSON 객체로 반환합니다."""
        ...

    def embed_text(self, text: str, *, purpose: str = "query") -> List[float]:
        """검색용 query 또는 저장용 passage 텍스트 임베딩 벡터를 반환합니다."""
        ...


HttpPost = Callable[[str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]]


@dataclass(frozen=True)
class UpstageConfig:
    """Upstage chat/embedding 호출에 필요한 런타임 설정입니다."""
    api_key: Optional[str] = None
    ai_mode: str = "mock"
    base_url: str = "https://api.upstage.ai/v1"
    chat_model: str = "solar-pro3"
    embedding_url: str = "https://api.upstage.ai/v1/solar/embeddings"
    embedding_query_model: str = "solar-embedding-1-large-query"
    embedding_passage_model: str = "solar-embedding-1-large-passage"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "UpstageConfig":
        """공통 Settings 객체에서 Upstage 설정을 구성합니다."""
        from app.config import get_settings

        settings = get_settings()
        embedding_query_model = (
            settings.upstage_embedding_query_model
            or settings.upstage_embedding_model
            or cls.embedding_query_model
        )
        embedding_passage_model = (
            settings.upstage_embedding_passage_model
            or settings.upstage_embedding_model
            or cls.embedding_passage_model
        )
        return cls(
            api_key=settings.upstage_api_key,
            ai_mode=settings.ai_mode,
            base_url=settings.upstage_base_url,
            chat_model=settings.upstage_chat_model,
            embedding_url=settings.upstage_embedding_url,
            embedding_query_model=embedding_query_model,
            embedding_passage_model=embedding_passage_model,
            timeout_seconds=settings.ai_timeout_seconds,
        )


def normalize_ai_mode(mode: Optional[str]) -> str:
    """AI_MODE 값을 mock 또는 live로 정규화하고 검증합니다."""
    normalized = (mode or "mock").strip().lower()
    if normalized not in ALLOWED_AI_MODES:
        raise ValueError(f"AI_MODE must be one of {sorted(ALLOWED_AI_MODES)}, got {mode!r}")
    return normalized


def create_ai_client(
    config: Optional[UpstageConfig] = None,
    *,
    http_post: Optional[HttpPost] = None,
) -> AIClientProtocol:
    """설정에 맞는 AI 클라이언트를 생성하고 live 설정 누락은 즉시 실패시킵니다."""
    config = config or UpstageConfig.from_env()
    requested_mode = normalize_ai_mode(config.ai_mode)

    if requested_mode == "mock":
        return DeterministicMockAIClient()

    if not config.api_key:
        raise LLMConfigurationError("UPSTAGE_API_KEY is required when AI_MODE=live")

    return UpstageSolarClient(config=config, http_post=http_post)


def parse_json_object(text: str) -> Dict[str, Any]:
    """모델 응답에서 JSON 객체만 뽑아내며, 코드블록이나 앞뒤 설명도 최대한 허용합니다."""
    content = text.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(content[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


class UpstageSolarClient:
    """Upstage chat completion과 embedding HTTP API를 호출하는 클라이언트입니다."""
    mode = "live"

    def __init__(self, config: UpstageConfig, http_post: Optional[HttpPost] = None):
        """운영 코드와 테스트에서 HTTP 호출 함수를 주입할 수 있게 초기화합니다."""
        self.config = config
        self._http_post = http_post or _urllib_post_json

    def complete_json(
        self,
        *,
        task: str,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        RouteDecision: Optional[Type[BaseModel]] = None,
    ) -> Dict[str, Any]:
        """RouteDecision 스키마가 있으면 structured output, 없으면 텍스트 파싱으로 JSON을 반환합니다."""
        llm = ChatUpstage(
                model=self.config.chat_model,
                upstage_api_key=self.config.api_key,
                temperature=0.2
            )
        if RouteDecision is not None:
            structured_llm = llm.with_structured_output(RouteDecision)
            response = structured_llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(user_payload, ensure_ascii=False)),
            ])
            return response.to_dict()

        last_error: Optional[Exception] = None
        messages = [SystemMessage(content=system_prompt),
                    HumanMessage(content=json.dumps(user_payload, ensure_ascii=False))]
        if task == "self_review":
            llm_with_tools = llm.bind_tools([check_length_N_forbidden])
            response = llm_with_tools.invoke(messages)
            messages.append(response)
            if response.tool_calls:
                for call in response.tool_calls:
                    result = check_length_N_forbidden.invoke(call["args"])   
                    messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"]))
        for attempt in range(2):
            if attempt == 1:                      
                system_prompt = (
                    f"{system_prompt}\n\n이전 응답은 JSON 파싱에 실패했습니다. "
                    "설명 없이 유효한 JSON 객체만 다시 출력하세요."
                )
            response_text = llm.invoke(messages)
            try:
                return parse_json_object(response_text.content)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc

        raise LLMResponseParseError(
            f"{task} response was not valid JSON after one retry"
        ) from last_error

    def embed_text(self, text: str, *, purpose: str = "query") -> List[float]:
        """query/passage 목적에 맞는 임베딩 모델로 텍스트를 벡터화합니다."""
        if not text or not text.strip():
            raise ValueError("text must not be empty")

        model = (
            self.config.embedding_passage_model
            if purpose == "passage"
            else self.config.embedding_query_model
        )
        headers = self._headers()
        payload = {"model": model, "input": text}
        response = self._http_post(
            self.config.embedding_url,
            headers,
            payload,
            self.config.timeout_seconds,
        )
        try:
            embedding = response["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Upstage embedding response did not include an embedding") from exc

        if not isinstance(embedding, list) or not embedding:
            raise LLMError("Upstage embedding response contained an invalid embedding")
        return [float(value) for value in embedding]

    def _complete_text(
        self,
        *,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        retry_json_only: bool,
    ) -> str:
        """Chat completion 엔드포인트를 호출하고 원문 메시지 텍스트만 반환합니다."""
        system_content = system_prompt
        if retry_json_only:
            system_content = (
                f"{system_prompt}\n\n이전 응답은 JSON 파싱에 실패했습니다. "
                "설명 없이 유효한 JSON 객체만 다시 출력하세요."
            )

        payload = {
            "model": self.config.chat_model,
            "messages": [
                {"role": "system", "content": system_content},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            "temperature": 0.2,
            "stream": False,
        }
        response = self._http_post(
            _join_url(self.config.base_url, "/chat/completions"),
            self._headers(),
            payload,
            self.config.timeout_seconds,
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Upstage chat response did not include message content") from exc

        if isinstance(content, list):
            return "".join(str(part.get("text", part)) for part in content)
        return str(content)

    def _headers(self) -> Dict[str, str]:
        """Upstage 요청에 필요한 인증 헤더를 구성합니다."""
        if not self.config.api_key:
            raise LLMConfigurationError("UPSTAGE_API_KEY is required for live calls")
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }


class DeterministicMockAIClient:
    """테스트와 API 키 없는 로컬 데모에서 사용하는 deterministic mock 클라이언트입니다."""
    mode = "mock"

    def complete_json(
        self,
        *,
        task: str,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        RouteDecision: Optional[Type[BaseModel]] = None
    ) -> Dict[str, Any]:
        """알려진 AI 작업명을 deterministic mock 구현으로 라우팅합니다."""
        del system_prompt
        if task == "classification":
            return _mock_classification(str(user_payload.get("review_text", "")))
        if task == "interpretation":
            return _mock_interpretation(
                str(user_payload.get("review_text", "")),
                _as_mapping(user_payload.get("classification")),
            )
        if task == "analysis":
            return _mock_analysis(str(user_payload.get("review_text", "")))
        if task == "reply_generation":
            return _mock_reply_generation(
                str(user_payload.get("review_text", "")),
                _as_mapping(user_payload.get("interpretation")),
                _as_mapping(user_payload.get("store_info")),
                list(user_payload.get("rag_references") or []),
            )
        if task == "self_review":
            return _mock_self_review(
                str(user_payload.get("reply_text", "")),
                str(user_payload.get("forbidden_expressions", "")),
            )
        raise ValueError(f"unknown mock task: {task}")

    def embed_text(self, text: str, *, purpose: str = "query") -> List[float]:
        """외부 호출 없이 안정적인 lexical embedding을 반환합니다."""
        del purpose
        if not text or not text.strip():
            raise ValueError("text must not be empty")
        return _stable_text_embedding(text)


def _urllib_post_json(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """urllib로 JSON POST를 실행하고 HTTP/timeout 오류를 LLM 예외로 정규화합니다."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except (TimeoutError, socket.timeout) as exc:
        raise LLMTimeoutError(f"Upstage request timed out after {timeout_seconds}s") from exc
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"Upstage request failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            raise LLMTimeoutError(f"Upstage request timed out after {timeout_seconds}s") from exc
        raise LLMError(f"Upstage request failed: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError("Upstage response body was not JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Upstage response body must be a JSON object")
    return parsed


def _join_url(base_url: str, path: str) -> str:
    """base URL과 path를 중복 슬래시 없이 결합합니다."""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Mapping 값은 그대로 반환하고 그 외 값은 빈 dict로 처리합니다."""
    return value if isinstance(value, Mapping) else {}


def _mock_classification(review_text: str) -> Dict[str, Any]:
    """live 스키마를 흉내 내는 키워드 기반 mock 분류 결과를 생성합니다."""
    text = review_text.lower()

    high_keywords = ["이물질", "머리카락", "벌레", "환불", "신고", "고소", "법적", "식중독", "욕"]
    malicious_keywords = ["사기", "고소", "신고", "망해", "쓰레기", "욕", "법적"]
    positive_keywords = ["맛있", "최고", "감사", "친절", "좋", "바삭", "만족", "재방문", "깨끗"]

    sub_type = _detect_sub_type(text)
    is_malicious = any(keyword in text for keyword in malicious_keywords)
    is_positive = any(keyword in text for keyword in positive_keywords) and not sub_type and not is_malicious

    if is_malicious:
        sentiment = "malicious"
    elif is_positive:
        sentiment = "positive"
    else:
        sentiment = "negative"

    if sentiment == "positive":
        return {"sentiment": "positive", "sub_type": None, "risk_level": "low"}

    risk_level = "high" if any(keyword in text for keyword in high_keywords) else "medium"
    return {
        "sentiment": sentiment,
        "sub_type": sub_type or "기타",
        "risk_level": risk_level,
    }


def _detect_sub_type(text: str) -> Optional[str]:
    """한국어 키워드 그룹으로 리뷰 불만 세부 유형을 감지합니다."""
    keyword_groups = [
        ("배달지연", ["늦", "지연", "한시간", "1시간", "식었", "차갑"]),
        ("이물질", ["이물질", "머리카락", "벌레", "비닐"]),
        ("음식맛", ["맛없", "짜", "싱겁", "탔", "냄새", "덜 익"]),
        ("불친절", ["불친절", "직원", "응대", "말투", "무시"]),
        ("가격불만", ["비싸", "가격", "가성비", "양이 적"]),
        ("포장불량", ["포장", "쏟", "샜", "봉투", "누락"]),
        ("환불요청", ["환불", "취소", "보상"]),
    ]
    for sub_type, keywords in keyword_groups:
        if any(keyword in text for keyword in keywords):
            return sub_type
    return None


def _mock_interpretation(
    review_text: str,
    classification: Mapping[str, Any],
) -> Dict[str, Any]:
    """정규화된 분류 결과를 바탕으로 mock 해석 결과를 생성합니다."""
    del review_text
    sentiment = classification.get("sentiment")
    sub_type = classification.get("sub_type") or "기타"

    if sentiment == "positive":
        return {
            "core_issue": "음식과 서비스에 대한 긍정적인 경험",
            "action_direction": "감사 인사와 재방문을 자연스럽게 유도",
            "reply_tone": "감사",
        }
    if sentiment == "malicious":
        return {
            "core_issue": "과격하거나 악의적인 표현으로 인한 평판 리스크",
            "action_direction": "감정적 대응을 피하고 사실 확인과 공식 문의 채널을 안내",
            "reply_tone": "단호한 대응",
        }

    action_by_type = {
        "배달지연": "사과와 배달 시간 개선 계획을 안내",
        "이물질": "즉시 사과하고 확인 절차와 재발 방지 조치를 안내",
        "음식맛": "맛 품질 불만에 사과하고 조리 기준 점검을 약속",
        "불친절": "응대 불편에 사과하고 직원 교육을 안내",
        "가격불만": "불만을 수용하고 품질 개선 의지를 안내",
        "포장불량": "포장 상태 불편에 사과하고 포장 점검을 안내",
        "환불요청": "불편에 사과하고 매장 문의를 통한 확인 절차를 안내",
        "기타": "불편 사항에 사과하고 개선 의지를 안내",
    }
    return {
        "core_issue": f"{sub_type} 관련 고객 불편",
        "action_direction": action_by_type.get(str(sub_type), action_by_type["기타"]),
        "reply_tone": "사과",
    }

def _mock_analysis(review_text: str) -> dict:
    classification = _mock_classification(review_text)
    interpretation = _mock_interpretation(review_text, classification)
    return {**classification, **interpretation}

def _mock_reply_generation(
    review_text: str,
    interpretation: Mapping[str, Any],
    store_info: Mapping[str, Any],
    rag_references: List[Any],
) -> Dict[str, Any]:
    """로컬/테스트 실행용 deterministic 답변 초안을 생성합니다."""
    del review_text, rag_references
    store_name = str(store_info.get("store_name") or "매장")
    tone = interpretation.get("reply_tone")
    core_issue = str(interpretation.get("core_issue") or "남겨주신 의견")
    action = str(interpretation.get("action_direction") or "개선 방향을 점검하겠습니다")

    if tone == "감사":
        reply = (
            f"안녕하세요, {store_name}입니다. 소중한 리뷰 감사합니다. "
            "만족스럽게 이용하셨다니 기쁩니다. 앞으로도 좋은 음식과 서비스로 보답하겠습니다."
        )
    elif tone == "단호한 대응":
        reply = (
            f"안녕하세요, {store_name}입니다. 남겨주신 내용은 확인하겠습니다. "
            "다만 사실과 다른 내용이나 과격한 표현에 대해서는 정확한 확인이 필요합니다. "
            "구체적인 이용 내역을 매장으로 알려주시면 차분히 확인해 안내드리겠습니다."
        )
    elif tone == "해명":
        reply = (
            f"안녕하세요, {store_name}입니다. {core_issue}에 대해 말씀 주셔서 감사합니다. "
            f"{action}. 오해가 없도록 더 명확히 안내드리겠습니다."
        )
    else:
        reply = (
            f"안녕하세요, {store_name}입니다. 이용에 불편을 드려 죄송합니다. "
            f"{core_issue}에 대해 내부적으로 확인하고, {action}. "
            "다시 이용하실 때 더 나은 경험을 드릴 수 있도록 점검하겠습니다."
        )

    return {"reply_text": reply[:500]}


def _mock_self_review(reply_text: str, forbidden_expressions: str) -> Dict[str, Any]:
    """mock 모드에서 길이 초과와 금지 표현 포함 여부만 체크합니다."""
    if len(reply_text) > 500:
        return {"passed": False, "reason": "답변이 500자를 초과합니다."}
    if forbidden_expressions:
        for expr in (e.strip() for e in forbidden_expressions.split(",") if e.strip()):
            if expr in reply_text:
                return {"passed": False, "reason": f"금지 표현이 포함되어 있습니다: {expr}"}
    return {"passed": True, "reason": None}


def _stable_text_embedding(text: str, dimensions: int = 64) -> List[float]:
    """RAG 테스트에서 재현 가능한 정규화 해싱 벡터를 생성합니다."""
    tokens = re.findall(r"[0-9a-zA-Z가-힣]+", text.lower())
    features: List[str] = []
    for token in tokens:
        features.append(token)
        features.extend(token[index : index + 2] for index in range(max(len(token) - 1, 0)))
        features.extend(token[index : index + 3] for index in range(max(len(token) - 2, 0)))

    if not features:
        features = [text.strip().lower()]

    vector = [0.0] * dimensions
    for feature in features:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
