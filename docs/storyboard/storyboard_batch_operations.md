# 故事板总览批量操作

## 功能范围

批量操作只在故事板的「总览」视图中启用。时间轴视图保持原有播放和编辑行为，不渲染复选框或批量工具栏。

总览支持两种状态：

1. 普通状态：编辑、复制、单镜头删除、添加和插入分镜均可使用。
2. 选择状态：每张分镜卡片显示复选框，支持全选、反选、清空，并提供批量配音、批量视频、按幕生成分镜图和批量删除。

选择框固定在缩略图左上角；进入选择状态后，视频/图片类型标签会自动右移并保留间距，避免标签与选择框相互遮挡。

选择状态是临时 UI 状态，不写入故事板配置，也不在页面刷新后恢复。离开总览时会自动退出并清空选择；已经提交的生成任务不受影响。

## 生成规则

### 批量生成配音

- 粒度是对话，而不是分镜：同一分镜的多条缺失配音会分别入队。
- 无对话、空台词、已有选中配音、缺少角色参考音色时跳过。
- 开启「使用视频音频」的分镜跳过，因为播放和完整视频导出不会使用其 TTS。
- 接口只以短事务写入 `ai_audio`、`tasks`、`storyboard_dialogue_audio` 和选中关系；实际 TTS 仍由 `task/audio_task.py` 调度，不在 Web 请求中执行。

接口：

```http
POST /api/storyboard/{storyboard_id}/batch-generate-missing-voiceovers
```

```json
{"scene_ids": [101, 102, 108], "skip_existing": true}
```

### 批量生成视频

复用 `storyboard_image_batch_job/item` 编排。`auto-generate-missing-videos` 新增可选 `scene_ids`：

- 未传 `scene_ids`：兼容原有全故事板补全。
- 传空数组：返回 `empty_scene_ids`，不会解释为全部。
- 普通视频和数字人都必须存在选中首帧。
- 已有视频、运行中任务和缺少首帧的分镜写入明确的完成/跳过状态。
- 数字人除首帧外仍需满足现有配音就绪条件。
- 生成继续使用首尾帧模式、当前视频模型、故事板比例和分镜视频提示词。

### 按幕生成分镜图

复用 `auto-generate-missing-images` 和现有效果模式宫格服务：

- 只为 `scene_ids` 中的分镜创建 batch item，未选中分镜不会进入宫格。
- 批量选择操作固定发送 `existing_policy: "regenerate"`：已有首帧会重新生成，缺失首帧会正常生成。
- 自动补全入口继续使用默认策略 `existing_policy: "skip"`，不会改变页面首次打开和剧本拆分后的补图行为。
- 优先按 `prompt_json.source.group_id` 分幕，兼容现有 `act_name`/手动分组回退。
- 商业版使用 `quality`，按幕提交 2×2/3×3 宫格并拆格回写首帧。
- 社区版使用 `balanced` 逐镜生成，不伪装为按幕宫格。
- 已有首帧在新图完成前保持展示且不会删除；新图作为新候选写入，成功后自动选中。
- 用户在任务期间手动切换候选时，新结果不得覆盖用户的新选择。
- 已经运行中的首帧任务继续复用，避免重复提交和重复扣费。

请求示例：

```json
{
  "scene_ids": [101, 102, 108],
  "asset_type": "first_frame",
  "sequence_mode": "quality",
  "existing_policy": "regenerate"
}
```

`regenerate` 必须显式提供非空 `scene_ids`，防止调用方遗漏选择范围后意外重生成整个故事板。
返回中的 `regenerated_count` 表示本批次计划重新生成的已有首帧数量；`submitted_count` 仍表示本轮计划生成总数。

## 批量删除

接口：

```http
POST /api/storyboard/{storyboard_id}/scenes/batch-delete
```

```json
{"scene_ids": [101, 102, 108]}
```

删除在一个数据库事务中完成：

1. 锁定并验证所有分镜都属于目标故事板。
2. 任意 ID 失效时返回 `409 selection_stale`，整批零删除。
3. 将相关 pending/running 批任务 item 标为 `scene_deleted_by_user`。
4. 删除分镜；对话、对话音频和分镜资产由现有外键级联清理。

外部供应商任务可能已经提交，无法保证取消，但后续回写不得重新创建已删除分镜的资产。

## 幂等、限制与恢复

- 图片幂等 payload 同时包含排序后的 `scene_ids` 和 `existing_policy`；相同范围、相同策略的重复提交复用原批次，不同范围或策略与活动批次冲突时返回 `active_batch_exists`。
- 音频依靠对话行锁和 `selected_audio_id` 防止重复入队。
- 单次选择上限由 `StoryboardAutoGenerateConstants.MAX_SELECTED_SCENE_COUNT` 控制。
- 图片/视频使用现有 batch session 和状态接口恢复；音频使用现有分镜任务状态轮询恢复。
- 所有同步数据库服务均通过 `asyncio.to_thread()` 从异步路由调用，生成工作不在请求事件循环中执行。

## 主要实现文件

- `web/js/storyboard/batch_selection_state.js`
- `web/js/storyboard/batch_operations.js`
- `web/js/storyboard/render.js`
- `web/js/storyboard/events.js`
- `services/storyboard_agent_cli_service.py`
- `services/storyboard_voiceover_bootstrap_service.py`
- `services/storyboard_batch_operation_service.py`
- `api/storyboard.py`
