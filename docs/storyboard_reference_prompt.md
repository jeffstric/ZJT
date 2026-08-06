# 分镜参考图提示词规则

分镜助手生成图片或视频时，**角色参考图以用户可编辑提示词中的 `【【角色名】】` 为权威来源**（对齐 `video_workflow` 分镜节点 `collectShotFrameRefImages`）。

## 匹配范围

- **角色**：只识别当前画面提示词或视频提示词中的 `【【角色名】】`。
  - 扫描字段：`scene_desc`、`opening_frame_description`、`image_prompt`、`video_prompt`（及 scene 级 `video_prompt`）。
  - 每个标记名独立按 `world_id + 精确全名` 查世界角色库；**不依赖**剧本拆分时的 `characters_present` / 对白列表。
  - 用户后改提示词**新加**的 `【【角色】】`，只要库中同名且有参考图，同样会进入清单。
- **道具**：优先识别 `〖〖道具名〗〗`，也兼容提示词正文中明确出现的道具名。
- **场景**：最多追加当前分镜场景的 1 张参考图。
- **`character_desc`、历史 `prompt_json.props`、剧本角色列表不能单独决定参考图**（例如对白里有角色 B，但提示词未 `【【B】】`，则不挂 B 的参考图）。

### 查不到 / 无图时

- 标记名与库全名不一致、库中无此角色、或无可用 `reference_image` / 变体：该标记**静默不进参考图**，并打 `[storyboard-ref]` warning 日志。
- 不做简称模糊匹配（别名/ID 重拼见 `docs/backend/character_reference_by_id_design.md` 另案）。

## 三条生图路径

| 路径 | 角色参考从哪来 | 如何提交给生图模型 | 备注 |
|------|----------------|--------------------|------|
| **智能体对话** | 提示词 `【【】】` → 查库 | `StoryboardAgentImageToolExecutor` **强制**把场景参考 URL 全量写入 `edit_image.image_url`（对齐节点直传，不靠 LLM 抄全） | 主修复路径 |
| **均衡/速度批量首帧** | 同上（`scene_context` / `generate_image`） | 服务端 `",".join(全部 URL)` | 无 LLM 漏传问题 |
| **效果（质量）首帧宫格** | spatial 可见角色（db_id）+ `【【】】` tag fallback | 整包 `reference_images` 确定性提交 | 新加标记角色会经 tag 补上；offscreen 故意排除 |

质量宫格额外规则：

- `spatial_layout` 中 `offscreen` / `occluded` 角色即使提示词仍有 `【【】】`，**不进入**该格参考图（连续性实体，非当前可见主体）。
- LLM 改写格文案时**不得改动**服务层给出的 `reference_indices`。

## 提示词输出

调用 `edit_image` 或参考图视频工具前，最终生成提示词必须追加图号说明：

```text
参考图说明：图1是角色：布冯。图2是场景：布冯的房间。
```

图号说明需要同时出现在智能体上下文和实际工具调用的 `prompt` 中，避免模型只看到 URL 而不知道每张图的语义。

### 前一分镜图（连续性参考）

在批量生成（均衡/效果模式）或手动图生图传 `source_image` 时，前一个分镜的结果图会作为「连续性参考」追加到 image-edit URL 队列的末尾。该末尾项**也会同步纳入参考图说明**，以「图N是前一分镜。」的形式输出，保证图号与 URL 位置严格一一对应：

```text
参考图说明：图1是角色：奶酪。图2是角色：奶昔。图3是前一分镜。
```

- 前一分镜图在说明中不带名称（`name` 为空），只输出 `图N是前一分镜。`，没有冒号和名称。
- 若前一分镜图 URL 与已有角色/道具/场景参考图重复，会被去重，不重复出现在说明里。
- 速度模式（speed）不引入前一分镜图，说明中也不会出现该项。

## 代码入口

当前复用 helper 位于 `services/storyboard_reference_prompt_service.py`：

- `build_storyboard_reference_items(...)`：生成最小参考图集合（仅提示词标记）。
- `extract_storyboard_reference_names(...)`：抽取有序角色/道具标记名。
- `reference_urls(...)`：按顺序提取工具调用 URL。
- `append_reference_legend(...)`：把“参考图说明”追加到最终工具提示词。
- `append_storyboard_visual_suffix(...)`：项目级画风/构图幂等后缀。

业务接入：

- `services/storyboard_agent_cli_service.py` 的 `scene_context()` / `_collect_reference_image_items`：每个 `【【】】` 独立查库（含新引用），生成 `reference_image_items`。
- `generate_image()`：确定性 `join` 全部参考 URL 后调用 `edit_image`。
- `/api/storyboard/scene/{scene_id}/ai-chat`：把 `reference_image_items` 与【参考图说明】注入智能体上下文；创建任务时把 URL 列表写入 `task.image_urls`。
- `StoryboardAgentImageToolExecutor`：在 `edit_image` / 误用的 `generate_text_to_image` 边界强制注入全量参考 URL，并按最终 URL 顺序重写尾部「参考图说明」，同时追加画风/构图/画幅。
- 质量宫格：`StoryboardFirstFrameGridService._scene_reference_items`（spatial + tag fallback）。

## 与 video_workflow 分镜节点对齐点

| 行为 | video_workflow 分镜节点 | 故事板智能体 / CLI |
|------|-------------------------|-------------------|
| 角色真源 | `imagePrompt` 中 `【【】】` | 提示词字段中 `【【】】` |
| 新引用 | 每标记独立查库 | 每标记独立查库 |
| 提交 | 前端 `ref_image_urls` 直传 | 工具层 / `generate_image` 强制全量 URL |
| 仅对白角色 | 不挂图 | 不挂图 |
