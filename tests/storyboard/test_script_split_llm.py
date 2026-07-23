"""剧本分段拆分 - LLM 客户端与 script_parser 单元测试。

覆盖测试方案 §2.3 / §2.4：
- normalize_finish_reason 归一化（Gemini MAX_TOKENS → length 等）
- Choice.is_truncated 属性
- get_llm_client 对 dict model 的拍平防御
- validate_parsed_script 修正为 shot_groups[].shots[] 协议
- script_parser 系统 prompt 含 presentation 字段规则
- strict_json / segment_context / qc_feedback 提示词注入点存在

LLM 客户端测试不连真实服务，只测归一化与工厂防御；
parse_script_to_shots 重型 async 路径走提示词源码断言，不实跑 LLM。
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from llm.base_llm_client import BaseLLMClient
from llm.llm_client_factory import get_llm_client
from llm.script_parser import validate_parsed_script


PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------- normalize_finish_reason ----------------

class TestNormalizeFinishReason:
    """各 provider 的 finish_reason 归一化为小写下划线，engine 只判 == 'length'。"""

    @pytest.mark.parametrize("raw,expected", [
        ("MAX_TOKENS", "length"),     # Gemini 驼峰 key 全大写值
        ("max_tokens", "length"),     # 兼容小写
        ("length", "length"),         # OpenAI 原样
        ("LENGTH", "length"),         # 大写归一
        ("stop", "stop"),
        ("tool_calls", "tool_calls"),
        ("content_filter", "content_filter"),
        ("SAFETY", "safety"),         # Gemini SAFETY 归一为小写
    ])
    def test_normalizes(self, raw, expected):
        assert BaseLLMClient.normalize_finish_reason(raw) == expected

    def test_none_or_empty_returns_none(self):
        assert BaseLLMClient.normalize_finish_reason(None) is None


# ---------------- Choice.is_truncated ----------------

class TestChoiceIsTruncated:
    def _choice(self, finish_reason):
        return BaseLLMClient.Choice(BaseLLMClient.Message("hi"), finish_reason)

    @pytest.mark.parametrize("finish_reason,truncated", [
        ("length", True),
        ("MAX_TOKENS", True),   # Gemini 截断归一后也是 length
        ("stop", False),
        (None, False),
    ])
    def test_is_truncated(self, finish_reason, truncated):
        assert self._choice(finish_reason).is_truncated is truncated


# ---------------- get_llm_client dict 防御 ----------------

class TestGetLlmClientDictFlattening:
    """前端入口可能把 model 传成 dict，工厂必须拍平为字符串，防 Gemini 404。"""

    def test_dict_with_model_key_flattened(self):
        """dict 里的 model 键被拍平为字符串；vendor_id 走显式参数。"""
        captured = {}

        def fake_get_client(model, vendor_id=None):
            captured["model"] = model
            captured["vendor_id"] = vendor_id
            return object()

        with patch("llm.llm_client_factory.LLMClientFactory.get_client", side_effect=fake_get_client):
            get_llm_client({"model": "gemini-3-flash", "model_id": 7}, vendor_id=2)

        assert captured["model"] == "gemini-3-flash"
        assert isinstance(captured["model"], str)
        assert captured["vendor_id"] == 2

    def test_dict_with_name_key_flattened(self):
        captured = {}

        def fake_get_client(model, vendor_id=None):
            captured["model"] = model
            return object()

        with patch("llm.llm_client_factory.LLMClientFactory.get_client", side_effect=fake_get_client):
            get_llm_client({"name": "deepseek-v3"})

        assert captured["model"] == "deepseek-v3"

    def test_string_model_passthrough(self):
        captured = {}
        with patch("llm.llm_client_factory.LLMClientFactory.get_client",
                   side_effect=lambda m, vendor_id=None: captured.update(model=m)):
            get_llm_client("gpt-4o")
        assert captured["model"] == "gpt-4o"


# ---------------- validate_parsed_script（shot_groups 协议） ----------------

class TestValidateParsedScript:
    """历史该校验器错误检查扁平 shots，现已修正为 shot_groups[].shots[]。"""

    def _valid(self):
        return {
            "characters": [{"id": "char_1", "name": "甲"}],
            "locations": [{"id": "loc_1", "name": "客厅"}],
            "shot_groups": [
                {"group_id": "grp_1", "shots": [{"shot_id": "s1", "duration": 2.0}]},
            ],
        }

    def test_valid_structure_passes(self):
        ok, msg = validate_parsed_script(self._valid())
        assert ok, msg

    def test_missing_required_key_fails(self):
        data = self._valid()
        del data["characters"]
        ok, msg = validate_parsed_script(data)
        assert not ok and "characters" in msg

    def test_flat_shots_not_accepted_via_groups(self):
        """shot_groups 缺 shots 数组 → 失败（修正点：旧版只查顶层 shots）。"""
        data = self._valid()
        data["shot_groups"] = [{"group_id": "grp_1"}]  # 无 shots
        ok, msg = validate_parsed_script(data)
        assert not ok

    def test_shot_missing_duration_fails(self):
        """每个 shot 必须有 duration 字段。"""
        data = self._valid()
        data["shot_groups"][0]["shots"][0] = {"shot_id": "s1"}  # 缺 duration
        ok, msg = validate_parsed_script(data)
        assert not ok and "duration" in msg

    def test_character_missing_id_fails(self):
        data = self._valid()
        data["characters"] = [{"name": "甲"}]  # 缺 id
        ok, msg = validate_parsed_script(data)
        assert not ok and "id" in msg


# ---------------- script_parser 系统 prompt 规则（源码断言） ----------------

class TestScriptParserPromptRules:
    """parse_script_to_shots 是重型 async，这里用源码断言验证提示词注入点存在。"""

    @property
    def _source(self):
        return (PROJECT_ROOT / "llm" / "script_parser.py").read_text(encoding="utf-8")

    def test_presentation_field_rule_exists(self):
        """系统 prompt 第 19 条要求输出 presentation 字段。"""
        src = self._source
        assert "presentation" in src
        assert "digital_human" in src
        assert "video" in src

    def test_multi_speaker_must_be_video_rule(self):
        """dialogue 中 ≥2 说话角色时 presentation 必须为 video。"""
        src = self._source
        assert "2 个及以上" in src or "2个及以上" in src

    def test_strict_json_param_exists(self):
        """parse_script_to_shots 支持 strict_json 参数。"""
        src = self._source
        assert "strict_json" in src

    def test_segment_context_param_exists(self):
        """parse_script_to_shots 支持 segment_context 参数（分段拆分约束）。"""
        src = self._source
        assert "segment_context" in src

    def test_qc_feedback_param_exists(self):
        """parse_script_to_shots 支持 qc_feedback（质检失败重拆注入）。"""
        src = self._source
        assert "qc_feedback" in src or "qc_retry_block" in src

    def test_async_log_save_exists(self):
        """日志写入走 _save_log_file_async（asyncio.to_thread），不阻塞事件循环。"""
        src = self._source
        assert "_save_log_file_async" in src
        assert "asyncio.to_thread" in src

    def test_previous_parsed_result_param_exists(self):
        """parse_script_to_shots 支持 previous_parsed_result（上一轮完整 JSON）。"""
        assert "previous_parsed_result" in self._source
