"""单次任务算力消耗上限（Power Budget）护栏。

用户对一次任务（从发送消息到任务结束）允许消耗的算力上限：

- 计量：任务启动时（PMAgent.execute）快照余额 start_balance，PM/专家循环每轮
  迭代用最新余额折算 consumed = start_balance - current。LLM token 计费与
  生成工具扣费都走同一余额，天然全部计入；中途充值使余额高于快照时自动重置
  快照（视为新预算起点）。
- 超限：抛 PowerBudgetExhaustedError（InsufficientComputingPowerError 子类），
  复用现有「算力不足」逐层停止链路：专家循环 → PM 循环捕获并向用户推送停止
  消息 → 任务结束。比较的是未授权消耗（consumed - authorized）：用户刚确认
  或已同意过单价的生成、以及剧本链路直接放行的生成，其实扣算力记入 authorized，
  不拿去和上限比较。会话与产出保留，充值或调高上限后发送新消息即开启新任务继续。
- ask_user 入口在超限后立即返回 ask_disabled，不再进入 5 分钟等待——掐断
  无人应答时「提问→300s 超时→LLM 重试→再提问」的空转扣费循环
  （docs/backend/incidents/2026-09-01、2026-09-26）。
- 上限解析：user_preferences.power_budget（用户级）→ 动态配置
  agent.power_budget_default → 常量 AGENT_POWER_BUDGET_DEFAULT。0 表示不限制。
  查询失败一律 fail-open（本次任务不启用上限），不得因护栏故障阻断任务。
"""

import logging
from typing import Any, Optional

from config.constant import AGENT_POWER_BUDGET_DEFAULT, PREF_WORLD_ID_GLOBAL
from script_writer_core.agents.base_agent import (
    PowerBudgetExhaustedError,
    check_computing_power_sync,
)
from script_writer_core.agents.power_confirm import (
    _coerce_non_negative_int,
    _try_parse_non_negative_int,
)

logger = logging.getLogger(__name__)

# check_computing_power_sync 在无 token/查询失败时返回的 sentinel，
# 不代表真实余额，观察时必须忽略
_BALANCE_SENTINEL = 900000


def query_balance(auth_token: str) -> Optional[int]:
    """查询当前算力余额；无 token 或查询失败返回 None（不抛异常）。"""
    if not auth_token:
        return None
    try:
        from perseids_server.client import make_perseids_request

        success, _message, response_data = make_perseids_request(
            endpoint='user/check_computing_power',
            method='GET',
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        if success and isinstance(response_data, dict):
            return int(response_data.get('computing_power') or 0)
    except Exception as e:
        logger.warning("查询算力余额失败: %s", e)
    return None


def resolve_user_power_budget(user_id: Optional[str]) -> tuple[int, bool]:
    """解析用户生效的单次任务算力上限。

    Returns:
        (limit, is_custom)。limit=0 表示不限制。
    """
    default = _resolve_platform_default()
    if not user_id:
        return default, False

    try:
        from model.user_preferences import PREF_TYPE_POWER_BUDGET, UserPreferencesModel

        pref = UserPreferencesModel.get(str(user_id), PREF_WORLD_ID_GLOBAL, PREF_TYPE_POWER_BUDGET)
    except Exception as e:
        logger.warning("读取用户算力上限偏好失败，回退平台默认: user_id=%s err=%s", user_id, e)
        return default, False

    if not pref or pref.config_value is None:
        return default, False

    value = pref.get_value()
    if isinstance(value, dict):
        value = value.get("limit")
    parsed = _try_parse_non_negative_int(value)
    if parsed is None:
        logger.warning("用户算力上限偏好非法，回退平台默认: user_id=%s value=%r", user_id, value)
        return default, False
    return parsed, True


def validate_power_budget_limit(raw: Any) -> int:
    """校验用户提交的上限，非法则抛 ValueError。0 表示不限制。"""
    parsed = _try_parse_non_negative_int(raw)
    if parsed is None:
        raise ValueError("算力上限必须是非负整数（0 表示不限制）")
    return parsed


def _resolve_platform_default() -> int:
    """平台默认上限：动态配置 agent.power_budget_default → 常量兜底。"""
    try:
        from config.config_util import get_dynamic_config_value

        return _coerce_non_negative_int(
            get_dynamic_config_value(
                "agent", "power_budget_default", default=AGENT_POWER_BUDGET_DEFAULT
            ),
            AGENT_POWER_BUDGET_DEFAULT,
        )
    except Exception as e:
        logger.warning("读取平台算力上限默认值失败，使用常量兜底: %s", e)
        return AGENT_POWER_BUDGET_DEFAULT


class PowerBudget:
    """一次任务的算力预算：快照起点余额，观察最新余额并判断是否超限。"""

    def __init__(self, limit: int, start_balance: Optional[int], agent_id: str = "power-budget"):
        self.limit = max(0, int(limit or 0))
        self.start_balance = start_balance
        self.last_balance = start_balance
        self.authorized = 0
        self.agent_id = agent_id

    @property
    def enabled(self) -> bool:
        """limit=0（不限制）或没有余额快照时不启用。"""
        return self.limit > 0 and self.start_balance is not None

    @classmethod
    def create_for_task(cls, task: Any, agent_id: str = "power-budget") -> Optional["PowerBudget"]:
        """为一次任务创建预算；limit=0 或快照失败返回 None（不启用，fail-open）。"""
        try:
            limit, _is_custom = resolve_user_power_budget(
                str(getattr(task, "user_id", "") or "")
            )
            start_balance = query_balance(getattr(task, "auth_token", "") or "")
        except Exception as e:
            logger.warning("创建算力预算失败，本次任务不启用上限: %s", e)
            return None
        budget = cls(limit, start_balance, agent_id=agent_id)
        if not budget.enabled:
            logger.info(
                "%s: 单次任务算力上限未启用 (limit=%s, start_balance=%s)",
                agent_id, limit, start_balance,
            )
            return None
        return budget

    def observe(self, balance: Optional[int]) -> None:
        """记录循环每轮迭代观察到的最新余额；余额升高（充值）时重置快照。"""
        if not self.enabled:
            return
        if balance is None or not isinstance(balance, int) or balance >= _BALANCE_SENTINEL:
            return
        if balance > self.start_balance:
            logger.info(
                "%s: 余额由 %s 升至 %s，重置算力预算快照", self.agent_id, self.start_balance, balance
            )
            self.start_balance = balance
            self.authorized = 0
        self.last_balance = balance

    def consumed(self) -> int:
        if not self.enabled or self.last_balance is None:
            return 0
        return max(0, self.start_balance - self.last_balance)

    def authorize(self, cost: int) -> None:
        """把用户已点头、或剧本链路已放行的生成实扣算力划出未授权消耗。"""
        if not self.enabled or isinstance(cost, bool):
            return
        try:
            amount = int(cost)
        except (TypeError, ValueError):
            return
        if amount <= 0:
            return
        self.authorized += amount

    def unauthorized_consumed(self) -> int:
        return max(0, self.consumed() - self.authorized)

    def check(self, balance: Optional[int] = None) -> None:
        """超限抛 PowerBudgetExhaustedError；未启用时静默放行。

        比较未授权消耗（总消耗减去已授权生成），不是余额总下降。

        Args:
            balance: 最新余额。传 None 时用最近一次 observe 的值（如 ask_user 入口）。
        """
        if not self.enabled:
            return
        if balance is not None:
            self.observe(balance)
        unauthorized = self.unauthorized_consumed()
        if unauthorized >= self.limit:
            logger.warning(
                "%s: 单次任务算力上限触发 - 未授权消耗 %s，总消耗 %s，已授权 %s，上限 %s",
                self.agent_id, unauthorized, self.consumed(), self.authorized, self.limit,
            )
            raise PowerBudgetExhaustedError(consumed=unauthorized, limit=self.limit)


def observe_and_check(budget: Optional[PowerBudget], auth_token: str, agent_id: str) -> None:
    """循环迭代处的统一核对入口：顺带复用 check_computing_power_sync 的返回余额。

    budget 为 None（未启用）时等价于只做原有的余额充足性检查。
    """
    current_power = check_computing_power_sync(auth_token, agent_id)
    if budget is not None:
        budget.observe(current_power)
        budget.check()
