"""API 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: int
    file_name: str
    category: str
    subcategory: str = ""
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CheckRequest(BaseModel):
    document_id: int
    template_key: str = "contract"


class IssueOut(BaseModel):
    id: int
    description: str
    location: str
    legal_basis: str
    category: str
    risk_level: str
    suggestion: str
    rule_id: str
    source: str
    handle_status: str

    class Config:
        from_attributes = True


class CheckTaskOut(BaseModel):
    id: int
    document_id: int
    template_key: str
    status: str
    summary: str
    issues: List[IssueOut] = []

    class Config:
        from_attributes = True


class TemplateOut(BaseModel):
    key: str
    name: str
    applies_to: str
    rigid_rules: int
    soft_rules: int
    ready: bool
