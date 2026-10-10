"""_handle_tool_calls 返回本轮工具结果 → 状态轮询豁免在生产真实生效的回归测试。

事故（e84112f9 修复未生效）：主循环用 `self.outputs[-len(tool_calls):]` 取本轮
结果做进展检测，但 outputs 只在 JSON 参数解析失败分支 append，成功结果从不
进入 → 切片恒为空 → _is_status_poll_round 因长度不等恒 False，轮询类任务
超过 max_consecutive_no_progress 轮仍被误判死循环（原事故 3d07080b 可复现）。
单测此前绕过 _handle_tool_calls 直接喂伪造结果，故未拦截。

修复：_handle_tool_calls 返回 batch_results（与 tool_calls 一一对应），
主循环消费返回值。本文件走真实 _handle_tool_calls 调用链。
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from script_writer_core.agents.expert_agent import ExpertAgent, LoopState


class _FakeToolExecutor:
    """记录调用并返回预置结果（鸭子类型，execute_tool 签名与 ToolExecutor 一致）"""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def execute_tool(self, tool_name, tool_args, user_id=None, world_id=None,
                     auth_token=None, model=None, vendor_id=None, model_id=None,
                     language=None):
        self.calls.append((tool_name, tool_args))
        return self.results.pop(0)


def _make_agent(executor) -> ExpertAgent:
    """绕过重量级 __init__，构造 _handle_tool_calls / _check_progress 依赖的属性"""
    agent = ExpertAgent.__new__(ExpertAgent)
    agent.agent_id = "test-expert"
    agent.task_manager = None
    agent.task_id = None
    agent.user_id = "1"
    agent.world_id = "1"
    agent.auth_token = "t"
    agent.model = "m"
    agent.vendor_id = None
    agent.model_id = None
    agent.allowed_tools = ["check_reference_audio_status", "get_task_status"]
    agent.tool_executor = executor
    agent.power_confirm_enabled = False
    agent.conversation_history = []
    agent._conversation_recorder = None
    agent._session_id = None
    agent.outputs = []
    agent.tool_calls_made = []
    agent.pending_project_ids = []
    agent.pending_computing_power = 0
    agent.max_consecutive_no_progress = 3
    agent.max_consecutive_errors = 3
    agent.max_total_errors = 7
    agent.max_status_poll_rounds = 15
    return agent


def _poll_message(args_json='{"task_id": "627"}'):
    return SimpleNamespace(
        tool_calls=[SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="check_reference_audio_status",
                                     arguments=args_json),
        )]
    )


POLL_SIG = "check_reference_audio_status(task_id=627)"
POLL_NAMES = ["check_reference_audio_status"]


def test_handle_tool_calls_returns_real_batch_results():
    """返回值必须是本轮真实工具结果（修复前：主循环切片取到的是空列表）"""
    executor = _FakeToolExecutor([{"success": True, "status": "processing", "task_id": "627"}])
    agent = _make_agent(executor)

    batch = agent._handle_tool_calls(_poll_message())

    assert batch == [{"success": True, "status": "processing", "task_id": "627"}]
    # 成功结果不再写入 self.outputs（该列表仅供落盘调试，语义保持不变）
    assert agent.outputs == []


def test_full_chain_poll_rounds_exempt_from_loop_guard():
    """真实调用链：连续 5 轮 processing 轮询不被死循环检测误杀（修复前第 4 轮触发）"""
    agent = _make_agent(_FakeToolExecutor(
        [{"success": True, "status": "processing", "task_id": "627"}] * 5))
    state = LoopState()

    for _ in range(5):
        batch = agent._handle_tool_calls(_poll_message())
        should_stop, reason = agent._check_progress(state, POLL_SIG, batch, POLL_NAMES)
        assert not should_stop, reason

    assert state.consecutive_poll_rounds == 5
    assert state.consecutive_no_progress == 0


def test_full_chain_retrying_and_scheduled_are_in_progress():
    """状态机中间态 retrying / scheduled 也算进行中（白名单补齐，防误杀）"""
    for status in ("retrying", "scheduled"):
        agent = _make_agent(_FakeToolExecutor([{"success": True, "status": status}]))
        state = LoopState()
        batch = agent._handle_tool_calls(_poll_message())
        should_stop, reason = agent._check_progress(state, POLL_SIG, batch, POLL_NAMES)
        assert not should_stop, f"{status}: {reason}"
        assert state.consecutive_poll_rounds == 1


def test_parse_error_round_counted_once_not_sticky():
    """JSON 参数解析失败轮：错误计入当轮 batch_results；下一轮成功后
    consecutive_errors 复位（修复前残留 outputs 会污染后续每轮切片）"""
    agent = _make_agent(_FakeToolExecutor(
        [{"success": True, "status": "processing", "task_id": "627"}] * 2))
    state = LoopState()

    # 第 1 轮：参数非法 → 解析失败分支
    batch = agent._handle_tool_calls(_poll_message(args_json='{"task_id": broken'))
    assert batch and isinstance(batch[0], dict) and batch[0].get("error")
    agent._check_progress(state, POLL_SIG, batch, POLL_NAMES)
    assert state.consecutive_errors == 1

    # 第 2 轮：正常轮询成功 → 错误计数复位，不残留
    batch = agent._handle_tool_calls(_poll_message())
    agent._check_progress(state, POLL_SIG, batch, POLL_NAMES)
    assert state.consecutive_errors == 0
