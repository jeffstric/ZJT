"""用户模块（接口模块）子系统主仓引导入口（develop_f1214 起）。

背景：用户模块原随商业版 enterprise 包提供（路由/运行时/调度/生成工具均从
enterprise.* 导入）。develop_f1214 将完整子系统迁入主仓并解除商业许可证门禁，
但存量 enterprise 包仍自带旧版实现（带许可证门禁）。为避免双份路由、双份
调度任务、双份 Supervisor 与双份生成工具注册，所有挂载点统一经
``enterprise_provides_user_modules()`` 分流：

- enterprise 包提供该能力（``enterprise.register``/bootstrap 含用户模块）→
  继续走 enterprise 版，主仓实现静默让位（行为与旧版一致，仍受许可证门禁）；
- enterprise 缺席或其新版已移除用户模块 → 主仓版接管（无门禁）。

迁移完成后（enterprise 仓移除用户模块并抬升 min_core_version），分流判定
恒走主仓版，届时可整体删除该兼容层。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def enterprise_provides_user_modules() -> bool:
    """enterprise 包是否实际接管用户模块（自带旧版实现且处于企业版模式）。

    与 utils/enterprise_loader.discover() 的第一道门一致：edition.mode !=
    enterprise 时 enterprise 不会注册任何路由，此时必须由主仓版接管，否则
    本地含 enterprise 目录的开源部署会出现"模块既不在 enterprise 侧也未在
    主仓侧挂载"的真空。企业版模式下再看旧版 __init__ 是否保留
    _register_user_modules（新版移除后恒走主仓版）。
    """
    try:
        from config.config_util import get_config_value

        mode = str(get_config_value("edition", "mode", default="community") or "community")
        if mode.strip().lower() != "enterprise":
            return False
        import enterprise

        return hasattr(enterprise, "_register_user_modules")
    except Exception:
        return False


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

    仅当 enterprise 不提供该能力时由 server.py 调用；与 enterprise 版互斥。
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
    "enterprise_provides_user_modules",
]
