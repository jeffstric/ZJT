# 接口自动对接（用户模块/接口模块）开放给开源版 — 实现方案

> 状态：已实现（2026-11-20，branch: develop_f1214）。实际落地与本修订版（含 4.6 的 shim 修订）一致；§5.1 所列测试已补齐：`tests/script_writer_core/test_enterprise_tool_dynamic_registry.py` 扩展同名替换/shim/主仓工具终态用例，`tests/api/test_admin_commercial_gates.py` 补 `features.user_modules` 恒 True 用例。
> 决策已确认：**接口模块归属 comfyui_server 主仓，主仓恒为 owner；enterprise 包不改动、不发布新包。**
> 本次修订：对照当前代码逐条复核后修正 3 处（见「0. 审查记录」），核心是给原方案补一个致命漏洞的修复。
> 关联文档：`docs/backend/user_modules.md`（子系统主文档）、`docs/版本差异说明.md`。

## 0. 审查记录（2026-11-20）

对原方案逐条代码复核结论：**主干方向与根因分析全部属实**（分流开关、enterprise 挂载点、features 上报、主仓链路无门禁、两侧路由一致、工具注册机制、运行时 deactivate/reactivate 不碰用户模块、现有测试无冲突断言——均已核实）。但原方案有 1 处致命漏洞、3 处细节问题，本次修订已修正：

- **【致命·新增 2.4 与 4.2】enterprise 侧绑定加载"先全量清空注册表"会抹掉主仓注册**。原方案 §3 只论证了"两侧读同一张 DB 表"，漏了进程内注册表是共享全局对象。不补这条，按原方案做完后页面解锁、接口 200，但实现方绑定被清空、功能仍是坏的，且原验证清单查不出来。
- **【修正 4.6】原"task/sync_task_executor.py 163-182 行 enterprise 后台 bootstrap 不动"与目标矛盾**——正是这段代码（经 `bootstrap_background_process` 第 84 行无条件调用）把 worker 进程里主仓刚加载的绑定抹掉。改为：仍保留该调用（Provider/许可证 runtime 仍需），但调用前先打 4.2 的中和 shim。
- **【修正 4.3】`register_dynamic_tools` 同名替换从"完全静默"改为 warning 日志**，保留重名可排查性；并明确 4.1 步骤 4（工具再注册）依赖 4.3 先落地，执行顺序不可交换。
- **【补充 5】验证清单增加绑定注册表非空检查、reload 间隔后复查、sync worker 场景、动态注册表测试**。

## 1. 背景与目标

「接口自动对接」= 管理后台**用户模块（接口模块）**子系统：AI 自动对接图片/视频供应商接口 → 审批发布 → 绑定任务（前端 `web/admin.html` 的 `userModules` 页 + `web/js/admin/user_modules.js`）。

develop_f1214 已把整个子系统从 enterprise 商业包迁入开源主仓（commit `ab41a92f`），**主仓版实现无任何商业许可证门禁**（已核实：`api/user_modules.py`、`api/user_module_admin.py`、`task/user_module_task.py`、`task/user_module_driver.py`、`services/user_module_*.py`、`module_runtime/generation.py`、`tools/user_module_agent_tools.py` 全链路无 license/enterprise 引用，唯一例外是分流开关本身所在的 `services/user_module_bootstrap.py`）。

**目标**：开源版（以及"商业部署但许可证已注销/过期"的状态）可正常使用接口模块。

### 用户报告的现象

admin.html 注销商业版密钥后，接口模块页显示锁定卡片「接口模块为商业版功能」（i18n `um_locked_title/desc`，`web/i18n/locales/zh-CN/admin.json:1075-1076`），功能不可用。

## 2. 根因分析（已核实）

现象环境 = `edition.mode: enterprise`（`config_prod.yml:59`）+ 本地存在旧版 `enterprise/` 包（git-ignored，未随主仓发布，仍自带用户模块旧实现）。

1. **分流开关不看许可证**：`enterprise_provides_user_modules()`（`services/user_module_bootstrap.py:25`）只判 `mode==enterprise` + 旧版 `hasattr(enterprise, "_register_user_modules")`。注销密钥后仍返回 True → 主仓版全部让位给 enterprise。
2. **enterprise 启动时无条件挂载**：`enterprise/__init__.py:394-469` `_register_user_modules(app)` 无条件挂载 `/api/modules`、`/api/admin/user-modules` 路由（挂 `require_strict_commercial_http_access` strict 门禁，注销后全 403）、注册 Supervisor 启动验证、绑定重载循环、7 个同名 agent 工具（工具内 `_require_user_module_admin` 多一层 strict 许可证检查，见 `enterprise/tools/user_module_agent_tools.py:128-135`）。
3. **features 上报**：`api/admin.py:212` `"user_modules": _is_user_module_available(...)`（84-98 行）= `registration_ready AND 许可证严格激活` → 注销后 False → 前端 `userModulesAvailable=false`（`web/js/admin.js:1608/2204`）→ 显示锁定卡片（`web/admin.html:1386`）。
4. **【致命·原方案遗漏】enterprise 绑定加载"先清空再按许可证决定"**：
   - `enterprise/services/user_module_binding_service.py:127-133`：`load_user_module_bindings()` 先 `_unregister_all_dynamic_locked()` **全量清空进程内注册表**，然后 `if not _commercial_license_allows_user_modules(): return 0`——注销时清空后不重载。
   - 调用点：enterprise Web 启动钩子（`enterprise/__init__.py:442`）与其绑定重载循环（453 行）；以及 `enterprise.bootstrap_background_process`（`enterprise/__init__.py:84`，**无条件**执行，不受 `include_marketing_tools=False` 影响）。
   - 注册表（`UnifiedConfigRegistry`/`VideoDriverFactory`）是**进程级全局对象**，两侧绑定服务写入的是同一个全局状态；enterprise 的清空不是清"自己那份"，而是清掉全进程动态实现方。
   - 后果：只去分流不打 shim 的话——Web 进程 startup 主仓加载 → enterprise 钩子清空，且每轮 reload 主仓先加载、enterprise 后清空，注册表长期为空 → 页面解锁但模型下拉/实现方列表为空；sync worker 内 enterprise bootstrap 把主仓刚加载的绑定抹掉 → 同步任务找不到用户模块实现方。

### 为何不能简单"注销时主仓接管"

- **路由阴影**：FastAPI 同路径先注册者胜。`server.py` 中 enterprise 加载（721 行）在主仓用户模块挂载（740 行）之前，主仓版后挂载永远被阴影 → 接口仍 403。
- **工具半覆盖**：`register_dynamic_tools`（`script_writer_core/mcp_tool.py:3405`）遇重名 schema 直接 `raise ValueError`。双侧都注册 7 个同名工具时：先注册方占住 `MCP_TOOLS`，后注册方在 `register_enterprise_tool`（`script_writer_core/agents/tool_executor.py:59-78`，函数 dict 先写、schema 后注入）里只覆盖到第 1 个函数就因 schema 重名抛错中断 → "半主仓半 enterprise" 混合态（`user_module_generation_create` 是 dict 第一个，恰好是核心工具）。
- 运行时注销/激活（`enterprise/routes/commercial_license.py` 的 deactivate/reactivate，无需重启）会令上述状态与 UI 不一致。

## 3. 方案：主仓恒为 owner（把迁移终态提前落地）

`docs/backend/user_modules.md` 头部已规划终态："enterprise 仓移除用户模块并抬升 min_core_version 后，分流恒走主仓版，兼容层可整体删除"。本方案直接把主仓定为**唯一 owner**，所有分流开关移除，不再看许可证。归属决策（2026-11-20 已拍板）：接口模块放 comfyui_server 主仓，enterprise 不动、不发新包——理由见 6。

| 部署形态 | 改前 | 改后 |
|---|---|---|
| 纯开源（无 enterprise 目录 / community 模式） | 主仓服务 ✓ | 不变（主仓挂载、无门禁） |
| 商业 + 许可证有效 | enterprise 版服务（有门禁） | **主仓版服务（无门禁）**——代码同源，商业版是开源超集，不缩水 |
| 商业 + 许可证注销（用户场景） | 全锁定 ✗ | **主仓版正常服务** ✅ |

enterprise 包旧版用户模块路由/工具在迁移期成为死代码（被主仓阴影/覆盖），待 enterprise 仓移除用户模块后自然消失。**本方案不改 enterprise 包**（独立商业仓；本 checkout 的 `enterprise/` 只是本地副本，git-ignored）。

### 安全性论证（已核实）

- 两侧绑定注册表（主仓 `services/user_module_binding_service.py` vs `enterprise/services/user_module_binding_service.py`）读**同一张 DB 表**（`model/user_module_binding.py` `UserModuleTaskBindingModel`），`implementation_id` 来自 DB（`next_implementation_id()`），跨侧/跨进程一致。
- **【关键补充】进程内注册表是共享全局对象**：enterprise 侧 load 的"先全量清空"会抹掉主仓侧刚注册的内容（见 2.4）。因此必须配合 4.2 的 shim 禁用 enterprise 侧绑定加载；shim 生效后绑定只由主仓侧加载，无一致性问题。
- Supervisor 子进程由 manager（`scripts/running/run_prod.py` / `run_dev.py`）以主仓 `module_runtime.supervisor` 拉起（`task/module_supervisor_launcher.py:57`），运行时本就是主仓代码。
- 已确认 `enterprise/` 包不引用 `enterprise_provides_user_modules`（grep 无命中），删除该函数无外部影响。
- 已确认剧本拆分 worker 链路（`task/script_split_task.py`、`script_writer_core/`）不解析实现方 ID（无 `get_implementation_id/name` 引用），无需改 `run_script_split_worker.py`。
- 已核实运行时 deactivate/reactivate（`enterprise/services/license/runtime.py:272-319`）不触碰用户模块工具与绑定（`unregister_enterprise_tool`/`unregister_user_module_agent_tools` 仅测试在用），无运行时卸载风险。

## 4. 改动清单

### 4.1 `server.py`（~714-743）— 核心：挂载顺序 + 中和 shim + 工具再注册

现状：

```python
# 714-715: 注释"用户模块（接口模块）属商业版能力……由 enterprise.register(app) 注入"
# 717-732: try: enterprise_loader.discover()/load(app)  else: api.user 社区路由
# 734-743: try: if not enterprise_provides_user_modules(): bootstrap_user_modules(app)
```

改为（顺序）：

1. **主仓用户模块无条件挂载，且移到 enterprise 加载块之前**（714-715 行注释一并更新为"接口模块为主仓能力（develop_f1214 起，无商业门禁）；必须先于 enterprise 挂载，迁移期内 enterprise 包自带的旧版同名路由后注册，被 FastAPI 同路径先注册优先自然阴影"）：

```python
try:
    from services.user_module_bootstrap import bootstrap_user_modules
    bootstrap_user_modules(app)
except Exception:
    logging.getLogger(__name__).exception("主仓用户模块挂载失败（接口模块将不可用）")
```

2. enterprise 加载块（717-732）**保持不变**。

3. **enterprise 加载块之后新增：中和 shim**（必须先于下方工具再注册执行；防止 enterprise 旧版清空主仓绑定注册表，见 2.4）：

```python
# 迁移期 shim：enterprise 旧版 _register_user_modules 的启动钩子与绑定重载循环会调用
# enterprise 侧绑定加载，其"先全量清空注册表 + 许可证未激活不重载"会抹掉主仓刚注册的
# 实现方。禁用该函数后绑定只由主仓侧加载（enterprise 新版移除用户模块后为纯 no-op）。
try:
    from services.user_module_bootstrap import neutralize_enterprise_user_module_binding_load

    neutralize_enterprise_user_module_binding_load()
except Exception:
    logging.getLogger(__name__).exception("enterprise 旧版用户模块绑定加载中和失败")
```

4. **继续新增主仓生成工具再注册**（enterprise 的 `register()` 会用同名工具覆盖主仓工具；配合 4.3 的"同名替换"语义，last-wins 生效。**注意：本步骤依赖 4.3 先落地**，否则幂等重复注册会触发旧的重名抛错。无 enterprise 时是幂等重复注册，无副作用）：

```python
# enterprise.register() 会用同名工具覆盖主仓用户模块生成工具（迁移期并存）；
# 再注册主仓版保证智能体工具链恒走主仓（无许可证门禁）。
try:
    from tools.user_module_agent_tools import register_user_module_agent_tools
    from script_writer_core.agents.tool_executor import register_enterprise_tool

    register_user_module_agent_tools(register_enterprise_tool)
except Exception:
    logging.getLogger(__name__).exception("主仓用户模块生成工具再注册失败")
```

### 4.2 `services/user_module_bootstrap.py` — 新增 shim + 删分流开关

- **新增** `neutralize_enterprise_user_module_binding_load() -> bool`：

```python
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
```

- **删除** `enterprise_provides_user_modules()`（25-44 行）及 `__all__` 项（128 行）——改后全仓无调用点（4.1/4.4/4.5/4.6 全部移除引用；已核实 enterprise 包不引用）。
- 更新模块 docstring（1-15 行）与 `bootstrap_user_modules` docstring（68-71 行）：主仓恒为 owner；迁移期内 enterprise 旧版路由被阴影（路由先注册优先）、旧版生成工具被主仓再注册覆盖（工具 last-wins + 动态 schema 同名替换）、旧版绑定加载被 shim 中和；enterprise 仓移除用户模块后阴影/覆盖/ shim 自然消失。
- `bootstrap_user_modules` / `bootstrap_user_modules_background` 函数体不变。

### 4.3 `script_writer_core/mcp_tool.py` `register_dynamic_tools`（3405-3418）

现状：

```python
for tool_def in tool_defs:
    name = tool_def.get("name")
    if not name or any(t.get("name") == name for t in MCP_TOOLS):
        raise ValueError(f"动态工具名缺失或重复: {name!r}")
MCP_TOOLS.extend(tool_defs)
```

改为：名字缺失仍抛错；已存在同名 → **原地替换**（last-wins，迁移期主仓/enterprise 双侧注册同名用户模块工具，后注册者生效），**重名时打 warning 日志**（保留排查性，避免完全静默掩盖其它真正的重名 bug），否则 append：

```python
for tool_def in tool_defs:
    name = tool_def.get("name")
    if not name:
        raise ValueError(f"动态工具名缺失: {tool_def!r}")
    for i, existing in enumerate(MCP_TOOLS):
        if existing.get("name") == name:
            MCP_TOOLS[i] = tool_def
            logger.warning("动态工具 schema 重名，已按 last-wins 原地替换: %s", name)
            break
    else:
        MCP_TOOLS.append(tool_def)
```

docstring 补一句同名替换（last-wins + warning）的语义。

### 4.4 `api/admin.py` — `features.user_modules` 恒为 True

- 212 行：`"user_modules": True`，注释改为"接口模块（用户模块）为主仓能力（develop_f1214 起），社区/商业版均可用，无商业许可证门禁"。
- **删除** `_is_user_module_available`（84-98 行）与 `_is_user_module_license_active`（101-113 行）。
- 其它（`_is_commercial_base_license_active`、`_get_enterprise_admin_status`、dashboard 其余字段）不动。

### 4.5 `config/unified_config.py` `_user_module_binding_service`（1901-1917）

去掉分流分支，恒返回主仓 `services.user_module_binding_service`（保留函数内 import，避免 config→services 顶层循环依赖）。docstring 说明：两侧注册表读同一张绑定表、`implementation_id` 来自 DB 跨侧一致，且 enterprise 侧绑定加载已被 shim 中和（4.2），恒读主仓版安全。

### 4.6 各挂载点去分流，恒用主仓版

| 文件 | 位置 | 改法 |
|---|---|---|
| `task/scheduler.py` | 737-754 | 恒 `from task.user_module_scheduler import register_user_module_scheduler_jobs`（与 `enterprise/task/user_module_scheduler.py` diff 仅 docstring，已核实）；注释同步更新 |
| `task/sync_task_executor.py` | 147-162 | 恒调 `bootstrap_user_modules_background()`；**保留** try/except + 日志、**保留**"放在 community early-return 之前，两版通吃"的位置 |
| `task/sync_task_executor.py` | 163-182 | **【修订】enterprise 后台 bootstrap 仍需调用**（Provider/许可证 runtime 仍需），但其内部第 84 行会**无条件**执行 enterprise 侧绑定加载并清空主仓注册（2.4）——在 `enterprise.bootstrap_background_process(...)` 调用**之前**插入 `neutralize_enterprise_user_module_binding_load()`（4.2 的同一 shim；worker 进程已 `import enterprise`，经 sys.modules 命中，补丁对其内部调用同样生效）。`include_marketing_tools=False` 时 enterprise 不注册用户模块工具，不存在工具互踩 |
| `scripts/running/run_prod.py` | 77-95 `_start_module_supervisor` | 恒 `from task.module_supervisor_launcher import start_module_supervisor`（ImportError 兜底返回 None 保留）；docstring 更新 |
| `scripts/running/run_dev.py` | 95-114 | 同上，恒用主仓 launcher；`user_modules.enabled` 配置判断保留 |

### 4.7 明确不改的部分

- **前端零改动**：`web/admin.html` 锁定卡片（1386-1394 行）、`web/js/admin.js` 的 `userModulesAvailable`（1055/1608/1921/2204 行）、`um_locked_*` i18n 全部保留——后端 `features.user_modules` 恒 True 后锁定卡片永不显示（i18n 变死文案，保留无害）。
- **enterprise 包不改**（独立商业仓）。`enterprise/tests/test_user_module_license_gate.py` 是 enterprise 仓专测该门禁的测试，仅在"路线 B（放开 enterprise）"下才需要处理；本方案不涉。
- **`scripts/running/run_script_split_worker.py` 不改**：拆分 worker 不解析实现方 ID；且历史上 `include_marketing_tools=False`（263 行）故意不在该进程注册用户模块 agent 工具，避免改变拆分 agent 的工具面。

### 4.8 文档同步（CLAUDE.md 规则 2）

- `docs/backend/user_modules.md` 头部"新旧并存分流"段（约 15-21 行）：改为"主仓恒为 owner；enterprise 旧版路由/工具/绑定加载在迁移期分别被阴影/覆盖/ shim 中和，兼容分流已移除"。
- `docs/版本差异说明.md`：第 30 行商业版能力清单中**移除"接口模块"**，补一句"接口模块（用户模块）自 develop_f1214 起为主仓能力，社区/商业版均可用，不要求商业许可证激活"。
- 本文档状态行更新为"已实现"并注明实际落地与 4.6 修订一致。

## 5. 验证

1. **回归测试**：
   `pytest tests/api/test_admin_commercial_gates.py tests/test_user_module_generation_tool_routing.py tests/script_writer_core/test_enterprise_tool_dynamic_registry.py tests/module_runtime/ -x`
   （`test_enterprise_tool_dynamic_registry` 为新增：4.3 改了共享函数语义，必须一并跑。如需补测：`register_dynamic_tools` 同名替换行为、`features.user_modules` 恒 True。）
2. **混合部署模拟用户场景**（本 checkout 自带 `enterprise/` 目录；用 `edition.mode: enterprise` 配置启动 `scripts/running/run_dev.py`）：
   - 不激活许可证（或 admin 调 `POST` 许可证 deactivate 注销）→ 打开 admin.html「接口模块」页：应显示完整管理面板而非锁定卡片；
   - `GET /api/admin/user-modules`（admin token）应 200 而非 403；
   - **【新增】startup 日志确认"已加载 N 条用户模块实现方绑定"且 N>0**（或 `/api/admin/user-modules` 模块列表非空），且**不出现**"商业许可证未激活：用户模块实现方绑定保持卸载"；
   - **【新增】等待超过一个 `USER_MODULE_BINDING_RELOAD_INTERVAL_SECONDS` 后再查一次绑定仍非空**——验证 shim 对 enterprise 重载循环同样生效、无"加载-清空"抖动；
   - 日志确认主仓 Supervisor 健康检查通过。
3. **工具注册一致性**（混合模式启动后）：`script_writer_core.agents.tool_executor._enterprise_tool_functions` 中 7 个 `user_module_*` 工具的 `__module__` 均为 `tools.user_module_agent_tools`（非 enterprise 侧）；`MCP_TOOLS` 中每个工具名仅 1 条。
4. **开源回归**：`edition.mode: community`（config_dev 默认）+ enterprise 目录在场 → 功能照常（行为与改前一致）。
5. **冒烟**：`python -c "import server"` 无路由/工具注册异常。
6. **【新增】sync worker 场景**：触发一次走用户模块实现方的同步任务，确认 worker 内能找到实现方（验证 4.6 修订的 shim 在 worker 进程生效、绑定未被 enterprise 清空）。

### 5.1 实施验证记录（2026-11-20）

- 回归测试：`tests/api/test_admin_commercial_gates.py` + `tests/test_user_module_generation_tool_routing.py` + `tests/script_writer_core/test_enterprise_tool_dynamic_registry.py` 共 24 passed；`tests/script_writer_core/` + `tests/module_runtime/` 全目录 486 passed / 1 skipped / 1 failed——该失败（`test_expert_agent_media_context`）经 stash 基线对比为存量失败，与本改动无关。
- 冒烟：`import server` OK（community 模式，109 drivers 注册，无异常）。
- 混合部署模拟（`temp/verify_mixed_enterprise_mode.py`，community 配置下 patch discover 走 enterprise 分支）：shim 日志出现且 `enterprise._load_user_module_bindings_safely` 被替换为 `services.user_module_bootstrap` 的 no-op；7 个用户模块工具执行函数终态 `__module__ == 'tools.user_module_agent_tools'`、MCP_TOOLS 各恰好 1 条；主仓两个路由 wrapper（`/api/modules`、`/api/admin/user-modules`）先于 enterprise 注册。
- **【环境发现 1】本地 fastapi 0.141.1 下 enterprise 旧包 `register()` 中途失败**（`'FastAPI' object has no attribute 'add_event_handler'`，branding 等组件用了新版已移除的 API），stash 基线同样失败——存量版本兼容问题，与本方案无关；主仓路径不依赖 enterprise 注册成功，真实生产环境版本配套不受影响。
- **【环境发现 2】fastapi 0.141 的 `include_router` 产生 `_IncludedRouter` 惰性包装**（`app.routes` 里不再直接展开 APIRoute），路由匹配仍按注册顺序遍历，"先注册优先阴影"结论不变；排查路由时需看 `wrapper.original_router`。
- CI lint：`lint_blocking_calls.py` exit 0（仅存量 R5 advisory）、`lint_tool_executor_signature.py`、`lint_migration_names.py`、`lint_frontend_xss.py` 全部通过。

## 6. 风险与边界

- **商业版行为变化**：许可证有效时接口模块由主仓版服务（enterprise 旧路由变死代码）——这是"开放给开源版"的目标方向，商业版功能不缩水（代码同源）。
- **迁移期冗余**（混合部署）：enterprise 侧仍注册旧路由（被阴影）、跑第二份 Supervisor 健康检查与绑定重载循环。打上 shim 后 enterprise 侧绑定加载变 no-op，其重载循环成为空转噪音（`app.state._user_module_binding_reload_task` 被后注册者覆盖，两份循环并存至进程退出；现状本无 shutdown 清理，属既有噪音）；enterprise 仓移除用户模块后全部消失。
- **【新增】shim 的适用边界**：依赖 enterprise 模块属性可 setattr（PyArmor 混淆不保护模块 `__dict__`，有效）；若未来 enterprise 改为冻结模块/C 扩展，shim 需改为"enterprise bootstrap 后由主仓补加载一次"的兜底策略。shim 经 `sys.modules` 探测、无 import 副作用，community 模式与新版 enterprise 下天然 no-op。
- **【记录】路线 B（放开 enterprise 门禁）已评估并否决**：①前端锁定卡片的数据源 `features.user_modules` 在主仓 `api/admin.py` 计算，enterprise 全放开也躲不掉主仓改动，不存在"只改 enterprise"；②终态是 enterprise 仓删除子系统，放开属返工；③需 enterprise 出新版且双包同步更新（min_core_version 耦合、混合版本窗口）；④双份路由/循环/工具的并存噪音从"迁移期临时态"变永久态。
- **CI 红线**（CLAUDE.md 规则 9/10/11）：本改动无新增 `Future.result()`/线程池；4.2 shim 的 `import sys` 为该函数内首次引用，不违反 R7。
- 若实现中发现 `web/js/admin.js` 其它地方对 `features.user_modules` 有隐藏依赖（如菜单显隐），以"恒 True"为准复核一遍即可，预期无。
