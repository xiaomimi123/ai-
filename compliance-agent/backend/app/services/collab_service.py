"""协同复核 + 在线批注服务（§3.7）。

整改状态机：
  open ── assign ──▶ assigned
  assigned ── start ──▶ fixing
  fixing ── submit ──▶ reviewing
  reviewing ── approve ──▶ resolved（销号）
  reviewing ── reject ──▶ rejected ── reopen ──▶ fixing

权限规则：
- 任何登录用户：可读自己有权访问的问题（继承文档分类权限）
- 管理员 / 审核人：可指派 / 复核
- 被指派人（assignee）：可提交整改说明
- 任何登录用户：可发评论
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.auth import log_action
from app.core.permissions import can_access_category, is_admin
from app.models import (
    CheckTask,
    Document,
    IssueComment,
    IssueRecord,
    User,
)

# 状态机白名单：from_status -> {transition -> to_status}
_TRANSITIONS = {
    "open":      {"assign": "assigned"},
    "assigned":  {"start": "fixing", "assign": "assigned"},  # 允许改派
    "fixing":    {"submit": "reviewing"},
    "reviewing": {"approve": "resolved", "reject": "rejected"},
    "rejected":  {"reopen": "fixing"},
    "resolved":  {},  # 终态
}


def get_accessible_issue(db: Session, issue_id: int, user: User) -> IssueRecord:
    """加载问题并校验访问权限（按其归属文档的分类校验）。"""
    issue = db.get(IssueRecord, issue_id)
    if issue is None:
        raise HTTPException(404, "问题不存在")
    # 单文件检查的 issue 关联到 task -> document
    doc: Optional[Document] = None
    if issue.task_id is not None:
        task = db.get(CheckTask, issue.task_id)
        if task is not None:
            doc = db.get(Document, task.document_id)
    if doc is not None and not can_access_category(user.role, doc.category):
        raise HTTPException(403, f"无权访问分类「{doc.category}」的问题")
    return issue


def assign_issue(db: Session, issue_id: int, assignee_id: int, user: User) -> IssueRecord:
    if not is_admin(user.role):
        raise HTTPException(403, "仅管理员可指派问题")
    issue = get_accessible_issue(db, issue_id, user)
    assignee = db.get(User, assignee_id)
    if assignee is None or not assignee.is_active:
        raise HTTPException(404, "指派对象不存在或已停用")
    _transition(issue, "assign")
    issue.assignee_id = assignee_id
    log_action(db, user, "issue.assign", target_type="issue", target_id=issue.id,
               detail=f"指派给 {assignee.username}")
    db.commit()
    db.refresh(issue)
    return issue


def start_fixing(db: Session, issue_id: int, user: User) -> IssueRecord:
    issue = get_accessible_issue(db, issue_id, user)
    if issue.assignee_id != user.id and not is_admin(user.role):
        raise HTTPException(403, "仅被指派人或管理员可开始整改")
    _transition(issue, "start")
    log_action(db, user, "issue.start", target_type="issue", target_id=issue.id)
    db.commit()
    db.refresh(issue)
    return issue


def submit_fix(db: Session, issue_id: int, fix_note: str, user: User) -> IssueRecord:
    issue = get_accessible_issue(db, issue_id, user)
    if issue.assignee_id != user.id and not is_admin(user.role):
        raise HTTPException(403, "仅被指派人或管理员可提交整改")
    if not fix_note.strip():
        raise HTTPException(400, "整改说明不能为空")
    _transition(issue, "submit")
    issue.fix_note = fix_note.strip()
    log_action(db, user, "issue.submit", target_type="issue", target_id=issue.id,
               detail=fix_note[:200])
    db.commit()
    db.refresh(issue)
    return issue


def approve_fix(db: Session, issue_id: int, review_note: str, user: User) -> IssueRecord:
    issue = get_accessible_issue(db, issue_id, user)
    if not is_admin(user.role):
        raise HTTPException(403, "仅管理员可销号")
    _transition(issue, "approve")
    issue.reviewer_id = user.id
    issue.review_note = (review_note or "").strip()
    log_action(db, user, "issue.approve", target_type="issue", target_id=issue.id,
               detail="销号")
    db.commit()
    db.refresh(issue)
    return issue


def reject_fix(db: Session, issue_id: int, review_note: str, user: User) -> IssueRecord:
    issue = get_accessible_issue(db, issue_id, user)
    if not is_admin(user.role):
        raise HTTPException(403, "仅管理员可打回")
    if not review_note.strip():
        raise HTTPException(400, "打回时必须填写复核意见")
    _transition(issue, "reject")
    issue.reviewer_id = user.id
    issue.review_note = review_note.strip()
    log_action(db, user, "issue.reject", target_type="issue", target_id=issue.id,
               detail=review_note[:200])
    db.commit()
    db.refresh(issue)
    return issue


def reopen_issue(db: Session, issue_id: int, user: User) -> IssueRecord:
    issue = get_accessible_issue(db, issue_id, user)
    if issue.assignee_id != user.id and not is_admin(user.role):
        raise HTTPException(403, "仅被指派人或管理员可重新打开")
    _transition(issue, "reopen")
    log_action(db, user, "issue.reopen", target_type="issue", target_id=issue.id)
    db.commit()
    db.refresh(issue)
    return issue


def add_comment(db: Session, issue_id: int, body: str, user: User) -> IssueComment:
    """所有有权访问该问题的登录用户均可发评论。"""
    if not body.strip():
        raise HTTPException(400, "评论内容不能为空")
    issue = get_accessible_issue(db, issue_id, user)
    comment = IssueComment(
        issue_id=issue.id,
        author_id=user.id,
        author_name=user.full_name or user.username,
        body=body.strip(),
    )
    db.add(comment)
    log_action(db, user, "issue.comment", target_type="issue", target_id=issue.id,
               detail=body[:200])
    db.commit()
    db.refresh(comment)
    return comment


def list_comments(db: Session, issue_id: int, user: User) -> list[IssueComment]:
    issue = get_accessible_issue(db, issue_id, user)
    return list(issue.comments)


# ─── 状态机 ──────────────────────────────────────────
def _transition(issue: IssueRecord, action: str) -> None:
    current = issue.handle_status or "open"
    allowed = _TRANSITIONS.get(current, {})
    if action not in allowed:
        raise HTTPException(
            400,
            f"状态「{current}」下不允许执行「{action}」操作；"
            f"可用操作：{', '.join(allowed.keys()) or '（无）'}",
        )
    issue.handle_status = allowed[action]
