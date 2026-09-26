"""ask_user options 归一化测试。

模型偶尔违反工具 schema，把 string 数组写成 {"label": ..., "description": ...}
对象数组（2026-09-26 事故：前端渲染成 [object Object]，用户无法作答，
连续两次 5 分钟超时）。归一化必须兜住对象选项，且在完全不可解析时报错重试。
"""

from script_writer_core.agents.ask_user_mixin import AskUserMixin, _normalize_ask_options


class _FakeVerification:
    def __init__(self):
        self.verification_id = "v-test-1"


class _FakeTaskManager:
    def __init__(self, wait_result):
        self.created = []
        self._wait_result = wait_result

    def create_verification(self, **kwargs):
        self.created.append(kwargs)
        return _FakeVerification()

    def wait_for_verification(self, verification, timeout=300):
        return self._wait_result


class _InteractiveAgent(AskUserMixin):
    agent_id = "expert_story-writer"

    def __init__(self, task_manager):
        self.task_manager = task_manager
        self.task_id = "task-1"
        self._ask_fail_count = 0


def _make_agent(options_raw):
    manager = _FakeTaskManager({"success": True, "user_input": "好"})
    agent = _InteractiveAgent(manager)
    result = agent._handle_ask_user({"question": "Q", "options": options_raw})
    return agent, manager, result


def test_normalize_helper_object_options():
    options = _normalize_ask_options(
        [{"label": "确认连续生成", "description": "逐集创作"},
         {"label": "分批生成", "description": "每批5-10集"}]
    )
    assert options == ["确认连续生成", "分批生成"]


def test_normalize_helper_keeps_strings_and_primitives():
    assert _normalize_ask_options(["科幻", "悬疑"]) == ["科幻", "悬疑"]
    assert _normalize_ask_options([" 科幻 ", ""]) == ["科幻"]
    assert _normalize_ask_options([1, 2.5]) == ["1", "2.5"]
    # 布尔/None/未知结构丢弃
    assert _normalize_ask_options([True, None, {"foo": "bar"}]) == []


def test_normalize_helper_accepts_json_string():
    assert _normalize_ask_options('["甲", "乙"]') == ["甲", "乙"]
    assert _normalize_ask_options('[{"label": "甲"}, "乙"]') == ["甲", "乙"]
    assert _normalize_ask_options("[not json") == []


def test_object_options_stored_as_strings():
    agent, manager, result = _make_agent(
        [{"label": "确认连续生成", "description": "逐集创作"},
         {"label": "分批生成", "description": "每批5-10集"}]
    )
    assert result.get("success") is True
    assert manager.created[0]["options"] == ["确认连续生成", "分批生成"]
    # 返回给会话记录的元数据同样已归一化
    assert result["_verification_meta"]["options"] == ["确认连续生成", "分批生成"]


def test_unparseable_options_return_error_without_verification():
    agent, manager, result = _make_agent([{"foo": "bar"}])
    assert result.get("user_input") is None
    assert "options" in result.get("error", "")
    assert manager.created == []


def test_string_options_flow_unchanged():
    agent, manager, result = _make_agent(["满意，继续", "先暂停"])
    assert result.get("success") is True
    assert manager.created[0]["options"] == ["满意，继续", "先暂停"]
