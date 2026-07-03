# 分镜助手对话生图

`web/storyboard.html` 的左侧「分镜助手」支持「对话改图」和「视频生成」模式。用户选择对话模型、生图模型和视频模型后，可以直接描述当前分镜首帧或视频要如何生成/调整；发送内容统一交给智能体理解，不直接把用户输入当作最终生成提示词。

## 交互流程

1. 前端读取当前分镜的 `prompt_json`、全局画风、构图倾向、画幅比例和已有首帧。
2. 用户在「对话改图」模式发送消息。
3. 前端调用 `POST /api/storyboard/scene/{scene_id}/ai-chat` 启动 `storyboard-image` 智能体任务；图片目标传 `generation_target=image`，视频目标传 `generation_target=video`。
4. 前端通过 `GET /api/storyboard/agent-task/{task_id}/stream` 使用 fetch 流式读取 SSE 消息，保留鉴权请求头。
5. 智能体调用 `generate_text_to_image` 或 `edit_image` 后，会推送 `image_task_submitted` 消息。
6. 前端调用 `POST /api/storyboard/scene/{scene_id}/bind-agent-image-task`，由后端把 `project_ids` 写入 `storyboard_scene_asset` 并选为当前首帧。
7. 前端切换分镜时调用 `GET /api/storyboard/scene/{scene_id}/assets` 加载「分镜图候选」和「视频候选」；后端会在返回前用 `ai_tool_id` 查询 `ai_tools.result_url` 补全候选 URL，避免绑定任务后资产表尚未写入 `result_url` 时出现空缩略图。
8. 如果当前分镜还没有首帧，智能体图片任务绑定后会立即成为当前选中首帧；任务完成轮询到 `result_url` 后，前端会自动回填主预览图和右侧候选图 URL。
9. 右侧「分镜图候选」一行只显示一个候选图。用户点击候选图时，前端调用 `POST /api/storyboard/scene/{scene_id}/asset/select` 把该候选设置为当前首帧，并同步更新主预览和候选选中态。

## 对话模型选择

分镜助手的对话模型来自 `/api/models`，前端会把选中的模型标准化为 `{ model, model_id, vendor_id }`。这一步兼容旧配置中只保存模型字符串的情况，也兼容模型列表使用 `model_id` 而不是 `id` 作为主键的返回格式，避免用户已在齿轮弹框中选中模型后，发送时仍被误判为未选择对话模型。

同名模型可能同时出现在多个供应商下，例如 `deepseek-v4-flash` 同时属于 `zjt_api` 和 `deepseek`。前端渲染选中态时必须优先匹配 `model_id + vendor_id`，不能只按模型名判断，否则弹框会出现多个 `selected`，真实发送的供应商也可能和用户看到的不一致。

生图模型和视频模型也会写入 storyboard 的 `config_json`，字段为 `selectedImageTaskId`、`selectedVideoTaskId` 和 `selectedDigitalHumanTaskId`。刷新页面后前端先恢复这些选择，再加载模型列表，避免模型下拉框回到默认项。

分镜页会兼容读取剧本页保存的旧 LLM 偏好；剧本页历史字段使用 `vendorId`，分镜页标准字段使用 `vendor_id`。恢复配置时必须同时识别这两种字段，并统一写回 `{ model, model_id, vendor_id }`，否则同名模型会因为供应商缺失而按列表顺序误选到 `zjt_api`。

后端 `StoryboardImageAgentRunner` 创建 `ExpertAgent` 时，必须用任务里的 `model_id` 查询 `model.model_name` 作为实际 LLM 模型名。`agents_config` 中的 `storyboard-image.model` 只作为兜底默认值，不能覆盖用户在弹框中选择的对话模型。

`POST /api/storyboard/scene/{scene_id}/ai-chat` 接收的 `Authorization` 请求头需要在写入 `agent_tasks.auth_token` 前统一归一化，去掉 `Bearer ` 前缀。后台工具函数会自行组装 `Authorization: Bearer {token}`，如果任务表保存了完整 header，会变成 `Bearer Bearer ...`，导致 `get_user_computing_power` 和 `generate_text_to_image` 返回认证失败。

每个分镜的智能体对话记录复用 `chat_messages` 表，session_id 固定为 `storyboard-scene-{scene_id}`，agent_scope 使用 `storyboard_scene`。前端切换分镜时通过 `GET /api/storyboard/scene/{scene_id}/ai-chat/history` 加载该分镜历史；再次发起对话时，后端会把同一分镜的历史 user/assistant 消息传入 `ExpertAgent` 的 `conversation_history`，让智能体保留上下文。

## 智能体约束

智能体技能定义位于：

- `agents/skills/storyboard-image/SKILL.md`
- `script_writer_core/skills/storyboard-image/SKILL.md`

技能要求智能体严格围绕当前分镜提示词工作：

- 后端会把当前分镜涉及的画风、角色、场景、道具和已有分镜图整理为参考图清单，并在提示词里标明“图 N 是谁”；所有 `upload/...` 或 `/upload/...` 会先按 `server.host` 转成 HTTP/HTTPS URL。
- 道具参考图以当前分镜的画面提示词和视频提示词为准，优先识别 `〖〖道具名〗〗`；历史 `prompt_json.props` 只作为候选信息，不能单独决定本次参考图。
- 前端提示词框会把 `〖〖道具名〗〗` 渲染为道具 chip，并从道具库的 `reference_image` / `reference_images` 等字段读取缩略图；道具列表加载上限保持足够大，避免世界道具较多时后面的道具无法显示参考图。
- 参考图清单非空时必须调用 `edit_image`，把清单中的 HTTP/HTTPS URL 按顺序用英文逗号拼接为 `image_url`，不要再询问用户选择文生图还是图生图，也不要传入相对路径或本地路径。
- 图片目标没有任何参考图时才调用 `generate_text_to_image`。
- 视频目标有参考图、首帧或尾帧时调用 `image_to_video`，没有任何参考图时才调用 `generate_text_to_video`。
- 提交生成任务后必须返回 `project_ids`，便于后端绑定资产。
- 高算力、多图或风格大幅变更前需要向用户确认。

## 后端注意事项

所有 Web API 中涉及同步数据库读取/写入的位置均通过 `asyncio.to_thread` 包装，避免阻塞 FastAPI 事件循环。该功能没有新增或修改数据库表结构。

`storyboard_scene_asset` 可能只保存 `ai_tool_id`，尤其是分镜助手提交生成任务后立即绑定的候选图/视频。资产列表接口需要把同步的 `AIToolsModel.get_by_id` 放到 `asyncio.to_thread` 中执行，并用任务表中的 `result_url`、`status`、`message` 和 `project_id` 补全返回数据；前端候选区再从补全后的 URL 渲染缩略图。

前端轮询 `/scene/{scene_id}/task-status` 时，需要同时更新当前分镜的 `firstFrameUrl` / `videoUrl` 和 `sceneCandidates` 缓存。这样生成任务完成后，即使用户没有重新切换分镜，空首帧也会自动显示新生成图片；如果候选资产尚未拿到 URL，候选区显示“生成中”占位，不输出空 `img src`。
