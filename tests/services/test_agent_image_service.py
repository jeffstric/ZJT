"""智能体 CLI 直接生图服务单元测试（纯 mock，不依赖数据库）。"""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import services.agent_image_service as mod
from services.agent_image_service import (
    AgentImageGenerationError,
    AgentImageGenerationService,
    extract_agent_token,
    _normalize_reference_urls,
    _resolve_model_config,
)

# 首页「智能体连接」弹窗复制的真实样例（中文提示行 + 尾部 JSON 块）
CONNECTION_TEXT = """请使用 $storyboard-agent-api 协助处理我的智剧通分镜：可查看世界列表、世界下的剧本。
连接信息如下，请不要把 token 放进 URL：
环境说明：请以 JSON 中的 environment 为准；如改用本地 CLI fallback，请先设置 comfyui_env 为该值。
{
  "skill": "storyboard-agent-api",
  "base_url": "https://example.com",
  "agent_token": "agt_abc123",
  "api_version": "1.0",
  "app_version": "2.0",
  "environment": "prod",
  "token_type": "agent",
  "expires_at": "2026-12-01T00:00:00",
  "note": "Use the fixed v1 endpoints; set comfyui_env before running commands."
}"""


class TestExtractAgentToken:
    def test_extracts_from_real_connection_text(self):
        assert extract_agent_token(CONNECTION_TEXT) == "agt_abc123"

    def test_extracts_from_plain_json(self):
        assert extract_agent_token('{"agent_token": "agt_x"}') == "agt_x"

    def test_falls_back_to_token_key(self):
        assert extract_agent_token('说明文本 {"token": "t1", "skill": "x"}') == "t1"

    def test_returns_none_without_json(self):
        assert extract_agent_token("没有任何 JSON 的文本") is None

    def test_returns_none_for_empty(self):
        assert extract_agent_token("") is None
        assert extract_agent_token(None) is None

    def test_skips_invalid_json_block(self):
        # 括号不配平的伪 JSON 应被跳过，不抛异常
        assert extract_agent_token('前缀 {"agent_token": "broken" 无闭括号') is None

    def test_handles_braces_inside_strings(self):
        text = '{"agent_token": "agt_{not_a_block}", "note": " escapes \\" inside"}'
        assert extract_agent_token(text) == "agt_{not_a_block}"

    def test_skips_balanced_but_invalid_json(self):
        # 花括号配平但不是合法 JSON 时必须继续扫描，不能停在同一个 '{'
        assert extract_agent_token('{bad}') is None
        assert extract_agent_token('说明 {token} 后面 {"agent_token": "agt_ok"}') == "agt_ok"
        assert extract_agent_token('{bad,} {"token": "t2"}') == "t2"


class TestResolveModelConfig:
    def test_moss_by_name_supports_text_to_image(self):
        info = _resolve_model_config("moss", "text_to_image")
        assert info["task_id"] == 53
        assert info["model_key"] == "moss"

    def test_moss_rejects_image_edit(self):
        with pytest.raises(AgentImageGenerationError) as exc:
            _resolve_model_config("moss", "image_edit")
        assert exc.value.error_code == "model_mode_unsupported"
        assert "仅支持文生图" in exc.value.message

    def test_moss_rejects_reference_with_text_mode(self):
        # mode=image_edit + moss：同样拒绝（moss 无图片编辑能力）
        with pytest.raises(AgentImageGenerationError):
            _resolve_model_config("53", "image_edit")

    def test_resolves_by_task_id_number(self):
        info = _resolve_model_config("53", "text_to_image")
        assert info["task_id"] == 53

    def test_unknown_model_rejected(self):
        with pytest.raises(AgentImageGenerationError) as exc:
            _resolve_model_config("no-such-model", "text_to_image")
        assert exc.value.error_code == "model_not_found"

    def test_edit_capable_model_supports_image_edit(self):
        # qwenimage2.1 同时支持图片编辑与文生图
        info = _resolve_model_config("qwenimage2.1", "image_edit")
        assert info["task_id"] == 52


class TestNormalizeReferenceUrls:
    def test_splits_and_dedupes(self):
        assert _normalize_reference_urls(" a.png , b.png ,a.png ") == ["a.png", "b.png"]

    def test_empty(self):
        assert _normalize_reference_urls(None) == []
        assert _normalize_reference_urls(" , , ") == []


@pytest.fixture()
def service():
    return AgentImageGenerationService()


def _mock_exchange(monkeypatch, user_id=7):
    monkeypatch.setattr(
        mod.AgentAuthService, "exchange_token",
        MagicMock(return_value={
            "success": True, "auth_token": "auth-token-1",
            "user_id": user_id, "token_type": "agent",
        }),
    )


class TestExchangeConnection:
    def test_missing_token_raises(self, service):
        with pytest.raises(AgentImageGenerationError) as exc:
            service.exchange_connection(None, None)
        assert exc.value.error_code == "missing_agent_token"

    def test_uses_pasted_text(self, service, monkeypatch):
        _mock_exchange(monkeypatch)
        result = service.exchange_connection(CONNECTION_TEXT, None)
        assert result["user_id"] == 7
        assert result["auth_token"] == "auth-token-1"
        # 验证提取出的 agent_token 被传给 exchange
        args = mod.AgentAuthService.exchange_token.call_args
        assert args[0][0] == "agt_abc123"

    def test_explicit_token_wins(self, service, monkeypatch):
        _mock_exchange(monkeypatch)
        service.exchange_connection(CONNECTION_TEXT, "agt_explicit")
        args = mod.AgentAuthService.exchange_token.call_args
        assert args[0][0] == "agt_explicit"

    def test_auth_error_propagates(self, service, monkeypatch):
        from services.agent_auth_service import AgentAuthError
        monkeypatch.setattr(
            mod.AgentAuthService, "exchange_token",
            MagicMock(side_effect=AgentAuthError(401, "invalid_agent_token", "invalid or expired agent token")),
        )
        with pytest.raises(AgentImageGenerationError) as exc:
            service.exchange_connection(None, "bad")
        assert exc.value.status_code == 401
        assert exc.value.error_code == "invalid_agent_token"


class TestIdentifyConnection:
    def test_returns_user_without_exchange(self, service, monkeypatch):
        monkeypatch.setattr(
            mod.AgentAuthService, "resolve_agent_user",
            MagicMock(return_value={"success": True, "user_id": 7, "token_type": "agent"}),
        )
        exchange = MagicMock()
        monkeypatch.setattr(mod.AgentAuthService, "exchange_token", exchange)
        result = service.identify_connection(CONNECTION_TEXT, None)
        assert result["user_id"] == 7
        args = mod.AgentAuthService.resolve_agent_user.call_args
        assert args[0][0] == "agt_abc123"
        exchange.assert_not_called()


class TestGenerate:
    def _mock_world(self, monkeypatch, world_id=1):
        monkeypatch.setattr(
            mod.WorldModel, "get_by_id",
            MagicMock(return_value=SimpleNamespace(id=world_id, user_id=7)),
        )
        monkeypatch.setattr(
            mod.WorldModel, "list_by_user",
            MagicMock(return_value={"data": [SimpleNamespace(id=world_id, user_id=7)]}),
        )

    def _mock_default_pref(self, monkeypatch):
        monkeypatch.setattr(
            mod.MediaGenerationPreferenceService, "get_profile",
            MagicMock(return_value=None),
        )

    def _mock_mcp(self, monkeypatch, result):
        fake = MagicMock()
        fake.generate_text_to_image = MagicMock(return_value=result)
        fake.edit_image = MagicMock(return_value=result)
        monkeypatch.setitem(sys.modules, "script_writer_core.mcp_tool", fake)
        return fake

    def test_validations(self, service, monkeypatch):
        # 参数校验全部在世界解析之前完成；mock world 防止校验顺序改动导致真实 DB 泄漏
        self._mock_world(monkeypatch)
        self._mock_default_pref(monkeypatch)
        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="  ")
        assert exc.value.error_code == "prompt_required"

        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", mode="bogus")
        assert exc.value.error_code == "invalid_mode"

        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", count=0)
        assert exc.value.error_code == "invalid_count"

        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", count=99)
        assert exc.value.error_code == "invalid_count"

        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", mode="text_to_image", reference_image="a.png")
        assert exc.value.error_code == "reference_not_allowed"

        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", mode="image_edit")
        assert exc.value.error_code == "reference_required"

    def test_world_forbidden(self, service, monkeypatch):
        monkeypatch.setattr(
            mod.WorldModel, "get_by_id",
            MagicMock(return_value=SimpleNamespace(id=1, user_id=99)),
        )
        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", world_id=1)
        assert exc.value.error_code == "world_forbidden"

    def test_no_world_available(self, service, monkeypatch):
        monkeypatch.setattr(
            mod.WorldModel, "list_by_user",
            MagicMock(return_value={"data": []}),
        )
        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p")
        assert exc.value.error_code == "world_required"

    def test_default_world_uses_latest_updated_owned_world(self, service, monkeypatch):
        listed = {}

        def _list_by_user(**kwargs):
            listed.update(kwargs)
            return {"data": [{"id": 8, "user_id": 7}]}

        monkeypatch.setattr(mod.WorldModel, "list_by_user", _list_by_user)
        self._mock_default_pref(monkeypatch)
        self._mock_mcp(monkeypatch, {"success": True, "project_ids": [1]})
        result = service.generate(7, "tok", prompt="p", model="moss")
        assert result["world_id"] == 8
        assert listed["order_by"] == "update_time"
        assert listed["restrict_to_user"] is True
        assert listed["user_id"] == 7

    def test_default_world_rejects_foreign_row(self, service, monkeypatch):
        monkeypatch.setattr(
            mod.WorldModel, "list_by_user",
            MagicMock(return_value={"data": [{"id": 3, "user_id": 99}]}),
        )
        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", model="moss")
        assert exc.value.error_code == "world_forbidden"

    def test_text_to_image_submission_with_moss(self, service, monkeypatch):
        self._mock_world(monkeypatch)
        self._mock_default_pref(monkeypatch)
        fake = self._mock_mcp(monkeypatch, {
            "success": True,
            "project_ids": [101],
            "computing_power_required": 1,
            "computing_power_total": 1,
            "image_size_used": "2K",
        })

        result = service.generate(
            7, "auth-token-1", prompt="一只戴墨镜的橘猫",
            model="moss", ratio="9:16", image_size="2K",
        )

        assert result["success"] is True
        assert result["project_ids"] == [101]
        assert result["mode"] == "text_to_image"
        assert result["task_type"] == 53
        assert result["model_key"] == "moss"

        kwargs = fake.generate_text_to_image.call_args.kwargs
        assert kwargs["user_id"] == "7"
        assert kwargs["world_id"] == "1"
        assert kwargs["auth_token"] == "auth-token-1"
        assert kwargs["prompt"] == "一只戴墨镜的橘猫"
        assert kwargs["aspect_ratio"] == "9:16"
        assert kwargs["task_type"] == 53
        assert kwargs["lock_ratio"] is True
        assert kwargs["lock_count"] is False
        assert kwargs["count"] == 1

    def test_explicit_count_is_locked(self, service, monkeypatch):
        self._mock_world(monkeypatch)
        self._mock_default_pref(monkeypatch)
        fake = self._mock_mcp(monkeypatch, {"success": True, "project_ids": [102]})
        service.generate(7, "tok", prompt="p", model="moss", count=1, ratio="1:1")
        kwargs = fake.generate_text_to_image.call_args.kwargs
        assert kwargs["count"] == 1
        assert kwargs["aspect_ratio"] == "1:1"
        assert kwargs["lock_count"] is True
        assert kwargs["lock_ratio"] is True

    def test_auto_mode_routes_to_image_edit(self, service, monkeypatch):
        self._mock_world(monkeypatch)
        self._mock_default_pref(monkeypatch)
        fake = self._mock_mcp(monkeypatch, {"success": True, "project_ids": [202]})

        result = service.generate(
            7, "tok", prompt="把背景换成海滩",
            model="qwenimage2.1", reference_image="https://a.png, https://b.png",
        )

        assert result["mode"] == "image_edit"
        kwargs = fake.edit_image.call_args.kwargs
        assert kwargs["image_url"] == "https://a.png,https://b.png"

    def test_default_model_from_cli_preference(self, service, monkeypatch):
        self._mock_world(monkeypatch)
        # CLI 偏好锁定 moss（task 53）
        monkeypatch.setattr(
            mod.MediaGenerationPreferenceService, "get_profile",
            MagicMock(return_value={"task_id": 53, "model_key": "moss"}),
        )
        fake = self._mock_mcp(monkeypatch, {"success": True, "project_ids": [303]})

        result = service.generate(7, "tok", prompt="p")
        assert result["task_type"] == 53

        kwargs = fake.generate_text_to_image.call_args.kwargs
        assert kwargs["task_type"] == 53

    def test_submission_failure_raises(self, service, monkeypatch):
        self._mock_world(monkeypatch)
        self._mock_default_pref(monkeypatch)
        self._mock_mcp(monkeypatch, {"success": False, "error": "算力不足"})
        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", model="moss")
        assert exc.value.error_code == "submission_failed"
        assert "算力不足" in exc.value.message

    def test_missing_project_ids_raises(self, service, monkeypatch):
        self._mock_world(monkeypatch)
        self._mock_default_pref(monkeypatch)
        self._mock_mcp(monkeypatch, {"success": True, "project_ids": []})
        with pytest.raises(AgentImageGenerationError) as exc:
            service.generate(7, "tok", prompt="p", model="moss")
        assert exc.value.error_code == "missing_project_ids"


class TestGetProjectStatus:
    def _tool(self, **overrides):
        fields = dict(id=101, user_id=7, status=1, result_url=None, message=None)
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def test_returns_processing(self, service, monkeypatch):
        monkeypatch.setattr(mod.AIToolModel, "get_by_id", MagicMock(return_value=self._tool(status=1)))
        result = service.get_project_status(101, 7)
        assert result["status"] == "PROCESSING"
        assert result["terminal"] is False

    def test_completed_returns_result_url(self, service, monkeypatch):
        monkeypatch.setattr(
            mod.AIToolModel, "get_by_id",
            MagicMock(return_value=self._tool(status=2, result_url="http://x/a.png", message="done")),
        )
        result = service.get_project_status(101, 7)
        assert result["terminal"] is True
        assert result["result_url"] == "http://x/a.png"

    def test_owner_isolation(self, service, monkeypatch):
        # 非本人任务一律 not_found（防枚举）
        monkeypatch.setattr(mod.AIToolModel, "get_by_id", MagicMock(return_value=self._tool(user_id=99)))
        with pytest.raises(AgentImageGenerationError) as exc:
            service.get_project_status(101, 7)
        assert exc.value.status_code == 404

    def test_not_found(self, service, monkeypatch):
        monkeypatch.setattr(mod.AIToolModel, "get_by_id", MagicMock(return_value=None))
        with pytest.raises(AgentImageGenerationError) as exc:
            service.get_project_status(404, 7)
        assert exc.value.error_code == "project_not_found"
