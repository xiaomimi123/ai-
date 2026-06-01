"""Celery 未安装时的 AsyncResult 兜底。"""
from __future__ import annotations


class EagerAsyncResult:
    def __init__(self, value, exc=None):
        self._value = value
        self._exc = exc

    @property
    def id(self) -> str:
        return "eager"

    def get(self, timeout=None):
        if self._exc:
            raise self._exc
        return self._value

    @property
    def state(self) -> str:
        return "FAILURE" if self._exc else "SUCCESS"
