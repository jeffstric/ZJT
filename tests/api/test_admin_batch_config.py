import asyncio
import logging
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import admin as admin_api
from model.system_config import SystemConfig
from model import system_config_history as history_module
from services import system_config_batch_service as batch_service


def test_batch_route_offloads_entire_database_batch(monkeypatch):
    main_thread_id = threading.get_ident()
    worker_thread_ids = []

    async def require_admin(_auth_token):
        return SimpleNamespace(id=23)

    def run_batch(*, env, configs, updated_by):
        worker_thread_ids.append(threading.get_ident())
        assert env == "test"
        assert configs == [("huimengi.api_key", "hm-secret")]
        assert updated_by == 23
        return {
            "results": [{"key": "huimengi.api_key", "status": "updated"}],
            "errors": [],
        }

    monkeypatch.setattr(admin_api, "require_admin", require_admin)
    monkeypatch.setattr(admin_api, "get_current_env", lambda: "test")
    monkeypatch.setattr(admin_api, "batch_update_system_configs", run_batch)
    monkeypatch.setattr(
        admin_api.EditionStrategy,
        "check_aggregator_sites",
        lambda _keys: (True, ""),
    )

    response = asyncio.run(
        admin_api.admin_batch_update_configs(
            admin_api.BatchConfigRequest(
                configs=[admin_api.BatchConfigItem(key="huimengi.api_key", value="hm-secret")]
            ),
            auth_token="token",
        )
    )

    assert worker_thread_ids and worker_thread_ids[0] != main_thread_id
    assert response == {
        "code": 0,
        "message": "批量更新完成，新建 0 条，更新 1 条配置",
        "data": {
            "results": [{"key": "huimengi.api_key", "status": "updated"}],
            "errors": [],
        },
    }


def test_batch_route_rejects_oversized_request_before_starting_worker(monkeypatch):
    async def require_admin(_auth_token):
        return SimpleNamespace(id=23)

    called = False

    def run_batch(**_kwargs):
        nonlocal called
        called = True
        return {"results": [], "errors": []}

    monkeypatch.setattr(admin_api, "require_admin", require_admin)
    monkeypatch.setattr(admin_api, "get_current_env", lambda: "test")
    monkeypatch.setattr(admin_api, "batch_update_system_configs", run_batch)
    monkeypatch.setattr(admin_api, "ADMIN_CONFIG_BATCH_MAX_ITEMS", 1)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            admin_api.admin_batch_update_configs(
                admin_api.BatchConfigRequest(
                    configs=[
                        admin_api.BatchConfigItem(key="huimengi.api_key", value="hm-secret"),
                        admin_api.BatchConfigItem(
                            key="huimengi.base_url",
                            value="https://example.com",
                        ),
                    ]
                ),
                auth_token="token",
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "单次最多更新 1 条配置"
    assert called is False


def test_batch_service_writes_history_and_invalidates_changed_keys(monkeypatch, caplog):
    connection = object()
    history_calls = []
    invalidated = []

    @contextmanager
    def fake_transaction():
        yield connection

    existing = SystemConfig(
        id=8,
        env="test",
        config_key="huimengi.base_url",
        config_value="https://old.example",
        value_type="string",
        editable=1,
        is_sensitive=0,
    )

    def get_config(_conn, _env, key, *, for_update):
        assert for_update is True
        return existing if key == "huimengi.base_url" else None

    monkeypatch.setattr(batch_service, "transaction", fake_transaction)
    monkeypatch.setattr(
        batch_service.SystemConfigModel,
        "get_by_key_in_transaction",
        get_config,
    )
    monkeypatch.setattr(
        batch_service.SystemConfigModel,
        "create_in_transaction",
        lambda *_args, **_kwargs: 19,
    )
    monkeypatch.setattr(
        batch_service.SystemConfigModel,
        "update_value_in_transaction",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(
        batch_service.SystemConfigHistoryModel,
        "create_in_transaction",
        lambda *args, **kwargs: history_calls.append((args, kwargs)) or len(history_calls),
    )
    monkeypatch.setattr(batch_service, "invalidate_dynamic_cache", invalidated.append)

    secret = "hm-never-log-this-secret"
    with caplog.at_level(logging.INFO):
        result = batch_service.batch_update_system_configs(
            env="test",
            configs=[
                ("huimengi.api_key", secret),
                ("huimengi.base_url", "https://new.example"),
            ],
            updated_by=23,
        )

    assert result == {
        "results": [
            {"key": "huimengi.api_key", "status": "created"},
            {"key": "huimengi.base_url", "status": "updated"},
        ],
        "errors": [],
    }
    assert invalidated == ["huimengi.api_key", "huimengi.base_url"]
    assert len(history_calls) == 2
    created_history = history_calls[0][1]
    assert created_history["old_value"] is None
    assert created_history["new_value"] == secret
    assert created_history["is_sensitive"] == 1
    updated_history = history_calls[1][1]
    assert updated_history["old_value"] == "https://old.example"
    assert updated_history["new_value"] == "https://new.example"
    assert secret not in caplog.text


def test_batch_service_rolls_back_config_when_history_fails(monkeypatch):
    events = []
    invalidated = []

    @contextmanager
    def fake_transaction():
        events.append("begin")
        try:
            yield object()
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    existing = SystemConfig(
        id=8,
        env="test",
        config_key="huimengi.base_url",
        config_value="https://old.example",
        value_type="string",
        editable=1,
        is_sensitive=0,
    )

    monkeypatch.setattr(batch_service, "transaction", fake_transaction)
    monkeypatch.setattr(
        batch_service.SystemConfigModel,
        "get_by_key_in_transaction",
        lambda *_args, **_kwargs: existing,
    )
    monkeypatch.setattr(
        batch_service.SystemConfigModel,
        "update_value_in_transaction",
        lambda *_args, **_kwargs: events.append("update") or 1,
    )

    def fail_history(*_args, **_kwargs):
        events.append("history")
        raise RuntimeError("database rejected history")

    monkeypatch.setattr(
        batch_service.SystemConfigHistoryModel,
        "create_in_transaction",
        fail_history,
    )
    monkeypatch.setattr(batch_service, "invalidate_dynamic_cache", invalidated.append)

    result = batch_service.batch_update_system_configs(
        env="test",
        configs=[("huimengi.base_url", "https://new.example")],
        updated_by=23,
    )

    assert events == ["begin", "update", "history", "rollback"]
    assert result == {
        "results": [],
        "errors": ["huimengi.base_url: 更新失败"],
    }
    assert invalidated == []


def test_transactional_history_masks_sensitive_values(monkeypatch):
    captured = {}

    def insert(_conn, _sql, params):
        captured["params"] = params
        return 31

    monkeypatch.setattr(history_module, "execute_insert_in_transaction", insert)

    history_id = history_module.SystemConfigHistoryModel.create_in_transaction(
        object(),
        config_id=19,
        env="test",
        config_key="huimengi.api_key",
        old_value="hm-old-secret-value",
        new_value="hm-new-secret-value",
        value_type="string",
        is_sensitive=1,
        updated_by=23,
    )

    assert history_id == 31
    assert captured["params"][3] == "hm-o****alue"
    assert captured["params"][4] == "hm-n****alue"
    assert "hm-old-secret-value" not in captured["params"]
    assert "hm-new-secret-value" not in captured["params"]
