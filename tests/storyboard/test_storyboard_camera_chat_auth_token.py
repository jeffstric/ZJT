"""scene_camera_chat 的 auth_token 归一化回归测试。

背景：路由曾把原始 Authorization 头（含 "Bearer " 前缀）直接传给
parse_camera_instruction，LLM 客户端内部拼 Bearer 调用量/熔断端点时形成
"Bearer Bearer xxx" 双重前缀，导致该接口的用量落账与欠费熔断静默失效。
修复后应传剥掉前缀的 token（与 server.py camera-chat、generate-from-script
同口径）。
"""
from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_scene_camera_chat_strips_bearer_before_llm_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import perseids_server.utils.permission as permission_utils

    from api import storyboard as storyboard_api

    app = FastAPI()
    app.include_router(storyboard_api.router)
    client = TestClient(app)

    captured = {"auth_token": None}

    async def fake_parse_camera_instruction(message, current_camera, **kwargs):
        captured["auth_token"] = kwargs.get("auth_token")
        return {"success": True, "camera": {"eye": {}, "target": {}, "fov": 50}}

    async def fake_resolve_authorization_user_id(auth_value):
        return 7, None

    async def fake_ensure_scene_access(scene_id, user_id, action):
        return SimpleNamespace(id=scene_id), None

    monkeypatch.setattr(storyboard_api, "get_user_id_from_header", lambda user_id: 7)
    monkeypatch.setattr(
        permission_utils,
        "resolve_authorization_user_id",
        fake_resolve_authorization_user_id,
    )
    monkeypatch.setattr(storyboard_api, "_ensure_scene_access", fake_ensure_scene_access)
    monkeypatch.setattr(storyboard_api, "parse_camera_instruction", fake_parse_camera_instruction)

    response = client.post(
        "/api/storyboard/scene/44/camera-chat",
        headers={"Authorization": "Bearer user-token-abc", "X-User-Id": "7"},
        json={
            "message": "把机位拉高一点",
            "current_camera": {"eye": {"x": 0, "y": 1.5, "z": 4}, "target": {"x": 0, "y": 1, "z": 0}, "fov": 50},
            "model": "gemini-3-flash-preview",
            "model_id": 1,
        },
    )

    assert response.status_code == 200
    # 关键断言：传给 LLM 客户端链路的 token 必须已剥掉 Bearer 前缀
    assert captured["auth_token"] == "user-token-abc"


# ---------------------------------------------------------------------------
# 请求校验分支（400/502）：此前仅覆盖成功路径
# ---------------------------------------------------------------------------

def _make_client(monkeypatch, parse_result=None, captured=None):
    """复用成功路径的鉴权/场景 mock，parse_camera_instruction 可注入返回值。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import storyboard as storyboard_api

    app = FastAPI()
    app.include_router(storyboard_api.router)
    client = TestClient(app)

    async def fake_parse(message, current_camera, **kwargs):
        if captured is not None:
            captured["kwargs"] = kwargs
        return parse_result or {"success": True, "camera": {"eye": {}, "target": {}, "fov": 50}}

    async def fake_resolve_authorization_user_id(auth_value):
        return 7, None

    async def fake_ensure(scene_id, user_id, action):
        return SimpleNamespace(id=scene_id), None

    import perseids_server.utils.permission as permission_utils
    monkeypatch.setattr(
        permission_utils,
        "resolve_authorization_user_id",
        fake_resolve_authorization_user_id,
    )

    monkeypatch.setattr(storyboard_api, "get_user_id_from_header", lambda user_id: 7)
    monkeypatch.setattr(storyboard_api, "_ensure_scene_access", fake_ensure)
    monkeypatch.setattr(storyboard_api, "parse_camera_instruction", fake_parse)
    return client


def _valid_payload(**overrides):
    payload = {
        "message": "把机位拉高一点",
        "current_camera": {
            "eye": {"x": 0, "y": 1.5, "z": 4},
            "target": {"x": 0, "y": 1, "z": 0},
            "fov": 50,
        },
        "model": "gemini-3-flash-preview",
        "model_id": 1,
    }
    payload.update(overrides)
    return payload


def test_camera_chat_empty_message_returns_400(monkeypatch):
    client = _make_client(monkeypatch)
    resp = client.post(
        "/api/storyboard/scene/44/camera-chat",
        headers={"X-User-Id": "7"},
        json=_valid_payload(message="   "),
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "指令不能为空"


def test_camera_chat_missing_camera_returns_400(monkeypatch):
    client = _make_client(monkeypatch)
    resp = client.post(
        "/api/storyboard/scene/44/camera-chat",
        headers={"X-User-Id": "7"},
        json=_valid_payload(current_camera={}),
    )
    assert resp.status_code == 400
    assert "机位" in resp.json()["error"]


def test_camera_chat_camera_eye_not_dict_returns_400(monkeypatch):
    client = _make_client(monkeypatch)
    resp = client.post(
        "/api/storyboard/scene/44/camera-chat",
        headers={"X-User-Id": "7"},
        json=_valid_payload(current_camera={"eye": [0, 1, 4], "target": {"x": 0}}),
    )
    assert resp.status_code == 400


def test_camera_chat_missing_model_returns_400(monkeypatch):
    client = _make_client(monkeypatch)
    resp = client.post(
        "/api/storyboard/scene/44/camera-chat",
        headers={"X-User-Id": "7"},
        json=_valid_payload(model=""),
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "请先选择对话模型"


def test_camera_chat_missing_model_id_returns_400(monkeypatch):
    client = _make_client(monkeypatch)
    resp = client.post(
        "/api/storyboard/scene/44/camera-chat",
        headers={"X-User-Id": "7"},
        json=_valid_payload(model_id=None),
    )
    assert resp.status_code == 400


def test_camera_chat_parse_failure_returns_502(monkeypatch):
    client = _make_client(
        monkeypatch,
        parse_result={"success": False, "error": "LLM 超时"},
    )
    resp = client.post(
        "/api/storyboard/scene/44/camera-chat",
        headers={"X-User-Id": "7"},
        json=_valid_payload(),
    )
    assert resp.status_code == 502
    assert resp.json()["success"] is False


def test_camera_chat_normalizes_model_selection_refs(monkeypatch):
    """model_id/vendor_id 须经 normalize_model_selection_refs 归一后再进 LLM。"""
    captured = {}
    client = _make_client(monkeypatch, captured=captured)

    from llm.llm_client_factory import normalize_model_selection_refs
    real_normalize = normalize_model_selection_refs

    def fake_normalize(model_id, vendor_id):
        # 保持真实函数行为（数值化），仅记录调用
        return real_normalize(model_id, vendor_id)

    import llm.llm_client_factory as lcf
    monkeypatch.setattr(lcf, "normalize_model_selection_refs", fake_normalize)

    resp = client.post(
        "/api/storyboard/scene/44/camera-chat",
        headers={"X-User-Id": "7"},
        json=_valid_payload(model_id="12", vendor_id=3),
    )
    assert resp.status_code == 200
    assert captured["kwargs"]["model_id"] == 12
    assert captured["kwargs"]["vendor_id"] == 3
