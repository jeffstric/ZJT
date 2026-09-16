# 月度订阅套餐升级（无需退订，低→高）

> 分支：develop_f716　|　日期：2026-09-16　|　关联：微信委托代扣·周期扣费（月度订阅）

## 需求

订阅生效中（ACTIVE）的用户，直接订阅更高档套餐完成升级，**无需先退订**。
降级/同档更换仍维持"先取消当前订阅"的既有规则。

## 方案原理

微信委托代扣的平台限制是"**同一协议模板**下一个用户只能有一份生效签约"
（限额限次按签约协议计）。本项目每档套餐各有一个协议模板
（`config/subscription_config.py` 的 `template_id`，101~104 共 4 个），
因此**不同模板的签约可以并存**：

1. 升级 = 在高套餐模板下新发起一笔「支付中签约」（新合约 PENDING + 首期订单，
   订单记录 `upgrade_from_contract_code` 指向被替换的旧合约）；
2. 旧合约此时完全不动——用户放弃支付也无损，PENDING 超 2 小时由
   `_cleanup_stale_pending_signs` 自动清理，天然回滚；
3. 新单支付成功回调结算后，商户侧自动解约旧合约、本地标记终止；
4. 新周期自支付成功起算 30 天，按新套餐发放整期算力（走既有
   `commission/settle` 档位阶梯抽佣，enterprise 侧无改动）。

### 资金安全设计

- **不双扣**：委托代扣由商户侧发起，本地把旧合约置 TERMINATED 后
  `get_renewal_due_contracts` 即不再对其续期；此外该查询排除所有
  "存在 PENDING 签约的用户"，升级签约未落定前旧合约暂停续期动作。
- **解约补偿**：旧合约先本地终止（`termination_remark = 套餐升级自动解约`），
  再尽力调微信解约 API；API 失败时由续期调度中的 `_retry_upgrade_terminations`
  补偿任务按备注识别并重试，确认成功后备注改为 `套餐升级自动解约(微信侧已解除)`。

## 状态机与接口变化

| 场景 | status | 说明 |
|---|---|---|
| 无订阅 | `none` | 不变 |
| 首次签约中 | `signing` | 不变 |
| 生效中 | `active` | 不变 |
| **升级签约中** | `upgrading` | 新增：`subscribed=true`，`plan` 为当前生效（旧）套餐，`pending_plan` 为升级目标套餐，当前套餐继续可用 |
| 升级支付成功 | `active` | 新合约成为最新 ACTIVE，旧合约 TERMINATED |
| 已解约 | `terminated` | 不变 |

- `POST /api/subscription/wechat-sign-pay`：已有 ACTIVE 签约且目标套餐更高时放行，
  响应新增 `upgrade: true` 与 `current_plan`（原套餐）；同档/降级报错文案调整为
  "如需更换为更低套餐请先取消当前订阅"。
- `GET /api/subscription/plans` / `status`：`subscription` 可能返回 `upgrading`。

## 业务规则

- **首期加赠**：升级单默认**不发** `first_period_bonus`（`SubscriptionConstants.UPGRADE_GRANT_FIRST_BONUS = false`），
  防止"升级/退订重订薅首赠"套利；解约后重新订阅仍按既有规则视为新订阅。
- **剩余天数**：升级立即切换，旧套餐本期剩余天数不折算、不退差价（产品决策，文案已展示）。
- **升级算力**：按新套餐整期发放（档位固定值口径与首期一致，抽佣规则相同）。

## 改动清单

| 文件 | 内容 |
|---|---|
| `config/constant.py` | `SubscriptionConstants` 新增 `UPGRADE_GRANT_FIRST_BONUS` / `UPGRADE_TERMINATE_REMARK(_CONFIRMED)` |
| `config/subscription_config.py` | 新增 `is_upgrade_plan()`（plan_id 单调递增即档位高低） |
| `model/subscription_orders.py` | 新增 `upgrade_from_contract_code` 字段（建表 SQL 同步） |
| `model/wx_papay_contracts.py` | `get_renewal_due_contracts` 排除有 PENDING 签约的用户；新增 `get_active_signed_by_user` / `get_upgrade_terminated_pending_confirm` / `update_termination_remark` |
| `services/subscription_service.py` | `create_sign_pay_order` 升级放行；`_settle_order_paid` 结算后解约旧约；`_terminate_replaced_contract` / `_delete_wechat_contract` / `_retry_upgrade_terminations`；`get_subscription_status` 升级视图；`_settle_and_grant` 升级单不发首赠 |
| `web/index.html` + `web/js/index_app.js` + `web/css/subscription.css` | 生效中/升级中展示"升级到更高套餐"区块与升级支付面板；`upgradePlans` / `isUpgradeMode` |
| `alembic/versions/no_137_20260916_add_subscription_upgrade_from_contract.py` | 订单表加列迁移（幂等） |
| `tests/services/test_subscription_service.py` | 新增升级场景用例 |

## 边界场景

- **升级签约期间用户重新发起**：`get_active_by_user` 取最新记录为 PENDING 升级约 →
  走既有"自动放弃旧签约"分支，可无缝更换目标套餐。
- **升级签约期间旧合约到期**：续期调度已排除该用户，旧合约不会扣款；
  若用户最终放弃升级，PENDING 清理后下个调度周期恢复旧合约续期。
- **用户在微信自助解约旧约**：DELETE 回调幂等标记旧约终止，升级流程不受影响。
- **支付成功但签约 ADD 回调丢失**：新合约停留 PENDING 被超时清理——既有风险
  （首期同样存在），结算幂等靠订单状态，算力不重复发放。
- **微信侧残留旧签约**（解约 API 持续失败）：不影响资金（商户不发起扣款），
  补偿任务持续重试并告警日志，必要时商户平台人工解约。

## 人工测试要点

1. 生效中（如入门版）→ 选标准版 → 扫码支付 → 状态变 `active`、套餐为标准版、
   算力按标准版到账（无首期加赠）、旧合约 `wx_papay_contracts.status=2` 且备注
   `套餐升级自动解约(微信侧已解除)`、微信「自动续费」列表旧签约消失。
2. 生效中 → 选同档/低档 → 提示需先取消。
3. 升级扫码未支付 → 状态 `upgrading`、当前套餐继续可用、旧合约不预扣费；
   2 小时后签约自动清理恢复原状态。
4. 升级单支付成功但模拟解约 API 失败 → 补偿任务下个调度周期重试成功。
