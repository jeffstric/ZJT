"""POST /api/upload-agent-video 硬校验单测（360极速浏览器 0 字节压缩视频事故修复）。

覆盖：
- 0 字节文件 → 400 拒绝（前端 MediaRecorder 在个别浏览器下产出空 Blob，
  曾被放行落盘为"上传成功"的损坏视频，下游 ffmpeg EBML 解析失败）
- ffprobe 无法解析（get_video_info 返回 None）→ 400 且落盘文件被删除
  （旧行为跳过全部校验当成功放行，是 0 字节视频入库的直接原因）
- 正常视频 → 200 success
- 时长超限 → 400 且文件被删除
"""
import os
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import script_writer
from model.user_tokens import UserTokensModel

# 正常视频的 ffprobe 结果（854x480=409920 像素 ≥ 最低 409600，duration/fps 合法）
VALID_VIDEO_INFO = {"width": 854, "height": 480, "duration": 10.0, "fps": 30.0}

UPLOAD_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "upload", "marketing", "video",
)
SESSION_ID = "ut_upload_agent_video"


@pytest.fixture
def client(monkeypatch):
    """挂载真实 upload_agent_video 的最小 app：鉴权放行、is_local 本地 URL、
    get_video_info 可控。"""
    monkeypatch.setattr(
        UserTokensModel, "get_user_id_by_token",
        staticmethod(lambda token: 1 if token == "valid-token" else None),
    )

    def _fake_dynamic(*keys, **kwargs):
        if keys == ("server", "is_local"):
            return True
        return kwargs.get("default")

    monkeypatch.setattr(script_writer, "get_dynamic_config_value", _fake_dynamic)
    monkeypatch.setattr(
        script_writer, "get_config",
        lambda: {"server": {"host": "http://test.local"}},
    )

    app = FastAPI()
    app.post("/api/upload-agent-video")(script_writer.upload_agent_video)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_session_dir():
    """清理测试落盘目录，避免污染仓库。"""
    yield
    session_dir = os.path.join(UPLOAD_ROOT, SESSION_ID)
    if os.path.isdir(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)


def _post_video(client, content=b"fake-webm-bytes", filename="a.webm"):
    return client.post(
        "/api/upload-agent-video",
        files={"file": (filename, content, "video/webm")},
        data={"session_id": SESSION_ID},
        headers={"Authorization": "Bearer valid-token"},
    )


def _session_files():
    session_dir = os.path.join(UPLOAD_ROOT, SESSION_ID)
    if not os.path.isdir(session_dir):
        return []
    return [f for f in os.listdir(session_dir) if not f.startswith(".")]


def test_empty_file_rejected(client):
    """0 字节文件：400 拒绝且不落盘（前端压缩失败产物，事故根因第一环）"""
    resp = _post_video(client, content=b"")

    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert "为空" in resp.json()["error"]
    assert _session_files() == []


def test_unparsable_video_rejected_and_removed(client, monkeypatch):
    """ffprobe 无法解析：400 拒绝且已落盘文件被删除（旧行为 None 跳过全部校验）"""
    async def _fail_probe(path):
        return None

    monkeypatch.setattr(script_writer, "get_video_info", _fail_probe)
    resp = _post_video(client)

    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert "无法解析" in resp.json()["error"]
    assert _session_files() == []


def test_valid_video_accepted(client, monkeypatch):
    """正常视频：200 success，返回本地 URL"""
    async def _ok_probe(path):
        return dict(VALID_VIDEO_INFO)

    monkeypatch.setattr(script_writer, "get_video_info", _ok_probe)
    resp = _post_video(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["url"].startswith("http://test.local/upload/marketing/video/")
    assert len(_session_files()) == 1


def test_overlong_video_rejected_and_removed(client, monkeypatch):
    """时长超限：400 拒绝且已落盘文件被删除"""
    async def _long_probe(path):
        return {**VALID_VIDEO_INFO, "duration": 99.0}

    monkeypatch.setattr(script_writer, "get_video_info", _long_probe)
    resp = _post_video(client)

    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert _session_files() == []


def test_missing_token_rejected(client):
    """未登录：401"""
    resp = client.post(
        "/api/upload-agent-video",
        files={"file": ("a.webm", b"x", "video/webm")},
        data={"session_id": SESSION_ID},
    )
    assert resp.status_code == 401
