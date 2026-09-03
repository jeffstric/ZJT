"""generate_character_variant_image 主参考图 URL 归一化测试。

背景：角色主参考图在系统内常态存储为 /upload/... 相对路径，而 edit_image
图生图要求 http/https 绝对 URL，导致角色变体图生成被
"主参考图URL无效（仅支持 http/https）" 拒绝（剧本拆分自动变体与智能体
手动变体同路径）。修复后相对路径应按 server 配置补齐为绝对 URL。
"""
from types import SimpleNamespace

import script_writer_core.mcp_tool as mcp_tool


def _install(monkeypatch, reference_image, server_host="http://localhost:12000",
             https_enabled=False, https_host=""):
    """安装挡板：角色 JSON + edit_image 捕获 + server 配置。返回捕获字典。"""
    captured = {}

    fake_fm = SimpleNamespace(
        get_character_json=lambda name, user_id, world_id: {
            "name": name,
            "reference_image": reference_image,
            "reference_images": [],
        }
    )
    monkeypatch.setattr(mcp_tool, "get_file_manager", lambda: fake_fm)

    def fake_edit_image(**kwargs):
        captured["image_url"] = kwargs["image_url"]
        return {"success": True, "task_id": "fake_task_1"}

    monkeypatch.setattr(mcp_tool, "edit_image", fake_edit_image)

    config_map = {
        ("server", "https", "enabled"): https_enabled,
        ("server", "https_host"): https_host,
        ("server", "host"): server_host,
    }
    monkeypatch.setattr(
        mcp_tool, "get_config_value",
        lambda *args, default=None, **kw: config_map.get(tuple(args), default),
    )
    return captured


def _call():
    return mcp_tool.generate_character_variant_image(
        user_id="1", world_id="3", auth_token="tok",
        character_name="小林", variant_label="晚礼服",
        variant_prompt="keep identity, new outfit",
    )


def test_relative_upload_path_is_resolved_to_absolute(monkeypatch):
    captured = _install(monkeypatch, "/upload/character/pic/abc.png")

    result = _call()

    assert result["success"] is True
    assert captured["image_url"] == "http://localhost:12000/upload/character/pic/abc.png"
    assert result["source_image_url"] == captured["image_url"]


def test_relative_path_without_leading_slash(monkeypatch):
    captured = _install(monkeypatch, "upload/character/pic/abc.png")

    result = _call()

    assert result["success"] is True
    assert captured["image_url"] == "http://localhost:12000/upload/character/pic/abc.png"


def test_absolute_url_passes_through(monkeypatch):
    captured = _install(monkeypatch, "https://cdn.example.com/img/main.png")

    result = _call()

    assert result["success"] is True
    assert captured["image_url"] == "https://cdn.example.com/img/main.png"


def test_https_enabled_prefers_https_host(monkeypatch):
    captured = _install(monkeypatch, "/upload/character/pic/abc.png",
                        https_enabled=True, https_host="https://zjt.example.cn")

    result = _call()

    assert result["success"] is True
    assert captured["image_url"] == "https://zjt.example.cn/upload/character/pic/abc.png"


def test_empty_main_image_still_skips(monkeypatch):
    captured = _install(monkeypatch, "")

    result = _call()

    assert result["success"] is False
    assert result["skip_reason"] == "no_main_image"
    assert "image_url" not in captured  # 未走到 edit_image
