"""
api/tts.py 火山TTS快速合成接口测试

核心合成链路已抽至 services/volcengine_tts_service.py（与 Agent 工具共用），
此处 mock service 层依赖（perseids 客户端/火山调用/落盘/DB），不连真实服务。

覆盖：音色列表与开关透出、计价档位、余额不足 400、上游失败退款幂等、
成功链路落盘+ai_audio、试听缓存命中、克隆开关（YAML）透出。
"""
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

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
        name="通用女声", language="zh", is_active=is_active,
    )


def _voice_dict(voice_id=9):
    return {
        "id": voice_id, "user_id": 0, "provider": "volcengine", "voice_type": "BV700_streaming",
        "name": "通用女声", "description": "", "gender": "female", "language": "zh",
        "style": "通用", "sample_url": None, "audio_url": None,
        "sort_order": 1, "is_active": 1, "create_at": None, "update_at": None,
    }




def _patch_tts_config(monkeypatch):
    """patch service 层配置读取：DB 不可用时也走通配置检查"""
    import services.volcengine_tts_service as svc

    monkeypatch.setattr(svc, "get_volcengine_tts_config",
                        lambda: {"api_key": "test-key", "resource_id": "seed-tts-2.0"})
    monkeypatch.setattr(svc, "is_tts_configured", lambda cfg: True)


# ------------------------- 音色列表 -------------------------

def test_voices_returns_list_and_tiers(client, monkeypatch):
    import api.tts as tts_mod

    monkeypatch.setattr(
        tts_mod.VoiceModel, "list_all",
        staticmethod(lambda **kw: {"total": 1, "data": [_voice_dict()]}),
    )

    res = client.get("/api/tts/voices", headers={"Authorization": "Bearer test-token"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["voices"]) == 1
    assert data["power_tiers"] and data["max_text_length"] > 0
    # 克隆开关必须透出（默认 False，法律风险控制）
    assert data["allow_clone_from_voice_library"] is False


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
    _patch_tts_config(monkeypatch)
    import services.volcengine_tts_service as svc

    monkeypatch.setattr(tts_mod_ref().VoiceModel, "get_by_id",
                        staticmethod(lambda rid: _voice_record()))

    async def _fake_check(auth_header, power):
        return False, "您的算力不足，需要 1 算力，当前仅有 0 算力"

    async def _fail(*a, **k):
        raise AssertionError("算力不足时不应走到扣费")

    monkeypatch.setattr(svc, "check_power_sufficient", _fake_check)
    monkeypatch.setattr(svc, "deduct_power", _fail)

    res = client.post("/api/tts/synthesize", json={"text": "你好世界", "voice_id": 9},
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 400
    assert "算力不足" in res.json()["detail"]


def tts_mod_ref():
    """延迟引用 api.tts（避免模块级 import 时序问题）"""
    import api.tts as tts_mod
    return tts_mod


# ------------------------- 合成：失败退款 -------------------------

def test_synthesize_upstream_fail_refunds(client, monkeypatch, tmp_path):
    _patch_tts_config(monkeypatch)
    import services.volcengine_tts_service as svc
    import api.tts as tts_mod

    monkeypatch.setattr(tts_mod.VoiceModel, "get_by_id",
                        staticmethod(lambda rid: _voice_record()))

    power_calls = []

    async def _fake_check(auth_header, power):
        return True, None

    async def _fake_deduct(auth_header, power, transaction_id, message=None):
        power_calls.append(("deduct", power, transaction_id))
        return True, None

    async def _fake_refund(auth_header, power, transaction_id, message=None):
        power_calls.append(("refund", power, f"refund-{transaction_id}"))
        return True, None

    async def _fail_synth(**kwargs):
        return False, b"", "火山TTS错误 code=3001: voice not found"

    monkeypatch.setattr(svc, "check_power_sufficient", _fake_check)
    monkeypatch.setattr(svc, "deduct_power", _fake_deduct)
    monkeypatch.setattr(svc, "refund_power", _fake_refund)
    monkeypatch.setattr(svc, "synthesize_speech", _fail_synth)

    res = client.post("/api/tts/synthesize", json={"text": "你好世界", "voice_id": 9},
                      headers={"Authorization": "Bearer t"})
    assert res.status_code == 502

    deducts = [c for c in power_calls if c[0] == "deduct"]
    refunds = [c for c in power_calls if c[0] == "refund"]
    assert len(deducts) == 1, "应恰好一次预扣"
    assert len(refunds) == 1, "失败后应恰好一次退款"
    # 退款金额与预扣一致，transaction_id 幂等配对
    assert refunds[0][1] == deducts[0][1]
    assert refunds[0][2] == f"refund-{deducts[0][2]}"
    # 流水描述非空
    assert deducts[0][2]


# ------------------------- 合成：成功链路 -------------------------

def test_synthesize_success_flow(client, monkeypatch, tmp_path):
    _patch_tts_config(monkeypatch)
    import services.volcengine_tts_service as svc
    import api.tts as tts_mod

    monkeypatch.setattr(tts_mod.VoiceModel, "get_by_id",
                        staticmethod(lambda rid: _voice_record()))

    async def _fake_perseids(endpoint=None, data=None, method="POST", headers=None):
        if endpoint == "user/check_computing_power":
            return True, "ok", {"computing_power": 100, "user_id": 1}
        return True, "ok", {}

    monkeypatch.setattr(svc, "async_make_perseids_request", _fake_perseids)

    fake_mp3 = b"\xff\xfb\x90fakeaudio"

    async def _ok_synth(**kwargs):
        return True, fake_mp3, "success"

    monkeypatch.setattr(svc, "synthesize_speech", _ok_synth)

    async def _fake_probe(path):
        return 1.25

    monkeypatch.setattr(svc, "resolve_result_dir", lambda: str(tmp_path))
    monkeypatch.setattr(svc, "probe_audio_duration", _fake_probe)
    monkeypatch.setattr(svc, "register_uploaded_file_mapping", lambda *a, **k: None)

    created = {}
    monkeypatch.setattr(svc.AIAudioModel, "create",
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

    # handler 使用 api.tts 顶层 import 的引用，patch 该名字才生效
    monkeypatch.setattr(tts_mod, "synthesize_speech", _should_not_run)

    res = client.get("/api/tts/preview/9", headers={"Authorization": "Bearer t"})
    assert res.status_code == 200
    assert res.json()["audio_url"].endswith("preview_BV700_streaming.mp3")
    assert called == [], "命中缓存不应再调火山"
