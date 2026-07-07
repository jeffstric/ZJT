# Storyboard 首帧生图对 Location 参考图的依赖控制

## 目标

分镜首帧生图前，检查当前 scene 引用的子场景 `location.reference_image` 是否就绪：
- 就绪 → 正常生图。
- 九宫格任务仍在运行 → **保持 PENDING，本 tick 等待**，不改状态。
- 九宫格失败/无图 → 走父图降级或纯文生图兜底。

## 设计：外部 readiness check（非 dependency_item_id）

**不复用 `storyboard_image_batch_item.dependency_item_id`**。该字段语义是同一 batch 内「上一分镜图」依赖，不能表达「外部 `grid_image_tasks` 还在跑」。

改为：在 `generate_image()` 内做 readiness 检查，批量调度器捕获特定 error_code 后 `continue` 保持 PENDING。

## 判定逻辑

`StoryboardAgentCliService._check_location_grid_readiness(context)`：

| location 状态 | 行为 |
|---|---|
| 有 `reference_image` | READY，直接返回（正常生图） |
| 无图 + 有运行中九宫格任务 | 抛 `StoryboardCliError(code=waiting_location_grid_reference)` |
| 无图 + 无运行中任务 | 不抛错，交由 mode=auto 走兜底 |

查询函数：`GridImageTasksModel.has_running_grid_for_entity(entity_id, item_type=5)`
- 查 `grid_image_tasks` 中 `item_type=5`(location_grid)、`status ∈ (QUEUED, PROCESSING)`、`target_entity_ids_json` 含该 entity_id 的任务。
- 用 MySQL `JSON_CONTAINS(target_entity_ids_json, %s, '$')` 匹配。

## 状态常量

`config/constant.py` 的 `LocationReferenceStatus`：
```python
READY = 'ready'
WAITING_GRID = 'waiting_location_grid_reference'
FALLBACK_PARENT = 'fallback_parent_location_reference'
MISSING = 'missing_location_reference'
```

## 批量调度（`_process_one_image_batch_job`）

PENDING 分支调 `generate_image()` 前已注入 `_check_location_grid_readiness`。捕获逻辑：

```python
except StoryboardCliError as exc:
    if exc.error_code == LocationReferenceStatus.WAITING_GRID:
        # 保持 PENDING，不改 status，仅写诊断 extra_json
        StoryboardImageBatchItemModel.update(item_id, extra_json={
            "waiting": "location_grid_reference",
            "location_db_id": exc.payload.get("location_db_id"),
        })
        continue  # 下一 tick 自动重试
    # 其他 error_code → FAILED（原逻辑）
```

**关键：waiting 不走 FAILED 写回**（否则不会自动恢复）。grid 完成回写 `location.reference_image` 后，下一 tick readiness check 通过，正常生图。

## 单张生图（`generate_image`）

mode 决策前已注入 `_check_location_grid_readiness`。单张入口直接抛 `StoryboardCliError(code=waiting_location_grid_reference)`，由前端 per-scene 轮询处理（单张不走 batch 重试）。

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
