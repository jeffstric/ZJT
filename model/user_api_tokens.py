"""User API token model for external agents and integrations."""
import hashlib
import json
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.constant import AgentAuthConstants
from .database import execute_insert, execute_query, execute_update


def hash_api_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def _parse_scopes(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return []


class UserApiToken:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.user_id = kwargs.get("user_id")
        self.token_hash = kwargs.get("token_hash")
        self.token_prefix = kwargs.get("token_prefix")
        self.token_type = kwargs.get("token_type")
        self.scopes = _parse_scopes(kwargs.get("scopes"))
        self.enabled = int(kwargs.get("enabled", 1) or 0)
        self.expire_at = kwargs.get("expire_at")
        self.last_used_at = kwargs.get("last_used_at")
        self.create_at = kwargs.get("create_at")
        self.update_at = kwargs.get("update_at")

    def has_scope(self, scope: Optional[str]) -> bool:
        if not scope:
            return True
        if scope in self.scopes or "*" in self.scopes:
            return True
        prefix = scope.split(":", 1)[0]
        return f"{prefix}:*" in self.scopes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "token_prefix": self.token_prefix,
            "token_type": self.token_type,
            "scopes": self.scopes,
            "enabled": self.enabled,
            "expire_at": self.expire_at.isoformat() if hasattr(self.expire_at, "isoformat") else self.expire_at,
            "last_used_at": self.last_used_at.isoformat() if hasattr(self.last_used_at, "isoformat") else self.last_used_at,
            "create_at": self.create_at.isoformat() if hasattr(self.create_at, "isoformat") else self.create_at,
            "update_at": self.update_at.isoformat() if hasattr(self.update_at, "isoformat") else self.update_at,
        }


class UserApiTokensModel:
    @staticmethod
    def generate_raw_token(token_type: str = AgentAuthConstants.TOKEN_TYPE_AGENT) -> str:
        prefix = AgentAuthConstants.RAW_TOKEN_PREFIX if token_type == AgentAuthConstants.TOKEN_TYPE_AGENT else "zjt_api_"
        return f"{prefix}{secrets.token_urlsafe(32)}"

    @staticmethod
    def create(
        user_id: int,
        raw_token: str,
        *,
        token_type: str = AgentAuthConstants.TOKEN_TYPE_AGENT,
        scopes: Optional[List[str]] = None,
        enabled: int = 1,
        expire_at: Optional[datetime] = None,
    ) -> int:
        scopes_json = json.dumps(scopes or [], ensure_ascii=False)
        token_prefix = raw_token[:16]
        sql = """
            INSERT INTO user_api_tokens
                (user_id, token_hash, token_prefix, token_type, scopes, enabled, expire_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        return execute_insert(
            sql,
            (int(user_id), hash_api_token(raw_token), token_prefix, token_type, scopes_json, int(enabled), expire_at),
        )

    @staticmethod
    def get_valid_by_raw_token(
        raw_token: str,
        required_scope: Optional[str] = None,
        token_type: Optional[str] = None,
    ) -> Optional[UserApiToken]:
        if not raw_token:
            return None
        conditions = [
            "token_hash = %s",
            "enabled = 1",
            "(expire_at IS NULL OR expire_at > NOW())",
        ]
        params: List[Any] = [hash_api_token(raw_token)]
        if token_type:
            conditions.append("token_type = %s")
            params.append(token_type)
        sql = f"SELECT * FROM user_api_tokens WHERE {' AND '.join(conditions)} LIMIT 1"
        row = execute_query(sql, tuple(params), fetch_one=True)
        if not row:
            return None
        token = UserApiToken(**row)
        return token if token.has_scope(required_scope) else None

    @staticmethod
    def touch_last_used(token_id: int) -> int:
        return execute_update(
            "UPDATE user_api_tokens SET last_used_at = NOW(), update_at = NOW() WHERE id = %s",
            (token_id,),
        )


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `user_api_tokens` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `token_hash` CHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `token_prefix` VARCHAR(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `token_type` VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'agent',
  `scopes` JSON DEFAULT NULL,
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `expire_at` DATETIME DEFAULT NULL,
  `last_used_at` DATETIME DEFAULT NULL,
  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idx_user_api_token_hash` (`token_hash`),
  KEY `idx_user_api_tokens_user` (`user_id`),
  KEY `idx_user_api_tokens_type` (`token_type`),
  KEY `idx_user_api_tokens_expire` (`expire_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User API tokens for agents and integrations'
"""
