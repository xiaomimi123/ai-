"""v2.0 并发扩容测试：

1. backend uvicorn 应指定 --workers 2（默认 1 进程 = 单核瓶颈）
2. Celery task 拆队列：enrich → 'enrich' 队列；run_audit → 'audit' 队列
3. 独立 enrich_worker 服务处理 enrich 队列，避免和 run_audit 抢资源

用途：2-3 用户并发上传时 backend 不再 GIL 排队，扫描件 OCR 也不再阻塞核查。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

# docker-compose.yml 在 compliance-agent/ 根，测试在 backend/tests/
# 容器内跑测试时（/app/tests/），仓库根不存在，用 skip 语义处理
DOCKER_COMPOSE = (
    Path(__file__).resolve().parents[2] / "docker-compose.yml"
)


def _require_compose_file():
    """容器内没有 docker-compose.yml（只 COPY 了 backend/），skip 而非 fail。"""
    if not DOCKER_COMPOSE.exists():
        pytest.skip(
            f"docker-compose.yml 不在 {DOCKER_COMPOSE}（可能在容器内跑）"
        )


# ============================================================
# Section 1：backend uvicorn --workers
# ============================================================
def test_backend_service_explicitly_sets_uvicorn_workers():
    """v2.0：docker-compose.yml 里 backend 服务应显式指定 --workers N（不吃默认）。

    默认 Dockerfile CMD 无 --workers → uvicorn 内部行为可能变化；
    显式指定让每次部署行为一致。当前 workers=1（7 GiB 服务器内存约束），
    未来升配可改 2 或换 gunicorn --preload。
    """
    _require_compose_file()
    text = DOCKER_COMPOSE.read_text(encoding="utf-8")
    assert "uvicorn" in text, "docker-compose 里没找到 uvicorn 相关命令"
    assert "--workers" in text, (
        "docker-compose.yml backend 服务未显式声明 --workers"
    )


# ============================================================
# Section 2：Celery task queue 路由
# ============================================================
def _jobs_source() -> str:
    from app.tasks import jobs
    return Path(inspect.getfile(jobs)).read_text(encoding="utf-8")


def test_enrich_material_task_uses_enrich_queue():
    """enrich_material_task 装饰器应指定 queue='enrich'。"""
    src = _jobs_source()
    # 找到 material.enrich 装饰器块
    marker = 'name="material.enrich"'
    assert marker in src, f"未找到 task 名 {marker}"
    idx = src.find(marker)
    # 从 marker 往前找 @celery_app.task 装饰器起始处，往后找到 def
    deco_end = src.find("def ", idx)
    deco_block = src[max(0, idx - 200): deco_end]
    assert ("queue=\"enrich\"" in deco_block
            or "queue='enrich'" in deco_block), (
        f"material.enrich 装饰器未声明 queue='enrich'。片段：\n{deco_block}"
    )


def test_run_audit_task_uses_audit_queue():
    """run_audit_task 装饰器应指定 queue='audit'。"""
    src = _jobs_source()
    marker = 'name="audit.run"'
    assert marker in src, f"未找到 task 名 {marker}"
    idx = src.find(marker)
    deco_end = src.find("def ", idx)
    deco_block = src[max(0, idx - 200): deco_end]
    assert ("queue=\"audit\"" in deco_block
            or "queue='audit'" in deco_block), (
        f"audit.run 装饰器未声明 queue='audit'。片段：\n{deco_block}"
    )


# ============================================================
# Section 3：独立 enrich_worker 服务
# ============================================================
def test_docker_compose_has_enrich_worker_service():
    """docker-compose.yml 应有独立 enrich_worker 服务处理 enrich 队列。"""
    _require_compose_file()
    text = DOCKER_COMPOSE.read_text(encoding="utf-8")
    assert "enrich_worker" in text, (
        "docker-compose.yml 缺少 enrich_worker 服务；"
        "audit 与 enrich 会在同一 worker 里抢并发槽"
    )
    # enrich_worker 段里应看到 --queues=enrich（或 -Q enrich）
    idx = text.find("enrich_worker:")
    block = text[idx: idx + 1000]
    assert ("--queues=enrich" in block
            or "-Q enrich" in block), (
        f"enrich_worker 未指定 --queues=enrich。片段：\n{block[:500]}"
    )


def test_main_worker_only_handles_audit_queue():
    """主 worker 服务应只跑 audit 队列（不再吞掉默认 celery 队列的所有任务）。"""
    _require_compose_file()
    text = DOCKER_COMPOSE.read_text(encoding="utf-8")
    # 找 `  worker:` 段（跟其它服务定义同一层缩进）
    idx = text.find("\n  worker:\n")
    assert idx >= 0, "未找到 worker 服务定义"
    block = text[idx: idx + 1000]
    assert ("--queues=audit" in block
            or "-Q audit" in block), (
        f"主 worker 未指定 --queues=audit。片段：\n{block[:500]}"
    )
