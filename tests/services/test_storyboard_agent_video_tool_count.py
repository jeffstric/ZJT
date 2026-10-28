"""StoryboardAgentVideoToolExecutor 会话级视频偏好 count 注入回归测试。

背景：界面视频偏好的生成次数 count（clamp 1-4）在 mcp_tool 的 DB 路径有注入
（tests/agents/test_generation_count_pref_injection.py 已测），但会话级
preferences 不走 DB 路径，必须在 wrapper 注入（否则委托层拿不到 count，
生图数量回落默认 1）。另守护 task_id 快照强制覆盖 task_type 的语义。
"""

from unittest.mock import MagicMock

from services.storyboard_agent_video_tool import (
    STANDARD_VIDEO_TOOL_NAMES,
    StoryboardAgentVideoToolExecutor,
)


def _make_executor(preferences):
    delegate = MagicMock()
    delegate.execute_tool.return_value = {"ok": True}
    executor = StoryboardAgentVideoToolExecutor(
        delegate, scene_id=1, video_preferences=preferences
    )
    return executor, delegate


def _run(executor, tool_name="generate_text_to_video", args=None):
    return executor.execute_tool(
        tool_name, dict(args or {}), "u1", "w1", "token", "zh-CN"
    )


def test_count_within_range_injected():
    executor, delegate = _make_executor({"count": 3})
    _run(executor)
    args = delegate.execute_tool.call_args[0][1]
    assert args["count"] == 3


def test_count_above_range_not_injected():
    executor, delegate = _make_executor({"count": 9})
    _run(executor)
    args = delegate.execute_tool.call_args[0][1]
    assert "count" not in args


def test_count_zero_not_injected():
    # 0 表示无效（不限制语义由 DB 层默认承担），wrapper 不写入
    executor, delegate = _make_executor({"count": 0})
    _run(executor)
    args = delegate.execute_tool.call_args[0][1]
    assert "count" not in args


def test_count_string_parsable_injected():
    executor, delegate = _make_executor({"count": "2"})
    _run(executor)
    args = delegate.execute_tool.call_args[0][1]
    assert args["count"] == 2


def test_count_garbage_string_not_injected():
    executor, delegate = _make_executor({"count": "abc"})
    _run(executor)
    args = delegate.execute_tool.call_args[0][1]
    assert "count" not in args


def test_count_missing_leaves_args_untouched():
    executor, delegate = _make_executor({"ratio": "16:9"})
    _run(executor, args={"prompt": "hi"})
    args = delegate.execute_tool.call_args[0][1]
    assert "count" not in args
    assert args["ratio"] == "16:9"
    assert args["prompt"] == "hi"


def test_count_injected_for_both_standard_tools():
    assert STANDARD_VIDEO_TOOL_NAMES == frozenset(
        {"generate_text_to_video", "image_to_video"}
    )
    for tool in STANDARD_VIDEO_TOOL_NAMES:
        executor, delegate = _make_executor({"count": 4})
        _run(executor, tool_name=tool)
        args = delegate.execute_tool.call_args[0][1]
        assert args["count"] == 4


def test_task_id_snapshot_overrides_llm_task_type():
    """快照 task_id 必须覆盖 LLM 传入的 task_type（防 list_video_models 自选漂移）。"""
    executor, delegate = _make_executor({"task_id": "55"})
    _run(executor, args={"task_type": 3})
    args = delegate.execute_tool.call_args[0][1]
    assert args["task_type"] == 55


def test_blank_task_id_keeps_llm_task_type():
    executor, delegate = _make_executor({"task_id": "  "})
    _run(executor, args={"task_type": 3})
    args = delegate.execute_tool.call_args[0][1]
    assert args["task_type"] == 3


def test_invalid_task_id_keeps_llm_task_type():
    executor, delegate = _make_executor({"task_id": "not-a-number"})
    _run(executor, args={"task_type": 3})
    args = delegate.execute_tool.call_args[0][1]
    assert args["task_type"] == 3
