"""RAG 分块与检索测试（用 stub embedder + memory store）。"""
from app.rag.chunking import chunk_regulation
from app.rag.embedder import StubEmbedder
from app.rag.vector_store import MemoryVectorStore


def test_chunk_by_article():
    text = (
        "《某某法》\n"
        "第一条 这是第一条内容。\n"
        "第二条 这是第二条内容，关于违约责任。\n"
    )
    chunks = chunk_regulation(text, category="合同")
    assert len(chunks) == 2
    assert chunks[0].metadata["article"] == "第一条"
    assert chunks[0].metadata["citation"] == "《某某法》第一条"
    assert chunks[1].metadata["category"] == "合同"


def test_retrieval_finds_relevant_chunk():
    emb = StubEmbedder(dim=256)
    store = MemoryVectorStore()
    texts = ["第五百七十七条 违约责任 赔偿损失", "第四百七十条 合同价款 履行期限"]
    metas = [{"category": "合同", "citation": "《民法典》第577条"},
             {"category": "合同", "citation": "《民法典》第470条"}]
    store.add(emb.embed(texts), texts, metas)

    hits = store.search(emb.embed_one("违约责任如何承担"), top_k=1, category="合同")
    assert len(hits) == 1
    assert "违约" in hits[0].text


def test_category_filter():
    emb = StubEmbedder(dim=128)
    store = MemoryVectorStore()
    store.add(emb.embed(["合同条款"]), ["合同条款"], [{"category": "合同"}])
    store.add(emb.embed(["资产条款"]), ["资产条款"], [{"category": "国有资产报告"}])
    hits = store.search(emb.embed_one("条款"), top_k=5, category="合同")
    assert all(h.metadata["category"] == "合同" for h in hits)
    assert len(hits) == 1
