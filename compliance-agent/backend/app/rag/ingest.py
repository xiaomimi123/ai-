"""法规知识库导入入口：python -m app.rag.ingest --dir ./data/regulations（§7.2）。

读取目录下法规文件 → 按条款分块 → 向量化入库。
文件名约定（可选）：以「分类__法规名.txt」形式标注分类，否则从《》标题猜测。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.parsers import parse
from app.parsers.dispatcher import SUPPORTED_EXTENSIONS
from app.rag import chunk_regulation, get_retriever


def ingest_dir(dir_path: str) -> int:
    retriever = get_retriever()
    base = Path(dir_path)
    if not base.exists():
        print(f"目录不存在: {dir_path}")
        return 0

    total = 0
    for path in sorted(base.rglob("*")):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        # 文件名解析分类：分类__法规名
        stem = path.stem
        category, law_name = ("", None)
        if "__" in stem:
            category, law_name = stem.split("__", 1)

        parsed = parse(str(path))
        chunks = chunk_regulation(
            parsed.text, law_name=law_name, category=category, source=path.name
        )
        n = retriever.index_chunks(chunks)
        total += n
        print(f"  导入 {path.name}: {n} 个条款块（分类={category or '无'}）")

    print(f"知识库导入完成，共 {total} 块，当前库内 {retriever.count()} 块。")
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="导入法规知识库")
    ap.add_argument("--dir", required=True, help="法规文件目录")
    args = ap.parse_args()
    ingest_dir(args.dir)
