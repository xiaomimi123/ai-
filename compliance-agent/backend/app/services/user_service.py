"""用户管理服务（密码修改 / 启停 / 软删）。

安全规则：
- 不允许操作自己的启停 / 删除
- 不允许停用 / 删除最后一个 super_admin
- 停用 / 删除会立即清空该用户的 AuthToken
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.auth import log_action
from app.core.permissions import is_admin
from app.core.security import hash_password, verify_password
from app.models import AuthToken, User


MIN_PASSWORD_LEN = 6


def update_password(db: Session, target_id: int, new_password: str,
                    operator: User, old_password: Optional[str] = None) -> User:
    """改密码。管理员可改任何人；非管理员只能改自己且必须提供旧密码。"""
    if not new_password or len(new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"密码至少 {MIN_PASSWORD_LEN} 位")

    target = db.get(User, target_id)
    if target is None:
        raise HTTPException(404, "用户不存在")

    operator_is_admin = is_admin(operator.role)
    is_self = target.id == operator.id

    if not operator_is_admin and not is_self:
        raise HTTPException(403, "无权修改他人密码")

    # 非管理员改自己必须验证旧密码
    if not operator_is_admin and is_self:
        if not old_password or not verify_password(old_password, target.password_hash):
            raise HTTPException(400, "原密码错误")

    target.password_hash = hash_password(new_password)

    # 改密码后吊销该用户所有 token（避免老 token 仍能用）
    # 但操作者改自己时保留当前会话 — 通过 token 是单独表，简单做法：
    # 直接全部清，让用户重新登录最稳
    db.query(AuthToken).filter(AuthToken.user_id == target.id).delete()

    log_action(db, operator, "user.password_change",
               target_type="user", target_id=target.id,
               detail=f"修改密码 {'(自己)' if is_self else f'(操作 {target.username})'}")
    db.commit()
    db.refresh(target)
    return target


def set_active(db: Session, target_id: int, active: bool, operator: User) -> User:
    """启用/停用。仅 super_admin 可操作。"""
    if not is_admin(operator.role):
        raise HTTPException(403, "需要超级管理员权限")

    target = db.get(User, target_id)
    if target is None:
        raise HTTPException(404, "用户不存在")

    if target.id == operator.id:
        raise HTTPException(400, "不允许操作自己的启停状态")

    # 停用前检查：不能让最后一个 super_admin 失效
    if not active and is_admin(target.role):
        active_admins = db.query(User).filter(
            User.role == "super_admin", User.is_active == True,
            User.id != target.id,
        ).count()
        if active_admins == 0:
            raise HTTPException(400, "不能停用最后一个超级管理员")

    if target.is_active == active:
        return target  # 无变化

    target.is_active = active

    # 停用立即吊销 token
    if not active:
        db.query(AuthToken).filter(AuthToken.user_id == target.id).delete()

    log_action(db, operator,
               "user.activate" if active else "user.deactivate",
               target_type="user", target_id=target.id,
               detail=f"{'启用' if active else '停用'} {target.username}")
    db.commit()
    db.refresh(target)
    return target


def soft_delete_user(db: Session, target_id: int, operator: User) -> User:
    """软删：停用 + 用户名加 deleted_ 前缀避免重名 + 清空 token。"""
    if not is_admin(operator.role):
        raise HTTPException(403, "需要超级管理员权限")

    target = db.get(User, target_id)
    if target is None:
        raise HTTPException(404, "用户不存在")

    if target.id == operator.id:
        raise HTTPException(400, "不允许删除自己")

    if is_admin(target.role):
        active_admins = db.query(User).filter(
            User.role == "super_admin", User.is_active == True,
            User.id != target.id,
        ).count()
        if active_admins == 0:
            raise HTTPException(400, "不能删除最后一个超级管理员")

    original_username = target.username
    # 软删标记：停用 + 改名避免重名
    target.is_active = False
    target.username = f"deleted_{target.id}_{original_username}"[:64]

    db.query(AuthToken).filter(AuthToken.user_id == target.id).delete()

    log_action(db, operator, "user.delete",
               target_type="user", target_id=target.id,
               detail=f"软删用户 {original_username}")
    db.commit()
    db.refresh(target)
    return target
