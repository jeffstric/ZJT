"""
本站公告 API 测试（2026-09 新增功能，commit ee890760 / 6a3c0400）。

覆盖：
- 用户侧：/api/announcements 列表、/unread-count、/read-all、/{id}/read
- 管理侧：/api/admin/announcements 创建/列表/编辑/发布/下线/删除/图片上传
- 权限：未登录、非管理员访问管理侧

说明：
- 主测试账号为 admin 角色（与 test_admin_api.py 一致），api_client 直接可用。
- 副账号（secondary）用于非管理员权限负向用例。
- 公告对用户全局可见，断言均按唯一标题/ID 过滤，不假设环境里无其他公告。
- 每个用例自包含并 best-effort 清理自己创建的公告，避免污染后续用例的未读数断言基线。
"""
import io
import time

import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.announcements,
    pytest.mark.p1,
]

TITLE_PREFIX = "pytest公告"


def _unique_title() -> str:
    return f"{TITLE_PREFIX}_{int(time.time() * 1000)}"


def _cleanup(api_client, announcement_id: int):
    """best-effort 删除（下线后删除均尝试，忽略异常）"""
    try:
        api_client.post(f"/api/admin/announcements/{announcement_id}/offline")
        api_client.delete(f"/api/admin/announcements/{announcement_id}")
    except Exception:
        pass


def _create_announcement(api_client, title: str, status: str = "draft") -> int:
    """admin 创建公告，返回公告 ID"""
    resp = api_client.post(
        "/api/admin/announcements",
        json={"title": title, "content": "自动化测试公告内容", "level": "info", "status": status},
    )
    assert resp.status_code == 200, f"创建公告失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"创建公告业务失败: {data}"
    aid = data.get("data", {}).get("id")
    assert aid is not None, f"响应缺少公告 ID: {data}"
    return aid


def _user_items(api_client) -> list:
    resp = api_client.get("/api/announcements", params={"limit": 100})
    assert resp.status_code == 200, f"用户侧公告列表失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"用户侧公告列表业务失败: {data}"
    return data.get("data", {}).get("items", [])


def _find_item(items: list, aid: int):
    return next((it for it in items if it.get("id") == aid), None)


# ============ 用户侧 ============


@pytest.mark.e2e
def test_user_list_requires_login(base_url):
    """ann_001 - 未登录访问公告列表应提示未登录"""
    resp = httpx.get(f"{base_url}/api/announcements", timeout=15)
    assert resp.status_code == 200, f"HTTP 层异常: {resp.status_code}"
    data = resp.json()
    assert data.get("code") == 1, f"未登录应 code=1: {data}"
    assert "未登录" in data.get("message", ""), f"message 应提示未登录: {data}"


def test_user_unread_count_shape(api_client):
    """ann_002 - 未读数接口返回非负整数"""
    resp = api_client.get("/api/announcements/unread-count")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("code") == 0, f"未读数接口失败: {data}"
    count = data.get("data", {}).get("count")
    assert isinstance(count, int) and count >= 0, f"count 应为非负整数: {data}"


def test_publish_shows_and_offline_hides(api_client):
    """ann_003 - 草稿用户不可见；发布后可见且未读+1；下线后不可见"""
    title = _unique_title()
    aid = _create_announcement(api_client, title, status="draft")
    try:
        # 草稿：用户列表不可见
        assert _find_item(_user_items(api_client), aid) is None, "草稿公告不应出现在用户列表"

        before = api_client.get("/api/announcements/unread-count").json()["data"]["count"]

        # 发布
        resp = api_client.post(f"/api/admin/announcements/{aid}/publish")
        assert resp.status_code == 200 and resp.json().get("code") == 0, f"发布失败: {resp.text}"
        item = _find_item(_user_items(api_client), aid)
        assert item is not None, "发布后公告应出现在用户列表"
        assert item.get("title") == title
        after = api_client.get("/api/announcements/unread-count").json()["data"]["count"]
        assert after == before + 1, f"发布后未读数应 +1: before={before}, after={after}"

        # 下线
        resp = api_client.post(f"/api/admin/announcements/{aid}/offline")
        assert resp.status_code == 200 and resp.json().get("code") == 0, f"下线失败: {resp.text}"
        assert _find_item(_user_items(api_client), aid) is None, "下线后公告不应出现在用户列表"
        # 管理侧列表仍含（状态 offline）
        admin_resp = api_client.get("/api/admin/announcements/list", params={"page": 1, "page_size": 100})
        admin_items = admin_resp.json().get("data", {}).get("items", [])
        admin_item = _find_item(admin_items, aid)
        assert admin_item is not None and admin_item.get("status") == "offline", \
            f"管理侧列表应含该公告且状态 offline: {admin_item}"
    finally:
        _cleanup(api_client, aid)


def test_mark_read_and_read_all(api_client):
    """ann_004 - 单条已读后未读-1；read-all 后未读清零"""
    title = _unique_title()
    aid = _create_announcement(api_client, title, status="published")
    try:
        before = api_client.get("/api/announcements/unread-count").json()["data"]["count"]

        resp = api_client.post(f"/api/announcements/{aid}/read")
        assert resp.status_code == 200 and resp.json().get("code") == 0, f"标记已读失败: {resp.text}"
        after = api_client.get("/api/announcements/unread-count").json()["data"]["count"]
        assert after == before - 1, f"单条已读后未读数应 -1: before={before}, after={after}"

        # 再造一条未读，再 read-all 清零
        aid2 = _create_announcement(api_client, _unique_title(), status="published")
        try:
            mid = api_client.get("/api/announcements/unread-count").json()["data"]["count"]
            assert mid >= 1, f"read-all 前应有未读: {mid}"
            resp = api_client.post("/api/announcements/read-all")
            assert resp.status_code == 200 and resp.json().get("code") == 0, f"read-all 失败: {resp.text}"
            final = api_client.get("/api/announcements/unread-count").json()["data"]["count"]
            assert final == 0, f"read-all 后未读数应为 0: {final}"
        finally:
            _cleanup(api_client, aid2)
    finally:
        _cleanup(api_client, aid)


def test_mark_read_nonexistent(api_client):
    """ann_005 - 标记不存在公告已读应业务失败"""
    resp = api_client.post("/api/announcements/999999999/read")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("code") == 1, f"不存在公告标记已读应 code=1: {data}"


# ============ 管理侧 ============


def test_admin_update_title(api_client):
    """ann_006 - 管理员编辑公告标题生效"""
    title = _unique_title()
    new_title = title + "_已编辑"
    aid = _create_announcement(api_client, title)
    try:
        resp = api_client.put(
            f"/api/admin/announcements/{aid}",
            json={"title": new_title, "content": "编辑后的内容", "level": "info"},
        )
        assert resp.status_code == 200 and resp.json().get("code") == 0, f"编辑公告失败: {resp.text}"
        admin_items = api_client.get(
            "/api/admin/announcements/list", params={"page": 1, "page_size": 100}
        ).json().get("data", {}).get("items", [])
        item = _find_item(admin_items, aid)
        assert item is not None and item.get("title") == new_title, f"编辑未生效: {item}"
    finally:
        _cleanup(api_client, aid)


def test_admin_delete(api_client):
    """ann_007 - 管理员删除公告后两侧列表均不可见"""
    title = _unique_title()
    aid = _create_announcement(api_client, title, status="published")
    resp = api_client.delete(f"/api/admin/announcements/{aid}")
    assert resp.status_code == 200 and resp.json().get("code") == 0, f"删除失败: {resp.text}"
    assert _find_item(_user_items(api_client), aid) is None, "删除后用户列表不应含该公告"
    admin_items = api_client.get(
        "/api/admin/announcements/list", params={"page": 1, "page_size": 100}
    ).json().get("data", {}).get("items", [])
    assert _find_item(admin_items, aid) is None, "删除后管理侧列表不应含该公告"


def test_admin_invalid_publish_at_rejected(api_client):
    """ann_008 - 非法 publish_at 时间格式应被服务层拒绝（6a3c0400）"""
    title = _unique_title()
    resp = api_client.post(
        "/api/admin/announcements",
        json={"title": title, "content": "", "level": "info", "publish_at": "不是合法时间"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("code") == 1, f"非法时间应 code=1: {data}"
    # 若误创建了记录则清理
    aid = data.get("data", {}).get("id")
    if aid:
        _cleanup(api_client, aid)


def test_non_admin_denied(api_client, secondary_auth_token):
    """ann_009 - 非管理员访问管理侧应权限不足"""
    headers = {"Authorization": f"Bearer {secondary_auth_token}"}
    resp = api_client.post(
        "/api/admin/announcements",
        json={"title": "非管理员创建", "content": "", "level": "info"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("code") == 1, f"非管理员创建应失败: {data}"
    assert "权限" in data.get("message", ""), f"message 应提示权限不足: {data}"


def test_upload_image_and_reject_non_image(api_client):
    """ann_010 - 上传 png 返回 /upload/ URL；非图片被拒"""
    # 1x1 透明 png
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB\x60\x82"
    )
    resp = api_client.post(
        "/api/admin/announcements/upload-image",
        files={"file": ("test.png", io.BytesIO(png), "image/png")},
    )
    assert resp.status_code == 200, f"图片上传失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"图片上传业务失败: {data}"
    url = data.get("data", {}).get("url", "")
    assert url.startswith("/upload/"), f"上传应返回 /upload/ 相对 URL: {data}"

    resp = api_client.post(
        "/api/admin/announcements/upload-image",
        files={"file": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("code") == 1, f"非图片上传应被拒: {data}"
