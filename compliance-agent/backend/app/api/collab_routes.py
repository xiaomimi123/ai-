"""协同复核 + 在线批注 API（§3.7）。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import (
    CommentCreateRequest,
    IssueAssignRequest,
    IssueCommentOut,
    IssueOut,
    IssueReviewRequest,
    IssueSubmitRequest,
)
from app.core.auth import get_current_user
from app.models import User, get_db
from app.services import collab_service as collab

collab_router = APIRouter(prefix="/api/issues", tags=["collab"])


@collab_router.get("/{issue_id}", response_model=IssueOut)
def get_issue(issue_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    return collab.get_accessible_issue(db, issue_id, user)


# ─── 状态流转 ─────────────────────────────────────────
@collab_router.post("/{issue_id}/assign", response_model=IssueOut)
def assign(issue_id: int, req: IssueAssignRequest,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collab.assign_issue(db, issue_id, req.assignee_id, user)


@collab_router.post("/{issue_id}/start", response_model=IssueOut)
def start(issue_id: int,
          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collab.start_fixing(db, issue_id, user)


@collab_router.post("/{issue_id}/submit", response_model=IssueOut)
def submit(issue_id: int, req: IssueSubmitRequest,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collab.submit_fix(db, issue_id, req.fix_note, user)


@collab_router.post("/{issue_id}/approve", response_model=IssueOut)
def approve(issue_id: int, req: IssueReviewRequest,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collab.approve_fix(db, issue_id, req.review_note, user)


@collab_router.post("/{issue_id}/reject", response_model=IssueOut)
def reject(issue_id: int, req: IssueReviewRequest,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collab.reject_fix(db, issue_id, req.review_note, user)


@collab_router.post("/{issue_id}/reopen", response_model=IssueOut)
def reopen(issue_id: int,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collab.reopen_issue(db, issue_id, user)


# ─── 在线批注 ─────────────────────────────────────────
@collab_router.get("/{issue_id}/comments", response_model=List[IssueCommentOut])
def get_comments(issue_id: int,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collab.list_comments(db, issue_id, user)


@collab_router.post("/{issue_id}/comments", response_model=IssueCommentOut)
def post_comment(issue_id: int, req: CommentCreateRequest,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return collab.add_comment(db, issue_id, req.body, user)
