# script_writer 发送快捷键（Enter / Ctrl+Enter）

## 背景

`web/script_writer.html` 消息输入框原先 Enter 直接发送，多行输入（Shift+Enter 换行）不符合多数 IM/创作工具的用户习惯，容易误发。

## 行为

- **默认：Ctrl+Enter 发送**（macOS 下 Cmd+Enter 等效），Enter / Shift+Enter 均为换行。
- **可切换：Enter 发送**（旧行为），Shift+Enter 换行。
- 输入法组词中（`e.isComposing`）任何形态的回车都不会触发发送。

## 切换入口

输入区状态行右侧的快捷键按钮（`#send-shortcut-toggle`，如「Ctrl+Enter 发送」），点击即在两种模式间切换。

## 实现

- 偏好持久化：`localStorage` 键 `script_writer_send_shortcut`，值 `ctrl_enter`（默认，缺省）/ `enter`。
- 按键处理：`web/js/script_writer.js` 中 `message-input` 的 `keydown` 监听，按当前模式分发。
- 文案：按钮与输入框 placeholder 随模式切换，i18n key 位于 `index.json`：
  - `send_shortcut_ctrl_enter` / `send_shortcut_enter`（按钮）
  - `placeholder_message_ctrl_enter` / `placeholder_message`（placeholder）
  - 监听 `ZJTi18n` 的 `locale-changed` 事件在语言切换后刷新文案。

## 回归点

- 切换后刷新页面，模式应保持（localStorage 持久化）。
- 语言切换后按钮与 placeholder 文案跟随新语言。
- Enter 模式下行为与旧版完全一致（Enter 发送、Shift+Enter 换行）。
