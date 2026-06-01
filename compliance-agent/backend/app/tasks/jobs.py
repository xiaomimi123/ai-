"""异步任务定义（v3）。

eager 模式下 .delay() 同步执行；生产由 worker 进程消费。
"""
from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="audit.run")
def run_audit_task(task_id: int) -> int:
    from app.engine import run_audit
    from app.models import AuditTask, SessionLocal

    db = SessionLocal()
    try:
        task = db.get(AuditTask, task_id)
        if task is not None:
            run_audit(db, task)
    finally:
        db.close()
    return task_id
