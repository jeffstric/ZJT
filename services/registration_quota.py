"""
注册人数配额公共门面。

社区版默认限制注册用户总数上限（COMMUNITY_MAX_REGISTERED_USERS），
不加载、不执行任何商业配额逻辑。商业版在启动时通过 ``register_provider``
注入放行实现（见 enterprise/__init__.py）。

并发说明（社区版）：
本门面对注册人数为"软上限"——``check_allowed`` 仅做一次计数快照判断，
不串行化"计数 + 落库"。并发注册时多个请求可能读到相同计数同时放行，
导致实际人数略超上限。社区版**不**保证注册人数严格不超过上限
（注册仅影响用户数计数，不涉及权限/支付，超限无安全风险）。如需严格
上限，请购买商业版（Provider 注入后不再计数）。
此前曾用 ``threading.Lock`` 做进程内串行化，但生产环境以 gunicorn
多 worker（多进程）部署时进程间不互斥，进程锁形同虚设反而造成"已解决
并发"的错觉，故已移除。

计数来源由调用方传入（auth_service 使用其模块级 UsersModel 引用），
本模块不直接访问数据库，便于测试 mock 与复用。
"""
import logging
from typing import Protocol, Tuple

from config.constant import COMMUNITY_MAX_REGISTERED_USERS

logger = logging.getLogger(__name__)


class RegistrationQuotaProvider(Protocol):
    """商业实现需要满足的最小协议；这里只声明能力，不包含业务算法。"""

    available: bool

    def check_allowed(self, total_count: int) -> Tuple[bool, str]: ...


class CommunityRegistrationQuotaProvider:
    """社区版默认实现：注册用户数达到上限后拒绝新注册。"""

    available = False

    def check_allowed(self, total_count: int) -> Tuple[bool, str]:
        if total_count >= COMMUNITY_MAX_REGISTERED_USERS:
            return False, (
                f"社区版最多支持 {COMMUNITY_MAX_REGISTERED_USERS} 个注册用户，"
                "如需更多用户请购买商业版"
            )
        return True, ""


_community_provider = CommunityRegistrationQuotaProvider()
_provider: RegistrationQuotaProvider = _community_provider


def register_provider(provider: RegistrationQuotaProvider) -> None:
    """由经过加载校验的企业模块注册真实实现。"""
    if provider is None or not getattr(provider, 'available', False):
        raise ValueError('注册配额 Provider 必须声明 available=True')
    global _provider
    _provider = provider
    logger.info('[Enterprise] Registration quota provider registered')


def reset_provider() -> None:
    """恢复社区默认实现，主要用于测试和企业模块加载失败回滚。"""
    global _provider
    _provider = _community_provider


def is_available() -> bool:
    return bool(getattr(_provider, 'available', False))


def check_allowed(total_count: int) -> Tuple[bool, str]:
    """检查给定用户总数下是否允许新用户注册，返回 (是否允许, 拒绝原因)。

    社区版为软上限：仅做计数快照判断，不串行化"计数 + 落库"，
    并发注册下实际人数可能略超上限（见模块 docstring 的并发说明）。
    """
    return _provider.check_allowed(total_count)
