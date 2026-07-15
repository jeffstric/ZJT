# Storyboard Agent CLI

供智能体调用的分镜自动化 CLI 位于 `scripts/storyboard_agent_cli.py`，业务逻辑在
`services/storyboard_agent_cli_service.py`。CLI 默认只提交任务并立即返回 JSON，不阻塞等待
图片或视频生成完成。

## 命令

```bash
python -m scripts.storyboard_agent_cli create-storyboard-from-script --script-id 20 --user-id 1
python -m scripts.storyboard_agent_cli create-storyboard-from-script --script-id 20 --user-id 1 --model deepseek-v4-pro --model-id 1008 --vendor-id 10
python -m scripts.storyboard_agent_cli scene-context --scene-id 123 --user-id 1
python -m scripts.storyboard_agent_cli split-from-script --storyboard-id 10 --user-id 1
python -m scripts.storyboard_agent_cli list-scenes --storyboard-id 10 --user-id 1
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --mode text_to_image
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --mode image_edit --source-image selected_first_frame
python -m scripts.storyboard_agent_cli generate-video --scene-id 123 --user-id 1 --mode image_to_video
python -m scripts.storyboard_agent_cli generate-video --scene-id 123 --user-id 1 --mode text_to_video
python -m scripts.storyboard_agent_cli task-status --scene-id 123
```

## 能力

- `scene-context` 聚合分镜画面提示词、视频提示词、关联角色、场景、道具、参考图和当前选中素材；同时返回 `reference_image_items`，包含参考图 URL、来源类型和给模型看的“图 N 是谁”的标签。道具以当前画面/视频提示词中的 `〖〖道具名〗〗` 或实际出现的道具名为准，历史 `prompt_json.props` 只作为候选，不会单独带入参考图。
  - **画面提示词文本（`image_prompt`）只保留画面本身需要呈现的信息**：标题 + 画风(style) + 构图(composition_preference) + 画面描述(scene_desc) + 镜头景别(perspective) + 光照(lighting)。**不再拼接** 角色名/外貌、场景名/描述、道具名/描述——这些实体的视觉特征已通过「参考图 + 参考图说明」由生图模型识别；把设定档案（尤其道具的“规格/功能/背景/剧情作用/象征意义”、场景的“类型/规模/剧情作用”）塞进文本会浪费 token 且干扰画面，也与「角色外貌交给角色库/参考图」的剧本解析规则保持一致。`video_prompt` 在无独立值时回退到 `image_prompt`，因此同样精简。
- `create-storyboard-from-script` 根据 `script_id` 创建或复用空 storyboard，返回 `storyboard_id`，
  供下一步 `split-from-script` 使用；重复调用同一 `user_id + world_id + episode_number` 会返回既有 storyboard。可显式传 `model/model_id/vendor_id`；未传时继承当前用户在该世界的拆分模型偏好，没有偏好时使用服务端默认模型，并写入 `config_json.selectedScriptSplitLlmModel`。
- `split-from-script` 复用 `api.storyboard.build_storyboard_scenes_from_parsed_script` 和
  `StoryboardModel.create_scenes`，把已关联剧本拆分为分镜。`storyboard.html` 在空分镜弹框中提供“拆分剧本模型”和“生图模型”选择，前端会把用户选择的 `model`、`model_id`、`vendor_id` 传给后端，避免落回服务端默认模型；“生图模型”选择写入 `state.selectedImageTaskId` 并持久化到 `config_json`，拆分完成后由 `auto-generate-missing-images` 直接读取，无需改动拆分接口本身。
- `generate-image` 支持 `auto`、`text_to_image` 和 `image_edit`，默认 `auto`。`auto` 会先收集当前分镜涉及的画风、角色、场景、道具和已有分镜图参考；只要存在参考图，就把这些 URL 按顺序发送给 `edit_image`，并把“图 1 是角色/场景/道具”的说明追加到 prompt；没有参考图时才调用 `generate_text_to_image`。`upload/...` 和 `/upload/...` 会按 `server.host` 转为 HTTP/HTTPS URL 后再暴露给智能体和工具。提交成功后把返回的 `project_ids` 绑定为 `storyboard_scene_asset`，默认选中第一条素材。
- `generate-video` 支持 `text_to_video` 和 `image_to_video`，图生视频默认使用当前首帧，也可用
  `first_last_with_ref` 或 `multi_reference` 汇入参考图。
- `bind-projects` 可把已有 `ai_tools` 记录绑定到分镜素材，便于外部 agent 已完成提交后回写分镜。

## 复用关系

生图链路复用 `script_writer_core.mcp_tool.generate_text_to_image` 和 `edit_image`，它们沿用首页
文生图、图片编辑的后端提交逻辑与用户模型偏好。`/api/storyboard/scene/{scene_id}/generate-image` 也调用同一个 service，因此 `storyboard.html` 手动生图、CLI 和分镜助手共享同一套参考图收集与自动模式选择规则。视频链路复用 `enterprise.tools.video_tools`
里的 `generate_text_to_video` 和 `image_to_video`，它们调用首页文生视频、图生视频对应后端接口，
并读取用户预设的视频模型偏好。

当前 CLI 和 Web API 都通过 `AiToolSubmissionService` 适配层集中复用现有后端能力。

## 推荐调用链

```bash
python -m scripts.storyboard_agent_cli create-storyboard-from-script --script-id 20 --user-id 1
```

从返回 JSON 中读取 `storyboard_id`，再调用：

```bash
python -m scripts.storyboard_agent_cli split-from-script --storyboard-id <storyboard_id> --user-id 1
python -m scripts.storyboard_agent_cli list-scenes --storyboard-id <storyboard_id> --user-id 1
```

`insert-scene` / `update-scene` 的 `--duration` 支持小数秒，会按 `DECIMAL(10,3)` 写入分镜；视频生成时再统一向上取整提交给视频模型。

## Agent 默认配置

- `split-from-script` 未显式传 `model` 时，后端优先读取 `storyboard.config_json.selectedScriptSplitLlmModel`（支持字符串或 `{model,model_id,vendor_id}` 对象，对象会被解包并精确路由到对应 vendor/model），再回退到服务端默认模型。
- `split-from-script` 是**异步命令**：它创建持久化拆分任务后立即返回 `task_id` + `status_url`，不再同步阻塞等待 LLM 解析（原同步路径会占用线程池约 7 分钟）。实际拆分、资产化、create_scenes、子场景九宫格全部由 `task/script_split_task.py` worker 推进（与 `generate-from-script` 路由收敛到同一 worker）。调用方需轮询 `GET /api/script-split/tasks/{task_id}` 直到终态，再用 `list-scenes` 查询结果。
- `split-from-script --force-overwrite-subscene-grids` 已废弃：字段仍被接受但不再生效，子场景九宫格 i2i 只填充无参考图的子场景，永不覆盖已有参考图。
- `auto-generate-missing-images` 未显式传 `task_type` 时，后端优先读取 `storyboard.config_json.selectedImageTaskId`。只有需要覆盖当前分镜配置时才传 `task_type`。

`world-context` 的 `scripts`、`characters`、`locations`、`props` 均为
`{total,page,page_size,data}` 分页对象，列表必须从对应 `.data` 读取。

`GET /api/storyboard/{storyboard_id}/task-status?asset_type=first_frame` 返回每个分镜的
`selected_assets`；首帧 URL 路径固定为
`scenes[].selected_assets.first_frame.result_url`。同一素材对象还包含 `id`、
`ai_tool_id`、`status`、`message` 和嵌套 `ai_tool`。

```json
{
  "success": true,
  "storyboard_id": 10,
  "asset_type": "first_frame",
  "scene_count": 1,
  "scenes": [
    {
      "scene_id": 123,
      "title": "分镜28",
      "selected_assets": {
        "first_frame": {
          "id": 900,
          "ai_tool_id": 501,
          "status": 2,
          "message": "done",
          "result_url": "https://example.com/upload/storyboard/first_frame/example.png",
          "ai_tool": {"id": 501, "status": 2}
        },
        "last_frame": null,
        "video": null
      }
    }
  ]
}
```

## Agent Token 与 HTTP 调用

除本地 CLI 外，分镜自动化能力也提供 HTTP 调用入口，供网页端或其他智能体调用。HTTP 调用不直接使用长期 Agent Token 操作业务接口，而是先用 Agent Token 换取短期 `auth_token`，后续请求继续沿用现有 `Authorization: Bearer <auth_token>` 鉴权链路。

Agent Token 存储在独立的 `user_api_tokens` 表，不复用 `users.api_token`，避免影响现有商业版权限判断。Token 记录包含 `token_type`、`scopes`、`enabled`、`expire_at`、`last_used_at` 等字段。分镜智能体 token 应使用 `token_type=agent`，并至少包含 `auth:exchange` scope；需要生成能力时再增加 `storyboard:generate`，只读场景使用 `storyboard:read`。

换取短期登录态：

```bash
curl -X POST http://localhost:9003/api/agent-auth/exchange \
  -H "Content-Type: application/json" \
  -d '{"token":"zjt_agent_xxx","device_uuid":"storyboard-agent"}'
```

返回示例：

```json
{
  "success": true,
  "auth_token": "short-lived-auth-token",
  "expires_at": "2026-07-03T20:00:00",
  "user_id": 1,
  "token_type": "agent",
  "scopes": ["auth:exchange", "storyboard:generate"]
}
```

获取可调用命令 schema：

```bash
curl http://localhost:9003/api/storyboard/agent/schema \
  -H "Authorization: Bearer short-lived-auth-token"
```

调用分镜命令：

```bash
curl -X POST http://localhost:9003/api/storyboard/agent/commands/generate-image \
  -H "Authorization: Bearer short-lived-auth-token" \
  -H "Content-Type: application/json" \
  -d '{"scene_id":123,"mode":"auto","asset_type":"first_frame"}'
```

HTTP 入口会从 `Authorization` 解析真实用户，并覆盖请求体中的 `user_id`。因此外部智能体不需要、也不能通过 body 冒充其他用户。后端路由内部调用同步 service 时统一使用 `asyncio.to_thread()`，不会阻塞 FastAPI 事件循环。

## CLI 环境

智能体连接包会返回 `environment` 字段，值来自后端 `comfyui_env`，未设置时为 `dev`。HTTP 调用不需要额外设置环境；只有改用本地 CLI fallback 时，才需要在运行 `python -m scripts.storyboard_agent_cli ...` 前设置：

```powershell
$env:comfyui_env="<environment>"
```

```bash
export comfyui_env="<environment>"
```

CLI 和 HTTP command API 的 JSON 返回都会带 `environment`，方便智能体确认当前连接和本地命令使用的是同一套配置。
