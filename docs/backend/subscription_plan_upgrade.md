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

### 单一订阅保障（微信侧只保留一个生效签约）

不同模板的签约在微信侧可以并存，若不加约束，用户换订/重订后微信侧会残留
多个生效签约导致双份扣款，而系统按"最新一条"展示、无法察觉。以下机制保证
系统与微信侧始终只有一个生效订阅：

- **新约生效即清理旧约**：ADD 签约回调（`handle_contract_callback`）与对账自愈
  （`_reconcile_pending_signs` 确认签约成功）中，新合约生效后立即解约该用户
  其它所有已签约合约（`_terminate_other_contracts`，备注
  `新订阅生效自动解约旧签约`）。
- **残留签约自愈**：已被"重新发起订阅自动放弃"等路径本地终止、但微信侧实际
  签约已生效（ADD 迟到/重推）的合约，回调中先复活落库；若用户已有其它生效签约
  则立即解约自己（残留清理），无其它生效签约则保留（误终止自愈）。重复推送时
  终态一致，幂等。
- **重新发起时清残留**：`create_sign_pay_order` 发现同一用户存在多条已签约合约
  （历史残留/竞态）时，先解约旧记录只留最新一条，再走升级/拒绝逻辑。
- **兜底去重**：续期调度新增 `_dedup_signed_contracts`，周期扫描多条已签约合约的
  用户，保留最新、解约其余。

### 资金安全设计

- **不双扣**：委托代扣由商户侧发起，本地把旧合约置 TERMINATED 后
  `get_renewal_due_contracts` 即不再对其续期；此外该查询排除所有
  "存在 PENDING 签约的用户"，升级签约未落定前旧合约暂停续期动作。
- **解约补偿**：旧合约先本地终止（`termination_remark = 套餐升级自动解约` 或
  `新订阅生效自动解约旧签约`），再尽力调微信解约 API；API 失败时由续期调度中的
  `_retry_upgrade_terminations` 补偿任务按备注识别并重试，确认成功后备注改为
  `…(微信侧已解除)`。

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
- `GET /api/subscription/order-status`（新增）：`order_id`/`user_id`/`auth_token` 查询单笔
  订阅订单，`{status, paid}`（`status=1` 即 `SubscriptionOrderStatus.PAID`）。Native 扫码支付后
  前端每 3s 轮询，支付成功自动 alert 并刷新订阅状态与算力（JSAPI 微信内走 WeixinJSBridge
  回调，无需轮询）；弹窗关闭/返回/重新发起时自动停止轮询。

## 支付密钥安全闸（生产强制）

- `POST /api/recharge/wechat-pay`：统一下单前检查 `secret/wechat/apiclient_key.pem`，
  缺失直接 503「微信支付商户密钥未配置，无法发起支付」——不允许展示二维码
  （缺失时签名降级为 `mock_signature`，微信必拒；同时杜绝验签旁路被伪造回调利用）。
- `POST /api/subscription/wechat-sign-pay`：检查 `pay.wxpay.api_v2_key` 非空，缺失同样 503。
- 验签 fail-closed（2026-10-23，审计 BUG-R2-S1-A3-H1/BUG-R2-S2-A1-H1 修复）：
  `verify_callback_signature` 缺公钥文件、`verify_v2_sign` 缺 V2 密钥一律
  `return False` 拒绝回调——密钥缺失即无法确认通知来源，接受回调等于接受
  任意伪造的支付/签约通知（曾可伪造回调免费入账算力、解约他人合约）。
  微信侧收到 4xx 后按 15s..6h 计划重试，补齐密钥后自动恢复，无需重启。
  上线前请确认 `secret/wechat/` 下平台公钥（`pub_key.pem`，公钥模式）或
  平台证书文件、以及 `pay.wxpay.api_v2_key` 均已配置，否则真实回调将被拒绝。
- **开发环境联调旁路（V3 验签，2026-10-23）**：开发环境通常没有微信平台
  公钥/证书文件，fail-closed 会卡死真实支付的回调入账。专用配置
  `pay.wxpay.dev_skip_callback_sign`（管理台 system_config 可编辑，默认
  留空）——值必须**精确填入** `DEV-OK-I-KNOW-THE-RISK`（严格匹配，不
  trim、区分大小写；true/1/随手字符串均不放行）才生效，仅在验签密钥
  文件缺失分支放行回调（密钥存在但签名错误仍拒绝），每次跳过打
  WARNING `DEV BYPASS` 便于审计。显式确认串设计防管理台误配置；配置
  读取异常按未开启处理（安全失败）。与 test_mode 挡板体系完全解耦
  （test_mode 会 mock 掉所有媒体生成任务，且 test_mode.* 被管理台 403
  仅允许脚本修改——支付联调不应牵连）。TTL 缓存热更新（30s），改完
  无需重启。测试见 `tests/utils/test_wechat_pay_callback_verify.py`
  （确认串放行/随手值拒绝/读取异常拒绝/密钥在但签名错不受旁路影响）。

## 业务规则

- **首期加赠**：全局规则为"仅「签约成功」后发放、且仅限用户首份成功签约合约的首期一次"——
  `subscription_service._grant_first_period_bonus` 在合约 ACTIVE 后发放（订单首期已支付、
  非升级单、`exists_signed_contract` 判定为首份成功签约、`first_bonus_granted` 幂等）；
  **用户只付款但签约未生效（订阅被关闭）时不加赠**，只付款未签约的历史合约不消耗资格。
  发放时机：支付结算时合约多半仍签约中 → 由签约结果回调（ADD）或补偿查单
  （`_reconcile_pending_signs`）成功后补发；两事件先到后到的任一顺序均可覆盖。
  幂等键为 `transaction_id + '_FIRST_BONUS'`（基础算力占用原 transaction_id）；
  升级单默认亦**不发**（`SubscriptionConstants.UPGRADE_GRANT_FIRST_BONUS = false`，独立兜底）。
- **剩余天数**：升级立即切换，旧套餐本期剩余天数不折算、不退差价（产品决策，文案已展示）。
- **升级算力**：按新套餐整期发放（档位固定值口径与首期一致，抽佣规则相同）。

## 改动清单

| 文件 | 内容 |
|---|---|
| `config/constant.py` | `SubscriptionConstants` 新增 `UPGRADE_GRANT_FIRST_BONUS` / `UPGRADE_TERMINATE_REMARK(_CONFIRMED)` / `PENDING_SIGN_CONFIRM_GRACE_MINUTES` / `SIGN_FAILED_TERMINATE_REMARK` |
| `config/subscription_config.py` | 新增 `is_upgrade_plan()`（plan_id 单调递增即档位高低） |
| `model/subscription_orders.py` | 新增 `upgrade_from_contract_code` 字段（建表 SQL 同步）；新增 `first_bonus_granted` 标记列（no_138 迁移）与 `mark_first_bonus_granted()` |
| `model/wx_papay_contracts.py` | `get_renewal_due_contracts` 排除有 PENDING 签约的用户；新增 `get_active_signed_by_user` / `get_upgrade_terminated_pending_confirm` / `update_termination_remark` / `get_paid_pending_signs`（支付成功但签约未收尾的签约中合约）/ `exists_signed_contract`（首订加赠资格判定） |
| `services/subscription_service.py` | `create_sign_pay_order` 升级放行；`_settle_order_paid` 结算后解约旧约；`_terminate_replaced_contract` / `_delete_wechat_contract` / `_retry_upgrade_terminations`；`get_subscription_status` 升级视图 + `first_bonus_eligible`；`_settle_and_grant` 升级单不发首赠、首订加赠仅限首次订阅；`_reconcile_pending_signs` 支付成功但签约通知未到的查单收尾 |
| `web/index.html` + `web/js/index_app.js` + `web/css/subscription.css` | 生效中/升级中展示"升级到更高套餐"区块与升级支付面板；`upgradePlans` / `isUpgradeMode`；`subFirstBonusEligible` 控制「首期加赠」标签按首订资格展示，已解约重新订阅文案同步修正；签约未生效（`sign_not_effective`）引导横幅提醒重新开通订阅 |
| `alembic/versions/no_137_20260916_add_subscription_upgrade_from_contract.py` | 订单表加列迁移（幂等） |
| `tests/services/test_subscription_service.py` | 新增升级场景用例 |

## 边界场景

- **升级签约期间用户重新发起**：`get_active_by_user` 取最新记录为 PENDING 升级约 →
  走既有"自动放弃旧签约"分支，可无缝更换目标套餐。
- **升级签约期间旧合约到期**：续期调度已排除该用户，旧合约不会扣款；
  若用户最终放弃升级，PENDING 清理后下个调度周期恢复旧合约续期。
- **用户在微信自助解约旧约**：DELETE 回调幂等标记旧约终止，升级流程不受影响。
- **支付成功但签约 ADD 回调丢失**：新合约停留 PENDING，由 `_reconcile_pending_signs`
  查单收尾（见下条）；超时清理 `_cleanup_stale_pending_signs` 排除已有 PAID 订单的
  合约，不会误清已付款合约（结算幂等靠订单状态，算力不重复发放）。
- **支付成功但签约结果通知（ADD 回调）未到**：用户已支付（订单 PAID、算力已发、周期已顺延）而合约停留
  签约中时，续期调度的 `_reconcile_pending_signs` 在宽限时间
  （`PENDING_SIGN_CONFIRM_GRACE_MINUTES = 10` 分钟）后主动调微信 `querycontract` 收尾：
  已签约（contract_state=0）补 `mark_signed` 激活（自愈）；未签约（1）或查无记录
  （-25 RESULT NULL）终止合约，备注固定为 `SIGN_FAILED_TERMINATE_REMARK`。
  **单期已付权益保留**（用户本月钱已付：算力照发、周期照顺延，不退款、不回收算力），
  只是没有自动续费；状态视图对该备注返回 `sign_not_effective=true`，前端展示
  "本月会员已付费…重新开通订阅持续享受优惠"的引导横幅（区别于用户主动解约的文案）。
  签约进行中（9）或查询异常则等下一周期。
  对账不受微信扣费窗口（7:00~22:00）限制，7×24 执行（见
  `subscription_deduct_window_scoping.md`），ADD 回调延迟时最迟下个调度周期（30 分钟）完成收尾。
  真实案例：用户在收银台支付但未完成「开通自动续费」确认（截图中的开关未开），
  微信侧支付成功且不退款、但无签约关系，故永远等不到 ADD 回调，前端表现为一直「签约进行中」。
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

## 前端状态轮询（2026-09-16）

支付/签约确认由微信回调驱动，前端原本无任何轮询（Native 扫码支付后用户须手动点
「刷新状态」）。现于以下时机启动轻量轮询（每 5 秒 `GET /api/subscription/status`，
单实例防重入，上一次未返回则跳过本次 tick）：

- 创建订阅/升级订单成功后（JSAPI / Native 共用分支；拿不到 Native 二维码时立即停）
- 打开充值中心时已有签约进行中（`signing` / `upgrading`），自动恢复等待

状态翻转为 `active`（签约/升级落定）即停止：刷新套餐卡片与算力、清理支付面板并弹
成功提示（升级单提示"升级成功"，首订提示"订阅成功"）；`signing`/`upgrading` 回落
`terminated`/`none`/`expired` 时停止并提示"签约未完成，如需订阅请重新发起"。
关闭充值中心、JSAPI 支付取消/失败、取消订阅均停止轮询。
回归见 `web/tests/subscription_status_polling.test.js`。
