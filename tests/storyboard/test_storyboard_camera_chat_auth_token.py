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
