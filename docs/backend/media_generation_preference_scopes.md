# 媒体生成模型偏好隔离与严格执行

## 目标

图片与视频生成统一使用“入口 × 媒体类型 × 生成模式”隔离的模型偏好。用户明确选择的模型在任务提交时形成不可变快照，LLM、共享偏好、默认排序和兼容降级均不得在运行期间覆盖该快照。

入口包括：

- `marketing_ui`
- `storyboard_ui`
- `storyboard_cli`

生成模式包括：

- `image.text_to_image`
- `image.image_edit`
- `video.text_to_video`
- `video.image_to_video`
- `video.reference_to_video`

数字人继续使用现有独立模型选择与执行链路，不纳入以上五种普通媒体模式。

## 模式判定

模式由后端根据真实输入判定，客户端声明只用于诊断，不能覆盖真实输入：

- 图片无输入图：`text_to_image`。
- 图片包含原图或参考图：`image_edit`。
- 视频无图片、视频和音频输入：`text_to_video`。
- 视频只有普通首帧或首尾帧：`image_to_video`。
- `multi_reference`、`first_last_with_ref`、多参考图、参考视频或参考音频：`reference_to_video`。

`first_last_with_ref` 同时要求模型支持首尾帧和多参考图。参考视频或参考音频统一使用现有 `supports_ref_audio_video` 能力校验，本阶段不拆分音频和视频能力字段，也不扩展图片编辑的细粒度输入能力。

## 偏好槽位

偏好复用 `user_preferences`，`pref_type` 使用以下格式：

```text
media_pref.<surface>.<media_type>.<mode>
```

三个入口和五种模式共形成 15 个独立槽位。`user_id + world_id + pref_type` 是唯一隔离键。偏好只作为未来任务的默认值，不是运行中任务的模型来源。

偏好内容示例：

```json
{
  "schema_version": 1,
  "task_id": 27,
  "model_key": "grok_image_to_video",
  "model_name": "Grok",
  "ratio": "16:9",
  "resolution": "720P",
  "duration_seconds": 6,
  "image_mode": "multi_reference",
  "enable_face_mask": false
}
```

`task_id` 是执行依据，`model_key` 用于配置漂移校验，`model_name` 仅用于展示。偏好槽位与默认模型解析不能选择 disabled 或 hidden 模型。偏好读取不使用永久进程内缓存，避免多 Worker 读取陈旧值。

`hidden` 语义分层：

| 场景 | disabled | hidden |
|------|----------|--------|
| 用户偏好保存 / 默认模型回落 | 拒绝 | 拒绝 |
| 模型选择器列表 | 不展示 | 不展示 |
| 直接生成 API（`/api/image-edit` 等，请求已显式 `task_id`） | 拒绝 | **允许**（内部/专用模型，如多角度） |
| 已提交任务的可信 `generation_snapshot` 重试 | 拒绝 | 允许 |

## 不可变任务快照

交互 Agent 在 `agent_tasks.execution_context_json` 中保存五槽位快照集合：

```json
{
  "schema_version": 1,
  "surface": "marketing_ui",
  "storyboard_id": null,
  "scene_id": null,
  "generation_snapshots": {
    "image.text_to_image": {},
    "image.image_edit": {},
    "video.text_to_video": {},
    "video.image_to_video": {},
    "video.reference_to_video": {}
  }
}
```

Storyboard 与 Marketing 的交互 Agent 都在提交时保存完整五槽位快照。工具根据真实输入选择槽位，运行期间不再读取用户偏好或 Storyboard 项目配置。

CLI/批次在 `storyboard_image_batch_job.extra_json` 保存批次快照，并复制到每个 `storyboard_image_batch_item.extra_json`。最终创建生成记录时，快照复制到 `ai_tools.extra_config.generation_snapshot`。

必须满足：

```text
snapshot.task_id == effective_task_id == ai_tools.type
```

任何不一致均返回 `SNAPSHOT_MISMATCH`，不得创建供应商任务。已持久化快照的 `task_id` 与当前 `model_key` 不匹配时同样拒绝执行。

## 模型解析优先级

Marketing UI / 剧本智能体（`script_writer.html` 与 marketing agent 共用 `marketing_ui` surface）：

```text
本次请求 image_preferences.task_id
  → 会话草稿 chat_sessions.text_to_image_model_id
  → marketing_ui 模式偏好 media_pref.*
  → 首次兼容默认模型
```

创建 `agent_tasks` 时上述结果写入不可变 `generation_snapshots`。工具执行只认该快照。

### 对话中切换生图模型（script_writer）

- 用户改选择器：`POST /api/text-to-image-model` + `scope=session` 更新会话草稿 `chat_sessions.text_to_image_model_id`（本对话）。
- **回显一致性**：`GET /api/text-to-image-model` 支持可选 `session_id` 参数，传入时优先读会话草稿（响应 `scope=session`），未传或草稿为空则回退世界默认（`scope=world_default`）。前端恢复会话时传入 `session_id` 回显，避免刷新后本对话选择被世界默认覆盖；`autoSetTextToImageModel` 检测到草稿已存在时跳过覆盖。
- 下拉底部 **「设为默认生图模型」**：`scope=world_default` 写入 legacy `text_to_image_model` + `media_pref.marketing_ui.image.*`（世界默认，供新会话种子；不改当前会话草稿）。
- 下拉底部 **「设为默认对话模型」**：`PUT /api/world-defaults/llm` 写入 `user_preferences.pref_type=default_llm_model`。
- 首页 **用户设置 → 创作默认偏好**：查看/修改同一套世界默认（对话模型 + 生图模型）；与「智能体连接 → 智能体模型偏好」（`storyboard_cli`）隔离。
- **当前已运行任务不变**；**下一条消息**新建 task 时：
  1. 前端应携带 `image_preferences.task_id`（以 UI 当前值为准）；
  2. 若未携带，后端回退读取 `chat_sessions.text_to_image_model_id`；
  3. 再回退 `media_pref` / legacy。
- 显式生图 `task_id` 会尽量同时写入本任务的 `image.text_to_image` 与 `image.image_edit` 快照（模型不兼容则跳过对应槽位）。

Storyboard UI：

```text
本次请求 task_id → storyboard.config_json 模式字段 → storyboard_ui 模式偏好 → 首次兼容默认模型
```

Storyboard CLI：

```text
显式 --task-type → storyboard_cli 模式偏好 → 首次兼容默认模型
```

已配置模型不存在、禁用、隐藏或不兼容时，偏好解析路径直接失败或在偏好界面回落并写入第一个兼容模型；只有从未配置过或已失效的槽位可以按 `sort_order` 初始化。直接生成 API 在请求已显式传入 `task_id` 时允许 `hidden=True` 的内部模型（例如相机控制 / 场景多角度使用的 `qwen-multi-angle`），但仍拒绝 disabled。已提交任务的可信快照同样允许模型后来变为 `hidden=True` 后继续执行，disabled 仍拒绝。

## Storyboard 项目配置

新字段为：

```json
{
  "selectedTextToImageTaskId": 16,
  "selectedImageEditTaskId": 7,
  "selectedTextToVideoTaskId": 20,
  "selectedImageToVideoTaskId": 27,
  "selectedReferenceToVideoTaskId": 29
}
```

旧 `selectedImageTaskId` 和 `selectedVideoTaskId` 只用于兼容初始化。模型字段通过专用接口逐字段原子更新，不再由前端回写整份 `config_json`。

## 严格执行

- LLM 工具 Schema 不允许自由决定媒体模型。
- 执行器使用赋值覆盖：`tool_args["task_type"] = snapshot.task_id`。
- 图片编辑不再自动切换到其他模型。
- Enterprise 视频显式模型无效时直接失败。
- 视频批次模型不兼容时不得把 `image_mode` 降级为 `first_last_frame`。
- 模型信息工具只返回当前任务锁定模型的信息。
- Web 异步路由中的同步数据库操作统一通过 `asyncio.to_thread` 执行。

## API

```text
GET/PUT /api/marketing/media-preferences
GET/PUT /api/storyboard/media-preferences
GET/PUT /api/storyboard/cli/media-preferences
```

路由决定 surface，客户端不能任意指定。一次 PUT 只更新一个模式。Storyboard UI 请求通过 `storyboard_id` 解析并校验 world 访问权限。CLI 偏好 Web 接口：

```text
GET  /api/storyboard/cli/media-preferences?world_id=
PUT  /api/storyboard/cli/media-preferences
     body: { world_id, media_type, mode, profile: { task_id } }
```

`surface` 固定为 `storyboard_cli`，按 `user_id + world_id` 隔离，不读写 Storyboard 项目 `config_json`。首页「智能体连接信息」弹窗的「智能体模型偏好」Tab 使用该接口。

统一错误码：

- `MODEL_REQUIRED`
- `MODEL_NOT_FOUND`
- `MODEL_DISABLED`
- `MODEL_HIDDEN`
- `MODEL_MODE_UNSUPPORTED`
- `MODEL_INPUT_UNSUPPORTED`
- `SNAPSHOT_MISMATCH`

## 兼容策略

采用兼容读取、只写新结构：

- Marketing 从现有图片、文生视频和图生视频偏好初始化相应槽位。
- Storyboard 从每个项目自己的旧模型字段初始化兼容的新字段。
- CLI 不继承 UI 偏好。
- 旧字段保留一个兼容周期，但不再作为已提交任务的运行时来源。

## 验收

1. 用户选择模型与最终 `ai_tools.type` 一致。
2. LLM 不能覆盖快照模型。
3. 不存在静默模型或输入模式降级。
4. 15 个偏好槽位互相隔离。
5. 多故事板、多分镜和多 Worker 任务快照互不污染。
6. 重试和批次恢复只读取提交时快照。
7. Storyboard 模型配置字段级更新。
8. 数据库迁移、前后端测试和阻塞调用检查通过。
