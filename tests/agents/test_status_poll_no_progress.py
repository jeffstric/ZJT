"""状态轮询死循环豁免 + check 工具内置等待的回归测试。

背景（事故：会话 3d07080b-590a-4f8b-8bae-317a32606271）：数字人专家每 3~4 秒
轮询一次 check_reference_audio_status，连续 3 次相同签名被 ExpertAgent._check_progress
误判死循环并优雅关闭；RunningHub TTS 44 秒后才完成，generate_digital_human 从未提交。

修复双保险：
1. ExpertAgent._check_progress 豁免"纯状态轮询（结果仍进行中）"轮次，由独立上限约束
2. check_reference_audio_status / check_image_status 内置有界等待，拉长单次轮询间隔
"""
from types import SimpleNamespace
from unittest.mock import patch

from script_writer_core.agents.expert_agent import ExpertAgent, LoopState


def _make_agent(max_no_progress: int = 3, max_poll_rounds: int = 15) -> ExpertAgent:
    """绕过重量级 __init__，只构造 _check_progress 依赖的属性"""
    agent = ExpertAgent.__new__(ExpertAgent)
    agent.max_consecutive_no_progress = max_no_progress
    agent.max_consecutive_errors = 3
    agent.max_total_errors = 7
    agent.max_status_poll_rounds = max_poll_rounds
    return agent


POLL_SIG = "check_reference_audio_status(task_id=627)"
POLL_NAMES = ["check_reference_audio_status"]
POLL_PROCESSING_RESULTS = [{"success": True, "status": "processing", "task_id": "627"}]


# ============ _check_progress 状态轮询豁免 ============

def test_poll_processing_rounds_are_exempt_from_loop_guard():
    """轮询进行中的任务超过 max_consecutive_no_progress 轮也不应触发死循环（事故场景）"""
    agent = _make_agent(max_no_progress=3)
    state = LoopState()

    for _ in range(5):  # 原逻辑第 3 轮即触发
        should_stop, reason = agent._check_progress(
            state, POLL_SIG, POLL_PROCESSING_RESULTS, POLL_NAMES)
        assert not should_stop, reason

    assert state.consecutive_poll_rounds == 5
    assert state.consecutive_no_progress == 0


def test_poll_exceeds_max_rounds_stops():
    """纯轮询轮达到独立上限仍要停止（防任务异常卡住时无限轮询）"""
    agent = _make_agent(max_poll_rounds=15)
    state = LoopState()

    for _ in range(14):
        should_stop, _ = agent._check_progress(
            state, POLL_SIG, POLL_PROCESSING_RESULTS, POLL_NAMES)
        assert not should_stop

    should_stop, reason = agent._check_progress(
        state, POLL_SIG, POLL_PROCESSING_RESULTS, POLL_NAMES)
    assert should_stop
    assert "轮询" in reason


def test_duplicate_non_poll_tool_still_stops():
    """回归：普通工具连续相同签名仍按原阈值触发死循环保护"""
    agent = _make_agent(max_no_progress=3)
    state = LoopState()
    sig = "generate_text_to_image(prompt=xx)"
    names = ["generate_text_to_image"]
    results = [{"success": True, "project_ids": ["p1"]}]

    # 阈值 3 指连续 3 次"重复"签名：首次不计，第 4 次调用触发
    for _ in range(3):
        should_stop, _ = agent._check_progress(state, sig, results, names)
        assert not should_stop
    should_stop, reason = agent._check_progress(state, sig, results, names)
    assert should_stop
    assert "死循环" in reason


def test_poll_terminal_result_not_exempt():
    """轮询返回终态（completed）不属合法等待，重复查询仍按原逻辑累计"""
    agent = _make_agent(max_no_progress=3)
    state = LoopState()
    results = [{"success": True, "status": "completed", "audio_url": "/x.mp3"}]

    for _ in range(3):
        should_stop, _ = agent._check_progress(state, POLL_SIG, results, POLL_NAMES)
        assert not should_stop
    should_stop, _ = agent._check_progress(state, POLL_SIG, results, POLL_NAMES)
    assert should_stop
    assert state.consecutive_poll_rounds == 0


def test_poll_failed_result_counts_as_error():
    """轮询返回 failed（带 error）不豁免，且计入错误统计"""
    agent = _make_agent()
    state = LoopState()
    results = [{"success": False, "status": "failed", "error": "boom"}]

    agent._check_progress(state, POLL_SIG, results, POLL_NAMES)

    assert state.consecutive_poll_rounds == 0
    assert state.consecutive_errors == 1


def test_mixed_tools_round_not_exempt():
    """轮询工具 + 非轮询工具混合的一轮不豁免"""
    agent = _make_agent()
    names = ["check_reference_audio_status", "generate_text_to_image"]
    results = [
        {"success": True, "status": "processing", "task_id": "627"},
        {"success": True, "project_ids": ["p1"]},
    ]

    assert not agent._is_status_poll_round(names, results)


# ============ check_reference_audio_status 内置等待 ============

def _audio_task(status, result_url=None, error_message=None):
    from model import AsyncTaskStatus
    return SimpleNamespace(
        status=status,
        result_url=result_url,
        error_message=error_message,
        external_task_id="rh-2105105573036118018",
    )


def test_check_audio_status_waits_until_completed(monkeypatch):
    """首次查询 processing → 等待后重查 completed：单次调用内拿到 audio_url"""
    from script_writer_core import mcp_tool
    from model import AsyncTaskStatus

    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(mcp_tool, "AGENT_CHECK_TOOL_WAIT_SECONDS", 30)
    monkeypatch.setattr(mcp_tool, "AGENT_CHECK_TOOL_POLL_INTERVAL_SECONDS", 5)

    processing = _audio_task(AsyncTaskStatus.PROCESSING)
    completed = _audio_task(AsyncTaskStatus.COMPLETED, result_url="/upload/voice/x.mp3")

    with patch("model.AsyncTasksModel.get_by_id", side_effect=[processing, completed]):
        result = mcp_tool.check_reference_audio_status(
            user_id="2", world_id="1", auth_token="t", task_id="627")

    assert result["status"] == "completed"
    assert result["success"] is True
    assert result["audio_url"] == "/upload/voice/x.mp3"
    assert result["waited_seconds"] == 5
    assert sleeps == [5]


def test_check_audio_status_timeout_returns_processing_with_guidance(monkeypatch):
    """超过等待上限仍 processing：返回 processing + 引导文案，不报错"""
    from script_writer_core import mcp_tool
    from model import AsyncTaskStatus

    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(mcp_tool, "AGENT_CHECK_TOOL_WAIT_SECONDS", 6)
    monkeypatch.setattr(mcp_tool, "AGENT_CHECK_TOOL_POLL_INTERVAL_SECONDS", 2)

    processing = _audio_task(AsyncTaskStatus.PROCESSING)

    with patch("model.AsyncTasksModel.get_by_id", return_value=processing):
        result = mcp_tool.check_reference_audio_status(
            user_id="2", world_id="1", auth_token="t", task_id="627")

    assert result["success"] is True
    assert result["status"] == "processing"
    assert result["waited_seconds"] == 6
    assert "再次查询" in result["message"]
    assert len(sleeps) == 3  # 2s * 3 = 6s 上限


def test_check_audio_status_failed_returns_immediately(monkeypatch):
    """首查即 failed：不进入等待，直接返回失败"""
    from script_writer_core import mcp_tool
    from model import AsyncTaskStatus

    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    failed = _audio_task(AsyncTaskStatus.FAILED, error_message="生成失败")

    with patch("model.AsyncTasksModel.get_by_id", return_value=failed):
        result = mcp_tool.check_reference_audio_status(
            user_id="2", world_id="1", auth_token="t", task_id="627")

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"] == "生成失败"
    assert sleeps == []


def test_check_audio_status_not_found_skips_wait(monkeypatch):
    """任务记录不存在：不等待，直接返回 not_found"""
    from script_writer_core import mcp_tool

    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    with patch("model.AsyncTasksModel.get_by_id", return_value=None), \
         patch("model.AsyncTasksModel.get_by_external_task_id", return_value=None):
        result = mcp_tool.check_reference_audio_status(
            user_id="2", world_id="1", auth_token="t", task_id="627")

    assert result["status"] == "not_found"
    assert sleeps == []


# ============ check_image_status 内置等待 ============

def test_check_image_status_waits_until_completed(monkeypatch):
    from script_writer_core import mcp_tool
    from model import GridImageTaskStatus

    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(mcp_tool, "AGENT_CHECK_TOOL_WAIT_SECONDS", 30)
    monkeypatch.setattr(mcp_tool, "AGENT_CHECK_TOOL_POLL_INTERVAL_SECONDS", 5)

    processing = SimpleNamespace(
        status=GridImageTaskStatus.PROCESSING, result_url=None, error_message=None)
    completed = SimpleNamespace(
        status=GridImageTaskStatus.COMPLETED, result_url="/upload/img.png", error_message=None)

    with patch("model.GridImageTasksModel.get_by_task_key",
               side_effect=[processing, completed]):
        result = mcp_tool.check_image_status(
            user_id="2", world_id="1", auth_token="t", project_id="p1")

    assert result["status"] == "completed"
    assert result["image_url"] == "/upload/img.png"
    assert result["waited_seconds"] == 5
    assert sleeps == [5]
