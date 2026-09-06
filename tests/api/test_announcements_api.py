"""
本站公告 API 接口测试

覆盖用户侧鉴权、已读流转与管理侧权限/校验（mock service 与数据层，不连真实数据库）。
"""
from types import SimpleNamespace
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _seed_config_cache(monkeypatch):
    monkeypatch.setenv("comfyui_env", "unit")
    import config.config_util as config_util

    config_util._config_cache["config_unit.yml"] = {
        "database": {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "unit",
            "password": "unit",
            "database": "unit",
        }
    }


def _client(monkeypatch):
    _seed_config_cache(monkeypatch)
    from api.announcements import router, admin_router

    app = FastAPI()
    app.include_router(router)
    app.include_router(admin_router)
    return TestClient(app)


AUTH = {"Authorization": "Bearer good-token"}


def _stub_admin(monkeypatch, client=None, admin_id=1):
    monkeypatch.setattr(
        "api.announcements._require_admin",
        lambda auth_token: SimpleNamespace(id=admin_id, role='admin'),
    )


def _stub_user(monkeypatch, user_id=7):
    monkeypatch.setattr(
        "api.announcements._get_current_user",
        lambda auth_token: user_id,
    )


# ============ 用户侧 ============

def test_list_requires_login(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr("api.announcements._get_current_user", lambda auth_token: None)

    response = client.get("/api/announcements")
    assert response.status_code == 200
    assert response.json()["code"] == 1


def test_list_returns_items_with_read_state(monkeypatch):
    client = _client(monkeypatch)
    _stub_user(monkeypatch, user_id=7)
    captured = {}

    def fake_list_for_user(user_id, limit=50):
        captured['user_id'] = user_id
        captured['limit'] = limit
        return [
            {"id": 1, "title": "公告A", "content": "内容", "level": "info",
             "status": "published", "images": [], "is_read": False,
             "link_url": None, "link_text": None, "publish_at": None,
             "expire_at": None, "created_by": 1, "created_at": None, "updated_at": None},
        ]

    monkeypatch.setattr("api.announcements.AnnouncementService.list_for_user", fake_list_for_user)

    response = client.get("/api/announcements?limit=10", headers=AUTH)
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["items"][0]["title"] == "公告A"
    assert captured == {"user_id": 7, "limit": 10}


def test_unread_count(monkeypatch):
    client = _client(monkeypatch)
    _stub_user(monkeypatch, user_id=7)
    monkeypatch.setattr("api.announcements.AnnouncementService.get_unread_count", lambda user_id: 3)

    response = client.get("/api/announcements/unread-count", headers=AUTH)
    assert response.json() == {"code": 0, "data": {"count": 3}}


def test_mark_read(monkeypatch):
    client = _client(monkeypatch)
    _stub_user(monkeypatch, user_id=7)
    monkeypatch.setattr(
        "api.announcements.AnnouncementService.mark_read",
        lambda user_id, announcement_id: {"success": True},
    )

    response = client.post("/api/announcements/5/read", headers=AUTH)
    assert response.json() == {"code": 0, "data": {"updated": True}}


def test_mark_read_announcement_missing(monkeypatch):
    client = _client(monkeypatch)
    _stub_user(monkeypatch, user_id=7)
    monkeypatch.setattr(
        "api.announcements.AnnouncementService.mark_read",
        lambda user_id, announcement_id: {"success": False, "message": "公告不存在"},
    )

    response = client.post("/api/announcements/999/read", headers=AUTH)
    assert response.json()["code"] == 1


def test_read_all(monkeypatch):
    client = _client(monkeypatch)
    _stub_user(monkeypatch, user_id=7)
    monkeypatch.setattr("api.announcements.AnnouncementService.mark_all_read", lambda user_id: 4)

    response = client.post("/api/announcements/read-all", headers=AUTH)
    assert response.json() == {"code": 0, "data": {"updated_count": 4}}


# ============ 管理侧 ============

def test_admin_create_requires_admin(monkeypatch):
    client = _client(monkeypatch)

    def deny(auth_token):
        raise ValueError("权限不足")

    monkeypatch.setattr("api.announcements._require_admin", deny)

    response = client.post("/api/admin/announcements", json={"title": "T"}, headers=AUTH)
    body = response.json()
    assert body["code"] == 1 and "权限" in body["message"]


def test_admin_create_success(monkeypatch):
    client = _client(monkeypatch)
    _stub_admin(monkeypatch, admin_id=1)
    captured = {}

    def fake_create(admin_user_id, payload):
        captured['admin_user_id'] = admin_user_id
        captured['payload'] = payload
        return {"success": True, "id": 20}

    monkeypatch.setattr("api.announcements.AnnouncementService.create", fake_create)

    response = client.post("/api/admin/announcements", json={
        "title": "智剧通9月征稿",
        "content": "详情见链接",
        "level": "info",
        "status": "published",
        "images": ["/upload/announcement/202609/x.png"],
    }, headers=AUTH)

    body = response.json()
    assert body == {"code": 0, "data": {"id": 20}}
    assert captured['admin_user_id'] == 1
    assert captured['payload']['title'] == "智剧通9月征稿"
    assert captured['payload']['status'] == "published"


def test_admin_create_invalid_payload(monkeypatch):
    client = _client(monkeypatch)
    _stub_admin(monkeypatch)
    monkeypatch.setattr(
        "api.announcements.AnnouncementService.create",
        lambda admin_user_id, payload: {"success": False, "message": "公告标题不能为空"},
    )

    response = client.post("/api/admin/announcements", json={"title": ""}, headers=AUTH)
    body = response.json()
    assert body["code"] == 1 and "标题" in body["message"]


def test_admin_publish_and_offline(monkeypatch):
    client = _client(monkeypatch)
    _stub_admin(monkeypatch)
    calls = []

    def fake_update_status(announcement_id, status):
        calls.append((announcement_id, status))
        return {"success": True}

    monkeypatch.setattr("api.announcements.AnnouncementService.update_status", fake_update_status)

    assert client.post("/api/admin/announcements/5/publish", headers=AUTH).json()["code"] == 0
    assert client.post("/api/admin/announcements/5/offline", headers=AUTH).json()["code"] == 0
    assert calls == [(5, "published"), (5, "offline")]


def test_admin_delete(monkeypatch):
    client = _client(monkeypatch)
    _stub_admin(monkeypatch, admin_id=1)
    captured = {}

    def fake_delete(admin_user_id, announcement_id):
        captured['admin_user_id'] = admin_user_id
        captured['announcement_id'] = announcement_id
        return {"success": True}

    monkeypatch.setattr("api.announcements.AnnouncementService.delete", fake_delete)

    response = client.delete("/api/admin/announcements/9", headers=AUTH)
    assert response.json() == {"code": 0, "data": {"deleted": True}}
    assert captured == {"admin_user_id": 1, "announcement_id": 9}


def test_admin_update(monkeypatch):
    client = _client(monkeypatch)
    _stub_admin(monkeypatch)
    captured = {}

    def fake_update(announcement_id, payload):
        captured['announcement_id'] = announcement_id
        captured['payload'] = payload
        return {"success": True}

    monkeypatch.setattr("api.announcements.AnnouncementService.update", fake_update)

    response = client.put("/api/admin/announcements/9", json={"title": "新标题"}, headers=AUTH)
    assert response.json()["code"] == 0
    assert captured['announcement_id'] == 9
    assert captured['payload']['title'] == "新标题"


# ============ 图片上传 ============

def test_upload_image_rejects_non_image(monkeypatch):
    client = _client(monkeypatch)
    _stub_admin(monkeypatch)

    response = client.post(
        "/api/admin/announcements/upload-image",
        files={"file": ("doc.txt", b"hello", "text/plain")},
        headers=AUTH,
    )
    body = response.json()
    assert body["code"] == 1 and "图片" in body["message"]


def test_upload_image_requires_admin(monkeypatch):
    client = _client(monkeypatch)

    def deny(auth_token):
        raise ValueError("未登录")

    monkeypatch.setattr("api.announcements._require_admin", deny)

    response = client.post(
        "/api/admin/announcements/upload-image",
        files={"file": ("x.png", b"png", "image/png")},
    )
    assert response.json()["code"] == 1


def test_upload_image_success(monkeypatch):
    client = _client(monkeypatch)
    _stub_admin(monkeypatch)
    monkeypatch.setattr(
        "api.announcements._save_announcement_image",
        lambda file: "/upload/announcement/202609/announcement_20260906_x.png",
    )

    response = client.post(
        "/api/admin/announcements/upload-image",
        files={"file": ("x.png", b"png-bytes", "image/png")},
        headers=AUTH,
    )
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["url"].startswith("/upload/announcement/")
