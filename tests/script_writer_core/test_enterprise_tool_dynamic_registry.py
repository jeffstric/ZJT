"""动态工具注册表与迁移期 shim 回归测试。

2026-11-20 起用户模块（接口模块）主仓恒为 owner：迁移期主仓与 enterprise 旧版
双侧注册同名用户模块生成工具，依赖 register_dynamic_tools 的 last-wins 同名
替换（否则后半覆盖中断，出现"半主仓半 enterprise"混合态）与绑定加载中和
shim（否则 enterprise 侧"先清空注册表"会抹掉主仓实现方）。见
docs/backend/user_modules_open_source_plan.md §2.4/§4.2/§4.3。
"""

import logging
import sys
from types import ModuleType

import pytest

from script_writer_core.agents.tool_executor import (
    ToolExecutor,
    _enterprise_tool_functions,
    _enterprise_tool_metadata,
    register_enterprise_tool,
    unregister_enterprise_tool,
)
from script_writer_core.mcp_tool import MCP_TOOLS, register_dynamic_tools


def _schema(name: str, marker: str) -> dict:
    return {
        "name": name,
        "description": f"test schema {name} ({marker})",
        "inputSchema": {"type": "object", "properties": {"marker": {"const": marker}}},
    }


@pytest.fixture()
def protect_mcp_tools():
    """register_dynamic_tools 原地修改共享 MCP_TOOLS，测试后恢复快照。"""
    snapshot = list(MCP_TOOLS)
    yield
    MCP_TOOLS[:] = snapshot


@pytest.fixture()
def protect_enterprise_tools():
    """register_enterprise_tool 写共享函数/metadata 字典，测试后恢复快照。"""
    snapshot_functions = dict(_enterprise_tool_functions)
    snapshot_metadata = dict(_enterprise_tool_metadata)
    yield
    _enterprise_tool_functions.clear()
    _enterprise_tool_functions.update(snapshot_functions)
    _enterprise_tool_metadata.clear()
    _enterprise_tool_metadata.update(snapshot_metadata)


# ---------------------------------------------------------------------------
# register_dynamic_tools：缺失名抛错 / 同名 last-wins 替换 / 新名追加
# ---------------------------------------------------------------------------


def test_missing_name_still_raises(protect_mcp_tools):
    with pytest.raises(ValueError, match="动态工具名缺失"):
        register_dynamic_tools([{"description": "no name"}])


def test_duplicate_name_replaced_last_wins(protect_mcp_tools):
    register_dynamic_tools([_schema("um_dup_tool", "v1")])
    length_after_first = len(MCP_TOOLS)

    register_dynamic_tools([_schema("um_dup_tool", "v2")])

    entries = [t for t in MCP_TOOLS if t["name"] == "um_dup_tool"]
    assert len(entries) == 1, "同名 schema 必须原地替换，不得出现重复条目"
    assert len(MCP_TOOLS) == length_after_first, "替换不得改变注册表长度"
    assert entries[0]["description"] == "test schema um_dup_tool (v2)", "last-wins：后注册者生效"


def test_duplicate_name_replacement_logs_warning(protect_mcp_tools, caplog):
    register_dynamic_tools([_schema("um_dup_warn", "v1")])
    with caplog.at_level(logging.WARNING):
        register_dynamic_tools([_schema("um_dup_warn", "v2")])
    assert any("last-wins" in r.message and "um_dup_warn" in r.message for r in caplog.records), (
        "重名替换必须留 warning，避免静默掩盖真正的重名 bug"
    )


def test_new_name_appended(protect_mcp_tools):
    length_before = len(MCP_TOOLS)
    register_dynamic_tools([_schema("um_brand_new_tool", "v1")])
    assert len(MCP_TOOLS) == length_before + 1
    assert any(t["name"] == "um_brand_new_tool" for t in MCP_TOOLS)


# ---------------------------------------------------------------------------
# register_enterprise_tool：函数 dict 与 schema 注册表同为 last-wins
# ---------------------------------------------------------------------------


def test_existing_executor_observes_enterprise_tool_replace_and_unregister():
    tool_name = "test_dynamic_enterprise_tool"

    def first_tool(user_id, world_id, auth_token):
        return {"implementation": "first"}

    def second_tool(user_id, world_id, auth_token):
        return {"implementation": "second"}

    register_enterprise_tool(tool_name, first_tool)
    executor = ToolExecutor(file_manager=None)
    try:
        assert executor.execute_tool(tool_name, {}, "7", "world", "token") == {
            "implementation": "first"
        }

        register_enterprise_tool(tool_name, second_tool)
        assert executor.execute_tool(tool_name, {}, "7", "world", "token") == {
            "implementation": "second"
        }

        unregister_enterprise_tool(tool_name)
        assert executor.execute_tool(tool_name, {}, "7", "world", "token") == {
            "error": f"未知工具: {tool_name}"
        }
    finally:
        unregister_enterprise_tool(tool_name)


def test_register_enterprise_tool_last_wins(protect_mcp_tools, protect_enterprise_tools):
    def _first():
        return "first"

    def _second():
        return "second"

    register_enterprise_tool("um_exec_tool", _first, schema=_schema("um_exec_tool", "v1"))
    register_enterprise_tool("um_exec_tool", _second, schema=_schema("um_exec_tool", "v2"))

    assert _enterprise_tool_functions["um_exec_tool"] is _second
    entries = [t for t in MCP_TOOLS if t["name"] == "um_exec_tool"]
    assert len(entries) == 1
    assert entries[0]["description"] == "test schema um_exec_tool (v2)"


def test_main_repo_user_module_tools_end_to_end(protect_mcp_tools, protect_enterprise_tools):
    """主仓 7 个用户模块生成工具注册后：注册表各恰好 1 条，函数来自主仓模块。

    幂等重复注册（模拟迁移期 enterprise 同名覆盖后再由主仓再注册）不得抛错，
    且终态恒为主仓版——这是 server.py 工具再注册步骤所依赖的行为。
    """
    from tools.user_module_agent_tools import (
        register_user_module_agent_tools,
        unregister_user_module_agent_tools,
    )

    expected = {
        "user_module_generation_create",
        "user_module_project_search",
        "user_module_project_read",
        "user_module_generation_get",
        "user_module_generation_read",
        "user_module_generation_write",
        "user_module_generation_validate",
    }

    # 先模拟 enterprise 侧同名注册（假函数占位），再由主仓版覆盖
    for name in expected:
        register_enterprise_tool(name, lambda: "enterprise", schema=_schema(name, "enterprise"))

    register_user_module_agent_tools(register_enterprise_tool)
    register_user_module_agent_tools(register_enterprise_tool)  # 幂等重复注册

    for name in expected:
        entries = [t for t in MCP_TOOLS if t["name"] == name]
        assert len(entries) == 1, f"{name} 在 MCP_TOOLS 中必须恰好 1 条"
        assert entries[0]["description"] != f"test schema {name} (enterprise)", (
            f"{name} 的 schema 终态必须为主仓版，不得残留 enterprise 假 schema"
        )
        func = _enterprise_tool_functions[name]
        assert func.__module__ == "tools.user_module_agent_tools", (
            f"{name} 的执行函数终态必须来自主仓（实际 {func.__module__}）"
        )

    unregister_user_module_agent_tools(unregister_enterprise_tool)
    # 卸载语义（既有行为）：只清函数/metadata 字典，schema 条目保留在 MCP_TOOLS
    assert not any(name in _enterprise_tool_functions for name in expected), (
        "卸载后函数 dict 不应残留"
    )


# ---------------------------------------------------------------------------
# neutralize_enterprise_user_module_binding_load：迁移期 shim
# ---------------------------------------------------------------------------


def test_shim_noop_without_enterprise(monkeypatch):
    monkeypatch.setitem(sys.modules, "enterprise", None)
    from services.user_module_bootstrap import neutralize_enterprise_user_module_binding_load

    assert neutralize_enterprise_user_module_binding_load() is False


def test_shim_patches_old_enterprise(monkeypatch):
    """旧版 enterprise（自带 _register_user_modules）：绑定加载函数被替换为 no-op。"""
    fake = ModuleType("enterprise")
    original_loader = lambda: 42  # noqa: E731
    fake._register_user_modules = lambda app: None
    fake._load_user_module_bindings_safely = original_loader
    monkeypatch.setitem(sys.modules, "enterprise", fake)

    from services.user_module_bootstrap import neutralize_enterprise_user_module_binding_load

    assert neutralize_enterprise_user_module_binding_load() is True
    assert fake._load_user_module_bindings_safely is not original_loader
    assert fake._load_user_module_bindings_safely() is None, "补丁后必须为 no-op"


def test_shim_noop_for_new_enterprise(monkeypatch):
    """新版 enterprise 已移除用户模块（无 _register_user_modules）：天然 no-op。"""
    fake = ModuleType("enterprise")
    original_loader = lambda: 42  # noqa: E731
    fake._load_user_module_bindings_safely = original_loader
    monkeypatch.setitem(sys.modules, "enterprise", fake)

    from services.user_module_bootstrap import neutralize_enterprise_user_module_binding_load

    assert neutralize_enterprise_user_module_binding_load() is False
    assert fake._load_user_module_bindings_safely is original_loader, "不得误伤新版 enterprise"


def test_binding_service_module_has_no_enterprise_gate():
    """主仓版绑定服务不得持有 enterprise 侧引用（分流层已移除，加载无许可证门禁）。"""
    import services.user_module_binding_service as binding_service

    assert "enterprise" not in vars(binding_service)
    assert callable(binding_service.load_user_module_bindings)
