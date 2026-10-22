# 2026-10-21 营销智能体 SSE 链路静默假死导致连环"请求超时"

## 现象

会话 `1be6829f-45e6-4f88-b879-2d1c72c2af54`（任务 `ee920cbb-1574-4d3f-825e-d84d1924786a`）：

- 用户 17:34 起连续收到 5 个"请求超时，请稍后重试"气泡（17:49:29 / 17:49:37 / 17:49:46 / 17:50:46 ×2）。
- 任务本身 17:36:44 已正常完成（done 已写入 `agent_task_messages`，视频 18:07 出片），后端无任何报错。
- 服务端日志显示同一任务挂了 5 条并发 SSE 流（17:34:29/37/46、17:35:46×2 `[SSE-STREAM] Starting`），
  之后全部停止产出：没有 `Got message`、没有 `Stream ending`、没有 `Stream error`。

## 根因

**TCP 链路单向静默死亡，两端都检测不到：**

1. 该用户所有流共享同一条网络路径（浏览器 ↔ frps ↔ frpc），17:34:47~17:35:47 之间发生了一次
   不带 RST/FIN 的静默中断（切换网络/VPN、WiFi 闪断、frpc 链路抖动等均可能）。
2. 服务端生成器被 ASGI 发送背压**永久冻结在 `yield` 上**（`api/script_writer.py` 的
   `while True` 轮询循环不再执行）：发送缓冲满 → uvicorn 背压 → 协程悬停。
   因此它既没轮询到库里的 done（最后取到的消息停在 17:34:47 的 record 20013），
   也不报错——"没有任何日志"正是协程停在 yield 上的特征。
3. 客户端 fetch 流式 API 在收不到字节时 `reader.read()` 只是一直 pending，
   没有 error/close/超时事件传给 JS。
4. 5 条流 = 恢复/重试路径重复挂流叠加（当时 `selectSession` 切会话新挂流不关旧流），
   每条流独立跑 900s 无业务事件计时器，于各自挂起点 +900s 各弹一个超时气泡。
5. 传输层帮不上忙：内核 TCP 发送缓冲满在协议语义里是"零窗口流控"而非错误；
   只要中间链路继续代 ACK，重传超时（tcp_retries2 ≈ 15~30 分钟）也不会触发。
   jeffS9 实测存在空闲 3~20 天仍 ESTABLISHED 的连接。

## 修复（develop_f1080）

### 1. 客户端空闲读超时 + 断点续传重连（治本） — `web/js/sse_client.js`

- 新增可选参数 `idleTimeoutMs`（marketing_agent 传 15000；服务端心跳 1~3s 一条，
  15s 有 5 倍余量）：超过该时长连 1 个字节（含心跳）都收不到，即判定链路静默假死。
- 判定后自动带 `Last-Event-ID` 断点续传重连（指数退避，`reconnectDelayMs` 基数，
  上限 `maxReconnects` 次），耗尽才走 `onError`。
- 缺省 `idleTimeoutMs=0` 保持旧行为，`script_writer.js` 等既有调用方不受影响。

### 2. 同一任务只允许一条 SSE 流 — `web/js/marketing_agent.js`

- 新增 `activeTaskStreams` 注册表：`handleStream` 挂新流前关闭同一 taskId 的旧流。
- `handleStream` 传入 `idleTimeoutMs/maxReconnects/reconnectDelayMs` 启用断流检测，
  新增 `onReconnect`（日志）与 `onClose`（未收到 done/error 即关闭时按异常结束统一收尾）。
- 收尾逻辑收敛为 `handleStreamEnd`：已收到过内容按静默完成处理，从未收到数据才计失败。

### 3. 服务端生成器背压看门狗 — `api/script_writer.py` + `config/constant.py`

- `_sse_stall_guard_iter` 包裹 `event_generator()`：`asyncio.wait_for` 要求单条事件
  生产+发送在 `SSE_STREAM_SEND_TIMEOUT_SECONDS`（90s，常量入 `config/constant.py`）内完成；
  超时判定连接假死，关闭生成器、终止响应并打 warning 日志，杜绝协程/连接永久泄漏。
- 健康连接心跳秒级，90s 阈值有 30 倍余量；慢客户端场景（缓冲 trickle 排空）不受影响。

### 4. 超时文案补充引导 — `web/i18n/locales/{zh-CN,en}/marketing_agent.json`

- "请求超时，请稍后重试" → "请求超时，任务可能仍在后台生成，请稍后刷新查看或重新发送"。

## 验证

- `tests/api/test_sse_stall_guard.py`：看门狗正常转发 / 卡死源超时关闭且 finally 执行 / 源异常透传。
- `tests/frontend/test_sse_stream_resilience.py`：前端断流检测、单流约束、看门狗接线源扫描。
- 相关回归：`tests/api/test_video_duration_capabilities.py`、`tests/api/test_output_language.py` 通过。

## 后续建议（未做）

- 内核侧：`net.ipv4.tcp_keepalive_time` 7200s 调小（如 300/30/5）、评估
  `TCP_USER_TIMEOUT`，可加速清理假死连接，但对"中间链路代 ACK"场景无效，不能替代应用层心跳。
- 数字人交付前可加尾部黑帧亮度检测自动重试（另案）。
