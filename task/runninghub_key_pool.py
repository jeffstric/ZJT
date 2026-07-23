"""
RunningHub 密钥池公共门面。

社区版只提供全局单密钥兼容行为，不加载、不扫描、不执行任何多密钥轮换或
熔断逻辑。商业版在启动时通过 ``register_provider`` 注入私有实现。
"""
import asyncio
import logging
from typing import Any, Optional, Protocol, Tuple

from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)

RUNNINGHUB_GLOBAL_KEY_INDEX = 0


class RunningHubKeyPoolUnavailableError(RuntimeError):
    """当前安装包没有 RunningHub 密钥池能力。"""


class RunningHubKeyPoolProvider(Protocol):
    """商业实现需要满足的最小协议；这里只声明能力，不包含业务算法。"""

    available: bool

    def acquire_key(self) -> Optional[Tuple[int, str, int]]: ...
    def get_key_by_index(self, index: int) -> str: ...
    def get_key_index_for_slot(self, task_id: int, source: str) -> int: ...
    def report_success(self, index: int) -> None: ...
    def report_failure(self, index: int, reason: str = '') -> None: ...
    def refresh_circuits(self) -> int: ...
    def get_pool_overview(self) -> list[dict[str, Any]]: ...
    def get_key_raw(self, index: int) -> str: ...
    def set_key(self, index: int, *, api_key: Optional[str], max_slots: Optional[int],
                label: Optional[str], enabled: Optional[bool], updated_by: int) -> list[str]: ...
    def delete_key(self, index: int) -> int: ...
    def reset_circuit(self, index: int) -> bool: ...


class CommunityRunningHubKeyPoolProvider:
    """社区版空实现：始终回退到原有全局单密钥。"""

    available = False

    def acquire_key(self) -> Optional[Tuple[int, str, int]]:
        return None

    def get_key_by_index(self, index: int) -> str:
        if index != RUNNINGHUB_GLOBAL_KEY_INDEX:
            return ''
        return get_dynamic_config_value('runninghub', 'api_key', default='')

    def get_key_index_for_slot(self, task_id: int, source: str) -> int:
        return RUNNINGHUB_GLOBAL_KEY_INDEX

    def report_success(self, index: int) -> None:
        return None

    def report_failure(self, index: int, reason: str = '') -> None:
        return None

    def refresh_circuits(self) -> int:
        return 0

    def _unavailable(self):
        raise RunningHubKeyPoolUnavailableError('此功能仅商业版本可用')

    def get_pool_overview(self) -> list[dict[str, Any]]:
        return self._unavailable()

    def get_key_raw(self, index: int) -> str:
        return self._unavailable()

    def set_key(self, index: int, *, api_key: Optional[str], max_slots: Optional[int],
                label: Optional[str], enabled: Optional[bool], updated_by: int) -> list[str]:
        return self._unavailable()

    def delete_key(self, index: int) -> int:
        return self._unavailable()

    def reset_circuit(self, index: int) -> bool:
        return self._unavailable()


_community_provider = CommunityRunningHubKeyPoolProvider()
_provider: RunningHubKeyPoolProvider = _community_provider


def register_provider(provider: RunningHubKeyPoolProvider) -> None:
    """由经过加载校验的企业模块注册真实实现。"""
    if provider is None or not getattr(provider, 'available', False):
        raise ValueError('RunningHub 密钥池 Provider 必须声明 available=True')
    global _provider
    _provider = provider
    logger.info('[Enterprise] RunningHub key pool provider registered')


def reset_provider() -> None:
    """恢复社区空实现，主要用于测试和企业模块加载失败回滚。"""
    global _provider
    _provider = _community_provider


def is_available() -> bool:
    return bool(getattr(_provider, 'available', False))


def acquire_key() -> Optional[Tuple[int, str, int]]:
    return _provider.acquire_key()


async def acquire_key_async() -> Optional[Tuple[int, str, int]]:
    if not is_available():
        return None
    return await asyncio.to_thread(_provider.acquire_key)


def get_key_by_index(index: int) -> str:
    return _provider.get_key_by_index(index)


async def get_key_by_index_async(index: int) -> str:
    if not is_available():
        return _community_provider.get_key_by_index(index)
    return await asyncio.to_thread(_provider.get_key_by_index, index)


def get_key_index_for_slot(task_id: int, source: str) -> int:
    return _provider.get_key_index_for_slot(task_id, source)


async def get_key_index_for_slot_async(task_id: int, source: str) -> int:
    if not is_available():
        return RUNNINGHUB_GLOBAL_KEY_INDEX
    return await asyncio.to_thread(_provider.get_key_index_for_slot, task_id, source)


def report_success(index: int) -> None:
    _provider.report_success(index)


async def report_success_async(index: int) -> None:
    if is_available():
        await asyncio.to_thread(_provider.report_success, index)


def report_failure(index: int, reason: str = '') -> None:
    _provider.report_failure(index, reason)


async def report_failure_async(index: int, reason: str = '') -> None:
    if is_available():
        await asyncio.to_thread(_provider.report_failure, index, reason)


def refresh_circuits() -> int:
    return _provider.refresh_circuits()


async def get_pool_overview_async() -> list[dict[str, Any]]:
    _require_available()
    return await asyncio.to_thread(_provider.get_pool_overview)


async def get_key_raw_async(index: int) -> str:
    _require_available()
    return await asyncio.to_thread(_provider.get_key_raw, index)


async def set_key_async(index: int, *, api_key: Optional[str], max_slots: Optional[int],
                        label: Optional[str], enabled: Optional[bool], updated_by: int) -> list[str]:
    _require_available()
    return await asyncio.to_thread(
        _provider.set_key,
        index,
        api_key=api_key,
        max_slots=max_slots,
        label=label,
        enabled=enabled,
        updated_by=updated_by,
    )


async def delete_key_async(index: int) -> int:
    _require_available()
    return await asyncio.to_thread(_provider.delete_key, index)


async def reset_circuit_async(index: int) -> bool:
    _require_available()
    return await asyncio.to_thread(_provider.reset_circuit, index)


def _require_available() -> None:
    if not is_available():
        raise RunningHubKeyPoolUnavailableError('此功能仅商业版本可用')
