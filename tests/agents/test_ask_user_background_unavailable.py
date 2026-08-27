"""ask_user 在无会话环境（后台任务）下的行为测试。

后台生成任务（接口模块智能体）不配置 task_manager/task_id，
ask_user 必须返回指导性错误并禁用重试，而不是让 LLM 反复尝试提问。
"""

from script_writer_core.agents.ask_user_mixin import AskUserMixin


class _BackgroundAgent(AskUserMixin):
    agent_id = "expert_generate-user-api-module"

    def __init__(self):
        # 后台任务：无 task_manager / task_id
        self.task_manager = None
        self.task_id = None
        self._ask_fail_count = 0


def test_ask_user_reports_unavailable_with_guidance():
    agent = _BackgroundAgent()
    result = agent._handle_ask_user({"question": "是否接入图片编辑能力？", "options": ["是", "否"]})

    assert result.get("user_input") is None
    assert result.get("ask_disabled") is True
    error = result.get("error", "")
    assert "不可用" in error
    # 指导性文案：要求停止提问并把问题写入总结，而非重试
    assert "停止" in error
    assert "总结" in error
