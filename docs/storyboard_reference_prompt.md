# 分镜参考图提示词规则

分镜助手生成图片或视频时，参考图必须来自当前分镜提示词的反向匹配结果。

## 匹配范围

- 角色：只识别当前画面提示词或视频提示词中的 `【【角色名】】`。
- 道具：优先识别 `〖〖道具名〗〗`，也兼容提示词正文中明确出现的道具名。
- 场景：最多追加当前分镜场景的 1 张参考图。
- `character_desc`、历史 `prompt_json.props`、剧本角色列表不能单独决定参考图。

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

- `build_storyboard_reference_items(...)`：生成最小参考图集合。
- `reference_urls(...)`：按顺序提取工具调用 URL。
- `append_reference_legend(...)`：把“参考图说明”追加到最终工具提示词。

如果恢复或新增 `/api/storyboard` 相关接口，构建分镜智能体上下文和最终工具提示词时应共用这组 helper。

## 当前接入点

- `services/storyboard_agent_cli_service.py` 的 `scene_context()` 使用 `build_storyboard_reference_items(...)` 生成 `reference_image_items`，不再从全局画风图、已有首帧或 `character_desc` 扩展参考图。
- `generate_image()` 调用 `edit_image` 前使用 `append_reference_legend(...)` 把图号说明追加到最终生图提示词。
- `/api/storyboard/scene/{scene_id}/ai-chat` 会把同一份 `reference_image_items` 和独立的【参考图说明】传给 `storyboard-image` 智能体，并要求智能体把该说明写入 `edit_image.prompt`。
