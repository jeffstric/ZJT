"""管理员批量系统配置写入服务。

该模块只暴露同步入口；异步 Web 路由必须在线程中调用。每个配置项使用一个
短事务，使配置值与对应审计历史要么一起提交、要么一起回滚，同时保留批量
接口原有的逐项成功/失败语义。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from config.config_util import invalidate_dynamic_cache
from config.default_configs import get_default_config_by_key, should_skip_history
from model.database import transaction
from model.system_config import SystemConfigModel
from model.system_config_history import SystemConfigHistoryModel


logger = logging.getLogger(__name__)


def _write_one_config(
    *,
    env: str,
    config_key: str,
    config_value: str,
    updated_by: int,
) -> str:
    """写入一个配置项并在同一事务内记录历史，返回状态。"""

    with transaction() as conn:
        config = SystemConfigModel.get_by_key_in_transaction(
            conn,
            env,
            config_key,
            for_update=True,
        )

        if config is None:
            config_def = get_default_config_by_key(config_key)
            if config_def is None:
                raise LookupError("配置不存在且无默认定义")

            config_id = SystemConfigModel.create_in_transaction(
                conn,
                env=env,
                config_key=config_key,
                config_value=config_value,
                value_type=config_def['value_type'],
                description=config_def['description'],
                editable=1 if config_def['editable'] else 0,
                is_sensitive=1 if config_def['is_sensitive'] else 0,
                updated_by=updated_by,
            )
            if not should_skip_history(config_key):
                SystemConfigHistoryModel.create_in_transaction(
                    conn,
                    config_id=config_id,
                    env=env,
                    config_key=config_key,
                    old_value=None,
                    new_value=config_value,
                    value_type=config_def['value_type'],
                    is_sensitive=1 if config_def['is_sensitive'] else 0,
                    updated_by=updated_by,
                )
            return "created"

        if not config.editable:
            raise PermissionError("该配置不允许修改")

        if config.config_value == config_value:
            return "unchanged"

        SystemConfigModel.update_value_in_transaction(
            conn,
            config.id,
            config_value,
            updated_by,
        )
        if not should_skip_history(config_key):
            SystemConfigHistoryModel.create_in_transaction(
                conn,
                config_id=config.id,
                env=env,
                config_key=config_key,
                old_value=config.config_value,
                new_value=config_value,
                value_type=config.value_type,
                is_sensitive=config.is_sensitive,
                updated_by=updated_by,
            )
        return "updated"


def batch_update_system_configs(
    *,
    env: str,
    configs: Sequence[tuple[str, str]],
    updated_by: int,
) -> dict[str, list]:
    """同步处理整批配置；调用方负责用 ``asyncio.to_thread`` 隔离。"""

    results: list[dict[str, str]] = []
    errors: list[str] = []

    for config_key, config_value in configs:
        if config_key.startswith("test_mode"):
            errors.append(
                f"{config_key}: test_mode 配置仅允许通过脚本修改，禁止在管理后台修改"
            )
            continue

        try:
            status = _write_one_config(
                env=env,
                config_key=config_key,
                config_value=config_value,
                updated_by=updated_by,
            )
        except (LookupError, PermissionError) as exc:
            # 仅返回固定业务错误，不包含配置值。
            errors.append(f"{config_key}: {exc}")
            continue
        except Exception as exc:
            # 数据库异常不得把 SQL 参数（可能含密钥）写进日志或 HTTP 响应。
            logger.error(
                "Failed to update config key=%s exception_type=%s",
                config_key,
                type(exc).__name__,
            )
            errors.append(f"{config_key}: 更新失败")
            continue

        results.append({"key": config_key, "status": status})
        if status in {"created", "updated"}:
            # 必须在事务提交后失效，后续动态配置读取才能看到已提交的新值。
            invalidate_dynamic_cache(config_key)

    return {"results": results, "errors": errors}
