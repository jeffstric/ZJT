"""商业许可证续租 job 的调度门面（开源主仓侧）。

scheduler 每 LICENSE_REBOOTSTRAP_INTERVAL_SECONDS 秒触发一次
rebootstrap_commercial_license()，委托给已注册的续租实现：
- 商业版：由 enterprise 仓库注册真实实现（周期性为 scheduler 进程续租，
  防止进程启动时获取的短期许可证租约到期后商业能力失效、结果交付链路被卡）；
- 社区版：未注册任何实现，默认为空操作（开源版无商业许可证概念）。

另提供 is_non_transient_error() 供 download_queue 等链路判定"许可证类非瞬态
错误"：此类错误走租约回收重试只会按固定周期循环失败，必须长退避置回 pending
（2026-09-15 生产事故教训）。
"""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class LicenseRebootstrapProvider(Protocol):
    """商业许可证周期续租实现需要满足的最小协议。"""

    available: bool

    def rebootstrap(self) -> None:
        """执行一次续租。实现内部自行处理全部异常，绝不抛出。"""
        ...

    def is_non_transient_error(self, exc: BaseException) -> bool:
        """判定异常是否为许可证类非瞬态错误（长退避决策用）。"""
        ...


class CommunityLicenseRebootstrapProvider:
    """社区默认实现：无商业许可证概念，全部空操作。"""

    available = False

    def rebootstrap(self) -> None:
        return None

    def is_non_transient_error(self, exc: BaseException) -> bool:
        return False


_community_provider = CommunityLicenseRebootstrapProvider()
_provider: LicenseRebootstrapProvider = _community_provider


def register_provider(provider: LicenseRebootstrapProvider) -> None:
    """由商业版模块注册真实实现。"""
    if provider is None or not getattr(provider, "available", False):
        raise ValueError("许可证续租 Provider 必须声明 available=True")
    global _provider
    _provider = provider
    logger.info("[Enterprise] License rebootstrap provider registered")


def reset_provider() -> None:
    """恢复社区默认实现，用于商业版加载失败回滚和测试隔离。"""
    global _provider
    _provider = _community_provider


def is_available() -> bool:
    return bool(getattr(_provider, "available", False))


def rebootstrap_commercial_license() -> None:
    """scheduler job 入口：委托给已注册的续租实现（社区版为空操作）。

    实现线程内绝不抛出——job 异常只会落 scheduler 日志，没有其他兜底。
    """
    _provider.rebootstrap()


def is_non_transient_error(exc: BaseException) -> bool:
    """判定是否为许可证类非瞬态错误（download_queue 长退避决策用）。"""
    return _provider.is_non_transient_error(exc)


__all__ = [
    "CommunityLicenseRebootstrapProvider",
    "LicenseRebootstrapProvider",
    "is_available",
    "is_non_transient_error",
    "rebootstrap_commercial_license",
    "register_provider",
    "reset_provider",
]
