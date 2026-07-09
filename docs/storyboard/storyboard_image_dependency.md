# Storyboard 首帧生图对 Location 参考图的依赖控制

## 目标

分镜首帧生图前，检查当前 scene 引用的子场景 `location.reference_image` 是否就绪：
- 就绪 → 正常生图。
- 九宫格任务仍在运行 → **保持 PENDING，本 tick 等待**，不改状态。
- 九宫格失败/无图 → 走父图降级或纯文生图兜底。

## 设计：外部 readiness check（非 dependency_item_id）

**不复用 `storyboard_image_batch_item.dependency_item_id`**。该字段语义是同一 batch 内「上一分镜图」依赖，不能表达「外部 `grid_image_tasks` 还在跑」。

改为：在 `generate_image()` 内做 readiness 检查，批量调度器捕获特定 error_code 后 `continue` 保持 PENDING。

## 判定逻辑（按 sequence_mode 条件阻止）

`StoryboardAgentCliService._check_location_grid_readiness(context, sequence_mode=...)`：

按用户选择的生图模式（`sequence_mode`）决定缺图时是否阻止首帧生图：

| reference_image | 运行中任务 | quality（效果）模式 | balanced/speed（均衡/速度）模式 |
|---|---|---|---|
| 有 | (任意) | READY 放行 | READY 放行 |
| 缺 | 有 | WAITING_GRID 阻止 | WAITING_GRID 阻止 |
| 缺 | 无 | **WAITING_GRID 阻止**（带 `quality_mode=True`） | 放行（t2i 兜底） |

**语义：**
- **quality（效果模式）**：严格阻止——子场景缺图就不让生图，强制等待九宫格完成。保证首帧质量，不降级走 t2i。
- **balanced/speed（均衡/速度模式）**：宽松——仅在九宫格任务运行中时阻止等待；缺图+无任务则放行走 t2i 兜底，保证生图不卡住。

**mode 来源**：前端 `autoImageSequenceMode`（speed/balanced/quality）→ `auto-generate-missing-images` 的 `sequence_mode` → batch job → `_process_one_image_batch_job` 透传给 `generate_image(sequence_mode=...)`。单张生图入口不传 → 默认 None → balanced 语义（不阻止）。

查询函数：`GridImageTasksModel.has_running_grid_for_entity(entity_id, item_type=5)`
- 查 `grid_image_tasks` 中 `item_type=5`(location_grid)、`status ∈ (QUEUED, PROCESSING)`、`target_entity_ids_json` 含该 entity_id 的任务。
- 用 MySQL `JSON_CONTAINS(target_entity_ids_json, %s, '$')` 匹配。

## quality 模式重试上限降级（防死锁）

quality 模式下"缺图+无运行中任务"会持续阻止——如果九宫格从未提交成功（如 `/api/image-edit` 返 400），会死锁。

**解法**：`_process_one_image_batch_job` 的 WAITING_GRID 捕获块对 `quality_mode=True` 的阻止做计数：
- batch item 的 `extra_json` 记录 `quality_wait_count`，每次阻止 +1
- 超过 `StoryboardAutoGenerateConstants.QUALITY_WAIT_MAX_TICKS`（默认 30，约 5 分钟）后**降级放行**（落入正常生图流程，mode=auto 走 t2i）
- 降级在日志记 `[batch-loc] ... quality 等待达上限 → 降级放行(t2i)`

`balanced/speed` 模式的阻止（有运行中任务）不计次——九宫格完成后自然解除。

## 状态常量

`config/constant.py` 的 `LocationReferenceStatus`：
```python
READY = 'ready'
WAITING_GRID = 'waiting_location_grid_reference'
FALLBACK_PARENT = 'fallback_parent_location_reference'
MISSING = 'missing_location_reference'
```

## 批量调度（`_process_one_image_batch_job`）

PENDING 分支调 `generate_image(sequence_mode=job.get("sequence_mode"))` 前已注入 `_check_location_grid_readiness`。捕获逻辑：

```python
except StoryboardCliError as exc:
    if exc.error_code == LocationReferenceStatus.WAITING_GRID:
        is_quality_wait = exc.payload.get("quality_mode")
        if is_quality_wait:
            # quality 模式重试上限保护：计数超限则降级放行（走 t2i）
            wait_count = prev_extra.get("quality_wait_count", 0) + 1
            if wait_count > QUALITY_WAIT_MAX_TICKS:
                # 降级：不 continue，落入正常生图流程
                logger.warning("quality 等待达上限 → 降级放行(t2i)")
            else:
                update(item_id, extra_json={..., "quality_wait_count": wait_count})
                continue  # 保持 PENDING，下一 tick 重试
        else:
            # 有运行中任务的等待（所有模式）：保持 PENDING
            update(item_id, extra_json={"waiting": "location_grid_reference", ...})
            continue
    # 其他 error_code → FAILED（原逻辑）
```

**关键：waiting 不走 FAILED 写回**（否则不会自动恢复）。grid 完成回写 `location.reference_image` 后，下一 tick readiness check 通过，正常生图。

## 单张生图（`generate_image`）

mode 决策前已注入 `_check_location_grid_readiness`。单张入口不传 sequence_mode → 默认 None → balanced 语义（缺图不阻止，保持现有行为）。单张入口若需 quality 阻止，由前端传 sequence_mode（当前未传，后续可扩展）。

## 降级策略

九宫格任务 FAILED 后（不再运行），readiness check 不再阻塞：
- 父场景有图 → 塞进 reference_urls 走 image_edit（`fallback_parent_location_reference`）。
- 父子都无图 → mode=auto 走 t2i 兜底（`missing_location_reference`，保留原静默降级行为）。

## 前端

`web/js/storyboard/auto_missing_images.js`：
- `scenesMissingFirstFrame` 只看 `taskStatus.first_frame` 是否为 0/1。
- waiting 的 item 保持 PENDING，scene 的 first_frame task 未创建 → `taskStatus.first_frame` 为 null → 不被当作"需补图"。
- batch 调度器持续 tick，waiting item 在 grid 完成后自动解除。

**前端无需改动**——现有 per-scene 轮询天然支持。
