"""ChromaDB와 deterministic 메모리 fallback을 사용하는 RAG 서비스입니다."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from app.config import get_settings

from ..llm.client import (
    AIClientProtocol,
    LLMConfigurationError,
    create_ai_client,
    normalize_ai_mode,
)
from ..llm.types import RAGReference


@dataclass(frozen=True)
class RAGConfig:
    """RAG 컬렉션과 벡터 저장소 백엔드 설정입니다."""

    collection_name: str = "review_reply_examples"
    persist_path: str = ".chroma/review_helper"
    ai_mode: str = "mock"

    @classmethod
    def from_env(cls) -> "RAGConfig":
        """애플리케이션 환경 설정에서 RAG 설정을 구성합니다."""

        settings = get_settings()
        return cls(
            collection_name=settings.rag_collection_name,
            persist_path=settings.chroma_persist_dir,
            ai_mode=settings.ai_mode,
        )


class RAGService:
    """승인된 리뷰-답변 예시를 저장하고 유사 사례를 검색합니다."""

    def __init__(
        self,
        *,
        client: Optional[AIClientProtocol] = None,
        config: Optional[RAGConfig] = None,
    ):
        """공유 AI 클라이언트와 벡터 저장소로 RAG 서비스를 생성합니다."""

        self.config = config or RAGConfig.from_env()
        self.mode = normalize_ai_mode(self.config.ai_mode)
        self.client = client or create_ai_client()
        self._store = self._build_store()

    def seed(self, pairs: Sequence[Mapping[str, Any]]) -> int:
        """유효한 시드 리뷰-답변 쌍을 저장하고 저장 개수를 반환합니다."""

        stored = 0
        for pair in pairs:
            review = str(pair.get("review") or "").strip()
            reply = str(pair.get("reply") or "").strip()
            if not review or not reply:
                continue
            self.add(
                review=review,
                reply=reply,
                sub_type=_optional_str(pair.get("sub_type")),
                risk_level=_optional_str(pair.get("risk_level")),
                order_type=_optional_str(pair.get("order_type")),
                metadata=_extra_metadata(pair),
            )
            stored += 1
        return stored

    def search(
        self,
        review_text: str,
        *,
        top_k: int = 3,
        sub_type: Optional[str] = None,
        risk_level: Optional[str] = None,
        order_type: Optional[str] = None,
        store_id: Optional[Union[int, str]] = None,
    ) -> List[Dict[str, Any]]:
        """선택 메타데이터 필터를 적용해 유사 승인 답변을 검색합니다."""

        if not isinstance(review_text, str) or not review_text.strip():
            raise ValueError("review_text must not be empty")
        if top_k <= 0:
            return []

        query_embedding = self.client.embed_text(review_text, purpose="query")
        filters = {
            key: value
            for key, value in {
                "sub_type": sub_type,
                "risk_level": risk_level,
                "order_type": order_type,
                "store_id": str(store_id) if store_id not in (None, "") else None,
            }.items()
            if value not in (None, "")
        }
        references = self._store.query(query_embedding, top_k=top_k, filters=filters)
        return [reference.to_dict() for reference in references]

    def add(
        self,
        *,
        review: str,
        reply: str,
        sub_type: Optional[str] = None,
        risk_level: Optional[str] = None,
        order_type: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """리뷰-답변 예시 1건을 추가 또는 갱신하고 stable id를 반환합니다."""

        if not isinstance(review, str) or not review.strip():
            raise ValueError("review must not be empty")
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("reply must not be empty")

        payload = {
            "review": review.strip(),
            "reply": reply.strip(),
            "sub_type": sub_type,
            "risk_level": risk_level,
            "order_type": order_type,
            **dict(metadata or {}),
        }
        example_id = _stable_example_id(payload)
        embedding = self.client.embed_text(review, purpose="passage")
        self._store.upsert(example_id, payload, embedding)
        return example_id

    def add_approved_reply(
        self,
        *,
        review_text: str,
        reply_text: str,
        classification: Mapping[str, Any],
        order_type: Optional[str] = None,
    ) -> str:
        """승인된 생성 답변을 분류 메타데이터와 함께 저장합니다."""

        return self.add(
            review=review_text,
            reply=reply_text,
            sub_type=_optional_str(classification.get("sub_type")),
            risk_level=_optional_str(classification.get("risk_level")),
            order_type=order_type,
        )

    def _build_store(self) -> "_VectorStore":
        """live 모드에서는 Chroma를, mock 모드에서는 메모리 저장소를 선택합니다."""

        if self.mode == "mock":
            return _InMemoryVectorStore()

        try:
            return _ChromaVectorStore(
                collection_name=self.config.collection_name,
                persist_path=self.config.persist_path,
            )
        except ImportError as exc:
            if self.mode == "live":
                raise LLMConfigurationError(
                    "chromadb is required when AI_MODE=live"
                ) from exc
            return _InMemoryVectorStore()


class _VectorStore:
    """RAGService가 사용하는 최소 벡터 저장소 인터페이스입니다."""

    def upsert(self, example_id: str, payload: Mapping[str, Any], embedding: List[float]) -> None:
        """임베딩된 예시 1건을 추가하거나 교체합니다."""

        raise NotImplementedError

    def query(
        self,
        query_embedding: List[float],
        *,
        top_k: int,
        filters: Mapping[str, str],
    ) -> List[RAGReference]:
        """메타데이터 필터와 일치하는 가장 유사한 reference를 반환합니다."""

        raise NotImplementedError


class _InMemoryVectorStore(_VectorStore):
    """mock 모드와 단위 테스트에서 쓰는 deterministic 메모리 벡터 저장소입니다."""

    def __init__(self) -> None:
        """빈 로컬 벡터 dict를 초기화합니다."""

        self._items: Dict[str, Dict[str, Any]] = {}

    def upsert(self, example_id: str, payload: Mapping[str, Any], embedding: List[float]) -> None:
        """메모리 저장소에 임베딩 예시 1건을 추가하거나 교체합니다."""

        self._items[example_id] = {
            "payload": dict(payload),
            "embedding": list(embedding),
        }

    def query(
        self,
        query_embedding: List[float],
        *,
        top_k: int,
        filters: Mapping[str, str],
    ) -> List[RAGReference]:
        """모든 로컬 예시의 점수를 계산하고 필터링된 상위 결과를 반환합니다."""

        matches: List[RAGReference] = []
        for item in self._items.values():
            payload = item["payload"]
            if not _matches_filters(payload, filters):
                continue
            similarity = _cosine_similarity(query_embedding, item["embedding"])
            matches.append(_reference_from_payload(payload, similarity))

        matches.sort(key=lambda reference: reference.similarity, reverse=True)
        return matches[:top_k]


class _ChromaVectorStore(_VectorStore):
    """live 모드에서 사용하는 Chroma 기반 영속 벡터 저장소입니다."""

    def __init__(self, *, collection_name: str, persist_path: str) -> None:
        """설정된 영속 Chroma 컬렉션을 열거나 생성합니다."""

        try:
            import chromadb
        except ImportError:
            raise

        client = chromadb.PersistentClient(path=persist_path)
        self._collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, example_id: str, payload: Mapping[str, Any], embedding: List[float]) -> None:
        """검색 가능한 메타데이터와 함께 Chroma에 예시 1건을 upsert합니다."""

        metadata = _metadata_for_chroma(payload)
        self._collection.upsert(
            ids=[example_id],
            documents=[str(payload["review"])],
            embeddings=[embedding],
            metadatas=[metadata],
        )

    def query(
        self,
        query_embedding: List[float],
        *,
        top_k: int,
        filters: Mapping[str, str],
    ) -> List[RAGReference]:
        """Chroma를 검색하고 distance를 similarity reference로 변환합니다."""

        where = _where_for_chroma(filters)
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        references: List[RAGReference] = []
        for index, document in enumerate(documents):
            metadata = dict(metadatas[index] or {})
            distance = float(distances[index] or 0.0)
            payload = {
                "review": document,
                "reply": metadata.get("reply", ""),
                "sub_type": _empty_to_none(metadata.get("sub_type")),
                "risk_level": _empty_to_none(metadata.get("risk_level")),
                "order_type": _empty_to_none(metadata.get("order_type")),
            }
            references.append(_reference_from_payload(payload, max(0.0, 1.0 - distance)))
        return references


def _stable_example_id(payload: Mapping[str, Any]) -> str:
    """RAG payload의 의미 필드로 deterministic id를 생성합니다."""

    digest = hashlib.sha256(
        repr(
            (
                payload.get("review"),
                payload.get("reply"),
                payload.get("sub_type"),
                payload.get("risk_level"),
                payload.get("order_type"),
            )
        ).encode("utf-8")
    ).hexdigest()
    return f"rag_{digest[:24]}"


def _matches_filters(payload: Mapping[str, Any], filters: Mapping[str, str]) -> bool:
    """payload가 모든 exact-match 메타데이터 필터를 만족하는지 반환합니다."""

    return all(str(payload.get(key)) == str(value) for key, value in filters.items())


def _reference_from_payload(payload: Mapping[str, Any], similarity: float) -> RAGReference:
    """저장된 payload 메타데이터를 공개 RAG reference 형태로 변환합니다."""

    return RAGReference(
        review=str(payload.get("review") or ""),
        reply=str(payload.get("reply") or ""),
        sub_type=_optional_str(payload.get("sub_type")),
        risk_level=_optional_str(payload.get("risk_level")),
        order_type=_optional_str(payload.get("order_type")),
        similarity=round(max(0.0, float(similarity)), 6),
    )


def _cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    """cosine similarity를 계산하고 호환되지 않는 벡터는 0으로 처리합니다."""

    left_values = list(left)
    right_values = list(right)
    if not left_values or not right_values or len(left_values) != len(right_values):
        return 0.0
    dot = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = math.sqrt(sum(a * a for a in left_values))
    right_norm = math.sqrt(sum(b * b for b in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _metadata_for_chroma(payload: Mapping[str, Any]) -> Dict[str, str]:
    """RAG payload 메타데이터를 Chroma가 받는 문자열 값으로 평탄화합니다."""

    metadata = {
        "reply": str(payload.get("reply") or ""),
        "sub_type": str(payload.get("sub_type") or ""),
        "risk_level": str(payload.get("risk_level") or ""),
        "order_type": str(payload.get("order_type") or ""),
    }
    for key, value in payload.items():
        if key in {"review", "reply", "sub_type", "risk_level", "order_type"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[key] = "" if value is None else str(value)
    return metadata


def _where_for_chroma(filters: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    """exact-match 필터를 Chroma where 표현식으로 변환합니다."""

    if not filters:
        return None
    if len(filters) == 1:
        key, value = next(iter(filters.items()))
        return {key: value}
    return {"$and": [{key: value} for key, value in filters.items()]}


def _optional_str(value: Any) -> Optional[str]:
    """존재하는 값은 문자열로 바꾸고 누락값은 None으로 유지합니다."""

    if value in (None, ""):
        return None
    return str(value)


def _empty_to_none(value: Any) -> Optional[str]:
    """Chroma의 빈 메타데이터 값을 다시 None으로 변환합니다."""

    return None if value in (None, "") else str(value)


def _extra_metadata(pair: Mapping[str, Any]) -> Dict[str, Any]:
    """시드 pair에서 사용자 정의 메타데이터 필드만 남깁니다."""

    reserved = {"review", "reply", "sub_type", "risk_level", "order_type"}
    return {key: value for key, value in pair.items() if key not in reserved}


_default_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """프로세스 전체에서 공유하는 RAG 서비스 싱글턴을 반환합니다."""

    global _default_rag_service
    if _default_rag_service is None:
        _default_rag_service = RAGService()
    return _default_rag_service


def search_similar_reviews(
    *,
    review_text: str,
    store_id: int,
    sub_type: Optional[str],
    order_type: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """백엔드 AI contract에서 호출하는 RAG 검색 어댑터입니다."""

    return get_rag_service().search(
        review_text,
        top_k=limit,
        sub_type=sub_type,
        order_type=order_type,
        store_id=store_id,
    )


def save_approved_reply(
    *,
    review: str,
    reply: str,
    store_id: int,
    sub_type: Optional[str],
    risk_level: Optional[str],
    order_type: str,
) -> None:
    """승인된 리뷰-답변 쌍을 RAG 저장소에 저장합니다."""

    get_rag_service().add(
        review=review,
        reply=reply,
        sub_type=sub_type,
        risk_level=risk_level,
        order_type=order_type,
        metadata={"store_id": str(store_id)},
    )


def seed_rag_pairs(pairs: Sequence[Mapping[str, Any]], store_id: int) -> None:
    """가게의 초기 RAG 예시 데이터를 저장합니다."""

    scoped_pairs = [{**dict(pair), "store_id": str(store_id)} for pair in pairs]
    get_rag_service().seed(scoped_pairs)
