"""用户自助修改昵称接口（PUT /api/user/nickname）回归测试。

覆盖：设置昵称成功、清空昵称（由 model 层重新随机分配）、
昵称超长 400、未登录/无效 token 401。
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api import user as user_api


def _run(monkeypatch, nickname, *, token_valid=True, saved="机智的熊猫521"):
    tokens_model = MagicMock()
    tokens_model.get_user_id_by_token.return_value = 7 if token_valid else None
    monkeypatch.setattr(user_api, "UserTokensModel", tokens_model)

    users_model = MagicMock()
    users_model.update_nickname.return_value = saved
    monkeypatch.setattr(user_api, "UsersModel", users_model)

    return asyncio.run(
        user_api.update_nickname(
            request=user_api.UpdateNicknameRequest(nickname=nickname),
            auth_token="Bearer test",
        )
    )


def test_set_nickname_success(monkeypatch):
    result = _run(monkeypatch, "小明", saved="小明")
    assert result["code"] == 0
    assert result["data"]["nickname"] == "小明"
    assert result["data"]["display_name"] == "小明"
    user_api.UsersModel.update_nickname.assert_called_once_with(7, "小明")


def test_empty_nickname_delegates_to_model(monkeypatch):
    # 空昵称 = 重置为随机默认昵称：接口透传空串，由 model 层生成并返回
    result = _run(monkeypatch, "   ", saved="快乐的柴犬88")
    assert result["code"] == 0
    assert result["data"]["nickname"] == "快乐的柴犬88"
    user_api.UsersModel.update_nickname.assert_called_once_with(7, "")


def test_nickname_too_long_rejected(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        _run(monkeypatch, "超" * 31)
    assert exc_info.value.status_code == 400
    user_api.UsersModel.update_nickname.assert_not_called()


def test_nickname_at_max_length_allowed(monkeypatch):
    result = _run(monkeypatch, "a" * 30, saved="a" * 30)
    assert result["code"] == 0
    user_api.UsersModel.update_nickname.assert_called_once_with(7, "a" * 30)


def test_nickname_requires_login(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        _run(monkeypatch, "小明", token_valid=False)
    assert exc_info.value.status_code == 401
    user_api.UsersModel.update_nickname.assert_not_called()
