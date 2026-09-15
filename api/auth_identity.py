"""API 共享身份解析。

只负责 Authorization Token 的规范化与真实用户解析；具体接口是否允许
X-User-Id 等兼容身份，由各业务路由自行决定。

实现位于 perseids_server/utils/auth_identity.py，此处 re-export 保持
既有调用点（api/storyboard.py、api/agent_auth.py 等）不变。
"""
from perseids_server.utils.auth_identity import (
    normalize_authorization_token,
    resolve_authorization_user_id,
)

__all__ = ["normalize_authorization_token", "resolve_authorization_user_id"]
