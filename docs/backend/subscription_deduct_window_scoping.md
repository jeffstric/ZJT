# 订阅续期调度：扣费窗口作用域收窄（7×24 对账自愈）

## 背景（线上事故）

2026-09-28 22:21，用户 2104（手机号 186****7782）首次订阅标准版并支付成功：
基础算力 808 正常到账，但**首订加赠 400 一直未发放**，需等次日早上 7 点后才可能补发。

根因：微信委托代扣约束「预扣费通知 / 申请扣款仅北京时间 7:00~22:00 可发起」，
系统原将 `_in_deduct_window()` 判断放在 `process_renewals()` 调度入口一刀切——
窗口外整个 tick 跳过，导致 8 个子步骤中 6 个本不受微信约束的步骤被"陪绑"：

| 步骤 | 是否受微信窗口约束 | 修复前 |
| --- | --- | --- |
| `_create_renewal_orders` 建单（本地落库） | 否 | 陪绑 |
| `pre_deduct_notify` 预扣费通知（微信，给用户推消息） | **是** | 正确限制 |
| `_apply_due_deductions` 申请扣款（微信，划扣） | **是** | 正确限制 |
| `_confirm_stale_orders` 查单确认（只读） | 否 | 陪绑 |
| `_reconcile_pending_signs` 签约对账自愈（只读+本地发算力） | 否 | 陪绑 |
| `_cleanup_stale_pending_signs` 签约超时清理（本地 SQL） | 否 | 陪绑 |
| `_retry_upgrade_terminations` / `_dedup_signed_contracts` 解约重试/去重 | 否（解约接口无窗口限制） | 陪绑 |
| `process_settlement_retry` 算力补发（内部服务） | 否 | 陪绑 |

事故链：22:21 支付回调结算基础算力时合约仍签约中（PENDING），首订加赠按规则
顺延到「签约成功」后发放（微信 ADD 签约结果回调一直未到）→ 兜底对账
`_reconcile_pending_signs`（支付后 10 分钟宽限）因已过 22:00 无法调度 →
加赠挂起整夜，最早次日 7:00~7:30 的 tick 才查单收尾补发。

微信窗口约束的权威范围（[周期扣费产品文档 V2](https://pay.weixin.qq.com/doc/v2/merchant/4011986682)）：
仅预扣费通知与申请扣款（预扣费模式下）限 7:00~22:00，目的是避免夜间打扰用户；
查询签约关系 / 查单 / 解约等接口无时间窗口限制。

## 修复内容（`services/subscription_service.py`）

1. `process_renewals()`：入口整体 return 改为计算 `in_window` 只传给两个受限步骤，
   查单、签约对账、超时清理、解约重试、算力补发 7×24 执行。
2. `_create_renewal_orders(in_window=True)`：建单不受窗口限制照常落库；
   `pre_deduct_notify` 仅窗口内发送，窗口外跳过、由下个窗口内 tick 凭
   `prenotify_sent_at` 幂等补发（等待期自实际发送日起算，语义不变）。
3. `_apply_due_deductions(in_window=True)`：窗口外整个函数跳过（含重试窗口耗尽
   关单，关单时点最多延后一夜，行为与修复前一致）。
4. `_cleanup_stale_pending_signs()`：SQL 增加 `NOT EXISTS` 排除「已有 PAID 订单」的
   合约——已付款但 ADD 回调未到 / 对账未决的合约由 `_reconcile_pending_signs`
   负责收尾（可能补签约并补发首订加赠），不能被超时清理终止，否则加赠资格悬空。
   （对账 7×24 后该路径触发频率上升，此防御为必要配套。）

## 修复后效果

- 22:00 后支付订阅的用户：签约 ADD 回调未到时，最迟下个调度周期（30 分钟）
  内由对账查单收尾——微信侧已签约则激活合约并补发首订加赠，不再等一整夜。
- 微信侧确实未签约的（用户付了首月但没开自动续费）：照旧单期权益保留、
  合约终止留痕、不加赠，行为不变。
- 窗口外不发起任何预扣费通知 / 申请扣款，微信约束遵守不变。

## 验证

- `tests/services/test_subscription_service.py` 新增 `TestDeductWindowScoping`：
  窗口外 tick 仅扣款两步收到 `in_window=False` 且其余步骤照常执行；窗口外不发
  prenotify / 不查待扣款订单；窗口内 prenotify 行为不变；清理 SQL 排除已支付合约。
