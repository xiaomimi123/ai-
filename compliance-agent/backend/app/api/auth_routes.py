"""认证与用户管理路由（§3.7）。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    AuditLogOut,
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    UserOut,
)
from app.core.auth import get_current_user, log_action, new_token, require_admin
from app.core.permissions import (
    ALL_ROLES,
    allowed_categories,
    role_label,
)
from app.core.security import hash_password, verify_password
from app.models import AuditLog, AuthToken, User, get_db

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"])
audit_router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


@auth_router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if user is None or not user.is_active or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    token_str = new_token()
    db.add(AuthToken(user_id=user.id, token=token_str))
    log_action(db, user, "auth.login", target_type="user", target_id=user.id,
               detail=f"用户 {user.username} 登录")
    db.commit()
    return LoginResponse(
        token=token_str,
        user=UserOut.model_validate(user),
        role_label=role_label(user.role),
        allowed_categories=sorted(allowed_categories(user.role)),
    )


@auth_router.post("/logout")
def logout(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(AuthToken).filter(AuthToken.user_id == user.id).delete()
    log_action(db, user, "auth.logout", target_type="user", target_id=user.id)
    db.commit()
    return {"status": "ok"}


@auth_router.get("/me", response_model=LoginResponse)
def me(user: User = Depends(get_current_user)):
    return LoginResponse(
        token="",  # 当前接口不重发 token，仅返回用户信息
        user=UserOut.model_validate(user),
        role_label=role_label(user.role),
        allowed_categories=sorted(allowed_categories(user.role)),
    )


# ─── 用户管理（仅管理员）──────────────────────────────
@users_router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()


@users_router.post("", response_model=UserOut)
def create_user(req: CreateUserRequest,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    if req.role not in ALL_ROLES:
        raise HTTPException(400, f"无效角色: {req.role}")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(400, "用户名已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=req.role,
        full_name=req.full_name,
        is_active=True,
    )
    db.add(user)
    db.flush()
    log_action(db, admin, "user.create", target_type="user", target_id=user.id,
               detail=f"创建用户 {user.username}（{user.role}）")
    db.commit()
    db.refresh(user)
    return user


# ─── 审计日志（管理员可看全部）──────────────────────
@audit_router.get("", response_model=List[AuditLogOut])
def list_audit_logs(limit: int = Query(default=100, le=500),
                    db: Session = Depends(get_db),
                    _: User = Depends(require_admin)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return rows
