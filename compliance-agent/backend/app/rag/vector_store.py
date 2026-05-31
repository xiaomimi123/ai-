"""向量库接口 + 两实现，支持 metadata（category）过滤（§3.1 分类检索刚需）。

- MemoryVectorStore：内存 + numpy 余弦，离线默认，零依赖。
- QdrantVectorStore：生产。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.core.config import settings


@dataclass
class ScoredChunk:
    text: str
    score: float
    metadata: Dict[str, str]


class VectorStore(abc.ABC):
    @abc.abstractmethod
    def add(self, vectors: List[List[float]], texts: List[str], metadatas: List[Dict[str, str]]) -> None:
        ...

    @abc.abstractmethod
    def search(
        self, query_vec: List[float], top_k: int = 5, category: Optional[str] = None
    ) -> List[ScoredChunk]:
        ...

    @abc.abstractmethod
    def count(self) -> int:
        ...


def _cosine(a: List[float], b: List[float]) -> float:
    # 向量已归一化时即点积；这里稳妥起见仍按余弦
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)


class MemoryVectorStore(VectorStore):
    def __init__(self):
        self._vecs: List[List[float]] = []
        self._texts: List[str] = []
        self._metas: List[Dict[str, str]] = []

    def add(self, vectors, texts, metadatas) -> None:
        self._vecs.extend(vectors)
        self._texts.extend(texts)
        self._metas.extend(metadatas)

    def search(self, query_vec, top_k=5, category=None) -> List[ScoredChunk]:
        scored: List[ScoredChunk] = []
        for vec, text, meta in zip(self._vecs, self._texts, self._metas):
            if category and meta.get("category") and meta.get("category") != category:
                continue
            scored.append(ScoredChunk(text=text, score=_cosine(query_vec, vec), metadata=meta))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._texts)


class QdrantVectorStore(VectorStore):
    COLLECTION = "regulations"

    def __init__(self, url: str, dim: int):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self._client = QdrantClient(url=url)
        self._dim = dim
        existing = {c.name for c in self._client.get_collections().collections}
        if self.COLLECTION not in existing:
            self._client.create_collection(
                self.COLLECTION,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        self._next_id = self._client.count(self.COLLECTION).count

    def add(self, vectors, texts, metadatas) -> None:
        from qdrant_client.models import PointStruct

        points = []
        for vec, text, meta in zip(vectors, texts, metadatas):
            payload = dict(meta)
            payload["text"] = text
            points.append(PointStruct(id=self._next_id, vector=vec, payload=payload))
            self._next_id += 1
        self._client.upsert(self.COLLECTION, points=points)

    def search(self, query_vec, top_k=5, category=None) -> List[ScoredChunk]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        flt = None
        if category:
            flt = Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])
        hits = self._client.search(self.COLLECTION, query_vector=query_vec, limit=top_k, query_filter=flt)
        out = []
        for h in hits:
            payload = dict(h.payload or {})
            text = payload.pop("text", "")
            out.append(ScoredChunk(text=text, score=h.score, metadata=payload))
        return out

    def count(self) -> int:
        return self._client.count(self.COLLECTION).count


def build_vector_store(dim: int) -> VectorStore:
    if settings.vector_store == "qdrant":
        try:
            return QdrantVectorStore(settings.qdrant_url, dim)
        except Exception:
            pass  # 连接失败 -> 降级内存
    return MemoryVectorStore()
