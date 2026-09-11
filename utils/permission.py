"""
用户与权限（轻量实现，演示级）

职责：
- 从 config/users.yml 加载用户、角色与权限映射
- 提供「取用户角色」「判定权限」的接口

设计说明（面试要点）：
- 当前 user_id 由前端声明，属于**演示级身份**，不可作为生产安全边界。
- 生产改造：身份由 JWT/SSO 签发并校验签名；角色由用户中心下发；
  权限判定收敛到统一中间件；所有敏感操作写审计日志（谁/何时/做了什么/结果）。
"""

import os
from typing import Optional

import yaml

from utils.logger_handler import logger
from utils.path_tool import get_abs_path


class PermissionService:
    """用户与权限服务（单例）"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._path = get_abs_path("config/users.yml")
        self._users: dict = {}
        self._roles: dict = {}
        self._default_user: str = "guest"
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            logger.warning(f"[Permission] 未找到 {self._path}，使用内置默认用户")
            self._users = {"guest": {"display_name": "访客", "role": "user"}}
            self._roles = {"user": {"permissions": ["chat"]}}
            return
        with open(self._path, "r", encoding="utf-8") as f:
            conf = yaml.safe_load(f) or {}
        self._users = conf.get("users", {})
        self._roles = conf.get("roles", {})
        self._default_user = conf.get("default_user", "guest")
        logger.info(f"[Permission] 已加载 {len(self._users)} 个用户、{len(self._roles)} 个角色")

    # ────────────── 用户 ──────────────

    @property
    def default_user(self) -> str:
        return self._default_user

    def exists(self, user_id: str) -> bool:
        return user_id in self._users

    def get_role(self, user_id: str) -> str:
        """取用户角色；未注册用户按默认角色（user）处理"""
        user = self._users.get(user_id)
        if not user:
            return "user"
        return user.get("role", "user")

    def get_display_name(self, user_id: str) -> str:
        user = self._users.get(user_id)
        return (user or {}).get("display_name", user_id)

    def list_users(self) -> list:
        """用户列表（供前端切换用户使用，附带角色信息）"""
        result = []
        for uid, info in self._users.items():
            result.append({
                "user_id": uid,
                "display_name": info.get("display_name", uid),
                "role": info.get("role", "user"),
                "permissions": self.permissions_of(uid),
            })
        return result

    # ────────────── 权限 ──────────────

    def permissions_of(self, user_id: str) -> list:
        role = self.get_role(user_id)
        return list(self._roles.get(role, {}).get("permissions", []))

    def has_permission(self, user_id: str, permission: str) -> bool:
        return permission in self.permissions_of(user_id)

    def is_admin(self, user_id: str) -> bool:
        return self.get_role(user_id) == "admin"

    def resolve_user(self, user_id: Optional[str]) -> str:
        """把空/未知身份归一到有效用户（未知用户按默认用户处理）"""
        if not user_id:
            return self._default_user
        return user_id if self.exists(user_id) else self._default_user


# 全局单例
permission_service = PermissionService()
