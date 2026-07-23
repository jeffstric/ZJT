# 创建世界：友好错误提示

## 背景

`POST /api/worlds`（`server.py` `create_world`）在以下场景会返回错误：

| 场景 | HTTP | `code` | `message` |
| --- | --- | --- | --- |
| 名称为空 | 400 | -1 | `世界名称不能为空` |
| **重名**（同 `user_id` 下 `name` 已存在，`WorldModel.get_by_name`） | 400 | -1 | `该世界已经存在，请选择其他名称` |
| 其他异常 | 500 | -1 | `str(e)` |

> 注意：后端**没有**独立的 `error_code` 字段区分"重名"与其他错误，前端只能依据 HTTP 状态码与 `message` 文案判断。重名判断的底层去重按 `(user_id, name)` 精确匹配（`model/world.py` `get_by_name`）。

## 入口位置

创建世界共有多处入口，均调用 `POST /api/worlds`：

| 入口页面 | 弹窗 | 驱动函数 | 备注 |
| --- | --- | --- | --- |
| 剧本策划 `web/script_writer.html` | `#new-world-modal`（左上角「新建世界」按钮 `onclick="showNewWorldModal()"`，`script_writer.html:220`） | `web/js/script_writer.js` `createNewWorld()` | **主要入口**，用户感知最强的「左上角新建」 |
| 画布 `web/video_workflow.html` | `createWorldModal`（`video_workflow.html:766`） | `web/js/events.js` `createWorld()` | 名称输入框 `createWorldNameInput` |
| 工作流列表 `web/video_workflow_list.html` | 新建世界弹窗 | `web/js/video_workflow_list.js` `handleWorldSubmit()` | |
| 营销智能体 | —— | `web/js/marketing_agent.js` `createWorld()` | 静默失败，无 UI 提示 |

> `web/storyboard.html`（故事板编辑器）本身**不创建世界**，仅读取 URL/故事板数据中的 `world_id`。用户口中的「storyboard 左上角新建世界」实际指剧本策划页（script-writer）侧边栏的「新建世界」按钮。

## 友好报错机制

为避免仅靠 3 秒即消失的 toast 提示（在弹窗内易被忽略），创建世界失败时采用**行内错误 + 输入框标红 + 自动聚焦**。

### 剧本策划页（script-writer，主要入口）

**根因**：`showError()`（`script_writer.js`）会把错误节点 `appendChild` 到 `#chat-messages`（聊天消息区），而 `#new-world-modal` 模态框完全遮挡聊天区，导致重名等错误虽被插入但**用户看不到**。修复方式：错误改为直接在弹窗内输入框下方行内展示。

- `web/script_writer.html:1128` 名称输入框下方新增 `#new-world-error`（`role="alert"`、`aria-live="polite"`）。
- `web/js/script_writer.js` 提供：
  - `showNewWorldFormError(message)`：行内红字 + `new-world-name` 边框置红（`#ef4444`）+ 聚焦。
  - `clearNewWorldFormError()`：隐藏错误文本、恢复边框。
- `createNewWorld()` 错误分支改为调用 `showNewWorldFormError`：

  | 触发条件 | 行为 |
  | --- | --- |
  | 名称未填 | `showNewWorldFormError('请输入世界名称')` |
  | 后端 `code !== 0`（含重名） | `showNewWorldFormError(data.message)`，原样透传「该世界已经存在，请选择其他名称」 |
  | `fetch`/解析异常 | `showNewWorldFormError(error.message \|\| '网络异常，创建世界失败')` |
  | 创建成功 | `showSuccess(...)` + 关闭弹窗 + 自动选中新世界 |
- 创建按钮进入「创建中...」loading 态，`finally` 恢复。
- `showNewWorldModal()` / `closeNewWorldModal()` / 名称输入框 `input` 事件均调用 `clearNewWorldFormError()`，避免红框/红字残留。

### 画布页（video_workflow / events.js）

- 名称输入框下方新增 `#createWorldError`（`role="alert"`、`aria-live="polite"`）作为行内错误容器。
- `web/js/events.js` 提供两个 helper：
  - `showWorldFormError(message)`：写入行内错误文本、把 `createWorldNameInput` 边框置红（`#ef4444`）、聚焦输入框。
  - `clearWorldFormError()`：隐藏错误文本、恢复输入框边框。
