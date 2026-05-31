"""RAG service backed by ChromaDB with deterministic in-memory fallback."""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from ..llm.client import (
    AIClientProtocol,
    LLMConfigurationError,
    create_ai_client,
    normalize_ai_mode,
)
from ..llm.types import RAGReference


@dataclass(frozen=True)
class RAGConfig:
    collection_name: str = "review_reply_examples"
    persist_path: str = ".chroma/review_helper"
    ai_mode: str = "auto"

    @classmethod
    def from_env(cls) -> "RAGConfig":
        return cls(
            collection_name=os.getenv("RAG_COLLECTION_NAME", os.getenv("CHROMA_COLLECTION", cls.collection_name)),
            persist_path=os.getenv("CHROMA_PERSIST_DIR", os.getenv("CHROMA_PERSIST_PATH", cls.persist_path)),
            ai_mode=os.getenv("AI_MODE", "auto"),
        )


class RAGService:
    """
    Store and search approved review-reply examples.

    Public contract for routers:
    - seed(pairs) -> number of stored examples
    - search(review_text, top_k=3, filters...) -> list of reference dicts
    - add(review=..., reply=..., metadata...) -> stable example id
    """

    def __init__(
        self,
        *,
        client: Optional[AIClientProtocol] = None,
        config: Optional[RAGConfig] = None,
    ):
        self.config = config or RAGConfig.from_env()
        self.mode = normalize_ai_mode(self.config.ai_mode)
        self.client = client or create_ai_client()
        self._store = self._build_store()

    def seed(self, pairs: Sequence[Mapping[str, Any]]) -> int:
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
        return self.add(
            review=review_text,
            reply=reply_text,
            sub_type=_optional_str(classification.get("sub_type")),
            risk_level=_optional_str(classification.get("risk_level")),
            order_type=order_type,
        )

    def _build_store(self) -> "_VectorStore":
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
    def upsert(self, example_id: str, payload: Mapping[str, Any], embedding: List[float]) -> None:
        raise NotImplementedError

    def query(
        self,
        query_embedding: List[float],
        *,
        top_k: int,
        filters: Mapping[str, str],
    ) -> List[RAGReference]:
        raise NotImplementedError


class _InMemoryVectorStore(_VectorStore):
    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Any]] = {}

    def upsert(self, example_id: str, payload: Mapping[str, Any], embedding: List[float]) -> None:
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
    def __init__(self, *, collection_name: str, persist_path: str) -> None:
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
    return all(str(payload.get(key)) == str(value) for key, value in filters.items())


def _reference_from_payload(payload: Mapping[str, Any], similarity: float) -> RAGReference:
    return RAGReference(
        review=str(payload.get("review") or ""),
        reply=str(payload.get("reply") or ""),
        sub_type=_optional_str(payload.get("sub_type")),
        risk_level=_optional_str(payload.get("risk_level")),
        order_type=_optional_str(payload.get("order_type")),
        similarity=round(float(similarity), 6),
    )


def _cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
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
    if not filters:
        return None
    if len(filters) == 1:
        key, value = next(iter(filters.items()))
        return {key: value}
    return {"$and": [{key: value} for key, value in filters.items()]}


def _optional_str(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    return str(value)


def _empty_to_none(value: Any) -> Optional[str]:
    return None if value in (None, "") else str(value)


def _extra_metadata(pair: Mapping[str, Any]) -> Dict[str, Any]:
    reserved = {"review", "reply", "sub_type", "risk_level", "order_type"}
    return {key: value for key, value in pair.items() if key not in reserved}


_default_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
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
    """Adapter used by the backend AI contract."""

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
    """Persist an approved review-reply pair into the RAG store."""

    get_rag_service().add(
        review=review,
        reply=reply,
        sub_type=sub_type,
        risk_level=risk_level,
        order_type=order_type,
        metadata={"store_id": str(store_id)},
    )


def seed_rag_pairs(pairs: Sequence[Mapping[str, Any]], store_id: int) -> None:
    """Seed initial examples for a store."""

    scoped_pairs = [{**dict(pair), "store_id": str(store_id)} for pair in pairs]
    get_rag_service().seed(scoped_pairs)
