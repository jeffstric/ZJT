"""数字人生成默认模型必须为 wan2.2 的回归测试 + 前端事件分类修复的回归测试。

背景：
1. 2026-09-30 曾把 generate_digital_human 默认模型切到 MiniMax H3，当日确认音频语义
   不匹配后切回 wan2.2：wan2.2 的 audio_url 是「参考音频」（提取音色，口播内容由
   text 驱动）；H3/LTX2.3 等的 audio_url 是「驱动说话的音频」（音频本身即最终声音）。
   本链路传入的音频是按口播文本合成的通用参考音频，只有 wan2.2 的语义匹配
   （事故会话 10eb0496）。
2. pm_agent 曾把 digital-human-creator 的 project_ids 推成 image_task_submitted，
   前端按图片轮询数字人视频任务，完成后拿不到图片 URL，误报"图片生成失败，
   请稍后重试"，视频实际已生成成功但从未展示（事故会话 5847bc38）。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from script_writer_core import mcp_tool


def _make_config(config_id, name, enabled=True, hidden=False, power=0):
    return SimpleNamespace(
        id=config_id,
        name=name,
        enabled=enabled,
        hidden=hidden,
        get_computing_power=lambda: power,
    )


WAN22 = _make_config(13, "wan2.2 数字人", power=12)
H3 = _make_config(35, "MiniMax H3 数字人")


def _run_generate_digital_human(monkeypatch, configs):
    monkeypatch.setattr(
        "config.unified_config.UnifiedConfigRegistry.get_by_category",
        classmethod(lambda cls, category: configs),
    )
    monkeypatch.setattr(
        mcp_tool, "get_config",
        lambda: {"server": {"comfyui_base_url_inner": "http://localhost:9003"}},
    )

    response = MagicMock()
    response.json.return_value = {"success": True, "project_id": 12550}
    response.raise_for_status.return_value = None
    with patch.object(mcp_tool.httpx, "post", return_value=response) as mock_post:
        result = mcp_tool.generate_digital_human(
            user_id="2",
            world_id="marketing",
            auth_token="token",
            image_url="http://zjt-dev.perseids.cn/upload/marketing/pic/x.png",
            text="我是你的数字人分身",
            audio_url="http://zjt-dev.perseids.cn/upload/marketing/audio/y.wav",
            aspect_ratio="9:16",
        )
    return result, mock_post


def test_generate_digital_human_defaults_to_wan22(monkeypatch):
    """数字人生成必须默认选 wan2.2（音频=参考音频语义），并把 task_id=13 透传给后端"""
    result, mock_post = _run_generate_digital_human(monkeypatch, [WAN22, H3])

    assert result["success"] is True
    assert result["model_used"] == "wan2.2 数字人"
    assert result["project_ids"] == ["12550"]
    # 后端按 task_id 建对应类型任务，必须与 model_used 一致
    assert mock_post.call_args.kwargs["data"]["task_id"] == "13"
    assert result["computing_power_required"] == 12


def test_generate_digital_human_falls_back_when_wan22_disabled(monkeypatch):
    """wan2.2 未启用时回退分类下第一个启用模型（保持可用性）"""
    wan_disabled = _make_config(13, "wan2.2 数字人", enabled=False)
    h3 = _make_config(35, "MiniMax H3 数字人")

    result, mock_post = _run_generate_digital_human(monkeypatch, [wan_disabled, h3])

    assert result["success"] is True
    assert result["model_used"] == "MiniMax H3 数字人"
    assert mock_post.call_args.kwargs["data"]["task_id"] == "35"


def test_generate_digital_human_no_enabled_configs(monkeypatch):
    configs = [_make_config(13, "wan2.2 数字人", enabled=False),
               _make_config(35, "MiniMax H3 数字人", enabled=False)]
    monkeypatch.setattr(
        "config.unified_config.UnifiedConfigRegistry.get_by_category",
        classmethod(lambda cls, category: configs),
    )
    monkeypatch.setattr(
        mcp_tool, "get_config",
        lambda: {"server": {"comfyui_base_url_inner": "http://localhost:9003"}},
    )

    result = mcp_tool.generate_digital_human(
        user_id="2", world_id="marketing", auth_token="token",
        image_url="http://x/a.png", text="hi", audio_url="http://x/a.wav",
    )

    assert result["success"] is False
    assert "未找到启用" in result["error"]


def test_resolve_generation_task_event_classifies_digital_human_as_video():
    """digital-human-creator 的数字人视频必须推 video_task_submitted（事故修复点）"""
    from script_writer_core.agents.pm_agent import PMAgent

    pm = PMAgent.__new__(PMAgent)

    event, message = pm._resolve_generation_task_event("digital-human-creator", 1)
    assert event == "video_task_submitted"
    assert "视频" in message

    event, _ = pm._resolve_generation_task_event("marketing-video", 2)
    assert event == "video_task_submitted"

    event, _ = pm._resolve_generation_task_event("article-to-video", 1)
    assert event == "video_task_submitted"

    event, message = pm._resolve_generation_task_event("marketing-image", 3)
    assert event == "image_task_submitted"
    assert "图片" in message
