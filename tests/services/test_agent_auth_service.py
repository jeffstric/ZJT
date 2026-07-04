from datetime import datetime, timedelta
from types import SimpleNamespace


def test_exchange_agent_token_creates_short_lived_auth_token(monkeypatch):
    from services.agent_auth_service import AgentAuthService
    from config.constant import AgentAuthConstants

    monkeypatch.setenv("comfyui_env", "unit")
    valid_token = SimpleNamespace(
        id=9,
        user_id=7,
        token_type=AgentAuthConstants.TOKEN_TYPE_AGENT,
        scopes=[AgentAuthConstants.SCOPE_AUTH_EXCHANGE, "storyboard:generate"],
    )
    user = SimpleNamespace(id=7, status=1)
    created = []

    monkeypatch.setattr(
        "services.agent_auth_service.UserApiTokensModel.get_valid_by_raw_token",
        lambda raw_token, required_scope=None, token_type=None: valid_token,
    )
    monkeypatch.setattr("services.agent_auth_service.UsersModel.get_by_id", lambda user_id: user)
    monkeypatch.setattr("services.agent_auth_service.generate_token", lambda user_id, device_uuid=None: "auth-token-123")
    monkeypatch.setattr(
        "services.agent_auth_service.UserTokensModel.create",
        lambda user_id, token, expire_time, device_uuid=None: created.append(
            (user_id, token, expire_time, device_uuid)
        ) or 21,
    )
    monkeypatch.setattr("services.agent_auth_service.UserApiTokensModel.touch_last_used", lambda token_id: 1)

    result = AgentAuthService.exchange_token("agent-token", device_uuid="agent-device")

    assert result["success"] is True
    assert result["auth_token"] == "auth-token-123"
    assert result["user_id"] == 7
    assert result["token_type"] == AgentAuthConstants.TOKEN_TYPE_AGENT
    assert result["environment"] == "unit"
    assert "storyboard:generate" in result["scopes"]
    assert created[0][0] == 7
    assert created[0][1] == "auth-token-123"
    assert created[0][2] > datetime.now() + timedelta(minutes=30)
    assert created[0][3] == "agent-device"


def test_exchange_agent_token_rejects_missing_scope(monkeypatch):
    from services.agent_auth_service import AgentAuthService, AgentAuthError

    monkeypatch.setattr(
        "services.agent_auth_service.UserApiTokensModel.get_valid_by_raw_token",
        lambda raw_token, required_scope=None, token_type=None: None,
    )

    try:
        AgentAuthService.exchange_token("bad-token")
    except AgentAuthError as exc:
        assert exc.status_code == 401
        assert exc.error_code == "invalid_agent_token"
    else:
        raise AssertionError("expected AgentAuthError")
