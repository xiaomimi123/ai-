"""检索器：组合 Embedder + VectorStore，提供入库与召回。"""
from __future__ import annotations

from typing import List, Optional

from app.rag.chunking import Chunk
from app.rag.embedder import get_embedder
from app.rag.vector_store import ScoredChunk, build_vector_store


class Retriever:
    def __init__(self):
        self.embedder = get_embedder()
        self.store = build_vector_store(self.embedder.dim)

    def index_chunks(self, chunks: List[Chunk]) -> int:
        if not chunks:
            return 0
        texts = [c.text for c in chunks]
        vectors = self.embedder.embed(texts)
        self.store.add(vectors, texts, [c.metadata for c in chunks])
        return len(chunks)

    def retrieve(self, query: str, category: Optional[str] = None, top_k: int = 5) -> List[ScoredChunk]:
        qvec = self.embedder.embed_one(query)
        return self.store.search(qvec, top_k=top_k, category=category)

    def count(self) -> int:
        return self.store.count()


_retriever: Optional[Retriever] = None


def get_retriever() -> Retriever:
    """进程内单例检索器（共享内存向量库）。"""
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
