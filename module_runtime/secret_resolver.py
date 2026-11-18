"""将 Manifest 声明的密钥解析为最小 Runner 环境变量映射。"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Dict, Optional


_SECRET_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


@lru_cache(maxsize=1)
def _grantable_aliases_cached() -> tuple[tuple[str, tuple[str, ...], str], ...]:
    """由 DEFAULT_CONFIGS 中 user_module_grantable=True 的配置项构建映射条目。

    DEFAULT_CONFIGS 是代码常量（改动需发版），进程内不变，可安全缓存；
    返回不可变 tuple 防止调用方篡改缓存。条目为 (规范名, 配置路径, 配置描述)。
    """
    from config.default_configs import DEFAULT_CONFIGS

    entries: list[tuple[str, tuple[str, ...], str]] = []
    seen: set[str] = set()
    for entry in DEFAULT_CONFIGS:
        if not isinstance(entry, Mapping) or not entry.get("user_module_grantable"):
            continue
        config_key = entry.get("key")
        if not isinstance(config_key, str) or not config_key:
            continue
        secret_name = config_key.upper().replace(".", "_")
        if secret_name in seen or not _SECRET_NAME_PATTERN.fullmatch(secret_name):
            continue
        seen.add(secret_name)
        description = entry.get("description")
        entries.append(
            (
                secret_name,
                tuple(config_key.split(".")),
                description if isinstance(description, str) else "",
            )
        )
    return tuple(entries)


def user_module_grantable_aliases() -> Dict[str, tuple[str, ...]]:
    """密钥规范名 → 动态配置路径 的可授权映射（每次返回新 dict，仅限模块只读使用）。

    规范名 = config_key 大写并把 "." 换成 "_"，如 runninghub.api_key →
    ("runninghub", "api_key") 对应 RUNNINGHUB_API_KEY。只有显式标记
    user_module_grantable=True 的配置才会出现在映射中。
    """
    return {name: path for name, path, _ in _grantable_aliases_cached()}


def user_module_grantable_catalog() -> Dict[str, tuple[tuple[str, ...], str]]:
    """密钥规范名 → (配置路径, 配置描述)，供生成任务注入带语义的可授权密钥清单。

    描述取自 DEFAULT_CONFIGS 的 description 字段（如「API 聚合站站点3 API Key」），
    用于让生成智能体区分 api_aggregator.site_N 这类同族编号槽位。
    """
    return {name: (path, desc) for name, path, desc in _grantable_aliases_cached()}


def read_dynamic_secret(config_path: tuple[str, ...]) -> object:
    """直接读取密钥配置，避免跨进程的 30 秒动态配置缓存返回旧密钥。"""

    try:
        from config.config_util import get_config_value, get_current_env
        from model.system_config import SystemConfigModel
    except Exception:
        return ""

    try:
        config = SystemConfigModel.get_by_key(
            get_current_env(),
            ".".join(config_path),
        )
        if config is not None and config.config_value:
            return config.config_value
    except Exception:
        # 数据库临时不可用时仍保留原有 YAML 兜底，但不读取任意配置路径。
        pass

    try:
        return get_config_value(*config_path, default="")
    except Exception:
        # 密钥解析失败不能扩大为读取其它配置或泄漏配置值；调用方只会看到缺失。
        return ""


def _configured_secret(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def resolve_declared_secrets(
    secret_names: Iterable[str],
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """解析已声明密钥；同名环境变量优先，其次查询 user_module_grantable
    自动映射对应的受控动态配置。

    返回值只能交给 Supervisor 写入当次 RPC 的 DriverContext.secrets。
    函数不记录密钥、不枚举宿主环境，也不会根据声明名称拼接任意动态配置键。
    """

    source = os.environ if environ is None else environ
    grantable = user_module_grantable_aliases()
    resolved: Dict[str, str] = {}
    dynamic_values: Dict[tuple[str, ...], object] = {}

    for secret_name in secret_names:
        if not isinstance(secret_name, str) or not _SECRET_NAME_PATTERN.fullmatch(secret_name):
            continue
        if secret_name in resolved:
            continue

        environment_value = source.get(secret_name)
        if _configured_secret(environment_value):
            resolved[secret_name] = environment_value
            continue

        config_path = grantable.get(secret_name)
        if config_path is None:
            continue
        if config_path not in dynamic_values:
            dynamic_values[config_path] = read_dynamic_secret(config_path)
        dynamic_value = dynamic_values[config_path]
        if _configured_secret(dynamic_value):
            resolved[secret_name] = dynamic_value

    return resolved
