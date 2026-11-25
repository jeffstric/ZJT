"""用户模块实现方绑定服务。

把已激活用户模块的 operation 能力注册为核心任务条目（UnifiedTaskConfig）的
动态实现方，使其出现在业务界面的模型选择与任务调度链路中：

- 注册内容：ImplementationConfig（driver_params 携带绑定参数）、
  VideoDriverFactory 驱动类、任务条目 implementations 候选列表、数字 ID 映射。
- 生命周期：绑定仅在模块 enabled + active 时生效（查询 JOIN 过滤）；
  web 进程创建/删除后立即重载，scheduler 等进程由定时任务周期重载。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from config.constant import (
    USER_MODULE_DEFAULT_COMPUTING_POWER,
    USER_MODULE_IMPL_NAME_PREFIX,
    USER_MODULE_OPERATION_CATEGORIES,
    USER_MODULE_OPERATION_LABELS,
    USER_MODULE_OPERATION_MEDIA_KINDS,
)
from config.unified_config import ImplementationConfig, UnifiedConfigRegistry
from model.user_module_binding import UserModuleTaskBindingEntity, UserModuleTaskBindingModel
from model.user_modules import UserModulesModel
from task.visual_drivers import VideoDriverFactory
from task.user_module_driver import UserModuleMediaDriver

logger = logging.getLogger(__name__)

# 动态实现方排在所有核心实现方之后
_DYNAMIC_SORT_ORDER = 990000.0

_lock = threading.Lock()
# 已注册的动态实现方名集合（卸载用）
_registered_impl_names: set = set()
# task_id -> 已追加到该条目 implementations 的动态实现方名（卸载用）
_registered_task_impls: Dict[int, List[str]] = {}
# 动态数字 ID 双向映射（get_dynamic_impl_id/name 查询用）
_dynamic_impl_ids: Dict[str, int] = {}
_dynamic_impl_names: Dict[int, str] = {}


class UserModuleBindingError(RuntimeError):
    """绑定校验/操作失败，code 供 admin API 转换为结构化错误。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_implementation_name(module_id: str, operation: str) -> str:
    return f"{USER_MODULE_IMPL_NAME_PREFIX}{module_id}:{operation}"


def plan_legacy_power_key_moves(
    rows: List[Dict[str, Any]],
    impl_to_driver_names: Dict[str, List[str]],
) -> List[tuple]:
    """把旧的 user_module_* driver_key 规划成挂载条目的真实 driver_name。"""

    moves: List[tuple] = []
    for row in rows or []:
        name = str(row.get("implementation_name") or "")
        key = str(row.get("driver_key") or "")
        if not name.startswith(USER_MODULE_IMPL_NAME_PREFIX) or not key.startswith("user_module_"):
            continue
        targets = [driver for driver in impl_to_driver_names.get(name, []) if driver]
        moves.append((name, key, targets))
    return moves


def _bound_driver_names_locked() -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for task_id, names in _registered_task_impls.items():
        config = UnifiedConfigRegistry.get_by_id(task_id)
        driver_name = getattr(config, "driver_name", None) if config is not None else None
        if not driver_name:
            continue
        for impl_name in names:
            keys = mapping.setdefault(impl_name, [])
            if driver_name not in keys:
                keys.append(driver_name)
    return mapping


def _remap_legacy_power_keys_locked() -> None:
    try:
        from model.implementation_power import ImplementationPowerModel

        rows = ImplementationPowerModel.get_all_configs() or []
        moves = plan_legacy_power_key_moves(rows, _bound_driver_names_locked())
        for impl_name, old_key, new_keys in moves:
            ImplementationPowerModel.reassign_driver_key(impl_name, old_key, new_keys)
    except Exception:
        logger.exception("改挂用户模块旧算力 driver_key 失败")


def get_dynamic_impl_id(name: str) -> Optional[int]:
    return _dynamic_impl_ids.get(name)


def get_dynamic_impl_name(implementation_id: int) -> Optional[str]:
    return _dynamic_impl_names.get(implementation_id)


def is_dynamic_implementation(name: str) -> bool:
    return name.startswith(USER_MODULE_IMPL_NAME_PREFIX)


def load_user_module_bindings() -> int:
    """（重新）加载全部生效绑定到当前进程的注册表，返回加载数量。"""
    with _lock:
        # 先全量清空再重载：绑定失效/删除时等价于卸载全部用户模块实现方，
        # 模型下拉与调度器在下次重载后自动跟上。
        _unregister_all_dynamic_locked()
        count = 0
        for binding in UserModuleTaskBindingModel.list_effective():
            try:
                _register_binding_locked(binding)
                count += 1
            except Exception:
                logger.exception("注册用户模块绑定失败: %s", binding.implementation_name)
        if count:
            logger.info("已加载 %d 条用户模块实现方绑定", count)
        _remap_legacy_power_keys_locked()
        return count


def _unregister_all_dynamic_locked() -> None:
    for task_id, names in _registered_task_impls.items():
        config = UnifiedConfigRegistry.get_by_id(task_id)
        if config is not None:
            dynamic = set(names)
            config.implementations = [n for n in config.implementations if n not in dynamic]
    for name in _registered_impl_names:
        UnifiedConfigRegistry.unregister_implementation(name)
        VideoDriverFactory.unregister_driver(name)
    _registered_impl_names.clear()
    _registered_task_impls.clear()
    _dynamic_impl_ids.clear()
    _dynamic_impl_names.clear()


def _register_binding_locked(binding: UserModuleTaskBindingEntity) -> None:
    config = UnifiedConfigRegistry.get_by_id(binding.task_id)
    if config is None:
        raise UserModuleBindingError(
            "TASK_NOT_FOUND", f"任务条目 {binding.task_id} 不存在，绑定无法注册"
        )

    impl_name = binding.implementation_name
    capability = _find_capability(_active_manifest(binding.module_id), binding.operation)
    resolution_options, default_resolution = _resolution_options(capability)
    base_name = binding.display_name or binding.module_name or binding.module_id
    operation_label = USER_MODULE_OPERATION_LABELS.get(binding.operation, binding.operation)
    display_name = (
        base_name
        if str(operation_label) in str(base_name)
        else f"{base_name}（{operation_label}）"
    )
    if impl_name not in _registered_impl_names:
        UnifiedConfigRegistry.register_implementation(
            ImplementationConfig(
                name=impl_name,
                display_name=display_name,
                driver_class="task.user_module_driver.UserModuleMediaDriver",
                default_computing_power=_default_computing_power(config),
                sort_order=_DYNAMIC_SORT_ORDER,
                driver_params={
                    "module_id": binding.module_id,
                    "operation": binding.operation,
                    "task_id": binding.task_id,
                    "impl_name": impl_name,
                },
                description=f"用户模块 {binding.module_id} 的 {binding.operation} 能力",
                # 分辨率档位来自模块 manifest 的 request_schema 声明；
                # 未声明时为空列表，validate_video_resolution 会丢弃 resolution 参数
                supported_video_resolutions=resolution_options,
                default_video_resolution=default_resolution,
            )
        )
        VideoDriverFactory.register_driver(impl_name, UserModuleMediaDriver)
    if impl_name not in config.implementations:
        config.implementations.append(impl_name)

    _registered_impl_names.add(impl_name)
    _registered_task_impls.setdefault(binding.task_id, []).append(impl_name)
    _dynamic_impl_ids[impl_name] = binding.implementation_id
    _dynamic_impl_names[binding.implementation_id] = impl_name


def _active_manifest(module_id: str) -> Optional[Dict[str, Any]]:
    try:
        release = UserModulesModel.get_active_release(module_id)
        return release.manifest if release else None
    except Exception:
        logger.exception("读取模块 %s 的激活 manifest 失败，按无声明处理", module_id)
        return None


def _default_computing_power(config) -> Any:
    """任务算力 > 0 则沿用；为 0 的空壳条目给用户模块默认 1 点，避免扣费被拒。"""
    power = getattr(config, "computing_power", 0)
    if isinstance(power, int) and power > 0:
        return power
    if isinstance(power, dict) and power:
        return power
    return USER_MODULE_DEFAULT_COMPUTING_POWER


def _find_capability(manifest: Optional[Dict[str, Any]], operation: str) -> Optional[Dict[str, Any]]:
    for capability in (manifest or {}).get("capabilities") or []:
        if isinstance(capability, dict) and capability.get("operation") == operation:
            return capability
    return None


def _resolution_options(capability: Optional[Dict[str, Any]]):
    """从 capability.request_schema 提取分辨率档位与默认值（供平台渲染与参数校验）。"""
    schema = (capability or {}).get("request_schema") or {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    spec = properties.get("resolution") if isinstance(properties, dict) else None
    if not isinstance(spec, dict):
        return [], ""
    enum_values = [value for value in (spec.get("enum") or []) if isinstance(value, str)]
    if not enum_values:
        return [], ""
    options = [{"value": value, "label": value} for value in enum_values]
    default = spec.get("default")
    return options, (default if default in enum_values else enum_values[0])


def create_binding(module_id: str, task_id: int, operation: str) -> Dict[str, Any]:
    """创建绑定并立即在当前进程重载注册，返回绑定详情。"""
    category = USER_MODULE_OPERATION_CATEGORIES.get(operation)
    if not category:
        raise UserModuleBindingError("INVALID_OPERATION", f"不支持的用户模块能力: {operation}")

    release = UserModulesModel.get_active_release(module_id)
    if release is None:
        raise UserModuleBindingError("MODULE_NOT_ACTIVE", f"模块 {module_id} 未激活，无法绑定")

    expected_media_kind = USER_MODULE_OPERATION_MEDIA_KINDS[operation]
    capabilities = (release.manifest or {}).get("capabilities") or []
    matched = any(
        cap.get("operation") == operation and cap.get("media_kind") == expected_media_kind
        for cap in capabilities
        if isinstance(cap, dict)
    )
    if not matched:
        raise UserModuleBindingError(
            "CAPABILITY_NOT_FOUND",
            f"模块 {module_id} 未声明 {operation}/{expected_media_kind} 能力",
        )

    config = UnifiedConfigRegistry.get_by_id(task_id)
    if config is None:
        raise UserModuleBindingError("TASK_NOT_FOUND", f"任务条目 {task_id} 不存在")

    allowed_categories = [config.category] + list(config.categories or [])
    if category not in allowed_categories:
        raise UserModuleBindingError(
            "CATEGORY_MISMATCH",
            f"任务条目 {config.name} 的分类不含 {category}，与能力 {operation} 不匹配",
        )

    if UserModuleTaskBindingModel.find_duplicate(module_id, operation, task_id):
        raise UserModuleBindingError("DUPLICATE_BINDING", "该能力已绑定到此任务条目")

    implementation_id = UserModuleTaskBindingModel.next_implementation_id()
    implementation_name = build_implementation_name(module_id, operation)
    display_name = (release.manifest or {}).get("name") or module_id
    binding_id = UserModuleTaskBindingModel.create(
        module_id=module_id,
        operation=operation,
        task_id=task_id,
        implementation_id=implementation_id,
        implementation_name=implementation_name,
        display_name=display_name,
    )
    load_user_module_bindings()
    entity = UserModuleTaskBindingModel.get_by_id(binding_id)
    return entity.to_dict() if entity else {"id": binding_id}


def delete_binding(binding_id: int) -> None:
    """删除绑定并立即在当前进程重载注册。"""
    entity = UserModuleTaskBindingModel.get_by_id(binding_id)
    if entity is None:
        raise UserModuleBindingError("BINDING_NOT_FOUND", "绑定不存在")
    UserModuleTaskBindingModel.delete(binding_id)
    load_user_module_bindings()


def list_bindings(module_id: str) -> List[Dict[str, Any]]:
    bindings = []
    for entity in UserModuleTaskBindingModel.list_by_module(module_id):
        item = entity.to_dict()
        config = UnifiedConfigRegistry.get_by_id(entity.task_id)
        item["task_name"] = config.name if config else None
        bindings.append(item)
    return bindings


def list_binding_targets(module_id: str) -> Dict[str, Any]:
    """列出可挂载的任务条目，按模块 capabilities 的分类过滤。

    返回 {"capabilities": [...], "tasks": {category: [{id, key, name}]}}，
    前端按 capability 的 operation 分组渲染候选下拉。
    """
    release = UserModulesModel.get_active_release(module_id)
    if release is None:
        raise UserModuleBindingError("MODULE_NOT_ACTIVE", f"模块 {module_id} 未激活，无法绑定")

    capabilities = []
    for cap in (release.manifest or {}).get("capabilities") or []:
        if not isinstance(cap, dict):
            continue
        operation = cap.get("operation")
        category = USER_MODULE_OPERATION_CATEGORIES.get(operation)
        # 只暴露本链路支持的 operation（audio 等暂不接入 visual 调度）
        if category and cap.get("media_kind") == USER_MODULE_OPERATION_MEDIA_KINDS.get(operation):
            capabilities.append({"operation": operation, "media_kind": cap.get("media_kind")})

    tasks_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for config in UnifiedConfigRegistry.get_all():
        if config.hidden or not config.enabled:
            continue
        for category in {config.category, *(config.categories or [])}:
            if category in USER_MODULE_OPERATION_CATEGORIES.values():
                tasks_by_category.setdefault(category, []).append(
                    {
                        "id": config.id,
                        "key": config.key,
                        "name": config.name,
                        "provider": config.provider,
                    }
                )

    return {"capabilities": capabilities, "tasks": tasks_by_category}
