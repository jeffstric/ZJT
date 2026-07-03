# Storyboard Agent CLI

供智能体调用的分镜自动化 CLI 位于 `scripts/storyboard_agent_cli.py`，业务逻辑在
`services/storyboard_agent_cli_service.py`。CLI 默认只提交任务并立即返回 JSON，不阻塞等待
图片或视频生成完成。

## 命令

```bash
python -m scripts.storyboard_agent_cli create-storyboard-from-script --script-id 20 --user-id 1
python -m scripts.storyboard_agent_cli scene-context --scene-id 123 --user-id 1
python -m scripts.storyboard_agent_cli split-from-script --storyboard-id 10 --user-id 1
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --mode text_to_image
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --mode image_edit --source-image selected_first_frame
python -m scripts.storyboard_agent_cli generate-video --scene-id 123 --user-id 1 --mode image_to_video
python -m scripts.storyboard_agent_cli generate-video --scene-id 123 --user-id 1 --mode text_to_video
python -m scripts.storyboard_agent_cli task-status --scene-id 123
```

## 能力

- `scene-context` 聚合分镜画面提示词、视频提示词、关联角色、场景、道具、参考图和当前选中素材；同时返回 `reference_image_items`，包含参考图 URL、来源类型和给模型看的“图 N 是谁”的标签。道具以当前画面/视频提示词中的 `〖〖道具名〗〗` 或实际出现的道具名为准，历史 `prompt_json.props` 只作为候选，不会单独带入参考图。
- `create-storyboard-from-script` 根据 `script_id` 创建或复用空 storyboard，返回 `storyboard_id`，
  供下一步 `split-from-script` 使用；重复调用同一 `user_id + world_id + episode_number` 会返回既有 storyboard。
- `split-from-script` 复用 `api.storyboard.build_storyboard_scenes_from_parsed_script` 和
  `StoryboardModel.create_scenes`，把已关联剧本拆分为分镜。`storyboard.html` 在空分镜弹框中提供“拆分剧本模型”选择，前端会把用户选择的 `model`、`model_id`、`vendor_id` 传给后端，避免落回默认 `gemini-3-flash-preview`。
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
```
