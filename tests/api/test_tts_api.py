"""
api/tts.py 火山TTS快速合成接口测试

覆盖计价扣费链路的关键分支：余额不足、音色不存在、上游失败退款、
成功落库、试听缓存命中。全部外部依赖 monkeypatch，不连真实 DB/火山。
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture()
def tmp_path():
    """自管临时目录（pytest 内置 tmp_path 在部分 Windows 环境有权限问题）"""
    path = tempfile.mkdtemp(prefix="tts_api_test_")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def client(monkeypatch):
    """带鉴权 stub 的 TestClient：任意 Authorization 视为 user_id=1"""
    import perseids_server.utils.permission as permission_mod

    async def _fake_resolve(auth_value):
        return 1, None

    monkeypatch.setattr(permission_mod, "resolve_authorization_user_id", _fake_resolve)

    from api.tts import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _voice_record(voice_id=9, voice_type="BV700_streaming", is_active=1):
    return SimpleNamespace(
        id=voice_id, user_id=0, provider="volcengine", voice_type=voice_type,
        name="通用女声", is_active=is_active,
    )


# ------------------------- 音色列表 -------------------------

def test_voices_returns_list_and_tiers(client, monkeypatch):
    import api.tts as tts_mod

    monkeypatch.setattr(
        tts_mod.VoiceModel, "list_all",
        staticmethod(lambda **kw: {"total": 1, "data": [{
            "id": 9, "user_id": 0, "provider": "volcengine", "voice_type": "BV700_streaming",
            "name": "通用女声", "description": "", "gender": "female", "language": "zh",
            "style": "通用", "sample_url": None, "audio_url": None,
            "sort_order": 1, "is_active": 1, "create_at": None, "update_at": None,
        }]}),
    )

    res = client.get("/api/tts/voices", headers={"Authorization": "Bearer test-token"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["voices"]) == 1
    assert data["power_tiers"] and data["max_text_length"] > 0


# ------------------------- 合成：参数与鉴权 -------------------------

def test_synthesize_empty_text_rejected(client):
    res = client.post("/api/tts/synthesize", json={"text": "  ", "voice_id": 9},
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 400


def test_synthesize_text_too_long_rejected(client):
    res = client.post("/api/tts/synthesize", json={"text": "a" * 2001, "voice_id": 9},
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 400
    assert "过长" in res.json()["detail"]


def test_synthesize_voice_not_found(client, monkeypatch):
    import api.tts as tts_mod

    monkeypatch.setattr(tts_mod.VoiceModel, "get_by_id", staticmethod(lambda rid: None))
    res = client.post("/api/tts/synthesize", json={"text": "你好", "voice_id": 99},
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 404


def test_synthesize_insufficient_power_rejected(client, monkeypatch):
    import api.tts as tts_mod

    monkeypatch.setattr(tts_mod.VoiceModel, "get_by_id",
                        staticmethod(lambda rid: _voice_record()))
    calls = []

    async def _fake_perseids(endpoint=None, data=None, method="POST", headers=None):
        calls.append((endpoint, data))
        if endpoint == "user/check_computing_power":
            return True, "ok", {"computing_power": 0, "user_id": 1}
        raise AssertionError("不应走到扣费")

    monkeypatch.setattr(tts_mod, "async_make_perseids_request", _fake_perseids)
    res = client.post("/api/tts/synthesize", json={"text": "你好世界", "voice_id": 9},
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 400
    assert "算力不足" in res.json()["detail"]
    # 只发生了预检，没有扣减
    assert all(c[1].get("behavior") != "deduct" for c in calls if c[1])


# ------------------------- 合成：失败退款 -------------------------

def test_synthesize_upstream_fail_refunds(client, monkeypatch, tmp_path):
    import api.tts as tts_mod

    monkeypatch.setattr(tts_mod.VoiceModel, "get_by_id",
                        staticmethod(lambda rid: _voice_record()))
    monkeypatch.setattr(tts_mod, "resolve_result_dir", lambda: str(tmp_path))
    monkeypatch.setattr(tts_mod, "get_dynamic_config_value", lambda *a, **k: None)

    power_calls = []

    async def _fake_perseids(endpoint=None, data=None, method="POST", headers=None):
        if endpoint == "user/check_computing_power":
            return True, "ok", {"computing_power": 100, "user_id": 1}
        power_calls.append((endpoint, dict(data or {})))
        return True, "ok", {}

    monkeypatch.setattr(tts_mod, "async_make_perseids_request", _fake_perseids)

    async def _fail_synth(**kwargs):
        return False, b"", "火山TTS错误 code=3001: voice not found"

    monkeypatch.setattr(tts_mod, "synthesize_speech", _fail_synth)

    res = client.post("/api/tts/synthesize", json={"text": "你好世界", "voice_id": 9},
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 502

    deducts = [c for c in power_calls if c[1].get("behavior") == "deduct"]
    refunds = [c for c in power_calls if c[1].get("behavior") == "increase"]
    assert len(deducts) == 1, "应恰好一次预扣"
    assert len(refunds) == 1, "失败后应恰好一次退款"
    # 退款金额与预扣一致，transaction_id 幂等配对
    assert refunds[0][1]["computing_power"] == deducts[0][1]["computing_power"]
    assert refunds[0][1]["transaction_id"] == f"refund-{deducts[0][1]['transaction_id']}"


# ------------------------- 合成：成功链路 -------------------------

def test_synthesize_success_flow(client, monkeypatch, tmp_path):
    import api.tts as tts_mod

    monkeypatch.setattr(tts_mod.VoiceModel, "get_by_id",
                        staticmethod(lambda rid: _voice_record()))
    monkeypatch.setattr(tts_mod, "resolve_result_dir", lambda: str(tmp_path))
    monkeypatch.setattr(tts_mod, "get_dynamic_config_value", lambda *a, **k: None)
    monkeypatch.setattr(tts_mod, "_build_public_audio_url", lambda fn: f"http://x/upload/tts/volcengine/{fn}")

    async def _fake_perseids(endpoint=None, data=None, method="POST", headers=None):
        if endpoint == "user/check_computing_power":
            return True, "ok", {"computing_power": 100, "user_id": 1}
        return True, "ok", {}

    monkeypatch.setattr(tts_mod, "async_make_perseids_request", _fake_perseids)

    fake_mp3 = b"\xff\xfb\x90fakeaudio"

    async def _ok_synth(**kwargs):
        return True, fake_mp3, "success"

    monkeypatch.setattr(tts_mod, "synthesize_speech", _ok_synth)

    async def _fake_probe(path):
        return 1.25

    monkeypatch.setattr(tts_mod, "probe_audio_duration", _fake_probe)
    monkeypatch.setattr(tts_mod, "register_uploaded_file_mapping", lambda *a, **k: None)

    created = {}
    monkeypatch.setattr(tts_mod.AIAudioModel, "create",
                        staticmethod(lambda **kw: created.update(kw) or 123))

    res = client.post("/api/tts/synthesize",
                      json={"text": "你好世界", "voice_id": 9, "speed_ratio": 1.5},
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["audio_id"] == 123
    assert data["char_count"] == 4
    assert data["computing_power"] == 1  # 4 字符 → ≤50 档 → 1 算力

    # 落盘文件存在且内容一致
    files = os.listdir(str(tmp_path))
    assert files and files[0].startswith("tts_") and files[0].endswith(".mp3")
    with open(os.path.join(str(tmp_path), files[0]), "rb") as f:
        assert f.read() == fake_mp3

    # ai_audio 记录了引擎与音色
    assert created["engine"] == "volcengine"
    assert created["voice_id"] == 9
    assert created["transaction_id"]
    assert float(created["speed"]) == 1.5


# ------------------------- 试听缓存 -------------------------

def test_preview_uses_cache_without_synth(client, monkeypatch, tmp_path):
    import api.tts as tts_mod

    monkeypatch.setattr(tts_mod.VoiceModel, "get_by_id",
                        staticmethod(lambda rid: _voice_record()))
    monkeypatch.setattr(tts_mod, "resolve_result_dir", lambda: str(tmp_path))
    monkeypatch.setattr(tts_mod, "_build_public_audio_url", lambda fn: f"http://x/{fn}")

    # 预置缓存文件
    cached = os.path.join(str(tmp_path), "preview_BV700_streaming.mp3")
    with open(cached, "wb") as f:
        f.write(b"cached-audio")

    called = []

    async def _should_not_run(**kwargs):
        called.append(1)
        return True, b"", "success"

    monkeypatch.setattr(tts_mod, "synthesize_speech", _should_not_run)

    res = client.get("/api/tts/preview/9", headers={"Authorization": "Bearer t"})
    assert res.status_code == 200
    assert res.json()["audio_url"].endswith("preview_BV700_streaming.mp3")
    assert called == [], "命中缓存不应再调火山"
