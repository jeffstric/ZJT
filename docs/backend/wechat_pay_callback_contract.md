# 微信支付回调响应契约与吞单防护（2026-10-23，审计 BUG-R2-S2-A2-H4）

## 契约

微信支付 V3 通知的响应码是"已履约"的证明：**200/204 = 处理成功，微信停止
全部重试（15 次 / 约 24h，间隔 15s..6h）；4xx/5xx = 请求重投**。因此回调
handler 的铁律：**算力未入账，就绝不応答 2xx**。

## 曾经的三条吞单路径（均已修复）

1. **取 token 失败裸 `return False`**：FastAPI 把非 Response 返回值序列化为
   `200 body false` → 微信停止重试，订单永远 `status=0`（用户已付款、算力
   永不到账）。触发：付款后 24h 内登出/改密/顶号（严格单会话删 token）或
   token 查询 DB 抖动。修复：应答 500 让微信重试，等用户重新登录后自动补账。
2. **`update_paid` 先于入账执行**：`status=1` 墓碑使后续每次重投命中
   `order.status == 1` 早退分支直接应答 SUCCESS，而算力从未发放。触发：
   入账调用失败 / 进程在两步之间重启 / 微信响应超时引发的重试竞态。
   修复：`update_paid` 移到入账成功（或幂等重放）之后。
3. **入账结果不校验**：`user/calculate_computing_power` 返回
   `success=False` 被无视，无条件记 "Payment processed successfully" 并应答
   SUCCESS。修复：除幂等重放（"该交易已处理"= 已发放过，补落
   `update_paid` 后应答 200）外，任何失败应答 500。

订单账本（payment_orders）与算力账本（computing_power/perseids）是两个
存储、无法跨库事务，只能以"入账成功后才落订单状态"收尾；重投由微信驱动，
幂等由入账侧 `transaction_id` 去重保证。

## 测试

`tests/api/test_wechat_payment_callback_retry.py`（4 例）：token 失败 5xx
不落墓碑 / 入账失败 5xx 不落墓碑 / 入账成功落账并应答 200 / 幂等重放补落
账并应答 200。
