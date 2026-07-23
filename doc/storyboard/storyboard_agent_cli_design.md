# 故事板智能体 CLI 设计方案

## 实现状态

本方案已落地首版：

- CLI 入口：`scripts/storyboard_agent_cli.py`
- 业务服务：`services/storyboard_agent_cli_service.py`
- 使用文档：`docs/storyboard/storyboard_agent_cli.md`
- 测试：
  - `tests/storyboard/test_storyboard_agent_cli.py`
  - `tests/storyboard/test_storyboard_agent_cli_service.py`

已实现命令：

```bash
python -m scripts.storyboard_agent_cli scene-context --scene-id 123 --user-id 1
python -m scripts.storyboard_agent_cli create-storyboard-from-script --script-id 20 --user-id 1
python -m scripts.storyboard_agent_cli split-from-script --storyboard-id 10 --user-id 1
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --mode text_to_image
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --mode image_edit --source-image selected_first_frame
python -m scripts.storyboard_agent_cli generate-video --scene-id 123 --user-id 1 --mode image_to_video
python -m scripts.storyboard_agent_cli generate-video --scene-id 123 --user-id 1 --mode text_to_video
python -m scripts.storyboard_agent_cli task-status --scene-id 123
python -m scripts.storyboard_agent_cli bind-projects --scene-id 123 --asset-type first_frame --project-ids 9001
```

首版没有实现语音生成、数字人和整集导出；这些仍按原计划留到后续补充。
`create-storyboard-from-script` 会先根据 `script_id` 读取 `world_id`、`episode_number`、`title`，
创建或复用空 storyboard，并返回后续 `split-from-script` 需要的 `storyboard_id`。

## 背景

`web/storyboard.html` 当前已经拆成轻量入口，主要逻辑位于 `web/js/storyboard/*`。故事板后端已有分镜表、分镜资产表、分镜生成接口，以及基于剧本拆分分镜的接口。现在需要补充一套供智能体稳定调用的 CLI，让智能体可以用结构化命令完成：

- 基于剧本拆分并写入分镜。
- 获取指定分镜的画面提示词、视频提示词、关联角色/场景/道具及参考图。
- 基于指定分镜生成分镜图。
- 基于指定分镜生成视频。

本期只覆盖拆分分镜、上下文读取、生图、生视频；语音生成、数字人、整集导出等后续再补充。

## 现有能力

### 故事板数据

- `model/storyboard_scene.py`
  - `prompt_json`：画面提示词结构，包含 `perspective`、`style`、`scene_desc`、`character_desc`、`location`、`props`、`source` 等。
  - `video_prompt`：视频提示词。
  - `video_config_json`：分镜视频配置。
  - `selected_first_frame_id` / `selected_last_frame_id` / `selected_video_id`：当前选中资产指针。
- `model/storyboard_scene_asset.py`
  - 以 `asset_type = first_frame | last_frame | video` 保存分镜生成资产。
  - 可绑定 `ai_tool_id`，最终结果由 `ai_tools.result_url` 回填。
- `api/storyboard.py`
  - `POST /api/storyboard/{storyboard_id}/generate-from-script`：已有基于剧本解析并写入分镜能力。
  - `POST /api/storyboard/scene/{scene_id}/generate-image`：已有分镜图生成提交能力。
  - `POST /api/storyboard/scene/{scene_id}/generate-video`：已有分镜视频生成提交能力。
  - `GET /api/storyboard/scene/{scene_id}/task-status`：已有分镜资产任务状态查询能力。

### 首页 AI 工具能力

`web/index.html` 首页加载以下工具页：

- `web/js/pages/text_to_image.js`：文生图，提交到 `POST /api/text-to-image`。
- `web/js/pages/image_edit.js`：图片编辑，提交到 `POST /api/image-edit`。
- `web/js/pages/ai_video_gen.js`：文生视频，提交到 `POST /api/ai-app-run`。
- `web/js/pages/image_to_video.js`：图生视频，提交到 `POST /api/ai-app-run-image`。

这些接口的共同后端链路是：

1. 校验 `UnifiedConfigRegistry` 中的 `task_id` 与任务分类。
2. 按模型、时长、分辨率、图片模式计算算力。
3. 扣减算力。
4. 创建 `ai_tools`。
5. 创建 `TasksModel(TASK_TYPE_GENERATE_VIDEO)`。
6. 由 scheduler 异步处理并回填结果。

CLI 不应复制这些业务逻辑，应复用同一套后端函数。必要时把 `server.py` 中四个路由内的核心提交逻辑抽成 service，再由首页 API、故事板 API、CLI 共同调用。

## 目标

提供一个稳定、机器可读、非交互优先的 CLI：

```bash
python -m scripts.storyboard_agent_cli split-from-script --storyboard-id 10 --user-id 1
python -m scripts.storyboard_agent_cli scene-context --scene-id 123 --user-id 1
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --mode text_to_image
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --mode image_edit
python -m scripts.storyboard_agent_cli generate-video --scene-id 123 --user-id 1 --mode image_to_video
python -m scripts.storyboard_agent_cli generate-video --scene-id 123 --user-id 1 --mode text_to_video
python -m scripts.storyboard_agent_cli task-status --scene-id 123 --user-id 1
```

默认行为是“提交任务后立即返回”，不阻塞等待生成完成。可选 `--wait` 仅在 CLI 进程内轮询，不影响 Web 接口事件循环。

## 推荐架构

### 分层

新增或抽取以下模块：

- `services/ai_tool_submission_service.py`
  - 从 `server.py` 中抽出首页四类生成接口的核心函数。
  - 提供同步函数，供 CLI 直接调用。
  - FastAPI 路由中使用 `asyncio.to_thread()` 调用同步函数，或保留异步 wrapper，避免阻塞事件循环。
- `services/storyboard_agent_cli_service.py`
  - 负责故事板场景上下文聚合、提示词构建、模型偏好解析、资产绑定。
  - 调用 `ai_tool_submission_service.py` 提交文生图、图片编辑、文生视频、图生视频任务。
- `scripts/storyboard_agent_cli.py`
  - 只负责参数解析、调用 service、JSON 输出和退出码。
- `api/storyboard.py`
  - 后续可逐步改为调用 `storyboard_agent_cli_service.py`，减少故事板接口与 CLI 的重复逻辑。

### 为什么不直接让 CLI 调 HTTP

直接调 HTTP 实现快，但会重复处理 host、token、权限头、上传格式和错误解析。CLI 位于同一仓库和同一运行环境中，直接复用 service 更稳定，也更容易测试。

## CLI 命令设计

### split-from-script

用途：复用现有“基于剧本拆分分镜”能力，把剧本解析结果写入 `storyboard_scene` 和 `storyboard_dialogue`。

命令：

```bash
python -m scripts.storyboard_agent_cli split-from-script \
  --storyboard-id 10 \
  --user-id 1 \
  --mode append
```

参数：

- `--storyboard-id`：必填。
- `--user-id`：必填，用于权限与写入 `last_modified_user_id`。
- `--script-id`：可选，不传时复用故事板上的 `script_id`，再回退到 `world_id + episode_number`。
- `--mode`：默认 `append`。
  - `append`：仅当故事板为空时生成；已有分镜则返回错误，保持现有防重复语义。
  - `force-empty`：后续扩展，清空旧分镜再生成。本期不做。
- `--style`：可选，覆盖故事板画风。

返回：

```json
{
  "success": true,
  "operation": "split_from_script",
  "storyboard_id": 10,
  "created_scene_count": 12,
  "scene_ids": [101, 102, 103],
  "status": "completed"
}
```

复用点：

- `api/storyboard.py::resolve_storyboard_script_id`
- `api/storyboard.py::build_storyboard_scenes_from_parsed_script`
- `StoryboardModel.create_scenes`

建议把这些逻辑整理为 `StoryboardScriptSplitService.split_from_script(...)`，API 和 CLI 共用。

### scene-context

用途：给智能体获取指定分镜的完整上下文。

命令：

```bash
python -m scripts.storyboard_agent_cli scene-context --scene-id 123 --user-id 1
```

返回：

```json
{
  "success": true,
  "operation": "scene_context",
  "scene_id": 123,
  "storyboard": {
    "id": 10,
    "world_id": 98,
    "workflow_ratio": "16:9",
    "style": "cinematic realism",
    "composition_preference": "low angle, centered subject"
  },
  "scene": {
    "title": "分镜1",
    "duration": 5,
    "prompt_json": {},
    "image_prompt": "完整画面提示词",
    "video_prompt": "完整视频提示词",
    "video_type": "video",
    "selected_first_frame": {
      "asset_id": 301,
      "ai_tool_id": 9001,
      "result_url": "/upload/xxx.png",
      "status": "completed"
    },
    "selected_video": {
      "asset_id": 401,
      "ai_tool_id": 9010,
      "result_url": "/upload/xxx.mp4",
      "status": "completed"
    }
  },
  "references": {
    "characters": [
      {
        "id": 1,
        "name": "角色A",
        "reference_image": "/upload/character/a.png",
        "reference_images": []
      }
    ],
    "location": {
      "id": 2,
      "name": "客厅",
      "reference_image": "/upload/location/living-room.png",
      "reference_images": []
    },
    "props": [
      {
        "id": 3,
        "name": "钥匙",
        "reference_image": "/upload/props/key.png"
      }
    ]
  }
}
```

上下文来源：

- 分镜主体：`StoryboardSceneModel.get_by_id`
- 故事板：`StoryboardModel.get_by_id`
- 角色：`storyboard_dialogue.character_id` 去重后查 `CharacterModel`
- 场景：`prompt_json.location.id` 或 `prompt_json.source.location_db_id`
- 道具：`prompt_json.props[].db_id` / `id` 查 `PropsModel`
- 当前资产：`StoryboardSceneAssetModel` + `AIToolsModel`

### generate-image

用途：生成或编辑当前分镜图。

命令：

```bash
python -m scripts.storyboard_agent_cli generate-image \
  --scene-id 123 \
  --user-id 1 \
  --mode text_to_image \
  --asset-type first_frame
```

```bash
python -m scripts.storyboard_agent_cli generate-image \
  --scene-id 123 \
  --user-id 1 \
  --mode image_edit \
  --asset-type first_frame \
  --source-image selected_first_frame
```

参数：

- `--mode`
  - `text_to_image`：文生图，复用首页 `POST /api/text-to-image` 的核心提交函数。
  - `image_edit`：图片编辑，复用首页 `POST /api/image-edit` 的核心提交函数。
- `--asset-type`
  - `first_frame`：默认。
  - `last_frame`：可选。
- `--source-image`
  - `selected_first_frame`：图片编辑默认值，使用当前选中首帧。
  - `selected_last_frame`
  - 显式 URL。
- `--task-id`：可选，显式指定模型任务 ID。
- `--ratio`：可选，默认故事板 `workflow_ratio`。
- `--image-size`：可选，默认读取用户图片偏好。
- `--prompt`：可选，默认根据分镜上下文生成。
- `--save-preference`：可选，显式指定时是否写入用户偏好；默认不写。

模型选择：

1. 显式 `--task-id` 优先。
2. 读取 `user_preferences.text_to_image_model`。
3. 回退到系统默认文生图模型。
4. `image_edit` 如当前文生图模型不支持图片编辑，回退到可用图片编辑模型。

图片编辑输入：

- CLI 必须验证图片 URL 来自当前分镜资产或用户显式参数。
- 不允许智能体伪造 URL。
- 如果 `--mode image_edit` 且找不到源图，返回错误，提示先生成分镜图或传入 URL。

返回：

```json
{
  "success": true,
  "operation": "generate_image",
  "scene_id": 123,
  "mode": "text_to_image",
  "asset_type": "first_frame",
  "ai_tool_id": 9001,
  "asset_id": 301,
  "project_ids": [9001],
  "model": {
    "task_id": 7,
    "name": "nano-banana-Pro"
  },
  "status": "submitted"
}
```

绑定规则：

- 首页提交函数返回 `project_ids`。
- CLI service 为每个 `project_id` 创建 `storyboard_scene_asset`。
- 默认选中第一个 asset。
- 不等待最终图像完成，最终 URL 由 scheduler 回填到 `ai_tools.result_url`，`task-status` 再读取。

### generate-video

用途：基于当前分镜生成视频。

命令：

```bash
python -m scripts.storyboard_agent_cli generate-video \
  --scene-id 123 \
  --user-id 1 \
  --mode image_to_video
```

```bash
python -m scripts.storyboard_agent_cli generate-video \
  --scene-id 123 \
  --user-id 1 \
  --mode text_to_video
```

参数：

- `--mode`
  - `image_to_video`：默认。复用首页 `POST /api/ai-app-run-image` 的核心提交函数。
  - `text_to_video`：复用首页 `POST /api/ai-app-run` 的核心提交函数。
- `--task-id`：可选，显式指定视频模型任务 ID。
- `--image-mode`
  - `first_last_frame`：默认，使用当前选中首帧和可选尾帧。
  - `multi_reference`：使用角色、场景、道具参考图。
  - `first_last_with_ref`：首尾帧 + 参考图。
- `--duration`：可选，默认 `storyboard_scene.duration`，再回退到用户视频偏好。
- `--ratio`：可选，默认故事板 `workflow_ratio`。
- `--resolution`：可选，默认读取用户视频偏好。
- `--prompt`：可选，默认 `scene.video_prompt`。

模型选择：

- `image_to_video`
  1. 显式 `--task-id`
  2. `user_preferences.image_to_video_model`
  3. 分类 `TaskCategory.IMAGE_TO_VIDEO` 中启用的默认模型
- `text_to_video`
  1. 显式 `--task-id`
  2. `user_preferences.text_to_video_model`
  3. 分类 `TaskCategory.TEXT_TO_VIDEO` 中启用的默认模型

输入图规则：

- `image_to_video + first_last_frame`
  - 必须已有 `selected_first_frame_id` 且对应 `result_url` 已完成。
  - 如果存在 `selected_last_frame_id` 且有结果，可作为尾帧。
- `image_to_video + multi_reference`
  - 从 `scene-context.references` 收集角色、场景、道具参考图。
  - 如果没有任何参考图，返回错误。
- `text_to_video`
  - 不需要图片，直接使用 `video_prompt`。

返回：

```json
{
  "success": true,
  "operation": "generate_video",
  "scene_id": 123,
  "mode": "image_to_video",
  "image_mode": "first_last_frame",
  "ai_tool_id": 9010,
  "asset_id": 401,
  "project_ids": [9010],
  "model": {
    "task_id": 12,
    "name": "Seedance 2.0"
  },
  "status": "submitted"
}
```

绑定规则：

- 提交成功后创建 `storyboard_scene_asset(asset_type='video')`。
- 默认选中第一个视频 asset。

### task-status

用途：查询当前分镜选中资产状态。

命令：

```bash
python -m scripts.storyboard_agent_cli task-status --scene-id 123 --user-id 1
```

返回结构复用 `GET /api/storyboard/scene/{scene_id}/task-status`，并可额外包含 `project_ids`。

## 提示词构建

### image_prompt

默认由以下字段拼接：

- 故事板 `style`
- 故事板 `composition_preference`
- 分镜 `prompt_json.perspective`
- 分镜 `prompt_json.style`
- 分镜 `prompt_json.scene_desc`
- 分镜 `prompt_json.character_desc`
- 场景名称与场景描述
- 道具名称
- 角色名称与可见外观描述

图片提示词应描述可见画面，不写心理活动。

### video_prompt

默认优先使用 `storyboard_scene.video_prompt`。为空时从 `prompt_json` 和 `video_config_json` 构建：

- 画面主体
- 动作
- 镜头运动
- 景别与视角
- 时长
- 风格与节奏

## 非阻塞与线程约束

- 所有 Web 路由必须保持 async 非阻塞语义。
- 如果 service 是同步 DB/文件逻辑，FastAPI 路由必须用 `asyncio.to_thread()` 包装。
- 禁止在 async 路由中直接调用阻塞网络库。
- 不引入无超时的 `Future.result()`。
- CLI 本身可以同步执行，但 `--wait` 轮询必须有超时参数：
  - `--wait-timeout` 默认 900 秒。
  - `--poll-interval` 默认 5 秒。

## 错误返回

所有 CLI 错误也返回 JSON，并使用非 0 退出码：

```json
{
  "success": false,
  "operation": "generate_video",
  "scene_id": 123,
  "error_code": "missing_first_frame",
  "error": "图生视频需要先生成并选中首帧图片"
}
```

建议错误码：

- `not_found`
- `permission_denied`
- `invalid_task_id`
- `missing_first_frame`
- `missing_reference_image`
- `missing_source_image`
- `insufficient_power`
- `submit_failed`
- `timeout`

## 文件改动建议

第一阶段只做可测试的核心闭环：

- 新增 `doc/storyboard/storyboard_agent_cli_design.md`
- 新增 `services/ai_tool_submission_service.py`
- 新增 `services/storyboard_agent_cli_service.py`
- 新增 `scripts/storyboard_agent_cli.py`
- 修改 `server.py`
  - 把 `/api/text-to-image`、`/api/image-edit`、`/api/ai-app-run`、`/api/ai-app-run-image` 的核心提交逻辑抽到 `ai_tool_submission_service.py`。
  - 路由保留现有入参和返回结构，避免影响首页。
- 修改 `api/storyboard.py`
  - 后续逐步让故事板生成图/视频接口调用 service。
  - 本期可先保持兼容，只保证 CLI 与首页共用提交 service。
- 修改或新增测试：
  - `tests/storyboard/test_storyboard_agent_cli_service.py`
  - `tests/storyboard/test_storyboard_agent_cli.py`
  - 针对 `server.py` 抽取后的兼容测试。

## 测试策略

单元测试：

- `scene-context` 能正确解析角色、场景、道具引用。
- `split-from-script` 复用现有拆分逻辑，空故事板能生成分镜，非空故事板默认拒绝重复生成。
- `generate-image text_to_image` 调用文生图提交 service 并绑定 `first_frame` asset。
- `generate-image image_edit` 在已有首帧时调用图片编辑提交 service 并绑定新 asset。
- `generate-video image_to_video` 在已有首帧时调用图生视频提交 service 并绑定 video asset。
- `generate-video text_to_video` 不要求首帧，调用文生视频提交 service 并绑定 video asset。

静态检查：

```bash
python -m py_compile scripts/storyboard_agent_cli.py services/storyboard_agent_cli_service.py services/ai_tool_submission_service.py
python scripts/lint_blocking_calls.py
```

关键回归：

```bash
pytest tests/storyboard -q
pytest tests/task -q
pytest tests/config -q
```

## 后续扩展

- 语音生成：接入 `storyboard_dialogue_audio` 和现有 TTS 任务。
- 数字人：复用现有 `SceneVideoType.DIGITAL_HUMAN` 与数字人生成链路。
- 整集批量生成：按分镜顺序批量提交图/视频任务。
- 智能体 MCP 工具化：在 CLI 稳定后，将同样 service 包装为可调用工具。
