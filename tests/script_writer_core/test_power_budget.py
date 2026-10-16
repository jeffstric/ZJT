"""单次任务算力上限（PowerBudget）行为测试。

覆盖：超限判定、充值重置快照、哨兵值忽略、fail-open、上限解析顺序、
异常链路契约（PowerBudgetExhaustedError 必须是 InsufficientComputingPowerError
子类才能复用 PM/专家循环的既有停止链路），以及 ask_user 超限立即返回。
"""

from types import SimpleNamespace

from script_writer_core.agents.ask_user_mixin import AskUserMixin
from script_writer_core.agents.base_agent import InsufficientComputingPowerError
from script_writer_core.agents import power_budget as pb
from script_writer_core.agents.power_budget import (
    PowerBudget,
    PowerBudgetExhaustedError,
    resolve_user_power_budget,
    validate_power_budget_limit,
)


class _FakePref:
    def __init__(self, config_value):
        self.config_value = config_value

    def get_value(self):
        return self.config_value


def test_exhausted_error_is_insufficient_power_subclass():
    # 链路契约：PM/专家循环与 _execute_tool 的既有 except 必须能兜住预算超限
    err = PowerBudgetExhaustedError(consumed=50, limit=30)
    assert isinstance(err, InsufficientComputingPowerError)
    assert "50" in err.message and "30" in err.message
    assert "继续" in err.message


def test_check_raises_when_consumed_reaches_limit():
    budget = PowerBudget(limit=10, start_balance=100)
    budget.observe(95)
    assert budget.consumed() == 5
    budget.check()  # 未超限，不抛
    budget.observe(90)
    try:
        budget.check()
        raise AssertionError("应当抛出 PowerBudgetExhaustedError")
    except PowerBudgetExhaustedError:
        pass


def test_recharge_resets_baseline():
    # 中途充值使余额高于快照 → 重置快照，视为新预算起点，不误停
    budget = PowerBudget(limit=10, start_balance=100)
    budget.observe(150)
    assert budget.consumed() == 0
    budget.observe(145)
    assert budget.consumed() == 5


def test_sentinel_balance_ignored():
    # check_computing_power_sync 的 999999 sentinel 不代表真实余额，必须忽略
    budget = PowerBudget(limit=10, start_balance=100)
    budget.observe(999999)
    assert budget.consumed() == 0


def test_disabled_when_limit_zero_or_no_snapshot():
    # limit=0 表示不限制；无余额快照时同样不启用（fail-open）
    for budget in (PowerBudget(limit=0, start_balance=100), PowerBudget(limit=10, start_balance=None)):
        budget.observe(0)
        budget.check()  # 不抛
        assert budget.consumed() == 0


def test_authorized_generation_does_not_pause_task():
    # 用户确认过的 303 视频从余额里扣掉，但不算进 200 的未授权上限
    budget = PowerBudget(limit=200, start_balance=1000)
    budget.observe(697)
    budget.authorize(303)
    assert budget.consumed() == 303
    assert budget.unauthorized_consumed() == 0
    budget.check()
    # 之后的 LLM 空转仍计入未授权消耗
    budget.observe(497)
    try:
        budget.check()
        raise AssertionError("未授权消耗达到上限时应当暂停")
    except PowerBudgetExhaustedError as e:
        assert e.consumed == 200
        assert e.limit == 200


def test_recharge_clears_authorized_credit():
    budget = PowerBudget(limit=200, start_balance=1000)
    budget.observe(697)
    budget.authorize(303)
    budget.observe(1500)
    assert budget.consumed() == 0
    assert budget.authorized == 0


def test_check_without_fresh_balance_uses_last_observed():
    # ask_user 入口不主动查询余额，用最近一次 observe 的值判定
    budget = PowerBudget(limit=10, start_balance=100)
    budget.observe(90)
    try:
        budget.check()
        raise AssertionError("应当抛出 PowerBudgetExhaustedError")
    except PowerBudgetExhaustedError:
        pass


def test_validate_power_budget_limit():
    assert validate_power_budget_limit(30) == 30
    assert validate_power_budget_limit("0") == 0
    for bad in (-1, "abc", None, 1.5, True):
        try:
            validate_power_budget_limit(bad)
            raise AssertionError(f"{bad!r} 应当非法")
        except ValueError:
            pass


def test_resolve_user_power_budget_pref_overrides_default(monkeypatch):
    monkeypatch.setattr(
        "model.user_preferences.UserPreferencesModel.get",
        lambda user_id, world_id, pref_type: _FakePref({"limit": 55}),
        raising=False,
    )
    limit, is_custom = resolve_user_power_budget("9")
    assert (limit, is_custom) == (55, True)


def test_resolve_user_power_budget_invalid_pref_falls_back(monkeypatch):
    monkeypatch.setattr(
        "model.user_preferences.UserPreferencesModel.get",
        lambda user_id, world_id, pref_type: _FakePref({"limit": "abc"}),
        raising=False,
    )
    limit, is_custom = resolve_user_power_budget("9")
    assert is_custom is False
    assert limit >= 0


def test_resolve_user_power_budget_no_pref(monkeypatch):
    monkeypatch.setattr(
        "model.user_preferences.UserPreferencesModel.get",
        lambda user_id, world_id, pref_type: None,
        raising=False,
    )
    limit, is_custom = resolve_user_power_budget("9")
    assert is_custom is False
    assert limit >= 0


def test_create_for_task_snapshots_balance(monkeypatch):
    monkeypatch.setattr(pb, "query_balance", lambda token: 500 if token else None)
    task = SimpleNamespace(user_id="9", auth_token="tok")
    budget = PowerBudget.create_for_task(task, agent_id="pm_agent")
    assert budget is not None
    assert budget.start_balance == 500
    assert budget.enabled


def test_create_for_task_fail_open(monkeypatch):
    # 快照失败（无 token）时不启用护栏，不得阻断任务
    monkeypatch.setattr(pb, "query_balance", lambda token: None)
    task = SimpleNamespace(user_id="9", auth_token="")
    assert PowerBudget.create_for_task(task) is None


class _FakeVerification:
    def __init__(self):
        self.verification_id = "v-budget-1"


class _FakeTaskManager:
    def __init__(self):
        self.created = []

    def create_verification(self, **kwargs):
        self.created.append(kwargs)
        return _FakeVerification()

    def wait_for_verification(self, verification, timeout=300):
        return {"success": True, "user_input": "好"}


class _BudgetAgent(AskUserMixin):
    agent_id = "expert_story-writer"

    def __init__(self, budget):
        self.task_manager = _FakeTaskManager()
        self.task_id = "task-1"
        self._ask_fail_count = 0
        self.power_budget = budget


def test_ask_user_disabled_immediately_when_budget_exhausted():
    # 超限后 ask_user 必须立即返回，不创建提问、不进入 5 分钟等待
    budget = PowerBudget(limit=10, start_balance=100)
    budget.observe(90)
    agent = _BudgetAgent(budget)
    result = agent._handle_ask_user({"question": "Q", "options": ["A", "B"]})

    assert result.get("user_input") is None
    assert result.get("ask_disabled") is True
    assert "算力上限" in result.get("error", "")
    assert agent.task_manager.created == []


def test_ask_user_normal_when_budget_not_exhausted():
    budget = PowerBudget(limit=10, start_balance=100)
    budget.observe(99)
    agent = _BudgetAgent(budget)
    result = agent._handle_ask_user({"question": "Q", "options": ["A", "B"]})

    assert result.get("success") is True
    assert len(agent.task_manager.created) == 1


def test_ask_user_unaffected_without_budget():
    # 未设置预算（如后台任务）时行为与原来一致
    agent = _BudgetAgent(None)
    result = agent._handle_ask_user({"question": "Q", "options": ["A", "B"]})
    assert result.get("success") is True
