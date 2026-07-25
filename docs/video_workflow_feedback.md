# 视频工作流意见反馈入口

## 更新内容
- 版本：2026-01-28
- 说明：视频工作流页面新增可见的浮动”意见反馈”按钮，并提供半透明遮罩与独立卡片式弹窗，用户可通过点击空白区域或关闭按钮及时收起弹窗。
- 版本：2026-07-25
- 说明：支持 YAML 配置关闭入口 / 替换个人微信二维码（`frontend.show_feedback_qr`、`frontend.feedback_qr_url`），见 [backend/frontend_ui_visibility.md](./backend/frontend_ui_visibility.md)。

## 交互细节
1. 右下角浮动按钮固定在视口上方，保持在其他元素之上。
2. 点击浮动按钮右侧的”×”会将按钮最小化为一个很小的”?”，以减少遮挡，同时不会影响工作流画布操作。
3. 最小化状态会在刷新页面后保持（通过 localStorage 持久化）。
4. 点击”?”会恢复按钮并打开反馈弹窗。
5. 弹窗采用 `modal-overlay.active` 控制显示状态，点击遮罩空白处或”×”按钮即可关闭。
6. 弹窗内容展示官方二维码，并附带”关闭”按钮，便于用户快速返回工作流画布。

## 实现细节

### 相关文件

| 文件 | 说明 |
|------|------|
| `web/video_workflow.html` | HTML 结构（反馈按钮和弹窗） |
| `web/js/events.js` | JavaScript 交互逻辑 |

### HTML 结构

- **浮动按钮容器**：`.feedback-btn-wrapper#feedbackBtnWrapper`
  - **反馈按钮**：`.feedback-btn#feedbackBtn`（显示”意见反馈”或”?”）
  - **最小化按钮**：`.feedback-btn-delete#feedbackMinimizeBtn`（显示”×”）
- **反馈弹窗**：`.modal-overlay#feedbackModal`
  - **弹窗卡片**：`.feedback-modal-card`
  - **关闭按钮**：`.feedback-modal-close`
  - **二维码图片**：默认 `/files/二维码.jpg`，可由 `frontend.feedback_qr_url` 覆盖
  - **关闭操作按钮**：底部”关闭”按钮

### 配置关闭 / 换图

| YAML 键 | 默认 | 作用 |
|---------|------|------|
| `frontend.show_feedback_qr` | `true` | 为 `false` 时隐藏 `#feedbackBtnWrapper` 与反馈弹窗 |
| `frontend.feedback_qr_url` | `/files/二维码.jpg` | 弹窗内二维码 `src` |

前端在 `web/js/events.js` 的 `applyFeedbackVisibilityFromServer()` 中读取  
`GET /api/system/server-config` 后应用；请求失败时保持默认开启。

**加载时序（防误点）**：

1. HTML 中 `#feedbackBtnWrapper` 默认带 `hidden` 类，不可见、不可点  
2. `handleFeedbackBtnClick` 依赖 `feedbackQrEnabled` 标志，配置未确认前直接 return  
3. `show_feedback_qr !== false` 时才 `showFeedbackUi()` 并置 `feedbackQrEnabled = true`  

这样在页面/配置尚未就绪时点击绿色区域，不会弹出微信二维码。

### 核心函数

| 函数 | 说明 |
|------|------|
| `applyFeedbackVisibilityFromServer()` | 读取 server-config；关闭时隐藏入口，开启时设置二维码 URL 并 `initFeedbackBtn` |
| `initFeedbackBtn()` | 初始化按钮最小化状态，从 localStorage 读取 |
| `applyFeedbackBtnState(isMinimized)` | 应用按钮状态（正常/最小化），更新 CSS 类和按钮文本 |
| `minimizeFeedbackBtn()` | 最小化按钮，设置 `localStorage.feedbackBtnMinimized = 'true'` |
| `restoreFeedbackBtn()` | 恢复按钮，设置 `localStorage.feedbackBtnMinimized = 'false'` |
| `handleFeedbackBtnClick(e)` | 点击反馈按钮处理：如果已最小化则先恢复，然后打开反馈弹窗 |

### localStorage 持久化

| 键名 | 说明 |
|------|------|
| `feedbackBtnMinimized` | 按钮最小化状态（`'true'` / `'false'`） |

> 注：旧版本使用 `feedbackBtnDeleted` 键，已自动迁移为 `feedbackBtnMinimized`。

### 初始化流程

1. 页面加载完成后调用 `initFeedbackBtn()`
2. 从 localStorage 读取 `feedbackBtnMinimized` 状态
3. 调用 `applyFeedbackBtnState()` 应用对应样式
4. 如果处于最小化状态，按钮显示为小号”?”，隐藏”×”按钮
