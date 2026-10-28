"""角色音色三端点回归测试（参考音频/音色指纹/预置音色应用）。

背景（4dcec8daa、9092d102b、2c0dbb834）：属主校验从 body user_id 改为登录
身份（防 X-User-Id 伪主人）；DB 行属主为他人时忽略该行不泄露数据；
音色分析失败返 502 不再吐兜底指纹；预置音色 style/gender 推导声学指纹。
此前 tests/ 对这三个端点零覆盖。
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import script_writer


def _unwrap(endpoint):
    return endpoint.__wrapped__


def _identity(monkeypatch, user_id=7, claimed_error=None):
    monkeypatch.setattr(
        script_writer, "get_auth_user_id", lambda request: user_id)
    monkeypatch.setattr(
        script_writer, "check_claimed_user_id",
        lambda claimed, auth: claimed_error)


def _mock_character(monkeypatch, character=None):
    model = MagicMock()
    model.get_by_id.return_value = character
    model.get_by_name.return_value = character
    monkeypatch.setattr(script_writer, "CharacterModel", model)
    return model


def _mock_analyze(monkeypatch, result):
    """result 为 async 函数时直接用；否则包装为 async 返回值。"""
    if callable(result) and asyncio.iscoroutinefunction(result):
        monkeypatch.setattr(script_writer, "analyze_character_voice", result)
        return
    async def _fn(*args, **kwargs):
        return result
    monkeypatch.setattr(script_writer, "analyze_character_voice", _fn)


class _VoiceRequest:
    def __init__(self, **kw):
        self.character_id = kw.get("character_id", 1)
        self.character_name = kw.get("character_name")
        self.world_id = kw.get("world_id", 10)
        self.character_data = kw.get("character_data")
        self.model = kw.get("model")
        self.vendor_id = kw.get("vendor_id")
        self.model_id = kw.get("model_id")


class _AudioRequest(_VoiceRequest):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.style_prompt = kw.get("style_prompt")
        self.text = kw.get("text")


# ==================== 身份校验 ====================

def test_voice_desc_requires_login(monkeypatch):
    _identity(monkeypatch, user_id=None)
    resp = asyncio.run(_unwrap(script_writer.generate_character_voice_desc)(
        request=SimpleNamespace(headers={}, query_params={}),
        voice_request=_VoiceRequest(),
        auth_token=None, user_id=None,
    ))
    assert resp.status_code == 401


def test_voice_desc_rejects_claimed_user_mismatch(monkeypatch):
    error = JSONResponse(
        {"success": False, "error": "user_mismatch"}, status_code=403)
    _identity(monkeypatch, user_id=7, claimed_error=error)
    resp = asyncio.run(_unwrap(script_writer.generate_character_voice_desc)(
        request=SimpleNamespace(headers={}, query_params={}),
        voice_request=_VoiceRequest(),
        auth_token=None, user_id=99,
    ))
    assert resp.status_code == 403


# ==================== 属主校验（防跨用户数据泄露） ====================

def test_voice_desc_ignores_other_owner_character_row(monkeypatch):
    """DB 行属主为他人 → 忽略该行走请求方数据（不泄露他人角色）。"""
    _identity(monkeypatch, user_id=7)
    other = SimpleNamespace(user_id=999, world_id=10, to_dict=lambda: {"name": "别人的角色"})
    model = _mock_character(monkeypatch, other)
    captured = {}

    async def fake_analyze(data, **kwargs):
        captured["data"] = data
        return {"voice_desc": "一位沙哑的男性声音"}

    _mock_analyze(monkeypatch, fake_analyze)

    resp = asyncio.run(_unwrap(script_writer.generate_character_voice_desc)(
        request=SimpleNamespace(headers={}, query_params={}),
        voice_request=_VoiceRequest(character_data={"name": "自己的角色"}),
        auth_token=None, user_id=None,
    ))
    assert resp.status_code == 200
    # 用的是请求方数据而非他人角色行
    assert captured["data"]["name"] == "自己的角色"
    assert model.get_by_id.called


def test_voice_desc_accepts_int_str_owner_match(monkeypatch):
    """属主对比必须 str 化（DB 返回 int 与 header str 对比的回归点）。"""
    _identity(monkeypatch, user_id=7)
    own = SimpleNamespace(user_id=7, world_id=10, to_dict=lambda: {"name": "自己的角色"})
    _mock_character(monkeypatch, own)
    _mock_analyze(monkeypatch, {"voice_desc": "清亮女声"})

    resp = asyncio.run(_unwrap(script_writer.generate_character_voice_desc)(
        request=SimpleNamespace(headers={}, query_params={}),
        voice_request=_VoiceRequest(),
        auth_token=None, user_id=None,
    ))
    assert resp.status_code == 200


def test_voice_desc_missing_data_returns_400(monkeypatch):
    _identity(monkeypatch, user_id=7)
    _mock_character(monkeypatch, None)
    resp = asyncio.run(_unwrap(script_writer.generate_character_voice_desc)(
        request=SimpleNamespace(headers={}, query_params={}),
        voice_request=_VoiceRequest(character_data=None),
        auth_token=None, user_id=None,
    ))
    assert resp.status_code == 400


# ==================== 502 语义（不吐兜底指纹） ====================

def test_voice_desc_analysis_failed_returns_502(monkeypatch):
    _identity(monkeypatch, user_id=7)
    own = SimpleNamespace(user_id=7, world_id=10, to_dict=lambda: {"name": "A"})
    _mock_character(monkeypatch, own)
    _mock_analyze(monkeypatch, {"analysis_failed": True})

    resp = asyncio.run(_unwrap(script_writer.generate_character_voice_desc)(
        request=SimpleNamespace(headers={}, query_params={}),
        voice_request=_VoiceRequest(),
        auth_token=None, user_id=None,
    ))
    assert resp.status_code == 502


def test_voice_desc_empty_result_returns_502(monkeypatch):
    _identity(monkeypatch, user_id=7)
    own = SimpleNamespace(user_id=7, world_id=10, to_dict=lambda: {"name": "A"})
    _mock_character(monkeypatch, own)
    _mock_analyze(monkeypatch, {})

    resp = asyncio.run(_unwrap(script_writer.generate_character_voice_desc)(
        request=SimpleNamespace(headers={}, query_params={}),
        voice_request=_VoiceRequest(),
        auth_token=None, user_id=None,
    ))
    assert resp.status_code == 502


def test_voice_desc_falls_back_to_description_field(monkeypatch):
    """旧模型输出缺 voice_desc 字段时回退 voice_description。"""
    _identity(monkeypatch, user_id=7)
    own = SimpleNamespace(user_id=7, world_id=10, to_dict=lambda: {"name": "A"})
    _mock_character(monkeypatch, own)
    _mock_analyze(monkeypatch, {"voice_description": "低沉的成年男声"})

    resp = asyncio.run(_unwrap(script_writer.generate_character_voice_desc)(
        request=SimpleNamespace(headers={}, query_params={}),
        voice_request=_VoiceRequest(),
        auth_token=None, user_id=None,
    ))
    assert resp.status_code == 200
    assert resp.body is not None


# ==================== 参考音频端点（任务落库 + voice_desc 返回） ====================

def test_reference_audio_submits_async_task(monkeypatch):
    _identity(monkeypatch, user_id=7)
    own = SimpleNamespace(user_id=7, world_id=10, to_dict=lambda: {"name": "A"})
    _mock_character(monkeypatch, own)
    _mock_analyze(monkeypatch, {"voice_desc": "清亮女声", "sample_text": "大家好"})

    async_model = MagicMock()
    async_model.create_and_schedule.return_value = 4242
    import model as model_pkg
    monkeypatch.setattr(model_pkg, "AsyncTasksModel", async_model)

    resp = asyncio.run(_unwrap(script_writer.generate_character_reference_audio)(
        request=SimpleNamespace(headers={}, query_params={}),
        audio_request=_AudioRequest(),
        auth_token="tok", user_id=None,
    ))
    assert resp.status_code == 200
    body = resp.body.decode() if isinstance(resp.body, bytes) else str(resp.body)
    assert "4242" in body
    async_model.create_and_schedule.assert_called_once()
    params = async_model.create_and_schedule.call_args.kwargs["params"]
    assert params["text"] == "大家好"


def test_reference_audio_analysis_failure_uses_default_prompt(monkeypatch):
    """音频端点对 analysis_failed 容忍：style/text 回退默认，不 502。"""
    _identity(monkeypatch, user_id=7)
    own = SimpleNamespace(user_id=7, world_id=10, to_dict=lambda: {"name": "A"})
    _mock_character(monkeypatch, own)
    _mock_analyze(monkeypatch, {"analysis_failed": True})

    async_model = MagicMock()
    async_model.create_and_schedule.return_value = 1
    import model as model_pkg
    monkeypatch.setattr(model_pkg, "AsyncTasksModel", async_model)

    resp = asyncio.run(_unwrap(script_writer.generate_character_reference_audio)(
        request=SimpleNamespace(headers={}, query_params={}),
        audio_request=_AudioRequest(),
        auth_token="tok", user_id=None,
    ))
    assert resp.status_code == 200
    params = async_model.create_and_schedule.call_args.kwargs["params"]
    # style_prompt 回退默认提示词，text 回退默认自我介绍
    assert params["style_prompt"]
    assert "大家好" in params["text"]


# ==================== 预置音色指纹推导（纯函数） ====================

def test_preset_voice_desc_style_hit():
    voice = SimpleNamespace(style="青年女声", gender="female")
    desc = script_writer._build_preset_voice_desc(voice)
    assert desc == script_writer.PRESET_VOICE_DESC_BY_STYLE["青年女声"]


def test_preset_voice_desc_gender_fallback():
    voice = SimpleNamespace(style="不存在的风格", gender="male")
    desc = script_writer._build_preset_voice_desc(voice)
    assert desc == script_writer.PRESET_VOICE_DESC_BY_GENDER["male"]


def test_preset_voice_desc_ultimate_fallback():
    voice = SimpleNamespace(style="", gender="")
    desc = script_writer._build_preset_voice_desc(voice)
    assert desc == script_writer.PRESET_VOICE_DESC_FALLBACK
    assert desc  # 兜底非空，保证前端输入框不会拿到空白指纹
