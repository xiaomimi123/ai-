"""自研 RAG 知识库模块（§3.3）：分块 / 嵌入 / 检索。"""
from app.rag.chunking import chunk_regulation, Chunk
from app.rag.retriever import Retriever, get_retriever

__all__ = ["chunk_regulation", "Chunk", "Retriever", "get_retriever"]
