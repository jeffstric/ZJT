"""
注册人数配额公共门面。

社区版默认限制注册用户总数上限（COMMUNITY_MAX_REGISTERED_USERS），
不加载、不执行任何商业配额逻辑。商业版在启动时通过 ``register_provider``
注入放行实现（见 enterprise/__init__.py）。
"""
import logging
from typing import Protocol, Tuple

from config.constant import COMMUNITY_MAX_REGISTERED_USERS

logger = logging.getLogger(__name__)


class RegistrationQuotaProvider(Protocol):
    """商业实现需要满足的最小协议；这里只声明能力，不包含业务算法。"""

    available: bool

    def check_allowed(self) -> Tuple[bool, str]: ...


class CommunityRegistrationQuotaProvider:
    """社区版默认实现：注册用户数达到上限后拒绝新注册。"""

    available = False

    def check_allowed(self) -> Tuple[bool, str]:
        # 延迟导入，避免模块加载期循环依赖
        from model.users import UsersModel

        if UsersModel.get_total_count() >= COMMUNITY_MAX_REGISTERED_USERS:
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


def check_allowed() -> Tuple[bool, str]:
    """检查当前是否允许新用户注册，返回 (是否允许, 拒绝原因)。"""
    return _provider.check_allowed()
