"""save_data_url_to_cache 落盘 AIGC 隐式标识挂点回归（不连 DB）。

回归背景：utils/media_cache.py 只有 download_and_cache（HTTP 下载路径）挂了
mark_file_for_task，save_data_url_to_cache（data URL 路径）漏挂——gpt_image /
gemini_image 等同步驱动经此落盘的产物全部缺隐式标识；opt-out 用户跳过显式
烧录后更是隐式/显式双无（违反《标识办法》第 4/5 条强制义务）。
"""
import base64
import io

import pytest

import utils.media_cache as media_cache_module
from utils.aigc_marking import has_aigc_label, read_aigc_json


def _make_isolated_manager(tmp_path, monkeypatch):
    """构造不依赖配置文件、落盘到 tmp_path 的 MediaCacheManager。"""
    monkeypatch.setattr(media_cache_module, "get_config", lambda: {})
    monkeypatch.setattr(
        media_cache_module, "get_dynamic_config_value", lambda *args, **kwargs: kwargs.get("default")
    )
    cm = media_cache_module.MediaCacheManager()
    cm.root_dir = tmp_path
    cm.cache_path = tmp_path / "cache"
    cm.cache_path.mkdir(parents=True, exist_ok=True)
    cm.upload_to_cloud = False
    cm._storage = None
    return cm


def _png_data_url() -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _jpeg_data_url() -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(40, 50, 60)).save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def test_png_data_url_landing_writes_aigc_label(tmp_path, monkeypatch):
    cm = _make_isolated_manager(tmp_path, monkeypatch)
    local_url = cm.save_data_url_to_cache(_png_data_url(), 424242)
    assert local_url and local_url.startswith("/")
    fp = tmp_path / local_url.lstrip("/")
    assert fp.is_file()
    assert has_aigc_label(fp) is True
    payload = read_aigc_json(fp)
    assert payload and payload["ProduceID"] == "424242"
    assert payload["ContentProp"] == "image"
    # 实例标识（多服务器/多路径部署区分）：主机名后 6 位 + 部署路径末两个目录
    assert payload.get("Instance") and "/" in payload["Instance"]
    host_tail, *path_dirs = payload["Instance"].split("/")
    assert len(host_tail) <= 6 and 1 <= len(path_dirs) <= 2


def test_jpeg_data_url_landing_writes_aigc_label(tmp_path, monkeypatch):
    cm = _make_isolated_manager(tmp_path, monkeypatch)
    local_url = cm.save_data_url_to_cache(_jpeg_data_url(), 424243)
    fp = tmp_path / local_url.lstrip("/")
    assert fp.is_file()
    assert has_aigc_label(fp) is True
    assert read_aigc_json(fp)["ProduceID"] == "424243"


def test_unrecognized_mime_still_returns_url_without_label(tmp_path, monkeypatch):
    """非媒体 mime（.bin）魔数识别不了：不写标但也不阻断交付。"""
    cm = _make_isolated_manager(tmp_path, monkeypatch)
    raw = base64.b64encode(b"\x00\x01not-a-media").decode()
    local_url = cm.save_data_url_to_cache("data:application/octet-stream;base64," + raw, 424244)
    assert local_url and local_url.startswith("/")
    fp = tmp_path / local_url.lstrip("/")
    assert fp.is_file()
    # .bin 魔数识别不了：has_aigc_label 返回 None（不支持校验），绝不能是 True
    assert has_aigc_label(fp) is not True


def test_marking_failure_does_not_block_delivery(tmp_path, monkeypatch):
    """标识写入抛异常时不阻断交付（local_url 照常返回）。"""
    cm = _make_isolated_manager(tmp_path, monkeypatch)
    monkeypatch.setattr(
        media_cache_module, "mark_file_for_task", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    local_url = cm.save_data_url_to_cache(_png_data_url(), 424245)
    assert local_url and (tmp_path / local_url.lstrip("/")).is_file()
