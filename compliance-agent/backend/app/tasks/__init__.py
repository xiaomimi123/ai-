"""Celery 异步任务包（v3）。

eager 模式（开发离线默认）：.delay() 在调用线程同步执行
生产模式：由 worker 进程从 Redis 消费
"""
from app.tasks.celery_app import celery_app
from app.tasks.jobs import enrich_material_task, run_audit_task

__all__ = ["celery_app", "enrich_material_task", "run_audit_task"]
