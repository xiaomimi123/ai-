"""认证与用户管理路由（v3 §3.7）。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import (
    AuditLogOut,
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    SetActiveRequest,
    UserOut,
)
from app.core.auth import get_current_user, log_action, new_token, require_admin
from app.core.permissions import ALL_ROLES, normalize_role, role_label
from app.core.security import hash_password, verify_password
from app.models import AuditLog, AuthToken, User, get_db
from app.services import user_service

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"])
audit_router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


def _user_to_login_response(user: User, token: str = "") -> LoginResponse:
    return LoginResponse(
        token=token,
        user=UserOut.model_validate(user),
        role_label=role_label(user.role),
    )


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
    return _user_to_login_response(user, token=token_str)


@auth_router.post("/logout")
def logout(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(AuthToken).filter(AuthToken.user_id == user.id).delete()
    log_action(db, user, "auth.logout", target_type="user", target_id=user.id)
    db.commit()
    return {"status": "ok"}


@auth_router.get("/me", response_model=LoginResponse)
def me(user: User = Depends(get_current_user)):
    return _user_to_login_response(user)


# ─── 用户管理（仅超级管理员）──────────────────────────
@users_router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()


@users_router.post("", response_model=UserOut)
def create_user(req: CreateUserRequest,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    role = normalize_role(req.role)
    if role not in ALL_ROLES:
        raise HTTPException(400, f"无效角色: {req.role}")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(400, "用户名已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        role=role,
        full_name=req.full_name,
        unit_id=req.unit_id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    log_action(db, admin, "user.create", target_type="user", target_id=user.id,
               detail=f"创建用户 {user.username}（{user.role}）")
    db.commit()
    db.refresh(user)
    return user


# ─── 用户管理增强：改密码 / 启停 / 软删 ──────────────
@users_router.patch("/{user_id}/password", response_model=UserOut)
def change_password(user_id: int, req: PasswordChangeRequest,
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """改密码。管理员可改任何人；非管理员只能改自己且必须提供旧密码。"""
    return user_service.update_password(
        db, user_id, req.new_password, user, req.old_password
    )


@users_router.patch("/{user_id}/activate", response_model=UserOut)
def set_user_active(user_id: int, req: SetActiveRequest,
                    db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    """启用/停用用户。"""
    return user_service.set_active(db, user_id, req.active, admin)


@users_router.delete("/{user_id}")
def delete_user(user_id: int,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    """软删用户（停用 + 用户名加 deleted_ 前缀避免重名）。"""
    user_service.soft_delete_user(db, user_id, admin)
    return {"status": "ok"}


# ─── 审计日志（仅超级管理员）──────────────────────────
@audit_router.get("", response_model=List[AuditLogOut])
def list_audit_logs(limit: int = Query(default=100, le=500),
                    db: Session = Depends(get_db),
                    _: User = Depends(require_admin)):
    return db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
