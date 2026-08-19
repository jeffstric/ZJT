# 邀请佣金（商业版）

> 仅商业版（enterprise）启用。社区版由 `IS_COMMUNITY_EDITION` 守卫，抽佣逻辑全部跳过，用户按全额算力到账。

## 一、功能概述

邀请人可设置一个佣金比例（合法范围 0%~50%，`0` 表示关闭抽佣）。其邀请的用户（被邀请人）每次充值（首充福利除外）时，邀请人按**实付金额**抽佣：

- 邀请人佣金 = `实付金额 × 比例`（以"元"累计）；
- 被邀请人到账算力 = `套餐算力 × (1 − 比例)`。

佣金累计满 10 元即可申请提现（全额提现），管理员审核通过后线下打款。

## 二、数据模型（纯账本式）

不维护聚合余额字段——所有佣金以流水形式记入 `commission_log`（单一数据源），余额/金额全部由聚合得出，从根本上避免多进程并发对聚合余额的"读-改-写"覆盖。

### 1. `users` 表新增字段
| 字段 | 类型 | 说明 |
|---|---|---|
| `commission_rate` | `DECIMAL(5,4)` DEFAULT 0.0000 | 邀请人佣金比例（0~0.5；0=关闭抽佣） |

### 2. `commission_log`（佣金明细 / 账本，唯一数据源）
| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `inviter_id` / `invitee_id` | 邀请人（佣金归属）/ 被邀请人（付款方） |
| `order_id` / `transaction_id` | 触发抽佣的订单号 / 微信交易号（**幂等键**，UNIQUE） |
| `package_id` / `order_amount` | 套餐ID / 订单实付金额 |
| `commission_rate` | 本单抽佣比例**快照**（比例中途变更不影响历史） |
| `commission_amount` | 本单佣金（元） |
| `granted_computing_power` | 被邀请人到账算力（打折后） |
| `withdraw_no` | 关联的提现单号；NULL=未提现 |
| `status` | 0-可用(未提现) / 1-已提现 / 2-已冲正 |

状态语义（`status` + `withdraw_no` 组合）：
- `status=0 AND withdraw_no IS NULL` → 可用（可参与提现）
- `status=0 AND withdraw_no IS NOT NULL` → 冻结中（已发起提现、待审核）
- `status=1` → 已提现（已打款）
- `status=2` → 已冲正（退款预留）

### 3. `commission_withdraw`（提现申请，不存金额）
| 字段 | 说明 |
|---|---|
| `withdraw_no` | 提现单号（UNIQUE） |
| `inviter_id` | 申请提现的邀请人 |
| `status` | 0-待审核 / 1-已打款 / 2-已驳回 |
| `apply_note` / `reject_reason` | 申请备注 / 驳回原因 |
| `reviewer_id` / `reviewed_at` / `paid_at` | 审核人 / 审核时间 / 打款时间 |

> 提现单**不存 amount**；某单金额 = `SELECT SUM(commission_amount) FROM commission_log WHERE withdraw_no = ?`。

## 三、抽佣流程

被邀请人微信支付成功 → `server.py` 的 `/api/recharge/wechat-callback`：
1. 查订单、首充特殊处理、`PaymentOrdersModel.update_paid`。
2. 调用 `commission/settle`（`perseids_server/client.py` 路由 → `CommissionService.settle`）。
3. 用返回的 `granted_computing_power`（已打折）替换原始算力，调用 `user/calculate_computing_power` 发放。

`CommissionService.settle` 判定顺序：
1. 社区版 → 全额，不抽佣；
2. `package_id == 1`（首充）→ 全额，不抽佣；
3. 幂等：`commission_log` 命中同 `transaction_id` → 回放历史 `granted`；
4. 被邀请人无 `inviter_id` → 全额，不抽佣；
5. 邀请人 `commission_rate == 0` → 全额，不抽佣；
6. 否则：`commission = round(price × rate, 2)`（四舍五入到分）；`granted = int(算力 × (1−rate))`（向下取整）；写入 `commission_log`。

> 抽佣调用异常时，`server.py` 降级为全额算力发放（宁可漏抽佣，不少发用户算力）。

## 四、佣金查询与提现

余额/金额全部按 `inviter_id` 聚合 `commission_log`：
- 可用余额 = `SUM(amount) WHERE status=0 AND withdraw_no IS NULL`
- 冻结中 = `SUM(amount) WHERE status=0 AND withdraw_no IS NOT NULL`
- 已提现 = `SUM(amount) WHERE status=1`
- 累计 = `SUM(amount) WHERE status IN (0,1)`

### 全额提现申请（事务内）
1. `SELECT ... FOR UPDATE` 锁住该邀请人当前全部可用记录（串行化并发申请）；
2. 合计 `< 10` 元 → 拒绝（回滚）；
3. 生成 `withdraw_no`，建提现单（待审核）；
4. 把这些记录 `withdraw_no` 置为单号（冻结）。

### 审核
- **通过**：关联记录 `status → 1`（已提现），提现单 `status → 1`（已打款）。
- **驳回**：关联记录 `withdraw_no → NULL`（解冻、回到可用），提现单 `status → 2`。

## 五、API 接口

### 用户侧（`/api/commission`，需登录 + 商业版）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/commission/rate` | 获取我的佣金比例 |
| PUT | `/api/commission/rate?rate=0.1` | 设置我的佣金比例（0~0.5） |
| GET | `/api/commission/summary` | 佣金汇总（可用/冻结/已提现/累计） |
| GET | `/api/commission/records?page=1&page_size=20` | 佣金明细分页 |
| POST | `/api/commission/withdraw?apply_note=...` | 全额提现申请 |
| GET | `/api/commission/withdrawals?page=1&page_size=20` | 我的提现单 |

### 管理端（`/api/admin/commission`，需管理员 + 商业版）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/commission/withdrawals?status=0` | 提现单列表（可按状态过滤） |
| POST | `/api/admin/commission/withdraw/{withdraw_no}/approve` | 审核通过 |
| POST | `/api/admin/commission/withdraw/{withdraw_no}/reject?reject_reason=...` | 审核驳回 |

## 六、常量（`config/constant.py`）
- `Commission`：`MIN_RATE=0.0` / `MAX_RATE=0.5` / `STEP=0.01` / `MIN_WITHDRAW_AMOUNT=10.0` / `FIRST_RECHARGE_PACKAGE_ID=1`
- `CommissionLogStatus`：`AVAILABLE=0` / `WITHDRAWN=1` / `REVERSED=2`
- `CommissionWithdrawStatus`：`PENDING=0` / `PAID=1` / `REJECTED=2`

## 七、数据库迁移

迁移脚本：`alembic/versions/no_97_20260613_invite_commission.py`
- `revision = '20260613_invite_commission'`，`down_revision = '20260612_chat_messages'`
- `upgrade()`：ALTER `users` 加 `commission_rate` + 建 `commission_log` / `commission_withdraw` 两表。
- `downgrade()`：DROP 两表 + DROP `users.commission_rate`。

> 新表/新列在社区版迁移也会建立（迁移脚本不区分版本）；是否启用抽佣由代码层 `IS_COMMUNITY_EDITION` 守卫。

## 八、与现有邀请奖励的关系

注册时的"+38 算力"邀请奖励（`auth_service._add_inviter_reward`）与本抽佣功能**并存**：前者是一次性拉新激励（注册触发），后者是持续变现（充值触发），维度不同，互不影响。

## 九、前端入口

用户侧入口位于 `web/index.html` 的「邀请码弹窗」（点击顶部手机号 `openInviteModal` 打开）：

- **复制邀请链接**：复制带 host 的注册链接 `{origin}{pathname}?invite_code=XXX`，对方点击即可带邀请码进入注册页。host 取运行时 `window.location.origin`（用户实际访问地址，比配置示例值 `localhost` 更可靠可达）。
- **佣金中心**（商业版；社区版 `/api/commission/*` 返回 403 时自动隐藏）：展示可提现/累计/冻结/已提现余额、全额提现申请按钮、抽佣比例滑块（0%~50%）+ 保存，以及**佣金明细列表**（显示被邀请人手机号脱敏 + 本单佣金 + 时间，回答"哪个用户充值、拿到多少佣金"）。
- **邀请码弹窗样式**：弹窗结构保留在 `web/index.html`，视觉样式集中在 `web/css/index.css` 的 `Invite Code Styles` 段，避免继续在页面中堆叠大量内联 CSS。
- **充值页算力显示**：套餐展示的算力为**扣邀请佣金后的实际到账算力**（`granted_computing_power`）。后端 `/api/recharge/packages` 针对当前用户（被邀请人）按其邀请人的佣金率计算（首充/社区版/无邀请人/比例 0 => 全额），**直接展示到账算力，不对被邀请人暴露任何佣金信息（静默抽佣）**。内部通过 `commission/recharge_grants` endpoint（`perseids_server/client.py`）由 `CommissionService.get_recharge_grants` 计算，与 `settle` 口径一致。
  - 前端必须优先展示 `pkg.granted_computing_power ?? pkg.computing_power`（含单价「元/百算力」分母），不得只读标称 `computing_power`。
  - 覆盖入口：`web/index.html`、`web/js/storyboard/render.js`、`web/js/script_writer.js`、`web/video_workflow.html`、`web/marketing_agent.html`。

> 管理端提现审核台（`web/admin.html`）暂未在前端实现，目前可通过管理端 API 操作。
