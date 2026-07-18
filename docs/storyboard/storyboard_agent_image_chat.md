# 分镜助手对话生图

`web/storyboard.html` 的左侧「分镜助手」支持「对话改图」和「视频生成」模式。用户选择对话模型、生图模型和视频模型后，可以直接描述当前分镜首帧或视频要如何生成/调整；发送内容统一交给智能体理解，不直接把用户输入当作最终生成提示词。

## 左侧布局与防遮挡

左侧栏为「上：画面/对话编辑」+「下：分镜助手」两段式：

- `.sidebar-content`：`flex:1; min-height:0; overflow:auto`，承载幕信息、Tab（画面/对话）与表单。
- `.ai-chat-section`：常态贴输入条高度；整区 `max-height: min(72vh, 680px)` 作上限。
- **聊天历史 hover 展开**：`.agent-chat-log` 默认收起；鼠标进入分镜助手 / 输入 `focus-within` / 智能体运行中时，以 **绝对定位浮层** 自输入区向上展开；高度上限约 `min(38vh, 100vh-360px, 400px)`，保证浮层完全落在左侧栏可见区内、顶部消息可滚动看到；移出约 0.3s 渐隐。
- **输入框 hover 加高**：同上触发条件下，`.chat-textarea` 由约 72px 加高到 `min-height:168px`（`max-height:280px`）；移出后收回。
- **长文「展开」/ 调字号**：点击后 `agentChatLogPinned` 固定浮层与输入加高（class `is-chat-log-pinned`），避免 rerender 丢失 `:hover` 导致弹层消失或 textarea 缩回、按钮跳动。鼠标离开助手区后取消 pin。
- 标题「分镜助手」可**手动折叠**（`state.agentChatHistoryOpen`）；手动折叠后 hover 也不展开，标题旁显示「N 条消息」。
- **字号调节**：标题行提供 `A−` / `A+`，档位 `-2…+8`（基准 12px，每档 ±1px，约 10–20px，照顾大龄用户），作用于消息与输入框；偏好写入 `localStorage`（`storyboard_agentChatFontStep`）。
- 单条过长回复默认截断（状态约 160 字、其它约 280 字），支持「展开/收起」。

## 交互流程

1. 前端读取当前分镜的 `prompt_json`、全局画风、构图倾向、画幅比例和已有首帧。
2. 用户在「对话改图」模式发送消息。
3. 前端调用 `POST /api/storyboard/scene/{scene_id}/ai-chat` 启动 `storyboard-image` 智能体任务；图片目标传 `generation_target=image`，视频目标传 `generation_target=video`。
4. 前端通过 `GET /api/storyboard/agent-task/{task_id}/stream` 使用 fetch 流式读取 SSE 消息，保留鉴权请求头。
5. 智能体调用 `generate_text_to_image` 或 `edit_image` 后，会推送 `image_task_submitted` 消息。
6. 前端调用 `POST /api/storyboard/scene/{scene_id}/bind-agent-image-task`，由后端把 `project_ids` 写入 `storyboard_scene_asset` 并选为当前首帧。
7. 前端切换分镜时调用 `GET /api/storyboard/scene/{scene_id}/assets` 加载「分镜图候选」和「视频候选」；后端会在返回前用 `ai_tool_id` 查询 `ai_tools`，**仅**用 `result_url`（任务产出）补全候选 URL，并附带 `status`。**禁止**把 `image_path` / `video_path`（输入参考图，图生图时常为逗号拼接的多张 URL）当作 `result_url`，否则生成中会渲染出无法显示的破图。
8. 如果当前分镜还没有首帧，智能体图片任务绑定后会立即成为当前选中首帧；任务完成轮询到合法单条 `result_url` 后，前端会自动回填主预览图和右侧候选图 URL。
9. 右侧「分镜图候选」：任务未完成（无合法 `result_url`）时展示 loading 占位（旋转图标 +「生成中」），不输出无效 `img src`；完成后显示缩略图。用户点击已完成的候选图时，前端调用 `POST /api/storyboard/scene/{scene_id}/asset/select` 把该候选设置为当前首帧，并同步更新主预览和候选选中态。即使该分镜已有选中视频，点击图片候选后主预览也必须切换到刚选中的首帧；点击视频候选时再切回视频预览。

## 分镜会话隔离

每个分镜视为一个独立的助手会话。前端禁止用页面级 `isAgentRunning` 控制所有分镜，否则上一分镜运行时会错误禁用新分镜的输入框。

- `state.agentRunsBySceneId[sceneId]` 保存每个分镜的运行态和 Agent `taskId`。
- `state.agentMessagesBySceneId[sceneId]` 缓存每个分镜的流式消息；切换分镜时通过 `activateSceneAgentMessages(sceneId)` 激活对应缓存，再异步加载后端历史。
- SSE 回调必须捕获任务发起时的 `streamSceneId`，消息追加、图片/视频任务绑定、运行态结束都只作用于该分镜。
- 旧分镜的后台流可以继续运行，但只有 `streamSceneId === currentSceneId` 时才刷新当前助手 UI，禁止把旧流消息写进新分镜。
- `finishSceneAgentRun(sceneId, expectedTaskId)` 必须校验任务 ID，防止旧任务的迟到回调清除同一分镜后来启动的新任务。
- 当前分镜运行时仅禁用当前分镜的输入框和发送按钮；切换到没有运行任务的分镜后应立即可继续对话。
- 任务进入 `done`、`error` 或连接失败等终态时，必须刷新完整 `AGENT_PANEL`，不能只刷新消息列表。`disabled` 是实际 DOM 属性，只刷新日志会导致输入框在状态结束后仍保持禁用。

该设计沿用 `marketing_agent` 的会话任务归属原则，同时允许 Storyboard 中多个分镜的 SSE 流在后台并行完成。

## 视频生成模式：首尾帧 / 全能参考 + 首帧槽

「视频生成」模式下，分镜助手对齐 `marketing_agent` 的图生视频交互：

### 图片模式切换

工具栏显示 **首尾帧 / 全能参考** 选择器（选项受当前视频模型 `supported_image_modes` 过滤）：

| 模式 | 含义 | `image_mode` | 槽位 |
|------|------|--------------|------|
| 首尾帧 | 第1张为首帧，第2张可选为尾帧 | `first_last_frame` | 最多 2 张（`supports_last_frame=false` 时仅 1 张） |
| 全能参考 | 多图综合驱动 | `multi_reference` | 最多 `max_multi_ref_images`（默认 5） |

模式写入 `config_json.videoImageMode`，刷新后恢复。

### 首帧自动带入

- 当前分镜存在合法 `firstFrameUrl` 时，自动注入 **「首帧」** 槽（`source=scene`），缩略图可见。
- 用户可移除；移除后在媒体栈旁显示紧凑链接「使用当前首帧」可重新带入（不再单独占满宽一行）。
- 切换候选首帧或首帧生成完成轮询到结果时，未 dismiss 的 scene 首帧槽会同步 URL。
- 切换分镜时清空用户上传槽，并按新分镜重新注入 scene 首帧/尾帧。

### 媒体槽 UI（与输入框同行）

视频模式下，参考图/首尾帧放在 `.chat-composer` 内：

- **`.chat-textarea-row`**：仅 `.media-stack` + `textarea` 共享宽度（媒体固定约 64px，不挤工具栏）。
- **`.chat-toolbar`**：单独满宽一行（齿轮 / 模式 / 首尾帧 / @ / 发送），发送按钮始终可见。

| 状态 | 表现 |
|------|------|
| 空 | 虚线 `+` 卡始终可见，点击上传 |
| 有图未满槽 · 默认 | 只显示缩略图（多图错位叠放 + 角标） |
| 有图未满槽 · hover / 点击展开 | 右侧出现虚线 `+`（文档流）；多图同时横向展开 |
| 满槽 | 不渲染 `+` |

角标 pill 规则（对齐 marketing_agent 展示习惯）：

| `videoImageMode` | 角标 |
|------------------|------|
| `first_last_frame` | 首帧 / 尾帧 |
| `multi_reference` | 图1 / 图2 / …（按槽位顺序，不用「首帧」） |

底层 `videoMediaItems[].role` 仍可为 `first_frame` / `last_frame` / `reference`（发送组装不变）。上传/删除 action 不变。

### 上传与发送

- 上传仍走 `POST /api/upload-agent-image`。
- 发送时组装有序绝对 URL 列表 `reference_image_urls`，并带上 `image_mode`。
- 后端视频目标：**`image_to_video.image_urls` 仅使用槽位列表**；角色/场景参考图只作为【参考图说明】文案，不混入 `image_urls`。
- 槽位为空时 Agent 走 `generate_text_to_video`。

### 模型列表字段

`GET /api/storyboard/models` 的图生视频项额外返回：

- `supported_image_modes`
- `supports_last_frame`
- `max_multi_ref_images`
- `supported_durations` / `default_duration`
- `supported_video_resolutions` / `default_video_resolution`

### 齿轮：分辨率 / 时长 / 裁剪至配音

分镜助手齿轮 →「视频模型」Tab 提供：

| 项 | 说明 |
|----|------|
| 分辨率 | 随当前模型 `supported_video_resolutions` 变化；无选项则隐藏 |
| 视频时长 | `Auto` + 模型档位；Auto = 选 **≥ 当前分镜 `duration`** 的最小支持秒数，若无则取最长档 |
| 裁剪至配音时长 | 默认开启；写入故事板 `config_json` 偏好，生成时再快照到 `scene.video_config_json` |

发送视频对话时 body 额外带：`duration`（解析后整数秒）、`duration_mode`、`resolution`、`clip_to_audio_duration`。  
后端校验后写入分镜 `video_config_json`：

```json
{
  "task_id": 123,
  "duration_mode": "auto",
  "duration_seconds": 8,
  "resolution": "720p",
  "clip_to_audio_duration": true,
  "audio_duration": 7.1,
  "updated_at": "..."
}
```

导出（后续实现）按 `clip_to_audio_duration` 决定是否把视频裁到 `scene.duration`；关闭则使用完整生成视频。

## 对话模型选择
分镜助手的对话模型来自 `/api/models`，前端会把选中的模型标准化为 `{ model, model_id, vendor_id }`。这一步兼容旧配置中只保存模型字符串的情况，也兼容模型列表使用 `model_id` 而不是 `id` 作为主键的返回格式，避免用户已在齿轮弹框中选中模型后，发送时仍被误判为未选择对话模型。

同名模型可能同时出现在多个供应商下，例如 `deepseek-v4-flash` 同时属于 `zjt_api` 和 `deepseek`。前端渲染选中态时必须优先匹配 `model_id + vendor_id`，不能只按模型名判断，否则弹框会出现多个 `selected`，真实发送的供应商也可能和用户看到的不一致。

生图模型和视频模型也会写入 storyboard 的 `config_json`，字段为 `selectedImageTaskId`、`selectedVideoTaskId` 和 `selectedDigitalHumanTaskId`。刷新页面后前端先恢复这些选择，再加载模型列表，避免模型下拉框回到默认项。

分镜页会兼容读取剧本页保存的旧 LLM 偏好；剧本页历史字段使用 `vendorId`，分镜页标准字段使用 `vendor_id`。恢复配置时必须同时识别这两种字段，并统一写回 `{ model, model_id, vendor_id }`，否则同名模型会因为供应商缺失而按列表顺序误选到 `zjt_api`。

后端 `StoryboardImageAgentRunner` 创建 `ExpertAgent` 时，必须用任务里的 `model_id` 查询 `model.model_name` 作为实际 LLM 模型名。`agents_config` 中的 `storyboard-image.model` 只作为兜底默认值，不能覆盖用户在弹框中选择的对话模型。

`POST /api/storyboard/scene/{scene_id}/ai-chat` 接收的 `Authorization` 请求头需要在写入 `agent_tasks.auth_token` 前统一归一化，去掉 `Bearer ` 前缀。后台工具函数会自行组装 `Authorization: Bearer {token}`，如果任务表保存了完整 header，会变成 `Bearer Bearer ...`，导致 `get_user_computing_power` 和 `generate_text_to_image` 返回认证失败。

每个分镜的智能体对话记录复用 `chat_messages` 表，session_id 固定为 `storyboard-scene-{scene_id}`，agent_scope 使用 `storyboard_scene`。前端切换分镜时通过 `GET /api/storyboard/scene/{scene_id}/ai-chat/history` 加载该分镜历史；再次发起对话时，后端会把同一分镜的历史 user/assistant 消息传入 `ExpertAgent` 的 `conversation_history`，让智能体保留上下文。

后台 `agent_tasks` 也复用同一个 `storyboard-scene-{scene_id}` 作为 session_id，每次执行仍由独立 task_id 区分。禁止再拼接 `storyboard-{scene_id}-{uuid}`：该格式会超过 `chat_messages.session_id VARCHAR(36)`，导致 `ConversationRecorder` 写入专家内部消息时触发 MySQL 1406。

## 智能体约束

智能体技能定义位于：

- `agents/skills/storyboard-image/SKILL.md`
- `script_writer_core/skills/storyboard-image/SKILL.md`

技能要求智能体严格围绕当前分镜提示词工作：

### 对话生图的空间与邻镜参考

图片模式启动 Agent 前，后端会从当前 `storyboard_scene.prompt_json` 提取一份紧凑的【当前分镜空间硬约束】，内容包括当前空间单元、相机位姿、容器槽位、可见实体、仅连续性实体及位移说明。该区块会与原始 `prompt_json` 一起交给 Agent：

- 物理锚点、容器槽位、三维位置优先于会随机位改变的画面左右描述。
- `visible` / `partial` 可以进入当前画面；`offscreen` / `occluded` 只用于推理角色仍在何处，不得被写成当前可见主体。
- Agent 应把结构化约束转成自然的当前镜头提示词，不得把完整 JSON 或无关容器说明机械抄给生图模型。

空间上下文统一调用 `services.storyboard_spatial.build_spatial_prompt_context()`：商业版由该门面进入 `enterprise.services.storyboard_spatial`，补充基于相机射线的 `derived_screen_position`；社区版继续读取兼容的槽位和可见性数据，并在门面未返回相机位姿时保留 `spatial_layout` 中的原始 `camera_pose`。API 层不实现第二套坐标投影算法。

图片模式还会按 `sort_order, id` 查询当前分镜紧邻的前一、后一分镜，并把存在合法单张首帧 URL 的图片加入 `edit_image` 参考清单。顺序固定为：当前分镜的角色/场景/道具资产图、当前已有首帧、前一分镜首帧、后一分镜首帧、用户补充参考图。URL 和【参考图说明】使用同一条目列表生成，保证图号严格对齐且自动去重。

- 前一分镜首帧用于恢复上游视觉状态。
- 后一分镜首帧仅用于检查下游连续性，禁止把未来动作、位移、入场或状态变化提前复制到当前镜头。
- 相邻分镜不能覆盖当前镜头的动作、机位、物理位置和可见实体；当前 `prompt_json` 和空间硬约束始终优先。
- 只有图片模式自动加载邻镜。视频模式的 `image_to_video.image_urls` 仍然只使用前端首帧/尾帧/全能参考槽位，不会自动混入邻镜首帧。
- 邻镜数据库查询通过 `asyncio.to_thread` 执行，不阻塞 FastAPI 事件循环；本功能不新增数据库字段或迁移。

- 后端会把当前分镜涉及的画风、角色、场景、道具和已有分镜图整理为参考图清单，并在提示词里标明“图 N 是谁”；所有 `upload/...` 或 `/upload/...` 会先按 `server.host` 转成 HTTP/HTTPS URL。
- 参考图清单现在复用 `services/storyboard_reference_prompt_service.py`：只包含当前画面提示词/视频提示词反向匹配出的角色、道具，再追加当前场景图；不会因为 `character_desc`、历史 `prompt_json.props`、全局画风图或已有首帧自动增加参考图。
- 道具参考图以当前分镜的画面提示词和视频提示词为准，优先识别 `〖〖道具名〗〗`；历史 `prompt_json.props` 只作为候选信息，不能单独决定本次参考图。
- 前端提示词框会把 `〖〖道具名〗〗` 渲染为道具 chip，并从道具库的 `reference_image` / `reference_images` 等字段读取缩略图；道具列表加载上限保持足够大，避免世界道具较多时后面的道具无法显示参考图。
- 前端提示词框会把角色 chip 渲染为可点击参考图选择入口。用户可在当前分镜内为角色选择主参考图或 `reference_images` 中的服装变体；场景 chip 可选择主参考图或多角度变体，浮层右侧的“切换场景”继续进入原有场景切换流程。
- 角色服装和场景角度选择保存在 `storyboard_scene.prompt_json.reference_selections`，同一分镜的图片提示词、视频提示词、普通首帧生成、分镜助手视频生成共用这一套选择。刷新页面后 adapter 会重新解析该字段恢复 chip 选中态。
- 后端参考图服务会校验选择结果。选中的 URL 只有在仍属于对应角色/场景的 `reference_image` 或 `reference_images` 时才会采用；跨角色、跨场景或已删除的 URL 会自动回退主参考图，不阻塞生成。
- 参考图清单非空时必须调用 `edit_image`，把清单中的 HTTP/HTTPS URL 按顺序用英文逗号拼接为 `image_url`，不要再询问用户选择文生图还是图生图，也不要传入相对路径或本地路径。
- 调用 `edit_image` 时，最终 `prompt` 末尾必须包含 `参考图说明：图1是角色：...`，确保模型知道每张参考图对应的角色、道具或场景。
- 图片目标没有任何参考图时才调用 `generate_text_to_image`。
- 视频目标有参考图、首帧或尾帧时调用 `image_to_video`，没有任何参考图时才调用 `generate_text_to_video`。
- 提交生成任务后必须返回 `project_ids`，便于后端绑定资产。
- 高算力、多图或风格大幅变更前需要向用户确认。

## 后端注意事项

所有 Web API 中涉及同步数据库读取/写入的位置均通过 `asyncio.to_thread` 包装，避免阻塞 FastAPI 事件循环。该功能没有新增或修改数据库表结构。

`storyboard_scene_asset` 可能只保存 `ai_tool_id`，尤其是分镜助手提交生成任务后立即绑定的候选图/视频。资产列表接口需要把同步的 `AIToolsModel.get_by_id` 放到 `asyncio.to_thread` 中执行，并用任务表中的 **`result_url`（产出）**、`status`、`message` 和 `project_id` 补全返回数据；**不得**用 `image_path` 兜底 `result_url`（`image_path` 是输入）。前端候选区：有合法单条 URL 才渲染 `<img>`/`<video>`，否则按 `status` 显示 loading 或失败占位。

## 角色/道具 chip 缩略图

分镜提示词弹框中的角色、道具 chip 会从世界资产接口加载参考图。前端需要兼容 `reference_image`、`referenceImage`、`reference_images`/`referenceImages` 数组，以及数据库常见的 JSON 字符串形态；数组元素可使用 `url`、`file_url`、`image_url`、`reference_image` 或 `path`。角色、场景、道具列表加载上限保持为 1000，避免世界资产较多时提示词里匹配到的后置资产没有缩略图。

前端会以 `page_size=1000` 请求 `/api/characters`、`/api/locations` 和 `/api/props`，后端 Query 上限必须与 `config.constant.ASSET_LIST_MAX_PAGE_SIZE` 保持一致；否则 FastAPI 会返回 422，导致分镜页面资产列表整体加载失败，角色/道具 chip 只能显示空占位。

角色名自动 chip 化只处理道具标记外的普通文本，不能改写 `〖〖道具名〗〗` 内部内容。历史提示词中如果已经出现 `〖〖【【角色名】】道具名〗〗` 这类嵌套标记，前端会在渲染时把它归一化后再匹配道具库，优先匹配完整道具名，也兼容后缀道具名。

道具 chip 只在 `〖〖道具名〗〗` 能匹配到当前世界道具库时渲染；如果历史提示词中残留了大模型幻觉出的道具（例如当前道具库没有“足球”），前端会去掉外层道具标记并按普通文本显示，避免把不存在的道具误展示为可引用资产。

前端轮询 `/scene/{scene_id}/task-status` 时，需要同时更新当前分镜的 `firstFrameUrl` / `videoUrl` 和 `sceneCandidates` 缓存（含 `status`）。这样生成任务完成后，即使用户没有重新切换分镜，空首帧也会自动显示新生成图片。每次请求发起前必须记录首帧/视频选中 ID；若响应返回前用户已切换对应候选，该部分响应视为过期，不得覆盖用户的新选择。判定「可展示 URL」时须排除逗号拼接的多图字符串；候选资产尚未拿到合法单条 URL 时，候选区显示 loading 占位（含旋转图标），不输出空或非法 `img src`。
