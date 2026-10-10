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


def _run_generate_digital_human(monkeypatch, configs, image_url=None):
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
            image_url=image_url or "http://zjt-dev.perseids.cn/upload/marketing/pic/x.png",
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


# ============ image_url 解析：LLM 臆造路径防御（事故会话 3c746a8d） ============

REAL_CACHE_URL = "/upload/cache/2026-09-30/12555_20260930110102_7f3a8213.png"


def _fake_exists_factory(existing_suffixes):
    """构造 os.path.exists 桩：路径归一化（统一斜杠、去前导斜杠）后，
    以下列后缀之一结尾时返回 True。归一化是必须的——实现对本地路径做
    os.path.join(project_root, ...) 后在 Windows 下是混合分隔符绝对路径，
    直接 endswith('/upload/...') 永远匹配不上（存量失败根因）。"""
    def norm(s):
        return str(s).replace('\\', '/').lstrip('/')
    targets = [norm(s) for s in existing_suffixes]
    def fake(p):
        p = norm(p)
        return any(p.endswith(t) for t in targets)
    return fake


def test_fabricated_local_path_auto_resolved_via_project_lookup(monkeypatch):
    """臆造的本地路径（/upload/project/12555.png，文件不存在）必须自动纠正为
    ai_tools.result_url 的真实图片地址，而不是放行后让任务在驱动层失败"""
    monkeypatch.setattr("os.path.exists", _fake_exists_factory([REAL_CACHE_URL]))
    record = SimpleNamespace(result_url=REAL_CACHE_URL)

    with patch("model.ai_tools.AIToolsModel.get_by_id", return_value=record) as mock_get:
        result, mock_post = _run_generate_digital_human(
            monkeypatch, [WAN22], image_url="/upload/project/12555.png")

    assert result["success"] is True
    assert mock_post.call_args.kwargs["data"]["image_url"] == REAL_CACHE_URL
    mock_get.assert_called_once_with(12555)


def test_fabricated_local_path_unresolvable_rejected(monkeypatch):
    """臆造路径且查库解析不到时，必须立刻报错并引导用 check_image_status，
    不得提交注定失败的任务"""
    monkeypatch.setattr("os.path.exists", _fake_exists_factory([]))

    with patch("model.ai_tools.AIToolsModel.get_by_id", return_value=None):
        result, _ = _run_generate_digital_human(
            monkeypatch, [WAN22], image_url="/upload/project/12555.png")

    assert result["success"] is False
    assert "check_image_status" in result["error"]
    assert "不存在" in result["error"]


def test_existing_local_path_passes_through_without_lookup(monkeypatch):
    """真实存在的本地路径直接通过，不触发查库纠正"""
    monkeypatch.setattr("os.path.exists", _fake_exists_factory([REAL_CACHE_URL]))

    with patch("model.ai_tools.AIToolsModel.get_by_id") as mock_get:
        result, mock_post = _run_generate_digital_human(
            monkeypatch, [WAN22], image_url=REAL_CACHE_URL)

    assert result["success"] is True
    assert mock_post.call_args.kwargs["data"]["image_url"] == REAL_CACHE_URL
    mock_get.assert_not_called()


def test_http_url_passes_through_without_local_check(monkeypatch):
    """公网 URL 不做本地存在性检查（回归：保持原有直通行为）"""
    monkeypatch.setattr("os.path.exists", _fake_exists_factory([]))

    with patch("model.ai_tools.AIToolsModel.get_by_id") as mock_get:
        result, mock_post = _run_generate_digital_human(
            monkeypatch, [WAN22],
            image_url="http://zjt-dev.perseids.cn/upload/marketing/pic/a.png")

    assert result["success"] is True
    assert mock_post.call_args.kwargs["data"]["image_url"] == \
        "http://zjt-dev.perseids.cn/upload/marketing/pic/a.png"
    mock_get.assert_not_called()


def test_descriptive_reference_rejected_with_guidance(monkeypatch):
    """描述性引用（"project_id:12555 的图"）解析失败时报错引导拿真实 URL"""
    with patch("model.ai_tools.AIToolsModel.get_by_id", return_value=None):
        result, _ = _run_generate_digital_human(
            monkeypatch, [WAN22], image_url="project_id:12555 的图")

    assert result["success"] is False
    assert "check_image_status" in result["error"]

def test_fallback_skips_ltx2_3_which_uses_v2_endpoint(monkeypatch):
    """回退不得选中 /api/digital-human 不接受的 LTX2.3(32)（走 v2 端点，提交必 400），
    即便它排在分类第一位；应跳过它选 H3(35)。"""
    wan_disabled = _make_config(13, "wan2.2 数字人", enabled=False)
    ltx = _make_config(32, "LTX2.3 数字人")
    h3 = _make_config(35, "MiniMax H3 数字人")

    result, mock_post = _run_generate_digital_human(monkeypatch, [ltx, wan_disabled, h3])

    assert result["success"] is True
    assert result["model_used"] == "MiniMax H3 数字人"
    assert mock_post.call_args.kwargs["data"]["task_id"] == "35"


def test_fallback_rejects_when_only_v2_models_enabled(monkeypatch):
    """wan2.2 与 H3 均未启用、只有 LTX2.3 时应明确报错，而不是提交一个必 400 的任务。"""
    wan_disabled = _make_config(13, "wan2.2 数字人", enabled=False)
    ltx = _make_config(32, "LTX2.3 数字人")
    h3_disabled = _make_config(35, "MiniMax H3 数字人", enabled=False)

    result, mock_post = _run_generate_digital_human(monkeypatch, [ltx, wan_disabled, h3_disabled])

    assert result["success"] is False
    assert "启用" in result["error"]
    mock_post.assert_not_called()

def test_year_in_path_never_triggers_project_lookup(monkeypatch):
    """路径中的年份/序号（/upload/cache/2026/abc.png 的 2026）不得被当成
    project_id 查库——ai_tools 早有同 id 记录时会静默换成无关图片（#5）。"""
    monkeypatch.setattr("os.path.exists", _fake_exists_factory([]))

    with patch("model.ai_tools.AIToolsModel.get_by_id") as mock_get:
        result, _ = _run_generate_digital_human(
            monkeypatch, [WAN22], image_url="/upload/cache/2026/abc.png")

    assert result["success"] is False
    assert "不存在" in result["error"]
    mock_get.assert_not_called()


def test_video_result_record_not_used_as_image(monkeypatch):
    """查库命中但 result_url 是视频（.mp4）时拒绝换图，报错引导重取真实图片 URL。"""
    monkeypatch.setattr("os.path.exists", _fake_exists_factory([]))
    video_record = SimpleNamespace(result_url="/upload/cache/2026-09-30/888_x.mp4")

    with patch("model.ai_tools.AIToolsModel.get_by_id", return_value=video_record):
        result, _ = _run_generate_digital_human(
            monkeypatch, [WAN22], image_url="/upload/project/888.png")

    assert result["success"] is False
    assert "check_image_status" in result["error"]


def test_descriptive_reference_resolved_via_directed_pattern(monkeypatch):
    """描述性引用 "project_id:12555 的图" 按定向模式提取查库纠正。"""
    monkeypatch.setattr("os.path.exists", _fake_exists_factory([REAL_CACHE_URL]))
    record = SimpleNamespace(result_url=REAL_CACHE_URL)

    with patch("model.ai_tools.AIToolsModel.get_by_id", return_value=record) as mock_get:
        result, mock_post = _run_generate_digital_human(
            monkeypatch, [WAN22], image_url="project_id:12555 的生成图")

    assert result["success"] is True
    assert mock_post.call_args.kwargs["data"]["image_url"] == REAL_CACHE_URL
    mock_get.assert_called_once_with(12555)
