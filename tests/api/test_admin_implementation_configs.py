"""实现方管理接口应包含用户模块动态实现方的归组展示。"""

import asyncio
from types import SimpleNamespace

import pytest

import services.user_module_binding_service as binding_service
from api import admin as admin_api
from services.user_module_binding_service import build_implementation_name, load_user_module_bindings

MODULE_ID = "huimeng.grok_video"
IMPL_NAME = build_implementation_name(MODULE_ID, "text_to_video")


class _FakePowerModel:
    @staticmethod
    def get_all_configs():
        return []

    @staticmethod
    def get_all_powers_for_implementation(*_a, **_k):
        return {}


def _task_config():
    from config.unified_config import TaskCategory, UnifiedConfigRegistry

    configs = UnifiedConfigRegistry.get_by_category(TaskCategory.TEXT_TO_VIDEO)
    assert configs
    return configs[0]


@pytest.fixture()
def dynamic_binding(monkeypatch):
    import model.implementation_power as power_module

    monkeypatch.setattr(power_module, "ImplementationPowerModel", _FakePowerModel)

    task_config = _task_config()
    row = SimpleNamespace(
        id=1,
        module_id=MODULE_ID,
        operation="text_to_video",
        task_id=task_config.id,
        implementation_id=9000,
        implementation_name=IMPL_NAME,
        display_name="MiniMax H3 视频生成（汇梦 API）",
        module_name="MiniMax H3 视频生成（汇梦 API）",
        module_effective=True,
        create_at=None,
        update_at=None,
    )

    class _FakeBindingModel:
        @staticmethod
        def list_effective():
            return [row]

    monkeypatch.setattr(binding_service, "UserModuleTaskBindingModel", _FakeBindingModel)
    load_user_module_bindings()
    yield task_config
    # 卸载动态注册，避免污染其他测试
    monkeypatch.setattr(
        binding_service,
        "UserModuleTaskBindingModel",
        SimpleNamespace(list_effective=lambda: []),
    )
    load_user_module_bindings()


def test_implementation_configs_group_dynamic_impl_by_task_driver(dynamic_binding, monkeypatch):
    async def require_admin(_auth_token):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(admin_api, "require_admin", require_admin)
    # ImplementationPowerModel 是模块级 import 进 admin 命名空间的，必须 patch
    # admin 模块属性才生效（patch model 模块不影响已绑定的名字）
    monkeypatch.setattr(admin_api, "ImplementationPowerModel", _FakePowerModel)
    # 端点会对每个非聚合器实现方做无参实例化验证；核心驱动构造函数读取
    # 动态配置会访问数据库，在无 DB 的测试环境里触发慢速连接超时。
    # 收窄注册表只保留动态驱动，聚焦本测试关心的归组逻辑。
    from task.visual_drivers import VideoDriverFactory
    from task.user_module_driver import UserModuleMediaDriver

    monkeypatch.setattr(
        VideoDriverFactory, "_registered_drivers", {IMPL_NAME: UserModuleMediaDriver}
    )
    # 端点尾部的重试开关读取走动态配置（会查库），测试环境直接返回默认值
    import config.config_util as config_util

    monkeypatch.setattr(
        config_util, "get_dynamic_config_value", lambda *a, **k: k.get("default")
    )

    response = asyncio.run(admin_api.admin_get_implementation_configs(auth_token="t"))

    assert response["code"] == 0
    groups = {group["driver_key"]: group["implementations"] for group in response["data"]}
    impls = groups.get(dynamic_binding.driver_name, [])
    names = [item["name"] for item in impls]

    assert IMPL_NAME in names
    assert "user_module_text_to_video" not in groups
    entry = next(item for item in impls if item["name"] == IMPL_NAME)
    assert "MiniMax H3 视频生成（汇梦 API）" in entry["display_name"]
    assert "文生视频" in entry["display_name"]
    assert entry["enabled"] is True
    # 动态实现方排在核心实现方之后
    assert names.index(IMPL_NAME) == len(names) - 1


def test_implementation_configs_same_impl_appears_in_each_bound_driver(monkeypatch):
    from config.unified_config import TaskCategory, UnifiedConfigRegistry
    from task.visual_drivers import VideoDriverFactory
    from task.user_module_driver import UserModuleMediaDriver

    configs = UnifiedConfigRegistry.get_by_category(TaskCategory.TEXT_TO_VIDEO)
    first = configs[0]
    second = next(item for item in configs if item.driver_name != first.driver_name)

    rows = [
        SimpleNamespace(
            id=1,
            module_id=MODULE_ID,
            operation="text_to_video",
            task_id=first.id,
            implementation_id=9000,
            implementation_name=IMPL_NAME,
            display_name="MiniMax H3 视频生成（汇梦 API）",
            module_name="MiniMax H3 视频生成（汇梦 API）",
            module_effective=True,
            create_at=None,
            update_at=None,
        ),
        SimpleNamespace(
            id=2,
            module_id=MODULE_ID,
            operation="text_to_video",
            task_id=second.id,
            implementation_id=9000,
            implementation_name=IMPL_NAME,
            display_name="MiniMax H3 视频生成（汇梦 API）",
            module_name="MiniMax H3 视频生成（汇梦 API）",
            module_effective=True,
            create_at=None,
            update_at=None,
        ),
    ]

    class _FakeBindingModel:
        @staticmethod
        def list_effective():
            return rows

    import model.implementation_power as power_module

    async def require_admin(_auth_token):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(power_module, "ImplementationPowerModel", _FakePowerModel)
    monkeypatch.setattr(binding_service, "UserModuleTaskBindingModel", _FakeBindingModel)
    monkeypatch.setattr(admin_api, "ImplementationPowerModel", _FakePowerModel)
    monkeypatch.setattr(admin_api, "require_admin", require_admin)
    monkeypatch.setattr(
        VideoDriverFactory, "_registered_drivers", {IMPL_NAME: UserModuleMediaDriver}
    )
    import config.config_util as config_util

    monkeypatch.setattr(
        config_util, "get_dynamic_config_value", lambda *a, **k: k.get("default")
    )
    load_user_module_bindings()
    try:
        response = asyncio.run(admin_api.admin_get_implementation_configs(auth_token="t"))
        groups = {group["driver_key"]: group["implementations"] for group in response["data"]}
        assert IMPL_NAME in [item["name"] for item in groups.get(first.driver_name, [])]
        assert IMPL_NAME in [item["name"] for item in groups.get(second.driver_name, [])]
        assert "user_module_text_to_video" not in groups
    finally:
        monkeypatch.setattr(
            binding_service,
            "UserModuleTaskBindingModel",
            SimpleNamespace(list_effective=lambda: []),
        )
        load_user_module_bindings()
