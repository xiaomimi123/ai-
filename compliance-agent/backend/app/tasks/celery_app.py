"""Celery 应用实例。

设计取舍：未安装 celery（开发环境最小化依赖）时提供一个最小兜底实现，
让导入与 .delay() 调用同步执行，不阻断单元测试。
"""
from __future__ import annotations

from app.core.config import settings

try:
    from celery import Celery

    celery_app = Celery(
        "compliance",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        task_always_eager=settings.celery_eager,
        task_eager_propagates=True,
        worker_max_tasks_per_child=100,
        task_acks_late=True,
        broker_connection_retry_on_startup=True,
    )

    # 显式导入任务模块以触发 @celery_app.task 注册
    celery_app.autodiscover_tasks(["app.tasks.jobs"], force=True)

except ImportError:  # celery 未安装：兜底为「直接调用函数」装饰器
    from app.tasks._fake_result import EagerAsyncResult

    class _EagerTask:
        """模拟 Celery Task：fn(args) 直调，.delay 同步执行。"""

        def __init__(self, fn, name=""):
            self._fn = fn
            self.name = name or fn.__name__

        def __call__(self, *args, **kwargs):
            return self._fn(*args, **kwargs)

        def delay(self, *args, **kwargs):
            try:
                return EagerAsyncResult(self._fn(*args, **kwargs))
            except Exception as exc:
                return EagerAsyncResult(None, exc=exc)

        apply_async = delay

    class _EagerCeleryStub:
        """最小兜底：保持 .task / .delay 接口可用，立即同步执行。"""

        def task(self, *dargs, **dkwargs):
            name = dkwargs.get("name", "")
            def deco(fn):
                return _EagerTask(fn, name=name)
            if dargs and callable(dargs[0]):
                return deco(dargs[0])
            return deco

    celery_app = _EagerCeleryStub()
