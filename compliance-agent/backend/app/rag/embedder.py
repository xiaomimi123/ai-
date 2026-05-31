"""Embedding 接口 + 两实现。

- StubEmbedder：确定性 hash 向量，无需下载模型，保证离线可跑可测。
- BGEEmbedder：bge-large-zh-v1.5（sentence-transformers），生产中文效果好。
"""
from __future__ import annotations

import abc
import hashlib
import math
from functools import lru_cache
from typing import List

from app.core.config import settings


class Embedder(abc.ABC):
    dim: int

    @abc.abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        ...

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]


class StubEmbedder(Embedder):
    """确定性词袋 hash 向量：对中文做 bi-gram 哈希散列到固定维度并归一化。

    虽非语义模型，但同义/同字面的查询能召回相关条款，足够离线联调与测试。
    """

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _tokens(self, text: str) -> List[str]:
        text = "".join(ch for ch in text if not ch.isspace())
        toks = list(text)  # 单字
        toks += [text[i:i + 2] for i in range(len(text) - 1)]  # bi-gram
        return toks

    def embed(self, texts: List[str]) -> List[List[float]]:
        vecs: List[List[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in self._tokens(text):
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vecs.append([v / norm for v in vec])
        return vecs


class BGEEmbedder(Embedder):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # 延迟导入

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> List[List[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()


@lru_cache
def get_embedder() -> Embedder:
    if settings.embedder == "bge":
        try:
            return BGEEmbedder(settings.bge_model_name)
        except Exception:
            pass  # 模型缺失 -> 降级 stub
    return StubEmbedder(dim=settings.embedding_dim)
