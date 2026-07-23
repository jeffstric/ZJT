# script_writer 响应式头部与暂存区

## 背景

`web/script_writer.html` 的顶部工具区包含世界入口、模型选择、AI 介入程度、生图模型、算力、提交、自动提交和语言切换。中等宽度屏幕下，右侧暂存区与头部工具区会同时占用横向空间，容易导致头部超出视口。

## 响应式规则

- `web/css/script_writer.css` 在 `max-width: 1400px` 时将 `.file-sidebar` 从常驻右栏切换为右侧抽屉。
- 中屏抽屉宽度为 `min(360px, 100vw)`，通过 `.file-sidebar.open` 滑入，并使用 `.file-sidebar-overlay` 阻止背景交互。
- `max-width: 768px` 时暂存区使用全屏宽度，适配手机和窄窗口。
- 顶部 `.top-header` 设置 `max-width: 100vw`、横向防溢出与可收缩的左右容器，外层保持左侧入口和右侧工具区同排。
- 中屏会隐藏面包屑和世界名，提交按钮与自动提交只保留图标/开关，右侧工具区内部从左向右换行，避免第一行右侧空白和后续行左侧空白。
- `max-width: 900px` 时，模型选择卡片折叠为“模型设置”图标按钮；点击后复用同一套控件，以固定浮层方式打开，遮罩或 Esc 可关闭。
- 中屏会隐藏 `.feedback-fab-container`，避免意见反馈浮层与输入区、发送按钮、暂存区浮动按钮互相遮挡。
- 中屏会把暂存区浮动按钮上移到输入区上方较远位置，避免贴近发送按钮。
- `max-width: 1024px` 时隐藏左侧 `.step-nav` 悬浮导览条（fixed 叠加约 60px，窄屏会遮挡聊天区/输入区），同时将 `.main-layout` 的 `margin-left` 归零。
- `.chat-area` 设置 `min-width: 0` + `overflow-x: hidden`，防止历史消息中的宽表格/长串把 flex 列撑出视口。
- `#send-btn` 在所有宽度下绝对定位在输入框内部右侧，避免被裁切后表现为“发送按钮消失”。
- **发送按钮垂直布局**：
  - 单行：`top: 50%` + `transform: translateY(-50%)` 在输入框内垂直居中。
  - 多行：JS `syncSendBtnLayout()` 在 `offsetHeight > 56` 时给 `.input-container` 加 `is-expanded`，按钮改为贴右下（`bottom: 8px`）。
  - hover 上浮与居中 `translateY` 合并（`calc(-50% - 1px)`），避免 hover 时位置跳动。
  - `pulse-sending` 只动 opacity，不与 transform 冲突。
- **输入区钉底**：`.input-section` 为聊天列 `flex-shrink: 0` 子项，并设置 `padding-bottom: max(..., env(safe-area-inset-bottom))`，窄屏/刘海机底部始终可见。
- **历史加载后**：`restoreInputControlsAfterHistory()` 恢复可点状态后调用 `syncSendBtnLayout()`，窄屏再对 `.input-section` 做 `scrollIntoView` 兜底。

## AI 介入程度多语言

AI 介入程度选择器由原生 `select` 和覆盖显示层组成。覆盖显示层不会被 `data-i18n` 自动扫描更新，因此 `web/js/script_writer.js` 使用 `INTERVENTION_LEVEL_I18N_KEYS` 将选项值映射到语言包 key：

- `balanced` -> `intervention_balanced`
- `concise` -> `intervention_concise`
- `detailed` -> `intervention_detailed`

语言切换时监听 `ZJTi18n` 的 `locale-changed` 事件，并调用 `updateInterventionLevelDisplay()` 刷新覆盖层文本。

相关语言包位于：

- `web/i18n/locales/zh-CN/index.json`
- `web/i18n/locales/en/index.json`

## 回归测试

静态回归测试位于 `tests/js/test_script_writer_responsive_i18n.js`，覆盖：

- 暂存区在中屏断点折叠为抽屉。
- 顶部容器具备防溢出和可收缩规则。
- 顶部工具区在中屏由右侧区域内部换行，不再整块掉到下一行。
- 900px 以下模型选择区默认折叠，需要时弹窗打开。
- 过窄时意见反馈浮层自动隐藏。
- `max-width: 1024px` 时左侧悬浮导览条（`.step-nav`）隐藏。
- AI 介入程度 i18n key 完整。
- 自绘显示层使用 `window.t()` 并在语言切换后刷新。
- 顶部模型选择器使用自绘下拉菜单，点击覆盖显示层时从控件下方打开固定定位菜单，避免浏览器原生 `select` 菜单向上展开。
