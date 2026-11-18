"""显式标识接口的归属校验，以及用户级开关不吃任务级留痕。"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.aigc import (
    ExplicitLabelRequest,
    ExplicitOptOutRequest,
    add_explicit_label,
    request_explicit_opt_out,
)
from model.aigc_explicit_opt_out import (
    AigcExplicitOptOutModel,
    OPT_OUT_SOURCE_CHAT_CARD,
    OPT_OUT_SOURCE_USER_SETTINGS,
)


def _request(user_id=5):
    return SimpleNamespace(
        state=SimpleNamespace(user_id=user_id),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
    )


def test_has_opt_out_user_filters_user_settings(monkeypatch):
    captured = {}

    def fake_execute(sql, params=None, fetch_one=False, fetch_all=False):
        captured["sql"] = sql
        captured["params"] = params
        return None

    monkeypatch.setattr("model.aigc_explicit_opt_out.execute_query", fake_execute)
    assert AigcExplicitOptOutModel.has_opt_out_user(7) is False
    assert "request_source" in captured["sql"]
    assert captured["params"] == (7, OPT_OUT_SOURCE_USER_SETTINGS)


def test_has_opt_out_user_true_only_for_user_settings_row(monkeypatch):
    def fake_execute(sql, params=None, fetch_one=False, fetch_all=False):
        assert params[1] == OPT_OUT_SOURCE_USER_SETTINGS
        return {"action": "opt_out"}

    monkeypatch.setattr("model.aigc_explicit_opt_out.execute_query", fake_execute)
    assert AigcExplicitOptOutModel.has_opt_out_user(7) is True


def test_explicit_label_foreign_tool_is_404(monkeypatch):
    monkeypatch.setattr(
        "api.aigc.AIToolsModel.get_by_id",
        lambda ai_tool_id: SimpleNamespace(user_id=9, result_url="/upload/a.png"),
    )
    monkeypatch.setattr(
        "api.aigc.burn_explicit_label",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应烧录")),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(add_explicit_label.__wrapped__(
            _request(5), ExplicitLabelRequest(ai_tool_id=42),
        ))
    assert exc.value.status_code == 404
    assert exc.value.detail == "任务不存在"


def test_explicit_optout_foreign_tool_is_404_even_for_user_scope(monkeypatch):
    created = []
    monkeypatch.setattr(
        "api.aigc.AIToolsModel.get_by_id",
        lambda ai_tool_id: SimpleNamespace(user_id=9, result_url="/upload/a.png"),
    )
    monkeypatch.setattr(
        "api.aigc.AigcExplicitOptOutModel.create",
        lambda *args, **kwargs: created.append(args) or 1,
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(request_explicit_opt_out.__wrapped__(
            _request(5),
            ExplicitOptOutRequest(ai_tool_id=42, scope="user"),
        ))
    assert exc.value.status_code == 404
    assert created == []


def test_user_scope_without_tool_records_user_settings(monkeypatch):
    created = {}

    def fake_create(*args, **kwargs):
        created["args"] = args
        return 1

    monkeypatch.setattr("api.aigc.AigcExplicitOptOutModel.create", fake_create)
    result = asyncio.run(request_explicit_opt_out.__wrapped__(
        _request(5),
        ExplicitOptOutRequest(scope="user"),
    ))
    assert result["opt_out"] is True
    assert "后续生成" in result["message"]
    assert created["args"][0] == 5
    assert created["args"][1] is None
    assert created["args"][4] == OPT_OUT_SOURCE_USER_SETTINGS


def test_task_level_optout_message_is_task_scoped(monkeypatch):
    created = {}

    def fake_create(*args, **kwargs):
        created["args"] = args
        return 1

    monkeypatch.setattr(
        "api.aigc.AIToolsModel.get_by_id",
        lambda ai_tool_id: SimpleNamespace(user_id=5, result_url="/upload/a.png"),
    )
    monkeypatch.setattr("api.aigc.AigcExplicitOptOutModel.create", fake_create)
    result = asyncio.run(request_explicit_opt_out.__wrapped__(
        _request(5),
        ExplicitOptOutRequest(ai_tool_id=42),
    ))
    assert result["opt_out"] is True
    assert "该任务" in result["message"]
    assert "后续生成" not in result["message"]
    assert created["args"][1] == 42
    assert created["args"][4] == OPT_OUT_SOURCE_CHAT_CARD
