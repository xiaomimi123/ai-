"""认证与审计：从 Authorization Bearer token 解析当前用户。

简单 token：DB 存随机字符串，请求头携带，无需 JWT 库。
"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import is_admin
from app.models import AuditLog, AuthToken, User, get_db


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _extract_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    record = db.query(AuthToken).filter(AuthToken.token == token).first()
    if record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已失效")
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号已停用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin(user.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def log_action(db: Session, user: Optional[User], action: str,
               target_type: str = "", target_id: Optional[int] = None,
               detail: str = "") -> None:
    """记录审计日志（§3.7「全程留痕可溯源」）。"""
    db.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "",
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail[:1000],
    ))
    # 不在此 commit，由调用方与业务一并提交
