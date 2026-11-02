"""工作流素材前端直传接口测试：/api/video-workflow/upload-token 与 upload-confirm

覆盖：
- CDN 未启用（server.auto_upload_to_cdn=false）：token 返回 direct_upload=false，
  前端降级 multipart，行为与直传功能上线前完全一致
- CDN 启用：token 正常颁发（key 绑定当前用户目录、policy 带 fsizeLimit）
- 非白名单扩展名 / 超大小上限 / TIFF 的降级与拒绝
- confirm：跨用户 key 拒绝、路径穿越拒绝、七牛侧未找到拒绝
- confirm 成功：回源落盘后返回本站永久 URL，mapping 以"本地为主副本"注册
- confirm 幂等：mapping 已存在直接返回 URL
"""
import os
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

# 模块级导入（收集阶段即完成）：tests/utils/test_image_upload_utils.py 会在模块级
# 裸注入 sys.modules['aiohttp'] = MagicMock() 且不恢复（存量隔离地雷），凡在注入后
# 才首次 import server 的测试都会因 litellm→aiohttp 解析到假模块而炸。本文件按
# 字母序先于 tests/utils 收集，提前缓存 server 即可免疫（惯例同 test_worlds_scope_gate.py）。
import server

from config.constant import MediaUploadSafetyConstants

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
KEY_PREFIX_USER1 = "upload/workflow/1/"


@pytest.fixture
def client(monkeypatch):
    """登录身份固定为用户 1（Authorization: valid-token）"""
    import server

    monkeypatch.setattr(
        "model.user_tokens.UserTokensModel.get_user_id_by_token",
        staticmethod(lambda token: 1 if token == "valid-token" else None),
    )
    return TestClient(server.app)


@pytest.fixture
def cdn_enabled(monkeypatch):
    """server.auto_upload_to_cdn=true"""
    import server

    monkeypatch.setattr(
        server, "get_config",
        lambda: {"server": {"host": "http://zjt-dev.perseids.cn", "auto_upload_to_cdn": True}},
    )


@pytest.fixture
def cdn_disabled(monkeypatch):
    """server.auto_upload_to_cdn=false（本地开发默认形态）"""
    import server

    monkeypatch.setattr(
        server, "get_config",
        lambda: {"server": {"host": "http://zjt-dev.perseids.cn", "auto_upload_to_cdn": False}},
    )


class _FakeStorage:
    """qiniu_long_term 存储替身：实现直传接口（端点只依赖 BaseFileStorage 接口方法）"""

    def __init__(self, stat_result=None, upload_url="https://upload.test.example.com"):
        self.stat_result = stat_result
        self.upload_url = upload_url
        self.browser_upload_calls = []

    async def get_browser_upload_info(self, key, max_bytes, expires=1800):
        self.browser_upload_calls.append({"key": key, "max_bytes": max_bytes, "expires": expires})
        return {
            "direct_upload": True,
            "upload_url": self.upload_url,
            "token": "fake-upload-token",
            "key": key,
            "expires": expires,
        }

    async def stat(self, key):
        return self.stat_result

    def get_download_url(self, key, expires=7200, attname=None):
        return f"https://cdn-download.test/{key}?e=1&token=sig"


class _UnsupportedStorage:
    """不支持浏览器直传的后端（基类默认语义）"""

    async def stat(self, key):
        return None

    def get_download_url(self, key, expires=7200, attname=None):
        return f"https://cdn-download.test/{key}"


def _patch_storage(monkeypatch, storage):
    import utils.file_storage as fs_mod

    monkeypatch.setattr(fs_mod, "get_file_storage", lambda config=None, section="qiniu": storage)


def _patch_mapping_lookup(monkeypatch, existing):
    from model.media_file_mapping import MediaFileMappingModel

    monkeypatch.setattr(
        MediaFileMappingModel, "get_by_local_path",
        staticmethod(lambda local_path: existing),
    )


# ========== upload-token ==========

def test_token_disabled_cdn_returns_fallback(client, cdn_disabled):
    """CDN 未启用：direct_upload=false，前端降级 multipart，行为不变"""
    resp = client.post(
        "/api/video-workflow/upload-token",
        data={"filename": "clip.mp4", "size": 100},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["direct_upload"] is False
    assert data["reason"] == "cdn_disabled"


def test_token_success_binds_key_and_fsize_limit(client, cdn_enabled, monkeypatch):
    """CDN 启用：key 绑定当前用户目录，直传信息经接口方法颁发（含大小上限）"""
    storage = _FakeStorage()
    _patch_storage(monkeypatch, storage)

    resp = client.post(
        "/api/video-workflow/upload-token",
        data={"filename": "clip.mp4", "size": 1024},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["direct_upload"] is True
    assert data["key"].startswith(KEY_PREFIX_USER1)
    assert data["key"].endswith(".mp4")
    assert data["token"] == "fake-upload-token"
    assert data["upload_url"] == "https://upload.test.example.com"
    call = storage.browser_upload_calls[0]
    assert call["key"] == data["key"]
    assert call["max_bytes"] == MediaUploadSafetyConstants.MAX_VIDEO_SIZE


def test_token_unsupported_backend_falls_back(client, cdn_enabled, monkeypatch):
    """存储后端不支持浏览器直传（接口默认语义）：降级 multipart"""
    _patch_storage(monkeypatch, _UnsupportedStorage())

    resp = client.post(
        "/api/video-workflow/upload-token",
        data={"filename": "clip.mp4", "size": 1024},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["direct_upload"] is False
    assert data["reason"] == "backend_unsupported"


def test_token_rejects_disallowed_extension(client, cdn_enabled):
    """可执行/非白名单扩展名直接 400"""
    resp = client.post(
        "/api/video-workflow/upload-token",
        data={"filename": "evil.html", "size": 10},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 400


def test_token_rejects_oversize(client, cdn_enabled):
    """超类别大小上限（视频 200MB）预校验 400"""
    resp = client.post(
        "/api/video-workflow/upload-token",
        data={"filename": "clip.mp4", "size": MediaUploadSafetyConstants.MAX_VIDEO_SIZE + 1},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 400


def test_token_rejects_nonpositive_size(client, cdn_enabled):
    """非法大小（负数/0）预校验 400，不依赖七牛 fsizeLimit 兜底"""
    for bad_size in ("-1", "0"):
        resp = client.post(
            "/api/video-workflow/upload-token",
            data={"filename": "clip.mp4", "size": bad_size},
            headers={"Authorization": "valid-token"},
        )
        assert resp.status_code == 400, bad_size


def test_token_tiff_falls_back_to_multipart(client, cdn_enabled):
    """TIFF 需服务端转码 PNG，直传 key 会与转码产物脱节 → 走 multipart"""
    resp = client.post(
        "/api/video-workflow/upload-token",
        data={"filename": "photo.tif", "size": 100},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["direct_upload"] is False
    assert data["reason"] == "tiff_unsupported"


# ========== upload-confirm ==========

def test_confirm_rejects_when_cdn_disabled(client, cdn_disabled):
    """CDN 未启用：confirm 不可用（正常流程不会走到）"""
    resp = client.post(
        "/api/video-workflow/upload-confirm",
        data={"key": KEY_PREFIX_USER1 + "a.mp4"},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 400


def test_confirm_rejects_cross_user_key(client, cdn_enabled):
    """key 属于其他用户目录 → 400（防跨用户伪造登记）"""
    resp = client.post(
        "/api/video-workflow/upload-confirm",
        data={"key": "upload/workflow/2/other.mp4"},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 400


def test_confirm_rejects_path_traversal_key(client, cdn_enabled):
    """路径穿越 key（../ 与嵌套目录）→ 400"""
    for bad_key in (
        "upload/workflow/1/../1/evil.png",
        "upload/workflow/1/sub/dir/a.png",
        "upload/workflow/1/a.png/../../workflow/1/b.png",
    ):
        resp = client.post(
            "/api/video-workflow/upload-confirm",
            data={"key": bad_key},
            headers={"Authorization": "valid-token"},
        )
        assert resp.status_code == 400, bad_key


def test_confirm_rejects_disallowed_extension(client, cdn_enabled):
    """扩展名白名单外（.html 可渲染文档）→ 400"""
    resp = client.post(
        "/api/video-workflow/upload-confirm",
        data={"key": KEY_PREFIX_USER1 + "evil.html"},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 400


def test_confirm_rejects_when_file_missing_on_cdn(client, cdn_enabled, monkeypatch):
    """七牛 stat 查不到文件（伪造 confirm / 直传实际失败）→ 400"""
    _patch_storage(monkeypatch, _FakeStorage(stat_result=None))
    _patch_mapping_lookup(monkeypatch, existing=None)

    resp = client.post(
        "/api/video-workflow/upload-confirm",
        data={"key": KEY_PREFIX_USER1 + "a.png"},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 400


def test_confirm_success_downloads_registers_and_returns_site_url(
    client, cdn_enabled, monkeypatch, tmp_path
):
    """成功路径：回源落盘（本地为主副本）→ mapping 注册 → 返回本站永久 URL"""
    import server

    storage = _FakeStorage(stat_result={"fsize": len(PNG_MAGIC)})
    _patch_storage(monkeypatch, storage)
    _patch_mapping_lookup(monkeypatch, existing=None)
    monkeypatch.setattr(server, "get_upload_subdir", lambda *parts, ensure=True: str(tmp_path))

    downloaded = {}

    def _fake_download(download_url, final_path, ext, expected_size, max_bytes):
        downloaded["url"] = download_url
        downloaded["final_path"] = final_path
        with open(final_path, "wb") as f:
            f.write(PNG_MAGIC)
        return len(PNG_MAGIC)

    monkeypatch.setattr(server, "_download_cdn_asset_to_local", _fake_download)

    registered = {}

    def _fake_register(**kwargs):
        registered.update(kwargs)
        return 321

    monkeypatch.setattr(server, "register_direct_uploaded_mapping", _fake_register)

    key = KEY_PREFIX_USER1 + "workflow_20261102_100000_ab12cd34.png"
    resp = client.post(
        "/api/video-workflow/upload-confirm",
        data={"key": key},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["url"].endswith("/upload/workflow/1/workflow_20261102_100000_ab12cd34.png")
    assert data["url"].startswith("http")
    # 回源确实执行：从七牛签名 URL 下载到用户素材目录
    assert downloaded["url"].startswith("https://cdn-download.test/")
    assert downloaded["final_path"] == os.path.join(str(tmp_path), os.path.basename(key))
    assert os.path.exists(downloaded["final_path"])
    # mapping 以"本地为主副本 + cloud_path 置位"语义注册
    assert registered["local_path"] == key
    assert registered["file_size"] == len(PNG_MAGIC)


def test_confirm_idempotent_when_mapping_exists(client, cdn_enabled, monkeypatch):
    """幂等：mapping 已存在时直接返回 URL，不重复回源下载"""
    import server

    existing = MagicMock()
    existing.cloud_path = KEY_PREFIX_USER1 + "a.png"
    _patch_mapping_lookup(monkeypatch, existing=existing)
    _patch_storage(monkeypatch, _FakeStorage(stat_result={"fsize": 1}))

    def _fail_download(*args, **kwargs):
        raise AssertionError("幂等路径不应触发回源下载")

    monkeypatch.setattr(server, "_download_cdn_asset_to_local", _fail_download)

    resp = client.post(
        "/api/video-workflow/upload-confirm",
        data={"key": KEY_PREFIX_USER1 + "a.png"},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["url"].endswith("/upload/workflow/1/a.png")


def test_confirm_rejects_oversize_on_cdn_stat(client, cdn_enabled, monkeypatch):
    """七牛侧实际大小超类别上限（绕过 token 预校验）→ 400"""
    storage = _FakeStorage(stat_result={"fsize": MediaUploadSafetyConstants.MAX_VIDEO_SIZE + 1})
    _patch_storage(monkeypatch, storage)
    _patch_mapping_lookup(monkeypatch, existing=None)

    resp = client.post(
        "/api/video-workflow/upload-confirm",
        data={"key": KEY_PREFIX_USER1 + "big.mp4"},
        headers={"Authorization": "valid-token"},
    )
    assert resp.status_code == 400
