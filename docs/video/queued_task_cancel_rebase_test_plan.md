# 排队任务取消：rebase 后上线测试方案（S0 覆盖）

> 背景：develop_f997（排队任务取消，后端 11999082 + 前端 e4806e7c）于 2026-10-23
> rebase 到最新 origin/develop（基点 c7ae8138 → 7f84c083c，跨越 216 个提交），
> rebase 结果 fc029daa..2f833f474 已推送。本文档给出上线前的针对性测试方案，
> 核心目标是覆盖 S0 级资金/算力风险：**取消没生效（上游照跑）却退了算力**、
> **重复退费**、**取消后任务复活再烧上游**。

## 0. S0 风险模型（不变量）

取消 × 上游提交 × 退费三者的状态错位是全部 S0 的来源。以下不变量任何一条
被破坏都是 S0，测试必须逐条对应覆盖：

| # | 不变量 | 破坏后果 |
|---|--------|----------|
| I1 | CAS 置 CANCELLED 终态的任务，之后绝不发生上游提交调用 | 退了算力 + 上游照跑 = 直接资损 |
| I2 | 已过提交闸门（PROCESSING）的任务取消必 409，绝不退费 | 用户拿结果 + 拿退款 |
| I3 | 退费恰好一次且金额 = 实扣金额（refund-{transaction_id} 幂等键） | 重复退费 / 少退引发客诉 |
| I4 | ai_tools/tasks 双表最终一致收敛到 CANCELLED，调度器不再拾取 | 任务"复活"重新提交上游 |
| I5 | 取消后占用的资源（RunningHub 槽位/密钥）最终归还 | 并发容量泄漏，全站排队 |

互斥机制（详见 `queued_task_cancel_design.md`）：取消接口与调度器三处提交闸门
（0→4 / 0→3 / 0→1）在 ai_tools 同一行上做条件 UPDATE，DB 行锁串行先到先得。
**该机制的正确性依赖真实 MySQL 行锁行为，mock 单测证明不了**（参数错序事故
即单测全绿但真库全错，见设计文档 §8 事故复盘）。

## 1. rebase 引入的新风险点（本次重点）

rebase 冲突恰好落在取消互斥的核心区域，以下回归点已代码核验 + 补测试，
上线前仍需真库/E2E 复验：

1. **PROCESS_RESULT 协议迁移**：origin/develop 把处理函数返回值从 `True/False`
   重构为 `PROCESS_RESULT_SUCCESS/FAILED/IN_FLIGHT` 字符串常量。f997 新增的
   取消守卫分支 `return True` 靠 1629 行的遗留兼容（`result is True` 按成功计）
   保持正确。风险：今后有人删除该兼容行。→ 已补 5 个测试锁定
   （`TestPipelineStageAdvanceCancelGuard`）。
2. **新状态 DOWNLOADING(6)**：下载队列解耦后新增。不在可取消集合（409），
   但已加入 ACTIVE 集合（过期写 FAILED 不覆盖取消终态）。语义正确，
   E2E 需验证「下载中点取消 → 409 + 前端按钮消失」。
3. **sync worker fork→spawn 重构**：子进程重新 import，CAS 闸门代码路径不变，
   但 spawn 模式下闸门首次真实执行需 E2E 验证（单测 mock 了 transition_status）。
4. **数字人 compose_job 补段（新代码）**：取消分段任务 → compose_job 视为缺口
   → 重新计费补段，受 MAX_RETRY_COUNT 约束有界。需 E2E 验证不无限补段、
   主任务终态正确。
5. **实现方重试链路**：before_finish 完成后 implementation_retry_driver 无条件
   写回 PENDING(0) → 重新变为可取消。合法（未提交上游），但 E2E 应覆盖
   「重试等待中取消」场景。

## 2. 测试分层

> **⚡ 执行状态（2026-10-23）**：L1/L2 已全部执行通过；L3 已自动化 9 项（E1/E2/E4/E4b/E5/
> E6/E11/属主 403/无鉴权 401/get-status 契约），另发现 1 个真实缺陷（见 §2.5）。
> 测试资产：`tests/integration/test_cancel_concurrency.py`（15 用例）、
> `tests/integration/test_cancel_endpoint_e2e.py`（9 过 + 1 xfail）。

### 2.5 执行发现（缺陷与实证）

1. **【缺陷·S1】退款失败提示为死代码**：`_refund_computing_power`
   （task/visual_task.py:250-274）所有失败路径静默 return、外层 except 吞异常，
   永不向上抛 → 取消接口 `refund_done` 恒 True → 「退款处理中，如未到账请联系客服」
   提示永远不出现。实测（E11，服务日志 "Failed to get auth token" 已证实退款真实
   失败但响应仍是「任务已取消」）。**影响**：退款失败用户无感知，只能靠 §L4 对账
   名单兜底。修复方向：让 `_refund_computing_power` 返回成败（或在 endpoint 侧
   复查 `is_already_refunded`）。已用 xfail 用例锁定（修复后去掉装饰器即转绿）。
2. **【实证】I1/I2 互斥成立**：真库 100 轮屏障竞态（取消 vs 0→1 上游提交闸门）
   每轮恰好一方成功，双侧都赢过；HTTP×DB 20 轮竞态 XOR 干净；
   「取消先行 → 闸门 0 行 + project_id 保持 NULL」确定性用例通过。
3. **【实证】入池/预处理后取消合法且安全**：0→3/0→4 与取消目标状态重叠，
   「闸门赢→取消再赢」是设计内时序（最终 CANCELLED），且后续 worker 闸门
   3→1、完成推进 4→0 均 0 行——不复活、不调上游（R2/R3 各 100 轮）。
4. **【实证】并发双取消恰好一个 affected=1**（100 轮）→ 只有一次退费路径。
5. **【实证】退费幂等键生效**：预插 `refund-{txn}` 流水后 `is_already_refunded`
   拦截二次退费（HTTP 层 E1 同时验证响应不再出现退款提示）。
6. **【次要发现】server.py 迁移失败时 `sys.exit(1)` 抛 NameError**（sys 未导入，
   server.py:12252）——失败退出路径自身崩溃，仅影响错误退出时的日志整洁。
7. **【环境备忘】本机 MySQL 实际端口 13314**（config_prod.yml 写的 3406、旧记忆
   3313 均已过期）；隔离测试库 `zjt_cancel_test`（schema 从 zjt 克隆 + alembic
   版本戳对齐），测试 token `s0-test-token-424242`（user 424242）。

### 2.6 隔离环境复现手册（HTTP E2E）

```bash
# 1) 生成隔离配置（已生成，gitignore 内不入库）：config_s0test.yml
#    = config_prod.yml 但 database→13314/zjt_cancel_test、server.port→13117
# 2) 造库：zjt_cancel_test 从 zjt 克隆 schema（CREATE TABLE LIKE）+ 对齐
#    alembic_version + 造 users/user_tokens 测试行（424242 / s0-test-token-424242）
# 3) 启动：comfyui_env=s0test python server.py   （端口 13117）
# 4) 跑测：python -m pytest tests/integration/test_cancel_endpoint_e2e.py -q
#    真库层：python -m pytest tests/integration/test_cancel_concurrency.py -q
#    （MySQL 不可达/服务未启动时自动 skip，不阻塞 CI）
```

### L1 单元/回归（已完成 ✅）

- `tests/task/test_queued_task_cancel.py`：17 个用例全绿（含本次新增 5 个）
- `tests/task/test_mock_channels.py` 等 f997 触及文件相关套件：45/45 通过
- 全量 `tests/task/ + tests/api/`：667 通过；9 个失败经干净 worktree 对照
  确认全部为 origin/develop 存量问题（环境依赖），与本分支无关

### L2 真实数据库并发验证（上线前必须，核心）

> 本地 MySQL 8.0（本机 3313，注意常停机需先启动）。参照设计文档 §8 的
> 验证方法，逐场景并发执行并断言。每个场景至少 50 轮。

| # | 场景 | 步骤 | S0 断言 |
|---|------|------|---------|
| C1 | 取消 vs 主提交竞争 | 两个连接同时对同一 PENDING 行执行 `status IN(0,3,4)→-2` 与 `0→1` | 每轮恰好一方 affected=1；绝不同时成功；取消赢后该行绝无 project_id |
| C2 | 取消 vs 同步池 | 并发执行 `0→3` 与取消；再对 `3→1`（worker 闸门）与取消竞争 | 同 C1；取消赢后 worker 闸门 affected=0 |
| C3 | 取消 vs 预处理推进 | 并发执行 `0→4` / `4→0` 与取消 | 同 C1；CANCELLED 行绝不被写回 0 |
| C4 | 并发双取消 | 两个连接同时取消同一任务 | 恰好一个 affected=1（一次退费）；另一个 409 |
| C5 | 参数错序回归 | 断言 `transition_status` 生成的 SQL 参数元组顺序 = SET→WHERE id→IN | 精确元组断言（防 §8 事故复发） |
| C6 | 过期/超限写 FAILED | 任务 CANCELLED 后触发过期清理 | 条件更新 0 行命中，CANCELLED 不被覆盖 |

工具：可复用设计文档 §8 的手工 SQL 会话方法；建议沉淀为
`tests/integration/test_cancel_concurrency.py`（pytest marker `@pytest.mark.mysql`，
连接失败 skip），一次编写长期回归。

### L3 E2E 手动验证（13007 环境，上线前）

前置：MySQL 3313 启动、13007 uvicorn 重启加载 rebase 后代码。
建议开 test_mode/mock（`task/mock_interceptor`）避免真烧上游；
退款链路验证用测试账号小额真实算力。

| # | 场景 | 操作 | 通过标准 |
|---|------|------|----------|
| E1 | 排队中取消（主路径） | 提交多任务制造排队 → 对队列中 1 个点取消 | 状态变已取消；算力按实扣退回 1 次；其余任务不受影响；`CANCEL_GUARD_REJECTED`/`USER_CANCELLED` 日志各就位 |
| E2 | 生成中取消（I2） | 任务进入生成中后点取消 | 409 提示；不退费；任务正常完成出片 |
| E3 | 下载中取消 | 任务处于下载阶段点取消 | 409；不退费 |
| E4 | 竞争窗口（I1 攻击） | 提交瞬间立刻连点取消，重复 10+ 次 | 要么取消成功且上游零调用（日志无 submit/project_id），要么 409；绝无「已取消又有 project_id」 |
| E5 | 双击取消 | 取消按钮连点 | 仅 1 次退费；第二次 409 或幂等提示 |
| E6 | 预处理中取消 | 带 param_prepare 的任务在预处理排队时取消 | 步骤连带取消；任务不再推进；不重复退费 |
| E7 | 重启恢复（I4） | 取消成功后重启 13007 | 调度器不拾取 CANCELLED；卡死恢复把 tasks 同步 -2 而非 FAILED |
| E8 | 工作流重载 | 取消后刷新页面/重新加载工作流（AGENTS.md 第 4 条） | 节点取消态复原、按钮可见性正确（QUEUED 才显示） |
| E9 | 数字人分段 | >15s 口播排队中取消 | 补段有界（≤MAX_RETRY_COUNT）；主任务终态明确；净退费=实扣 |
| E10 | 同步池排队取消 | sync_mode 实现任务入池后、worker 执行前取消 | worker 侧 CANCELLED 跳过日志；不调上游；退费 1 次 |
| E11 | 退款失败路径（S1） | 模拟 perseids 退款接口失败 | 任务仍 CANCELLED；响应明示"退款处理中"；重放取消幂等不二次退费 |
| E12 | 槽位归还（I5） | 占满 RunningHub 并发后取消排队任务 | reclaimer 在宽限期后回收槽位；新任务可提交 |

### L4 上线后观测（对账兜底）

灰度顺序：内测账号 → 小流量 → 全量。每日对账 SQL（任何一条命中即 S0 告警）：

```sql
-- I1 违反：已取消却调过上游（最严重，理论上必须恒为 0）
SELECT id, user_id, project_id, update_at FROM ai_tools
WHERE status = -2 AND project_id IS NOT NULL AND project_id != '';

-- I3 违反：同一扣费流水出现多条退款
SELECT transaction_id, COUNT(*) FROM computing_power_transactions
WHERE transaction_id LIKE 'refund-%' GROUP BY transaction_id HAVING COUNT(*) > 1;

-- 客服补偿名单：取消成功但未退费（S1，需人工处理）
SELECT a.id, a.user_id FROM ai_tools a
WHERE a.status = -2 AND NOT EXISTS (
  SELECT 1 FROM computing_power_transactions t
  WHERE t.transaction_id = CONCAT('refund-', a.transaction_id));
```

观测指标：CANCELLED 状态占比、409 率（异常升高=前端状态显示滞后）、
`CANCEL_GUARD_REJECTED` 日志频次（正常应只出现在取消成功后的下一轮调度）、
退费净额对账（当日扣费-退费 vs 上游账单）。

## 3. 已知接受的残余风险（非阻塞）

- 取消成功但退款 HTTP 失败：无自动重试，靠响应文案 + L4 对账名单人工补偿（S1）。
- 409 文案对"已被取消"与"已开始"未区分（并发双取消时第二条提示略歧义）。
- f997 取消守卫 `return True` 计入 success_count 统计（口径轻微偏差，无调度影响）。

## 4. 回滚策略

取消功能无独立开关，回滚 = 回退发布版本。回滚后已 CANCELLED 的任务保持终态
（调度器不再拾取，无残留副作用）；已退费不回收（按对账名单处理）。
