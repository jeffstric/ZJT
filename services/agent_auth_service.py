"""Exchange external agent tokens for short-lived auth tokens."""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from config.constant import AgentAuthConstants
from config.config_util import get_current_env
from config.version import get_app_version
from model.user_api_tokens import UserApiTokensModel
from model.user_tokens import UserTokensModel
from model.users import UsersModel
from perseids_server.utils.token import generate_token


class AgentAuthError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {"success": False, "error_code": self.error_code, "error": self.message}


class AgentAuthService:
    @staticmethod
    def create_storyboard_agent_token(user_id: int) -> Dict[str, Any]:
        user = UsersModel.get_by_id(int(user_id))
        if not user or int(getattr(user, "status", 0) or 0) != 1:
            raise AgentAuthError(403, "user_unavailable", "user is disabled or not found")

        raw_token = UserApiTokensModel.generate_raw_token(AgentAuthConstants.TOKEN_TYPE_AGENT)
        expire_time = datetime.now() + timedelta(days=AgentAuthConstants.DEFAULT_AGENT_TOKEN_EXPIRE_DAYS)
        scopes = [
            AgentAuthConstants.SCOPE_AUTH_EXCHANGE,
            AgentAuthConstants.SCOPE_STORYBOARD_READ,
            AgentAuthConstants.SCOPE_STORYBOARD_GENERATE,
        ]
        token_id = UserApiTokensModel.create(
            int(user_id),
            raw_token,
            token_type=AgentAuthConstants.TOKEN_TYPE_AGENT,
            scopes=scopes,
            expire_at=expire_time,
        )
        return {
            "success": True,
            "token_id": int(token_id),
            "agent_token": raw_token,
            "token_type": AgentAuthConstants.TOKEN_TYPE_AGENT,
            "api_version": AgentAuthConstants.STORYBOARD_AGENT_API_VERSION,
            "app_version": get_app_version(),
            "environment": get_current_env(),
            "scopes": scopes,
            "expires_at": expire_time.isoformat(),
        }

    @staticmethod
    def exchange_token(raw_token: str, device_uuid: Optional[str] = None) -> Dict[str, Any]:
        token = UserApiTokensModel.get_valid_by_raw_token(
            raw_token,
            required_scope=AgentAuthConstants.SCOPE_AUTH_EXCHANGE,
            token_type=AgentAuthConstants.TOKEN_TYPE_AGENT,
        )
        if not token:
            raise AgentAuthError(401, "invalid_agent_token", "invalid or expired agent token")

        user = UsersModel.get_by_id(int(token.user_id))
        if not user or int(getattr(user, "status", 0) or 0) != 1:
            raise AgentAuthError(403, "user_unavailable", "user is disabled or not found")

        device = device_uuid or AgentAuthConstants.DEFAULT_DEVICE_UUID
        auth_token = generate_token(int(token.user_id), device)
        expire_time = datetime.now() + timedelta(hours=AgentAuthConstants.DEFAULT_SESSION_EXPIRE_HOURS)
        UserTokensModel.create(int(token.user_id), auth_token, expire_time, device)
        UserApiTokensModel.touch_last_used(int(token.id))

        return {
            "success": True,
            "auth_token": auth_token,
            "expires_at": expire_time.isoformat(),
            "user_id": int(token.user_id),
            "token_type": token.token_type,
            "environment": get_current_env(),
            "scopes": list(token.scopes),
        }
