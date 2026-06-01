"""异步任务定义：单文件检查 + 3 条联动链。

每个任务：
- 接受已经在 DB 中创建（status="pending"）的 task 行 id 作为参数
- 自己开一个 Session 执行；执行完毕由 service 层把 status 置 done/failed
- 返回 task_id 便于追踪

eager 模式下与同步调用等价；生产模式由 worker 进程消费。
"""
from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="compliance.run_check")
def run_check_task(check_task_id: int) -> int:
    from app.models import CheckTask, Document, SessionLocal
    from app.services.check_service import execute_pending_check
    db = SessionLocal()
    try:
        task = db.get(CheckTask, check_task_id)
        if task is None:
            return check_task_id
        doc = db.get(Document, task.document_id)
        execute_pending_check(db, task, doc)
    finally:
        db.close()
    return check_task_id


@celery_app.task(name="compliance.chain.procurement")
def run_procurement_chain_task(chain_task_id: int) -> int:
    from app.models import ChainCheckTask, SessionLocal
    from app.services.chain_service import execute_pending_chain
    db = SessionLocal()
    try:
        task = db.get(ChainCheckTask, chain_task_id)
        if task is not None:
            execute_pending_chain(db, task)
    finally:
        db.close()
    return chain_task_id


@celery_app.task(name="compliance.chain.finance")
def run_finance_chain_task(chain_task_id: int) -> int:
    return run_procurement_chain_task(chain_task_id)  # 同一调度器，差异由 chain_type 路由


@celery_app.task(name="compliance.chain.report")
def run_report_chain_task(chain_task_id: int) -> int:
    return run_procurement_chain_task(chain_task_id)
