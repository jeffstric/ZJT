# 单次任务算力消耗上限（PowerBudget）

## 背景

无人应答时 agent 会进入「ask_user 提问 → 300s 超时 → LLM 重试 → 再提问」的空转循环，每轮消耗 1–2 算力（见 `docs/backend/incidents/2026-09-01-script-writer-power-confirm-loop.md`、`2026-09-26-script-writer-ask-user-object-options.md`）。长批量任务（如连续生成 60 集剧本）合法消耗也可能超出用户预期。既有保护只有余额熔断（`COMPUTING_POWER_CHECK_THRESHOLD = 1`），兜底太晚。

按产品决策，为**一次任务**引入用户可配置的累计算力消耗上限：达到上限自动暂停任务，充值或调高上限后发送新消息即可继续。**不**修改 `ASK_USER_MAX_CONSECUTIVE_FAILS` 的语义（超时不计入失败，避免无人应答直接杀死可恢复的任务）。

## 机制

- **计量**：任务启动时（`PMAgent.execute` → `PowerBudget.create_for_task`）快照一次余额 `start_balance`；PM/专家循环每轮迭代用最新余额折算 `consumed = start_balance - current`。暂停线比较的是未授权消耗 `consumed - authorized`。
- **已授权生成**：用户在确认门点了「确认生成」或「本次对话不再询问」、本笔落在已同意单价内且高于软阈值、或剧本链路确认门关闭而直接放行时，工具返回的实扣算力记入 `authorized`。一条 303 的 Seedance 确认并生成后，不会因为这笔扣费立刻暂停。同会话下一条同价视频不再弹确认：已同意单价来自本会话已通过的算力确认记录，gunicorn 各 worker 都能读到。没有授权的后续消耗（主要是 LLM 空转）仍累计到上限才暂停。低于软阈值、未经确认就放行的小额生成不划入 `authorized`，继续计入未授权消耗。
- **充值容错**：中途充值使余额高于快照时自动重置快照（视为新预算起点），不会误停。
- **超限**：抛 `PowerBudgetExhaustedError`（`InsufficientComputingPowerError` 的子类），复用既有「算力不足」逐层停止链路：
  1. 专家循环（`expert_agent._run_task_loop` 每迭代 `observe_and_check`）截断历史上抛；
  2. PM 循环（`pm_agent._run_pm_loop` 每迭代）捕获并向会话推送「任务执行停止：已达本次任务算力上限…」消息后结束任务；
  3. `ask_user_mixin._handle_ask_user` 入口超限**立即返回** `ask_disabled`，不创建提问、不进入 5 分钟等待——掐断空转循环。
- **预算传递**：PM 通过 `call_agent` 拉起专家时把同一 `PowerBudget` 实例透传给 `ExpertAgent`，子 agent 不重新快照，计数不重置。
- **fail-open**：余额查询/偏好读取失败时本次任务不启用上限，护栏故障不得阻断任务。

## 上限解析顺序

1. 用户偏好 `user_preferences.power_budget`（用户级，`world_id = "_global"`，值 `{"limit": int}`，0 表示不限制）；
2. 动态配置 `agent.power_budget_default`；
3. 常量 `AGENT_POWER_BUDGET_DEFAULT`（`config/unified_config.py`，当前 200）。

## API（`api/user.py`，Authorization 头认证）

商业版进程在 `enterprise_loader` 成功时挂载独立仓库 `enterprise/routes/user.py`，不会挂载本文件的 router。`power-confirm` 已在该路由按同样路径再注册一层；`power-budget` 目前只定义在本文件。商业版上线前需要在 `enterprise/routes/user.py` 用同样方式再挂 GET/PUT/DELETE `/power-budget`，否则设置接口 404，任务仍按默认上限 200 暂停。

- `GET /api/user/power-budget` → `{limit, is_custom, default_limit}`
- `PUT /api/user/power-budget` body `{limit: int}`（0 = 不限制）
- `DELETE /api/user/power-budget` 删除自定义，回退平台默认

## 前端（script_writer.html）

「模型设置」卡片新增「本次任务算力上限」数字输入：加载时回填当前生效值，修改即保存；清空提交或点击「恢复默认」回退平台默认；悬停图标显示说明（含平台默认值）。词条见 `web/i18n/locales/{zh-CN,en}/index.json` 的 `power_budget_*`。

## 适用范围

`MarketingPMAgent` 继承 `PMAgent.execute`，营销链路同样启用（2026-09-01 事故遗留风险的修复）。执行顺序：任务启动 → 快照 → 循环核对 → 超限暂停 → 用户发送新消息开启新任务（重新快照）继续。

## 测试

`tests/script_writer_core/test_power_budget.py`：超限判定、已授权生成不暂停、充值重置授权额度、哨兵值忽略、fail-open、解析顺序与非法值回退、异常子类契约、ask_user 超限立即返回 / 未超限不受影响。

`tests/script_writer_core/test_power_confirm.py`：已同意单价内不再确认、更贵再确认、免打扰后单笔高于硬阈值不再确认、多笔小额累计仍确认、从确认记录还原最高价（取消不计入）。
