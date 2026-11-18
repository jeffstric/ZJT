"""用户模块实现方绑定服务与核心链路集成测试。

通过 fake 数据层注入验证：
- create_binding 的校验（激活/能力/分类/重复）与实现方 ID 分配
- load_user_module_bindings 的运行时注册（注册表/驱动工厂/候选列表/数字 ID 映射）
- 卸载后动态实现方从所有注册点消失
"""

from types import SimpleNamespace

import pytest

import services.user_module_binding_service as binding_service
from services.user_module_binding_service import (
    UserModuleBindingError,
    _default_computing_power,
    build_implementation_name,
    create_binding,
    load_user_module_bindings,
    plan_legacy_power_key_moves,
)

def test_default_computing_power_uses_one_when_task_is_zero():
    assert _default_computing_power(SimpleNamespace(computing_power=0)) == 1
    assert _default_computing_power(SimpleNamespace(computing_power=6)) == 6
    assert _default_computing_power(SimpleNamespace(computing_power={5: 8, 10: 18})) == {5: 8, 10: 18}


MODULE_ID = "huimeng.grok_video"
MANIFEST = {
    "module_id": MODULE_ID,
    "name": "MiniMax H3 视频生成（汇梦 API）",
    "capabilities": [
        {
            "operation": "text_to_video",
            "media_kind": "video",
            "request_schema": {
                "type": "object",
                "properties": {
                    "resolution": {"type": "string", "enum": ["768P", "2K"], "default": "768P"}
                },
            },
        },
        {"operation": "image_to_video", "media_kind": "video"},
    ],
}


class _FakeBindingModel:
    """绑定表 fake：内存行 + 可注入的查询结果。"""

    effective = []
    by_module = []
    duplicate = None
    rows = []
    next_id = 9000
    created = []

    @classmethod
    def reset(cls):
        cls.effective = []
        cls.by_module = []
        cls.duplicate = None
        cls.rows = []
        cls.next_id = 9000
        cls.created = []

    @classmethod
    def list_effective(cls):
        return cls.effective

    @classmethod
    def list_by_module(cls, module_id):
        return cls.by_module

    @classmethod
    def find_duplicate(cls, module_id, operation, task_id):
        return cls.duplicate

    @classmethod
    def next_implementation_id(cls):
        return cls.next_id

    @classmethod
    def create(cls, module_id, operation, task_id, implementation_id, implementation_name, display_name=""):
        cls.created.append(
            {
                "module_id": module_id,
                "operation": operation,
                "task_id": task_id,
                "implementation_id": implementation_id,
                "implementation_name": implementation_name,
                "display_name": display_name,
            }
        )
        return len(cls.created)

    @classmethod
    def get_by_id(cls, binding_id):
        if not cls.created:
            return None
        data = dict(cls.created[-1])
        data.update(
            id=binding_id,
            module_name=MANIFEST["name"],
            module_effective=True,
        )
        return SimpleNamespace(**data, to_dict=lambda: data)


def _make_binding_row(task_id, operation="text_to_video", implementation_id=9000):
    data = {
        "id": 1,
        "module_id": MODULE_ID,
        "operation": operation,
        "task_id": task_id,
        "implementation_id": implementation_id,
        "implementation_name": build_implementation_name(MODULE_ID, operation),
        "display_name": MANIFEST["name"],
        "module_name": MANIFEST["name"],
        "module_effective": True,
        "create_at": None,
        "update_at": None,
    }
    entity = SimpleNamespace(**data)
    entity.to_dict = lambda: data
    return entity


@pytest.fixture()
def binding_env(monkeypatch):
    """注入 fake 数据层并屏蔽实现方算力表的数据库访问。"""

    class _FakePowerModel:
        @staticmethod
        def get_config(*_a, **_k):
            return None

        @staticmethod
        def get_all_powers_for_implementation(*_a, **_k):
            return {}

        @staticmethod
        def is_enabled(*_a, **_k):
            return True

        @staticmethod
        def get_power(*_a, **_k):
            return None

    import model.implementation_power as power_module

    monkeypatch.setattr(power_module, "ImplementationPowerModel", _FakePowerModel)
    _FakeBindingModel.reset()
    monkeypatch.setattr(binding_service, "UserModuleTaskBindingModel", _FakeBindingModel)
    # 注册时会读取激活 Release 的 manifest（request_schema 提取分辨率档位）
    release = SimpleNamespace(manifest=MANIFEST)
    monkeypatch.setattr(
        binding_service.UserModulesModel,
        "get_active_release",
        staticmethod(lambda _module_id: release),
    )
    # 卸载兜底，避免注册表残留影响其他测试
    _FakeBindingModel.effective = []
    load_user_module_bindings()
    yield monkeypatch
    _FakeBindingModel.effective = []
    load_user_module_bindings()


def _active_release(monkeypatch, manifest=MANIFEST):
    release = SimpleNamespace(manifest=manifest)
    monkeypatch.setattr(
        binding_service.UserModulesModel, "get_active_release", staticmethod(lambda _m: release)
    )


def _no_active_release(monkeypatch):
    monkeypatch.setattr(
        binding_service.UserModulesModel, "get_active_release", staticmethod(lambda _m: None)
    )


def _text_to_video_task_id():
    from config.unified_config import TaskCategory, UnifiedConfigRegistry

    configs = UnifiedConfigRegistry.get_by_category(TaskCategory.TEXT_TO_VIDEO)
    assert configs, "注册表缺少 text_to_video 条目"
    return configs[0].id


# --------------------------------------------------------------------------- #
# create_binding 校验与落库
# --------------------------------------------------------------------------- #

def test_create_binding_rejects_inactive_module(binding_env):
    _no_active_release(binding_env)
    with pytest.raises(UserModuleBindingError) as exc:
        create_binding(MODULE_ID, _text_to_video_task_id(), "text_to_video")
    assert exc.value.code == "MODULE_NOT_ACTIVE"


def test_create_binding_rejects_missing_capability(binding_env):
    _active_release(
        binding_env,
        manifest={"module_id": MODULE_ID, "name": "x", "capabilities": [
            {"operation": "image_to_video", "media_kind": "video"},
        ]},
    )
    with pytest.raises(UserModuleBindingError) as exc:
        create_binding(MODULE_ID, _text_to_video_task_id(), "text_to_video")
    assert exc.value.code == "CAPABILITY_NOT_FOUND"


def test_create_binding_rejects_category_mismatch(binding_env):
    from config.unified_config import TaskCategory, UnifiedConfigRegistry

    _active_release(binding_env)
    image_task = UnifiedConfigRegistry.get_by_category(TaskCategory.TEXT_TO_IMAGE)[0]
    with pytest.raises(UserModuleBindingError) as exc:
        create_binding(MODULE_ID, image_task.id, "text_to_video")
    assert exc.value.code == "CATEGORY_MISMATCH"


def test_create_binding_rejects_duplicate(binding_env):
    _active_release(binding_env)
    _FakeBindingModel.duplicate = _make_binding_row(_text_to_video_task_id())
    with pytest.raises(UserModuleBindingError) as exc:
        create_binding(MODULE_ID, _text_to_video_task_id(), "text_to_video")
    assert exc.value.code == "DUPLICATE_BINDING"


def test_create_binding_persists_with_allocated_id(binding_env):
    _active_release(binding_env)
    _FakeBindingModel.next_id = 9004
    task_id = _text_to_video_task_id()

    result = create_binding(MODULE_ID, task_id, "text_to_video")

    (row,) = _FakeBindingModel.created
    assert row["implementation_id"] == 9004
    assert row["implementation_name"] == "user_module:huimeng.grok_video:text_to_video"
    assert row["display_name"] == MANIFEST["name"]
    assert result["implementation_id"] == 9004


# --------------------------------------------------------------------------- #
# SQL 参数占位符与 fetch 标志防回归
# （execute_query 使用 pymysql pyformat，且不传 fetch_one/fetch_all 时返回 None）
# --------------------------------------------------------------------------- #

def test_binding_queries_placeholder_count_and_fetch_flags(monkeypatch):
    import model.user_module_binding as binding_model

    captured = []

    def _capture(sql, params=None, **kwargs):
        captured.append((sql, params, kwargs))
        return []

    monkeypatch.setattr(binding_model, "execute_query", _capture)

    binding_model.UserModuleTaskBindingModel.get_by_id(1)
    binding_model.UserModuleTaskBindingModel.list_by_module("m.x")
    binding_model.UserModuleTaskBindingModel.find_duplicate("m.x", "text_to_video", 34)
    binding_model.UserModuleTaskBindingModel.list_effective()
    binding_model.UserModuleTaskBindingModel.next_implementation_id()

    assert len(captured) == 5
    for sql, params, kwargs in captured:
        assert sql.count("%s") == len(params or ()), (
            f"占位符数量不匹配: {sql.count('%s')} 个 %s vs {len(params or ())} 个参数: {sql}"
        )
        # 列表查询必须显式声明 fetch 标志，否则 execute_query 返回 None
        assert kwargs.get("fetch_one") or kwargs.get("fetch_all"), f"查询缺少 fetch 标志: {sql}"
        if kwargs.get("fetch_one"):
            assert kwargs.get("fetch_all") is None


# --------------------------------------------------------------------------- #
# 运行时注册与核心链路集成
# --------------------------------------------------------------------------- #

def test_load_registers_dynamic_implementation_everywhere(binding_env):
    from config.unified_config import UnifiedConfigRegistry, get_implementation_id, get_implementation_name
    from task.visual_drivers import VideoDriverFactory
    from task.user_module_driver import UserModuleMediaDriver
    from utils.video_resolution import validate_video_resolution

    task_id = _text_to_video_task_id()
    config = UnifiedConfigRegistry.get_by_id(task_id)
    impl_name = build_implementation_name(MODULE_ID, "text_to_video")
    assert impl_name not in config.implementations

    _FakeBindingModel.effective = [_make_binding_row(task_id, implementation_id=9001)]
    count = load_user_module_bindings()

    assert count == 1
    assert UnifiedConfigRegistry.get_implementation(impl_name) is not None
    assert impl_name in config.implementations
    assert VideoDriverFactory.is_driver_registered(impl_name)
    assert get_implementation_id(impl_name) == 9001
    assert get_implementation_name(9001) == impl_name

    driver = VideoDriverFactory.create_driver_by_implementation(impl_name)
    assert isinstance(driver, UserModuleMediaDriver)
    assert driver.module_id == MODULE_ID
    assert driver.operation == "text_to_video"

    # 分辨率档位来自模块 manifest 的 request_schema：
    # 显式合法值透传、非法值回退默认、未传时给默认（不再被丢弃）
    assert validate_video_resolution("2K", impl_name) == "2K"
    assert validate_video_resolution("720P", impl_name) == "768P"
    assert validate_video_resolution(None, impl_name) == "768P"

    impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
    assert [item["value"] for item in impl_config.supported_video_resolutions] == ["768P", "2K"]
    assert impl_config.default_video_resolution == "768P"


def test_load_without_request_schema_drops_resolution(binding_env):
    """manifest 未声明 request_schema 时无分辨率档位，resolution 会被校验层丢弃（既有语义）。"""
    from config.unified_config import UnifiedConfigRegistry
    from utils.video_resolution import validate_video_resolution

    task_id = _text_to_video_task_id()
    impl_name = build_implementation_name(MODULE_ID, "image_to_video")
    _FakeBindingModel.effective = [
        _make_binding_row(task_id, operation="image_to_video", implementation_id=9003)
    ]
    load_user_module_bindings()

    assert validate_video_resolution("2K", impl_name) is None
    assert UnifiedConfigRegistry.get_implementation(impl_name).supported_video_resolutions == []


def test_load_lists_dynamic_implementation_as_candidate(binding_env):
    from config.unified_config import UnifiedConfigRegistry

    task_id = _text_to_video_task_id()
    impl_name = build_implementation_name(MODULE_ID, "text_to_video")
    _FakeBindingModel.effective = [_make_binding_row(task_id, implementation_id=9002)]
    load_user_module_bindings()

    config = UnifiedConfigRegistry.get_by_id(task_id)
    info = [item for item in config._get_implementations_info() if item["name"] == impl_name]

    assert len(info) == 1
    assert info[0]["is_default"] is False
    assert info[0]["display_name"] == f"{MANIFEST['name']}（文生视频）"
    # 动态实现方排在核心实现方之后
    all_names = [item["name"] for item in config._get_implementations_info()]
    assert all_names.index(impl_name) >= len(all_names) - 1


def test_reload_unregisters_stale_bindings(binding_env):
    from config.unified_config import UnifiedConfigRegistry, get_implementation_id
    from task.visual_drivers import VideoDriverFactory

    task_id = _text_to_video_task_id()
    impl_name = build_implementation_name(MODULE_ID, "text_to_video")
    config = UnifiedConfigRegistry.get_by_id(task_id)
    original = list(config.implementations)

    _FakeBindingModel.effective = [_make_binding_row(task_id)]
    load_user_module_bindings()
    assert impl_name in config.implementations

    # 模块禁用后（有效绑定变空）重载：注册点全部清理
    _FakeBindingModel.effective = []
    load_user_module_bindings()

    assert UnifiedConfigRegistry.get_implementation(impl_name) is None
    assert not VideoDriverFactory.is_driver_registered(impl_name)
    assert config.implementations == original
    assert get_implementation_id(impl_name) == 0


def test_plan_legacy_power_key_moves_rewrites_user_module_driver_keys():
    impl_name = build_implementation_name("huimeng.nano2", "image_edit")
    rows = [
        {"implementation_name": impl_name, "driver_key": "user_module_image_edit"},
        {"implementation_name": "seedream5_volcengine_v1", "driver_key": "seedream_text_to_image"},
        {"implementation_name": impl_name, "driver_key": "seedream_text_to_image"},
    ]
    moves = plan_legacy_power_key_moves(
        rows,
        {impl_name: ["seedream_text_to_image", "gemini_3_1_flash_image_edit"]},
    )
    assert moves == [
        (impl_name, "user_module_image_edit", ["seedream_text_to_image", "gemini_3_1_flash_image_edit"]),
    ]


def test_plan_legacy_power_key_moves_drops_unbound_legacy_rows():
    impl_name = build_implementation_name("huimeng.nano2", "text_to_image")
    moves = plan_legacy_power_key_moves(
        [{"implementation_name": impl_name, "driver_key": "user_module_text_to_image"}],
        {},
    )
    assert moves == [(impl_name, "user_module_text_to_image", [])]


# --------------------------------------------------------------------------- #
# 默认实现方兜底必须尊重 admin 禁用（不得静默放行被禁用实现方）
# --------------------------------------------------------------------------- #

def _fallback_task_config(monkeypatch, *, default_impl, candidates, registered, enabled):
    """构造最小任务配置与可注入的注册表/工厂状态，直测 _get_implementation_for_user 兜底。"""
    from config.unified_config import UnifiedConfigRegistry
    from task.visual_drivers import VideoDriverFactory

    config = SimpleNamespace(
        key="demo_task_key",
        driver_name="demo_driver",
        implementation=default_impl,
        _get_implementations_info=lambda: [{"name": name} for name in candidates],
    )
    fake_impl_config = SimpleNamespace(
        is_enabled=lambda _driver_key: enabled, driver_params={}
    )
    monkeypatch.setattr(
        UnifiedConfigRegistry, "get_implementation", staticmethod(lambda _name: fake_impl_config)
    )
    monkeypatch.setattr(VideoDriverFactory, "_registered_drivers", dict(registered))
    monkeypatch.setattr(VideoDriverFactory, "_last_create_error", None)
    return VideoDriverFactory, config


def test_fallback_refuses_disabled_default_implementation(monkeypatch):
    """候选全不可用 + 默认实现方被 admin 禁用：返回 None 并给出明确错误，绝不放行禁用实现方。"""
    factory, config = _fallback_task_config(
        monkeypatch,
        default_impl="builtin_disabled_v1",
        candidates=["ghost_user_module_impl"],
        registered={"builtin_disabled_v1": object},  # 已注册（可实例化）但被禁用
        enabled=False,
    )

    impl_name, driver_params, _error = factory._get_implementation_for_user(34, None, config)

    assert impl_name is None
    assert driver_params == {}
    error = factory.get_last_create_error()
    assert error["reason"] == "NO_IMPLEMENTATION_AVAILABLE"
    assert "demo_task_key" in error["message"]
    assert "实现方管理" in error["message"]


def test_fallback_uses_default_when_enabled_and_available(monkeypatch):
    """默认实现方可用且启用时，兜底行为保持不变。"""
    factory, config = _fallback_task_config(
        monkeypatch,
        default_impl="builtin_ok_v1",
        candidates=[],
        registered={"builtin_ok_v1": object},
        enabled=True,
    )

    impl_name, _driver_params, _err = factory._get_implementation_for_user(34, None, config)

    assert impl_name == "builtin_ok_v1"
    assert factory.get_last_create_error() is None
