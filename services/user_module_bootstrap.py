"""用户模块（接口模块）子系统主仓引导入口（develop_f1214 起，主仓恒为 owner）。

背景：用户模块原随商业版 enterprise 包提供（路由/运行时/调度/生成工具均从
enterprise.* 导入）。develop_f1214 将完整子系统迁入主仓并解除商业许可证门禁。

2026-11-20 起归属决策落地：主仓是用户模块的唯一 owner，所有挂载点恒用主仓版，
不再看 enterprise 是否自带旧版实现（分流开关 enterprise_provides_user_modules
已删除）。迁移期内存量 enterprise 包仍自带旧版实现，三者的共存关系：

- 路由：主仓版先挂载（server.py 中先于 enterprise 加载），FastAPI 同路径先
  注册者胜，enterprise 旧版同名路由后注册、被自然阴影（死代码）；
- 生成工具：enterprise.register 仍会用同名工具覆盖主仓版（dict/schema 均
  last-wins），server.py 在 enterprise 加载后用主仓版再注册覆盖回来；
- 绑定加载：enterprise 旧版"先全量清空注册表 + 许可证未激活不重载"会抹掉
  主仓刚注册的实现方，由 ``neutralize_enterprise_user_module_binding_load``
  中和为 no-op，绑定只由主仓侧加载。

enterprise 仓移除用户模块并抬升 min_core_version 后，阴影/覆盖/shim 自然消失。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def neutralize_enterprise_user_module_binding_load() -> bool:
    """迁移期 shim：禁用 enterprise 旧版"先清空注册表"的用户模块绑定加载。

    仅当旧版 enterprise（自带 _register_user_modules）已在当前进程导入时生效：
    经 sys.modules 探测（不打断 enterprise_loader 的加载决策、无 import 副作用），
    把 enterprise._load_user_module_bindings_safely 替换为 no-op。enterprise 的
    Web 启动钩子（enterprise/__init__.py:442）与绑定重载循环（453 行）均在调用时
    经模块全局名解析，补丁对两者同时生效；bootstrap_background_process
    （enterprise/__init__.py:84）同理。新版 enterprise 移除用户模块后 hasattr 为
    False，本函数天然 no-op。PyArmor 混淆不影响模块属性 setattr。
    """
    import sys

    enterprise = sys.modules.get("enterprise")
    if enterprise is None:
        return False
    if not hasattr(enterprise, "_register_user_modules"):
        return False  # 新版 enterprise 已移除用户模块子系统
    if getattr(enterprise, "_load_user_module_bindings_safely", None) is None:
        return False

    def _noop() -> None:
        return None

    enterprise._load_user_module_bindings_safely = _noop
    logger.info("已中和 enterprise 旧版用户模块绑定加载（主仓恒为 owner）")
    return True


def _load_bindings_safely() -> None:
    try:
        from services.user_module_binding_service import load_user_module_bindings

        loaded = load_user_module_bindings()
        logger.info("User module bindings loaded: %d", loaded)
    except Exception:
        logger.exception("加载用户模块实现方绑定失败，模型下拉暂不包含用户模块")


def _register_agent_tools() -> None:
    try:
        from tools.user_module_agent_tools import register_user_module_agent_tools
        from script_writer_core.agents.tool_executor import register_enterprise_tool

        register_user_module_agent_tools(register_enterprise_tool)
    except Exception:
        logger.exception("注册用户模块生成工具失败")


def bootstrap_user_modules(app) -> None:
    """主仓版用户模块挂载：路由 + Supervisor 启动验证 + 绑定重载循环 + 生成工具。

    server.py 无条件调用且必须先于 enterprise 加载（路由先注册优先）；
    enterprise 旧版同名路由/工具/绑定加载分别被阴影/再注册覆盖/shim 中和。
    """
    import os

    from api.user_module_admin import router as user_module_admin_router
    from api.user_modules import router as user_modules_router
    from config.constant import USER_MODULE_ENABLED_ENV_NAME

    # 用户模块只通过固定网关转发到独立 Supervisor；核心进程不导入用户模块代码。
    app.include_router(user_modules_router)
    app.include_router(user_module_admin_router)

    @app.on_event("startup")
    async def verify_user_module_supervisor_startup():
        """让每个 Web Worker 在开始接流量前验证唯一 Supervisor，而不是自行加载用户代码。"""
        from module_runtime.client import SupervisorClient, SupervisorClientError

        enabled = os.environ.get(USER_MODULE_ENABLED_ENV_NAME, "true").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            return
        client = SupervisorClient()
        if not client.base_url or not client.token:
            logger.warning("用户模块 Supervisor 未配置；/api/modules 将返回服务不可用")
            return
        try:
            await client.health()
        except SupervisorClientError as exc:
            logger.error("用户模块 Supervisor 启动验证失败: %s", exc)
        # 绑定加载放在 startup：实现方注册影响模型下拉与调度
        _load_bindings_safely()
        # web 进程周期重载：调度器进程先行感知绑定变化时，本进程的模型下拉/
        # 实现方列表最长一个重载间隔内自动跟上。
        from config.constant import USER_MODULE_BINDING_RELOAD_INTERVAL_SECONDS

        async def _binding_reload_loop():
            while True:
                await asyncio.sleep(USER_MODULE_BINDING_RELOAD_INTERVAL_SECONDS)
                await asyncio.to_thread(_load_bindings_safely)

        app.state._user_module_binding_reload_task = asyncio.create_task(
            _binding_reload_loop()
        )

    _register_agent_tools()


def bootstrap_user_modules_background() -> None:
    """无 FastAPI app 的后台进程引导：绑定加载 + 生成工具（调度器/智能体 worker）。

    Supervisor 与 HTTP 路由仅由 Web/Manager 进程负责。
    """
    _load_bindings_safely()
    _register_agent_tools()


__all__ = [
    "bootstrap_user_modules",
    "bootstrap_user_modules_background",
    "neutralize_enterprise_user_module_binding_load",
]
