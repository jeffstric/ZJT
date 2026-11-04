"""P2 修复：退款幂等识别、宫格能力门闩、连接信息长度、直传源站与孤儿清理。"""
from types import SimpleNamespace

import pymysql
import pytest
from pydantic import ValidationError


def test_duplicate_transaction_integrity_error():
    from perseids_server.services.computing_power_service import (
        _is_duplicate_transaction,
        _is_duplicate_user_power_row,
    )

    txn_error = pymysql.err.IntegrityError(1062, "Duplicate entry 'refund-1' for key 'uk_transaction_id'")
    user_error = pymysql.err.IntegrityError(1062, "Duplicate entry '7' for key 'user_id'")
    assert _is_duplicate_transaction(txn_error) is True
    assert _is_duplicate_transaction(user_error) is False
    assert _is_duplicate_user_power_row(user_error) is True
    assert _is_duplicate_user_power_row(txn_error) is False


def test_connection_info_max_length():
    from api.agent_auth import AgentImageGenerationRequest, AgentImageStatusRequest
    from config.constant import AGENT_CLI_CONNECTION_INFO_MAX_CHARS

    AgentImageGenerationRequest(prompt="画一只猫", connection_info="a" * AGENT_CLI_CONNECTION_INFO_MAX_CHARS)
    with pytest.raises(ValidationError):
        AgentImageGenerationRequest(
            prompt="画一只猫",
            connection_info="a" * (AGENT_CLI_CONNECTION_INFO_MAX_CHARS + 1),
        )
    with pytest.raises(ValidationError):
        AgentImageStatusRequest(
            project_id=1,
            connection_info="b" * (AGENT_CLI_CONNECTION_INFO_MAX_CHARS + 1),
        )


def test_connection_scan_ignores_bytes_past_cap():
    from config.constant import AGENT_CLI_CONNECTION_INFO_MAX_CHARS
    from services.agent_image_service import extract_agent_token

    pad = "{" * AGENT_CLI_CONNECTION_INFO_MAX_CHARS
    assert extract_agent_token(pad + '{"agent_token":"hidden-token"}') is None
    assert extract_agent_token('说明\n{"agent_token":"visible-token"}') == "visible-token"


def test_moss_grid_rejected_before_submit():
    from config.constant import TaskTypeId
    from config.unified_config import init_unified_config
    from script_writer_core.mcp_tool import generate_text_to_image

    init_unified_config()
    result = generate_text_to_image(
        user_id="1",
        world_id="1",
        auth_token="token",
        prompt="一只猫",
        is_grid=True,
        task_type=TaskTypeId.MOSS_IMAGE,
    )
    assert result["success"] is False
    assert "不支持宫格" in result["error"]


def test_qiniu_put_time_and_orphan_selection():
    from task.qiniu_orphan_cleanup import qiniu_put_time_expired, select_orphan_keys

    now = 1_700_000_000
    fresh = int(now * 10_000_000)
    old = int((now - 86_400 - 10) * 10_000_000)
    assert qiniu_put_time_expired(None, now, 86_400) is False
    assert qiniu_put_time_expired(fresh, now, 86_400) is False
    assert qiniu_put_time_expired(old, now, 86_400) is True

    mapped = {"upload/workflow/1/kept.png"}
    items = [
        {"key": "upload/workflow/1/kept.png", "putTime": old},
        {"key": "upload/workflow/1/old.png", "putTime": old},
        {"key": "upload/workflow/1/new.png", "putTime": fresh},
        {"key": "upload/other/1/old.png", "putTime": old},
        {"key": "upload/workflow/", "putTime": old},
        {"key": "upload/workflow/1/unknown-age.png"},
    ]
    chosen = select_orphan_keys(
        items, now, lambda key: key in mapped, 86_400, "upload/workflow/", 10,
    )
    assert chosen == ["upload/workflow/1/old.png"]


def test_origin_download_does_not_use_cdn_domain():
    from unittest.mock import MagicMock, patch

    with patch("utils.file_storage.qiniu_storage.qiniu.Auth") as auth_cls:
        auth_cls.return_value.token_of_request.side_effect = lambda url: "ak:sig"
        from utils.file_storage.qiniu_storage import QiniuFileStorage, _io_host_cache

        storage = QiniuFileStorage("ak", "sk", "bucket-a", "cdn.example.com")
        storage._auth = MagicMock()
        storage._auth.token_of_request.side_effect = lambda url: "ak:sig"
        _io_host_cache.clear()
        with patch("utils.file_storage.qiniu_storage.qiniu.Region") as region_cls:
            region_cls.return_value.get_io_host.return_value = "iovip-z0.qbox.me"
            request = storage.get_origin_download_request("upload/workflow/1/a.png")
        assert request["url"].startswith("https://iovip-z0.qbox.me/getfile/")
        assert "cdn.example.com" not in request["url"]
        assert request["headers"]["Authorization"] == "QBox ak:sig"
        _io_host_cache.clear()


def test_compensation_skips_task_without_deduct_log(monkeypatch):
    from task.refund_compensation import compensate_missed_refunds

    tool = SimpleNamespace(
        id=9, user_id=3, transaction_id="txn-9", status=-2, message="任务已取消（退款处理中，如未到账请联系客服）",
    )
    monkeypatch.setattr(
        "task.refund_compensation.find_refund_compensation_ids",
        lambda limit=None: [9],
    )
    monkeypatch.setattr(
        "model.ai_tools.AIToolsModel.get_by_id",
        staticmethod(lambda tool_id: tool),
    )
    monkeypatch.setattr(
        "model.computing_power_log.ComputingPowerLogModel.get_deducted_power_by_transaction",
        staticmethod(lambda user_id, transaction_id: None),
    )
    called = {}

    def _refund(*args, **kwargs):
        called["hit"] = True
        return True

    monkeypatch.setattr("task.visual_task._refund_computing_power", _refund)
    assert compensate_missed_refunds() == 0
    assert called == {}


def test_deferred_cancel_persists_pending_message(monkeypatch):
    from task import queued_cancel

    monkeypatch.setattr(
        "model.ai_tool_pipeline_steps.PipelineStepModel.has_processing_for_ai_tool",
        staticmethod(lambda ai_tool_id: False),
    )
    monkeypatch.setattr(
        "model.ai_tools.AIToolsModel.transition_status",
        staticmethod(lambda *args, **kwargs: 1),
    )
    monkeypatch.setattr(
        "model.tasks.TasksModel.update_by_task_id",
        staticmethod(lambda *args, **kwargs: 1),
    )
    monkeypatch.setattr(
        "model.ai_tool_pipeline_steps.PipelineStepModel.cancel_pending_steps_by_ai_tool",
        staticmethod(lambda ai_tool_id: 0),
    )
    monkeypatch.setattr(
        "model.ai_tools_log.AIToolsLogModel.log",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "model.ai_tools.AIToolsModel.get_by_id",
        staticmethod(lambda ai_tool_id: SimpleNamespace(id=ai_tool_id, user_id=1, transaction_id="t")),
    )
    monkeypatch.setattr("task.visual_task._refund_computing_power", lambda tool, reason: False)
    saved = {}

    def _update(record_id, **fields):
        saved["id"] = record_id
        saved.update(fields)
        return 1

    monkeypatch.setattr("model.ai_tools.AIToolsModel.update_only_fields", staticmethod(_update))
    assert queued_cancel.commit_deferred_cancel(42) is True
    assert saved["id"] == 42
    assert "退款处理中" in saved["message"]
