# script_writer SSE 断线状态恢复

`web/script_writer.html` 在发送剧本创作消息后，会先创建后台任务，再通过
`/api/task/{task_id}/stream` 监听 SSE 流式响应。

## 前端状态约定

- 发送开始时，`#send-btn` 会设置 `disabled = true` 并添加 `sending` class。
- 任务正常 `done`、任务返回 `error`、任务最终失败或取消时，必须调用 `resetProcessingState()`。
- `resetProcessingState()` 负责清理 `isProcessing`、`pendingVerificationId`、`pendingVerificationData`，并恢复发送按钮。

## ask_user / human_verification 输入框保护

AI 通过 `ask_user` 弹出询问选项时，底部 `#message-input` 可能已有用户草稿。提交验证答案的
`submitVerificationAnswer(userInput, { fromInput })` 约定：

- **点击预设选项**：`fromInput=false`，只提交选项文案，**不清空**输入框草稿。
- **从输入框发送**（Enter / 发送按钮）：`fromInput=true`，仅在**提交成功后**清空输入框。
- **提交失败**（业务失败、网络错误等）：始终保留输入框内容，便于用户重试；若仍处于
  `pendingVerificationId` 状态，会恢复发送按钮。

## SSE 断线兜底

当 SSE `onerror` 触发时，前端会先调用 `/api/task/{task_id}/status` 确认后台任务状态：

- 如果任务已经 `completed`、`failed` 或 `cancelled`，立即调用 `resetProcessingState()`。
- 如果任务仍在运行，前端尝试重连 SSE。
- 如果 `/status` 也失败，说明浏览器已经无法确认后台任务是否存在，通常对应服务重启、端口断开或网络异常。此时前端必须隐藏打字和工具调用提示，调用 `resetProcessingState()`，并显示需要刷新/重试的错误提示，避免发送按钮长期停留在 `sending` 状态。

## 回归测试

相关静态回归测试：

```bash
node tests/js/test_script_writer_sse_disconnect_state.js
```
