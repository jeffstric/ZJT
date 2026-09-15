# script_writer 对话白点刷屏与选项不可点 —— SSE 回调作用域回归修复

## 现象

用户在 `script_writer.html` 与智能体对话时，聊天区左侧不断出现白色小圆角块（"小白点"），
持续堆积铺满聊天区；`ask_user` 提问选项卡片被不断顶走/挤出可视区，用户无法点击选项。

## 根因

回归由提交 `58e459fb`（2026-09-11，P0 安全审计：统一鉴权与属主校验）引入。

该提交将前端裸 `EventSource` 替换为 `SSEClient.createEventStream`（fetch 流，可携带
Authorization 头）。重构 `web/js/script_writer.js` 首次发送路径时，把原本位于流外、
每次发送只执行一次的初始化代码（`addMessage('assistant', '')` 气泡容器、`fullText` 重置、
`startTime`）误留在了 `onMessage` 回调体内。

`SSEClient`（`web/js/sse_client.js`）对**每一条** SSE 事件都调用 `onMessage`，而
`/api/task/{id}/stream` 在一次任务中会推送大量非文本事件：

| 事件 | 频率 |
| --- | --- |
| `connected` | 连接建立时 1 条 |
| `heartbeat` | 流空闲时每 9 秒 1 条（`api/script_writer.py` stream 端点） |
| `progress` | PM 主循环每次迭代 1 条，上限 50 轮（`script_writer_core/agents/pm_agent.py`） |
| `tool_call` | 每次工具调用 1 条 |

因此每条事件都会新建一个**空白** assistant 气泡（`.assistant-message .message-content`
白底圆角 + padding，无内容时即为约 38x30px 的白色小块），且 `addMessage` 内部的
`scrollToBottom()` 不断把视口拉向堆积区，选项卡片被顶走——即"白点 + 无法点击选项"。

### 为什么之前没有

`58e459fb` 之前权限装饰器为空实现（`be8e30b8`），SSE 端点实际零鉴权，原生
`EventSource` 可直连；旧代码结构为：

```javascript
const eventSource = new EventSource(url);
const messageDiv = addMessage('assistant', '');  // 流外，每次发送仅 1 次
eventSource.onmessage = (event) => { ... };      // 回调内不创建气泡
```

一条回复只建 1 个气泡，所有 message 事件向同一气泡累加，无白点。`58e459fb` 将
`eventSource.onmessage = (event) => {` 替换为 `onMessage: async (data) => {` 时，
回调边界划分失误，上述初始化代码被划入回调体内，语义从"每次发送 1 次"变为
"每条事件 1 次"。

## 修复内容

### web/js/script_writer.js

1. 首次发送路径：`messageDiv`/`contentDiv`/`fullText`/`startTime` 移回
   `createEventStream` 调用之前（恢复"整次任务一个气泡容器"语义）。顺带修复了
   `startTime` 被卷入回调导致状态栏"AI 正在回复... (等待了 Xs)"恒为 0.0s 的问题。
2. `reconnectSSE` 重连路径：message 分支增加 `!contentDiv` 判空——首连尚未收到任何
   message 就断线时，旧实现会对 `undefined.innerHTML` 赋值抛 TypeError。

### web/js/marketing_agent.js（同一提交的孪生回归）

`handleStream` 中 `fullContent`/`msgUid`/`streamSettled`/`streamTimeoutId` 等流式状态
及 `settleStream`/`ensurePlaceholder`/`findMsgByIdx` 辅助函数同样被误卷入 `onMessage`
回调体内：

- 状态变量每条事件被重置（流式内容无法跨事件累加，每条 message 事件新建占位气泡）；
- 平级的 `onError` 回调与外层超时 `setTimeout` 引用这些变量时触发 ReferenceError，
  网络错误/超时的清理与 reject 逻辑失效。

修复：将上述声明整体移回 `createEventStream` 调用之前（Promise 构造器作用域）。

## 防回归测试

`tests/js/test_sse_stream_state_scope.js`（node 直接运行，静态断言风格）：

- script_writer.js：`const messageDiv = addMessage('assistant', '')` 必须位于
  `SSEClient.createEventStream` 调用之前且相邻（同一函数内）；
- script_writer.js：重连路径必须存在 `!contentDiv || needsNewMessageDiv` 判空；
- marketing_agent.js：全部流式状态声明与辅助函数必须位于 `createEventStream` 之前。

```bash
node tests/js/test_sse_stream_state_scope.js
```

## 经验

把 `X.onmessage = (event) => {` 机械替换为回调风格 `onMessage: async (data) => {` 时，
必须核对新回调的**边界**：位于旧回调赋值语句之前的初始化代码属于"流外"，不可随之
卷入回调体。凡是 SSE 流会推送多种事件类型的端点，回调体内只应包含"对事件的处理"，
不应包含"每轮对话仅需一次"的状态初始化。
