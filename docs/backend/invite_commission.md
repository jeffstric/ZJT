# 邀请佣金（商业版）

> 仅商业版（enterprise）启用。社区版由 `IS_COMMUNITY_EDITION` 守卫，抽佣逻辑全部跳过，用户按全额算力到账。

## 一、功能概述

商业版邀请分两层：

1. **邀请链接（默认开放）**：所有登录用户都可在「邀请中心」弹窗复制推广链接。好友注册登录后，邀请人获得一次性算力奖励（+38）。
2. **渠道现金佣金（管理员开通）**：默认关闭。只有后台管理员把该用户 `channel_level` 设为 `2` 后，其邀请的用户充值/订阅才会产生现金佣金。未开通时推广链接**只发算力、不产生佣金**。

用户侧不能自己打开佣金。未开通的商业版用户可点「申请开通渠道推广」，弹窗展示客服微信二维码（`frontend.customer_service_qr_url` 可覆盖，默认 `/files/二维码.jpg`），微信扫码添加客服，由客服转管理员开通。本地部署（`server.is_local=true`）不展示该入口。

佣金比例按套餐档位写死（见 `Commission.COMMISSION_TIERS`），不再由邀请人自调。累计满 10 元可申请提现，管理员审核通过后线下打款。

> 社区版：抽佣整体跳过；不展示申请开通按钮与佣金中心；邀请链接仍可获取算力。

**注册时的邀请码**：注册页仅在非本地模式展示邀请码输入框（`web/index.html` `v-if="!isLocal"`）。本地部署（`server.is_local=true`）下，后端 `/api/auth/register` 直接忽略请求中的 `invite_code`（前端同步不提交），避免线上邀请链接携带的邀请码在本地库查无此码时报「无效邀请码」阻断注册。

## 二、数据模型（纯账本式）

不维护聚合余额字段——所有佣金以流水形式记入 `commission_log`（单一数据源），余额/金额全部由聚合得出，从根本上避免多进程并发对聚合余额的"读-改-写"覆盖。

### 1. `users` 表相关字段
| 字段 | 类型 | 说明 |
|---|---|---|
| `commission_rate` | `DECIMAL(5,4)` DEFAULT 0.0000 | 历史佣金比例字段（新价目不再由用户自调） |
| `channel_level` | `TINYINT` DEFAULT 0 | 渠道推广等级：`0` 默认 / `1` 兼容推广链接（均仅算力） / `2` 渠道现金佣金 |

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
2. 幂等：`commission_log` 命中同 `transaction_id` → 回放历史 `granted`；
3. 未知档位 → 全额，不抽佣；
4. 被邀请人无 `inviter_id` → 全额，不抽佣；
5. 邀请人 `channel_level < 2`（管理员未开通渠道佣金）→ 用户按档位不抽成值到账，**不写佣金账本**；
6. 邀请人 `channel_level >= 2` → 用户到账 `invited_power`，邀请人记入档位固定 `channel_cash`。

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
| GET | `/api/commission/rate` | 获取我的佣金比例（只读；自调已停用） |
| PUT | `/api/commission/rate?rate=0.1` | 已停用，返回失败提示 |
| GET | `/api/commission/summary` | 佣金汇总（含 `channel_level`） |
| GET | `/api/commission/records?page=1&page_size=20` | 佣金明细分页 |
| POST | `/api/commission/withdraw` | 全额提现申请 |
| GET | `/api/commission/withdrawals?page=1&page_size=20` | 我的提现单 |

### 管理端（需管理员）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/commission/withdrawals?status=0` | 提现单列表（可按状态过滤） |
| POST | `/api/admin/commission/withdraw/{withdraw_no}/approve` | 审核通过 |
| POST | `/api/admin/commission/withdraw/{withdraw_no}/reject?reject_reason=...` | 审核驳回 |
| PUT | `/api/admin/users/{user_id}/channel-level` | 设置用户渠道等级 `{level}` |
| GET | `/api/admin/users/{user_id}/channel-level` | 查询用户渠道等级 |

用户列表 `GET /api/admin/users` 与详情 `GET /api/admin/users/{id}` 均返回 `channel_level`。

## 六、常量（`config/constant.py`）
- `Commission`：`MIN_RATE` / `MAX_RATE` / `STEP` / `MIN_WITHDRAW_AMOUNT` / `COMMISSION_TIERS` / `WITHDRAW_FREEZE_DAYS`
- `ChannelLevel`：`NONE=0` / `INVITE=1` / `COMMISSION=2` / `CUSTOMER_SERVICE_WECHAT`
- `CommissionLogStatus`：`AVAILABLE=0` / `WITHDRAWN=1` / `REVERSED=2`
- `CommissionWithdrawStatus`：`PENDING=0` / `PAID=1` / `REJECTED=2`

## 七、数据库迁移

- `alembic/versions/no_97_20260613_invite_commission.py`：`commission_rate` + `commission_log` / `commission_withdraw`
- `alembic/versions/no_136_20260916_add_users_channel_level.py`：`users.channel_level`（幂等 ADD COLUMN）

> 新表/新列在社区版迁移也会建立（迁移脚本不区分版本）；是否启用抽佣由代码层 `IS_COMMUNITY_EDITION` 守卫，渠道佣金另受 `channel_level>=2` 门控。

## 八、与现有邀请奖励的关系

注册时的"+38 算力"邀请奖励（`auth_service._add_inviter_reward`）与本抽佣功能**并存**：前者是一次性拉新激励（注册触发），后者是持续变现（充值触发），维度不同，互不影响。

## 九、前端入口

用户侧入口位于 `web/index.html`：

- **邀请中心**（`showInviteModal` 弹窗）：所有登录用户可见；复制带 host 的注册链接 `{origin}{pathname}?invite_code=XXX`。host 取运行时 `window.location.origin`。（原顶部账号点击入口已随 `user-agent-row` 移除，弹窗当前无页面入口。）
- **申请开通渠道推广**（商业版且 `channel_level < 2` 且非 `is_local`）：邀请中心内按钮。点击弹出客服微信二维码（`/api/system/server-config` 的 `customer_service_qr_url`，默认 `/files/二维码.jpg`），微信扫码添加客服开通。
- **佣金中心**（商业版且 `channel_level >= 2`）：可提现/累计/冻结/已提现、提现申请、档位佣金说明、佣金明细。社区版或未开通时隐藏。
- **邀请码弹窗样式**：弹窗结构在 `web/index.html`，视觉样式在 `web/css/index.css` 的 `Invite Code Styles` 段。
- **充值页算力显示**：优先展示 `pkg.granted_computing_power ?? pkg.computing_power`。覆盖入口：`web/index.html`、`web/js/storyboard/render.js`、`web/js/script_writer.js`、`web/video_workflow.html`、`web/marketing_agent.html`。

管理端（`web/admin.html` 用户管理，商业版）：

- 用户列表操作列「开佣金 / 关佣金」：`PUT /api/admin/users/{user_id}/channel-level`，开启写 `level=2`，关闭写 `level=0`。
- 用户详情展示当前渠道状态，可同样切换。
