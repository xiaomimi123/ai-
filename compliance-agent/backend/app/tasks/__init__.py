"""Celery 异步任务包。

离线 / 测试模式下走 eager（同步执行），生产由独立 worker 进程消费。
"""
from app.tasks.celery_app import celery_app
from app.tasks.jobs import (
    run_check_task,
    run_procurement_chain_task,
    run_finance_chain_task,
    run_report_chain_task,
)

__all__ = [
    "celery_app",
    "run_check_task",
    "run_procurement_chain_task",
    "run_finance_chain_task",
    "run_report_chain_task",
]
