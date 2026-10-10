"""image_to_video force 锁定路径不得做 clone 家族换算（会话 d4b3face 回归）。

事故（2026-09-29 会话 d4b3face-884d-4445-a605-ea994e36dbb3）：用户指定
MiniMax H3 首尾帧（task_type=34）+ 1 张参考图，generate_marketing_video 以
force_task_type=34 调 image_to_video；force 分支曾做 resolve_video_clone_task_config
家族换算（34→37 参考生），换算后的 preferred=37 撞防降级防线（37 != force 34），
被误报「指定视频模型(task_type=34)不可用，已阻止降级」——实际 34 配置 enabled、
非 hidden、实现方可用。Agent 被误导性文案带偏，转告用户"34 不可用"并自行改用 37。

修复：force 分支去掉 clone 换算（force 语义是调用方锁定条目）；clone 换算仅保留
给非 force 的 UI 视频克隆/参考生快照路径。H3 首尾帧驱动对 multi_reference 输入
会自动取参考图[0]作首帧、[1]作尾帧（minimax_h3_runninghub_v1_driver.py:223-229），
marketing 链路的 image_mode 硬编码无需改动。
"""
import os

import pytest

os.environ.setdefault("comfyui_env", "unit")


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"project_ids": ["p-1"]}


@pytest.fixture
def force_flow(monkeypatch):
    """mock image_to_video 的全部外部依赖，捕获提交到 /api/ai-app-run-image 的请求体。

    配置注入必须在 fixture 内做：同进程其他测试（如 marketing fallback）会在模块级
    重写 _config_cache["config_unit.yml"] 且 server 为空，模块级注入会被覆盖。
    """
    from enterprise.tools import video_tools
    from config import config_util
    import enterprise.services.license.runtime as license_runtime
    import script_writer_core.mcp_tool as mcp_tool
    from services.media_generation_preference_service import MediaGenerationPreferenceService

    captured = {"posts": []}

    monkeypatch.setattr(
        config_util, "get_config",
        lambda: {"server": {"comfyui_base_url_inner": "http://127.0.0.1:9003"}},
    )
    monkeypatch.setattr(license_runtime, "require_commercial_license", lambda *a, **k: None)
    monkeypatch.setattr(video_tools, "_validate_real_media_urls", lambda *a, **k: None)
    monkeypatch.setattr(mcp_tool, "_get_video_preferences", lambda uid, wid: {})
    monkeypatch.setattr(
        MediaGenerationPreferenceService, "determine_mode",
        staticmethod(lambda *a, **k: "reference_to_video"),
    )
    monkeypatch.setattr(
        "task.visual_drivers.driver_factory.VideoDriverFactory.get_implementation_for_user",
        lambda tid, uid: "fake_impl",
    )

    def fake_post(url, data=None, headers=None, timeout=None, verify=None):
        captured["posts"].append({"url": url, "data": dict(data or {})})
        return _FakeResponse()

    monkeypatch.setattr(video_tools.httpx, "post", fake_post)
    return captured


def _call(force_task_type):
    from enterprise.tools.video_tools import image_to_video

    return image_to_video(
        "55", "1", "tok",
        prompt="彩铅手绘治愈风格……旁白口播：\u201c一点动静就惊醒\u201d",
        image_urls="/upload/marketing_fetched/20260929/a.png",
        image_mode="multi_reference",
        duration_seconds=10,
        force_task_type=force_task_type,
        force_duration=True,
    )


def test_force_34_submits_34_not_rewritten_to_37(force_flow):
    """事故回归：force 34 必须以 34 提交，不得被 clone 换算篡改成 37 后误报不可用。"""
    result = _call(34)

    assert result.get("success") is True, result
    assert result.get("model_used") == "MiniMax H3"
    assert len(force_flow["posts"]) == 1
    assert force_flow["posts"][0]["data"]["task_id"] == "34"
    assert "已阻止降级" not in str(result)


def test_force_37_still_passes(force_flow):
    """37 在 clone 白名单内，行为不变（换算恒等）。"""
    result = _call(37)

    assert result.get("success") is True, result
    assert force_flow["posts"][0]["data"]["task_id"] == "37"
