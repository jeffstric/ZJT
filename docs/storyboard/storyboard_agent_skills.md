# Storyboard Agent Skills

本项目提供两套给外部智能体使用的 storyboard 自动化 skill：

- Codex：`.agents/skills/storyboard-agent-api/SKILL.md`
- Claude Code：`.claude/skills/storyboard-agent-api/SKILL.md`

两套 skill 都支持 `api_version = storyboard-agent-api/v1`，并使用相同的 HTTP command API 和本地 CLI fallback。

## 连接方式

智能体一开始不知道协议、host、port 和 token。用户需要在 `web/index.html` 首页用户名旁点击 2x2 智能体图标按钮，复制连接信息给智能体。按钮使用 `web/assets/logos` 中本地化的 Codex/OpenAI、Claude Code、OpenClaw、WorkBuddy 图标快照，hover 显示“智能体连接”。社区版的连接信息弹框会显示“限时免费”徽章，商业版不显示。

连接信息包含：

```json
{
  "base_url": "https://example.com",
  "agent_token": "zjt_agent_xxx",
  "api_version": "storyboard-agent-api/v1",
  "app_version": "1.0.0"
}
```

首页复制给智能体的提示词应明确要求使用 `$storyboard-agent-api` 协助处理智剧通分镜，并说明可查看世界列表、世界下的剧本、角色、场景、道具和分镜场次，再按需创建分镜、拆分剧本、生成分镜图/视频和查询任务状态。

智能体必须先调用：

```text
POST /api/agent-auth/exchange
```

用 `agent_token` 换取短期 `auth_token`，后续 HTTP 调用统一使用：

```text
Authorization: Bearer <auth_token>
```

## 固定入口

`storyboard-agent-api/v1` 的固定入口如下：

```text
POST /api/agent-auth/exchange
POST /api/agent-auth/storyboard-connection
GET  /api/storyboard/agent/schema
POST /api/storyboard/agent/commands/{command}
POST /api/storyboard/{storyboard_id}/auto-generate-missing-images
GET  /api/storyboard/{storyboard_id}/task-status?asset_type=first_frame
```

## 新增发现命令

为了让智能体不再要求用户手动提供剧本 ID，CLI 和 HTTP command API 增加了以下只读命令：

```text
list-worlds
list-world-scripts
get-script
list-world-characters
list-world-locations
list-world-props
world-context
list-scenes
```

推荐流程：

1. `list-worlds`：查看当前 token 用户可访问的世界列表。
2. `world-context`：查看某个世界下的剧本、角色、场景、道具列表。
3. `get-script`：只有需要剧本全文时再读取单个剧本内容。
4. 再调用 `create-storyboard-from-script`、`split-from-script`。
5. `split-from-script` 返回 `scenes` 概要；也可以调用 `list-scenes` 按 `storyboard_id` 查询场次 ID、标题、时长和素材概要。
6. 再调用生成相关命令。

`world-context` 中的 `scripts`、`characters`、`locations`、`props` 不是数组，而是
统一的 `{total,page,page_size,data}` 分页对象；智能体应读取 `.data`。

`list-world-scripts` 默认不返回剧本全文，只返回 `content_length`。确实需要全文时，可以传 `include_content: true`，或调用 `get-script`。

世界对象里的 `story_outline` 默认只返回预览：前 50 字 + 后 50 字，并带有 `story_outline_preview` 与 `story_outline_truncated` 字段。需要完整故事大纲时，在 HTTP body 里传 `include_full_story_outline: true`；CLI 对应参数是 `--include-full-story-outline`。

`split-from-script` 不传 `model` 时，后端优先读取 `storyboard.config_json.selectedScriptSplitLlmModel`；`auto-generate-missing-images` 不传 `task_type` 时，后端优先读取 `storyboard.config_json.selectedImageTaskId`。只有确实要覆盖当前分镜配置时，智能体才应显式传这些字段。

`create-storyboard-from-script` 可传 `model/model_id/vendor_id` 保存当前世界的拆分模型偏好；未传时自动继承该偏好。故事板任务状态中的首帧地址位于 `scenes[].selected_assets.first_frame.result_url`。

## CLI 示例

```bash
python -m scripts.storyboard_agent_cli list-worlds --user-id 1
python -m scripts.storyboard_agent_cli world-context --world-id 1 --user-id 1
python -m scripts.storyboard_agent_cli world-context --world-id 1 --user-id 1 --include-full-story-outline
python -m scripts.storyboard_agent_cli get-script --script-id 20 --user-id 1
python -m scripts.storyboard_agent_cli list-scenes --storyboard-id 10 --user-id 1
python -m scripts.storyboard_agent_cli list-world-characters --world-id 1 --user-id 1
python -m scripts.storyboard_agent_cli list-world-locations --world-id 1 --user-id 1
python -m scripts.storyboard_agent_cli list-world-props --world-id 1 --user-id 1
```

## 关键约束

- HTTP 路由会从 `Authorization` 解析真实用户，并覆盖 body 里的 `user_id`。
- 本地 CLI fallback 必须显式传 `--user-id`。
- 新增发现命令会校验 `world_id` / `script_id` 是否属于当前用户。
- 批量生成缺失分镜图必须调用 `auto-generate-missing-images`。
- 不允许通过直接写数据库或绕过 command service 的方式创建生成任务。
- 批量生成内部逐个调用现有 `generate_image()`，算力扣减继续由现有图像生成链路完成。
- 任务状态 `0` / `1` 表示运行中，`2` 表示完成，负数表示失败、取消或超时。

## 环境字段

智能体连接包、`/api/agent-auth/exchange`、`/api/storyboard/agent/schema` 和 `POST /api/storyboard/agent/commands/{command}` 的返回结果都会带上 `environment` 字段，值来自 `comfyui_env`，未设置时为 `dev`。

HTTP 调用只需要使用连接包中的 `base_url` 和 `agent_token`；如果智能体改用本地 CLI fallback，必须先按连接包中的 `environment` 设置环境变量：

```powershell
$env:comfyui_env="<environment>"
```

```bash
export comfyui_env="<environment>"
```

首页复制给智能体的提示词也会包含该环境说明，避免智能体在本地 CLI 中误连到默认 `dev` 配置。
