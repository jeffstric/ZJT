# script_writer / marketing_agent 发送快捷键（Enter / Ctrl+Enter）

## 背景

两个对话页面的消息输入框原先均为 Enter 直接发送、Shift+Enter 换行。不少用户
不习惯该交互（多行输入易误发），要求支持 Ctrl+Enter 发送；但直接改默认会打扰
已习惯 Enter 的老用户，因此做成**可切换偏好，默认保持 Enter 发送**。

## 行为

- **默认：Enter 发送**，Shift+Enter 换行（与旧版完全一致）。
- **可切换：Ctrl+Enter 发送**（macOS 下 Cmd+Enter 等效），Enter / Shift+Enter 换行。
- 输入法组词中（`e.isComposing`）任何形态的回车都不会触发发送。

## 切换入口

- **script_writer.html**：输入区状态行（「● 就绪」「会话: xxx」）最右侧的胶囊按钮。
- **marketing_agent.html**：输入栏右侧、发送按钮左边的小按钮。

## 实现

- 偏好持久化（各自独立）：
  - script_writer：`localStorage` 键 `script_writer_send_shortcut`
  - marketing_agent：`localStorage` 键 `marketing_send_shortcut`
  - 值均为 `enter`（默认，缺省即 Enter 发送）/ `ctrl_enter`。
- 按键处理：
  - script_writer：`web/js/script_writer.js` 中 `message-input` 的 `keydown` 监听按模式分发。
  - marketing_agent：`web/js/marketing_agent.js` 的 `onPromptKeydown`，Enter 分支按
    `sendShortcutMode` 判定；@ 引用下拉展开时仍由 mention 导航逻辑优先拦截。
- 文案 i18n：
  - script_writer：`index.json` 的 `send_shortcut_ctrl_enter` / `send_shortcut_enter` /
    `placeholder_message_ctrl_enter`（placeholder 随模式切换）。
  - marketing_agent：`marketing_agent.json` 的 `send_shortcut_ctrl_enter` /
    `send_shortcut_enter` / `send_shortcut_toggle_hint`（按钮文案用 Vue 模板响应式绑定，
    语言切换自动跟随）。
  - script_writer 监听 `ZJTi18n` 的 `locale-changed` 事件刷新按钮与 placeholder 文案。

## 回归点

- 默认（未设置过偏好）行为与旧版一致：Enter 发送、Shift+Enter 换行。
- 切换后刷新页面，模式应保持（localStorage 持久化）。
- 语言切换后按钮与 placeholder 文案跟随新语言。
- @ 引用下拉展开时，Enter/上下键/Esc 的导航行为不受快捷键模式影响。
