# Storyboard Auto Missing Images

## Goal

When `web/storyboard.html` opens a storyboard, the page automatically submits generation jobs for scene nodes that do not have a first-frame image yet. The same batch capability is exposed to external agents through CLI and HTTP, so frontend and agents share one implementation path.

## Shared Commands

CLI batch generation:

```bash
python -m scripts.storyboard_agent_cli auto-generate-missing-images \
  --storyboard-id 10 \
  --user-id 1 \
  --auth-token short-lived-auth-token \
  --asset-type first_frame \
  --limit 5 \
  --sequence-mode balanced
```

HTTP batch generation:

```bash
curl -X POST http://localhost:9003/api/storyboard/10/auto-generate-missing-images \
  -H "Authorization: Bearer short-lived-auth-token" \
  -H "Content-Type: application/json" \
  -d '{"asset_type":"first_frame","mode":"auto","limit":5,"sequence_mode":"balanced","task_type":7}'
```

The response includes `batch_id`. Use it to poll orchestration progress:

```bash
python -m scripts.storyboard_agent_cli storyboard-image-batch-status \
  --batch-id 88 \
  --user-id 1
```

```bash
curl http://localhost:9003/api/storyboard/image-batches/88/status \
  -H "Authorization: Bearer short-lived-auth-token"
```

CLI storyboard status:

```bash
python -m scripts.storyboard_agent_cli storyboard-task-status \
  --storyboard-id 10 \
  --user-id 1 \
  --asset-type first_frame
```

HTTP storyboard status:

```bash
curl http://localhost:9003/api/storyboard/10/task-status?asset_type=first_frame \
  -H "Authorization: Bearer short-lived-auth-token"
```

## 前端闪烁防护（宫格整图 vs 单格首帧）

效果模式九宫格/四宫格生成时，`ai_tools.result_url` 先是整张宫格图（常在 `storyboard/temp/`），拆分后 `storyboard_scene_asset.result_url` 才是单格 `first_frame/`。

若轮询里用宫格 URL 覆盖已有单格 URL，时间轴缩略图会在「整图 / 单格」间来回闪。前端约定：

- `preferSceneMediaUrl` / batch apply：**禁止用宫格整图覆盖非宫格首帧 URL**
- `updateSceneThumb` / 主预览：媒体签名未变时跳过 `innerHTML` 重建，避免同 URL 重复解码闪烁

后端 `_asset_task_info` 仅在 asset 无 `result_url` 时才用 `ai_tools.result_url` 兜底。

## 涂色 / 手动选中首帧保护

自动补全 batch 轮询（`applyImageBatchStatus`）会带上 item 的 `asset_id` / `result_url`。  
若用户已通过**涂色上传**或**右侧候选点击**把 `selectedFirstFrameId` 切到其它资产，batch item 往往仍指向生成时的旧 asset。

前端约定（`shouldApplyBatchFirstFrameToScene`）：

- 场景**无选中** → 允许 batch 写入（补全缺失）
- 场景选中 **===** batch `asset_id` → 允许同步 URL（宫格拆分、任务完成回写）
- 场景选中 **!==** batch `asset_id` → **禁止**覆盖 `firstFrameUrl` / `selectedFirstFrameId`

否则会出现：涂色保存成功后，因页面仍在「补全中 x/y」轮询，隔几秒预览又跳回原图。

## Billing Boundary

`auto-generate-missing-images` creates one orchestration job. In `speed` and `balanced` it selects scenes that need an image and calls the existing `StoryboardAgentCliService.generate_image()` method for each submitted scene. In `quality + first_frame` it submits same-act storyboard first-frame grids through `StoryboardFirstFrameGridService`, then `task/grid_image_task.py` cuts the grid and writes each cell back as `storyboard_scene_asset(first_frame)`.

That means billing and permission behavior remain on the existing image-generation chain:

1. `generate_image()` calls `generate_text_to_image` or `edit_image`; quality first-frame grid calls `submit_grid_image_task(item_type=8, mode="image_edit")`.
2. Those tools call the existing image endpoints with `auth_token`.
3. The image endpoints perform the current auth and computing-power deduction.

The batch command requires a non-empty `auth_token`. It skips scenes that already have a result URL and skips scenes whose selected task is already pending or processing.

`limit` semantics: **omitting `limit` (or passing `limit=0`) means "no cap"** — all missing scenes are planned in one batch. The scheduler still paces submission per tick (`QUALITY_GRID_BATCHES_PER_TICK`, etc.), so an uncapped batch does not flood the generation chain. Passing a positive `limit` caps the number of *planned* (pending) scenes for this batch; excess missing scenes are marked `limit_reached`/`skipped` within this batch and must be picked up by a later request. A positive `limit` is clamped to `[1, StoryboardAutoGenerateConstants.MAX_BATCH_LIMIT]`.

## Idempotency and Duplicate Click Protection

`auto-generate-missing-images` is idempotent while a matching orchestration job is still active. The backend stores an `idempotency_key` in `storyboard_image_batch_job.extra_json`, derived from the storyboard, user, asset type, sequence mode, image mode, selected image task, ratio, image size, count, limit, prompt, source image, and `stop_on_error`.

- If the same request is repeated while the previous batch is `pending` or `running`, the service returns the existing batch status with `idempotent_reuse=true` and does not create another job or another set of items.
- If the same storyboard and asset type already has an active batch with different generation parameters, the service raises `active_batch_exists`. The HTTP endpoint maps it to `409`, including the active batch id and mode in the response payload.
- Once a batch reaches a terminal state (`completed`, `failed`, or `partial`), a new request may be created. Scenes that already have a selected result URL are still skipped by planning, so failed or still-missing scenes can be retried without regenerating completed frames.

## Sequence Modes

`auto-generate-missing-images` creates a storyboard image batch orchestration job and returns `batch_id` immediately. The job is advanced solely by the scheduler (`task/storyboard_image_batch_task.py` → `process_image_batch_jobs`), which runs every `StoryboardAutoGenerateConstants.BATCH_SCHEDULER_INTERVAL_SECONDS` (7s). The HTTP handler intentionally does **not** advance the job synchronously: doing so would race with the scheduler and could double-submit the same pending item (producing two `ai_tools` records with identical prompts for one scene). The orchestration job never writes generation tasks directly; it calls `generate_image()` only when an item is ready.

Because the handler returns before the scheduler submits anything, the response's `submitted_count` is **not** "tasks already pushed this tick". It is the fixed **planned count** for this round (`pending` + `already_running` items), written once at plan time and never mutated by later ticks. Poll the status endpoint to follow actual progress through the `pending` → `running` → `completed`/`failed` transitions (see "Status Response Fields" below). Do **not** interpret `submitted_count` as a live submission counter.

- `speed`: submit all missing images (up to `limit`; omitted/`0` = no cap) without referencing neighboring frames.
- `balanced` (default): scenes in different parsed groups can submit concurrently. Within the same group, each missing scene waits for the previous scene result and then submits as `image_edit` with the previous result URL as `source_image`.
- `quality + first_frame`: pending scenes in the same parsed `shot_group` (`storyboard_image_batch_item.group_key` / `prompt_json.source.group_id`) are submitted as 2x2 or 3x3 storyboard first-frame grids; `act_name` is only a display/fallback grouping value. Scenes whose location reference image is missing remain pending with `waiting=location_grid_reference`; ready scenes in the same parsed group can still proceed. The old global previous-frame chain is used only when `StoryboardFeatureFlags.QUALITY_GRID_FIRST_FRAME_ENABLED` is disabled.

`quality` is an enterprise-only sequence mode. The storyboard UI keeps the "效果" option visible in community builds, but clicking it shows "效果模式仅商业版支持，请购买商业版后使用" and does not persist the mode. CLI/HTTP calls are guarded by the shared service as well: community edition requests with `sequence_mode=quality` fail with `enterprise_only` (`403` on HTTP). Enterprise edition keeps the behavior described below.

Quality grid details:

- 企业版效果模式由 `enterprise.services.storyboard_quality_sequence` 决定幕级推进顺序。每个调度周期只允许最早未完成的一幕进入宫格生成；同一幕超过一个宫格时，也必须等待当前宫格完成并回写分镜首帧后才会提交下一宫格。
- 下一幕只能引用前一幕最后一个分镜的已拆分首帧，不能引用完整宫格图，也不能在参考图缺失时降级无参考生成。前一幕失败会将所有后续未开始幕标记为 `previous_group_failed`；前一幕已经结束但首帧长期未回写时，下一幕以 `previous_group_reference_timeout` 失败。
- 拆分发布阶段会调用企业版策略预提交场景参考图：新建且缺图的顶层场景先按最多 4 个一批提交 2x2 t2i 宫格；父图就绪后，再为其子场景提交 3x3 i2i 宫格。两条路径都携带 `location.id`，切图结果按数据库 ID 回写。场景图生成不会阻止分镜数据发布。
- `quality + first_frame` 在创建 `storyboard_image_batch_job` 前执行全批场景参考图预检。宫格运行中返回 HTTP 202 `waiting_location_references`，不创建 job/item，前端按 `retry_after_ms` 补偿轮询；顶层父场景缺图返回 HTTP 409 `quality_parent_reference_missing`，展示 `blockers` 和受影响分镜，同样不创建 batch。
- 每次 202 复检都会从数据库恢复状态：顶层 t2i 参考图回写后提交下一层子场景 i2i 宫格，直到所有目标分镜场景就绪才在全局创建锁内复检并创建首帧 batch。宫格失败返回 409 `location_reference_generation_failed`，禁止自动无限重提，也不回退到普通分镜 t2i。
- `active_batch_exists` 仍按原语义恢复已有批次；202/409 的场景预检响应不是批次状态，前端不得传给 `applyImageBatchStatus()`。
- **缺场景参考图的超时降级（balanced/speed 模式）**：`generate_image` 在 `_check_location_grid_readiness` 发现 scene 引用的 location 缺 `reference_image` 且有运行中九宫格任务时抛 `WAITING_GRID`。quality 模式严格失败（见上文）；**balanced/speed 模式保持 PENDING 等待，但累加 `extra_json.location_grid_wait_count`，超过 `BALANCED_LOCATION_REFERENCE_WAIT_MAX_TICKS`（默认 30，与 quality 对齐）后放弃等待，降级走 `text_to_image` 文生图**（`generate_image(mode="text_to_image", force_bypass=True)`），保证九宫格卡死时分镜仍能生成。降级后 `extra_json.degraded_from_location_reference=True` 供诊断，诊断日志 tag `[batch-loc] degraded to t2i after N ticks`。这是 balanced/speed 与 quality 的关键差异：前者宁可降级也不卡住，后者宁可失败也不降级。
- 1-4 ready scenes use a 2x2 grid; 5-9 use a 3x3 grid; a single ready scene still uses 2x2 with placeholders to keep the quality-mode grid path uniform.
- Grid size is decided after parsed-group partitioning. For example, if one displayed act contains multiple parsed groups of 3, 2, and 1 shots, each group is processed independently instead of being merged into one 3x3 grid.
- `limit` keeps its planning meaning: maximum real scenes planned for the batch (omitted/`0` = no cap; positive value clamped to `MAX_BATCH_LIMIT`). Per scheduler tick throughput is controlled separately by `StoryboardAutoGenerateConstants.QUALITY_GRID_BATCHES_PER_TICK`.
- The grid uses the storyboard/job ratio (`job.ratio` or `storyboard.workflow_ratio`), not a hard-coded `16:9`.
- Each real cell prompt is built with a two-layer prompt flow. In enterprise edition, `storyboard_scene.prompt_json.spatial_world` provides an episode-level registry of multiple local `space_units`; `storyboard_scene.prompt_json.spatial_layout` references the current shot's `space_unit_refs`, anchors, and `camera_pose`. The enterprise spatial engine (`enterprise.services.storyboard_spatial`) derives `derived_screen_position` from `camera_pose + position_3d`, so raw LLM `screen_position` is only a fallback. The community facade (`services.storyboard_spatial`) keeps legacy v1 `spatial_layout` payloads readable but does not enable quality-grid projection. The optional LLM prompt rewriter receives `spatial_layout`, `visible_entities`, `hidden_continuity_entities`, and the derived projection context, so it can reason about continuity without inventing new seat/slot positions. The final image-generation prompt stays clean: it describes only visible/partial entities in natural image language; `offscreen`/`occluded` continuity entities are not written as visible subjects, their names are removed from the final prompt if the source text leaks them, and they do not enter that cell's reference indices. The service stores each submitted cell's final prompt and spatial summary in `storyboard_image_batch_item.extra_json.grid_prompt_cell_context`; the group-level summary is stored in `grid_prompt_group_context` and is passed to the next act/group as `previous_grid_prompt_context` for continuity reference.
- Quality-grid reference images are resolved from visible/partial structured spatial entities first. A `slot` or `loose_position` with `character_id` / `character_db_id` and no explicit `occupant_type` is treated as a character, matching the shared spatial schema; an explicit non-character type is not. If structured references are incomplete, `【【角色名】】` and `〖〖道具名〗〗` markers in the shot prompt are resolved by `world_id + name` as a fallback. Explicitly `offscreen`/`occluded` characters remain excluded even when their names occur in source text. A fallback asset is appended only when its database record has a usable reference image, and the resulting character/prop/location URLs are stored in `grid_image_tasks.reference_images` and sent to `/api/image-edit` through `ref_image_urls`.
- `submit_grid_image_task(item_type=8)` creates an `ai_tool_pipeline_steps` record with `step_type=storyboard_first_frame_grid_split`. The step params store `grid_task_id`, grid layout, and per-cell bindings (`grid_index`, `scene_id`, `batch_item_id`, `placeholder`).
- At an act/group boundary, quality first-frame grids wait for the previous group’s last storyboard frame before submitting the next group. The reference is the split first-frame asset/result URL for that previous storyboard scene, not the full grid image. If that previous frame is still pending/running, the next group remains pending with `waiting=previous_group_first_frame`; once ready, the previous frame is added to the next grid’s `reference_images` and every real cell prompt mentions it as the previous storyboard frame for continuity.
- `waiting=previous_group_first_frame` has its own cap: `StoryboardAutoGenerateConstants.QUALITY_PREVIOUS_REFERENCE_WAIT_MAX_TICKS` (default 30 scheduler ticks). If the previous group reference never becomes available, pending items in the waiting group fail with `previous_group_reference_timeout`, so the batch job can settle as `failed` or `partial` instead of staying active forever.
- After the grid `ai_tools` task succeeds, `task/grid_image_task.py` records the downloaded grid image on `ai_tools.result_url` and dispatches the pipeline step. The global pipeline scheduler and before-finish stage-completion path intentionally skip `storyboard_first_frame_grid_split`; otherwise a failed upstream image submission can enter implementation retry and accidentally execute split before the grid image exists. The pipeline driver splits the grid, skips placeholder cells, creates `storyboard_scene_asset(asset_type="first_frame")`, sets it selected, and updates the owning `storyboard_image_batch_item`. It uses `batch_item_id` first and falls back to `grid_task_id + scene_id` for older records.
- If a grid task times out before the bound `ai_tools` record writes its `result_url`, `task/grid_image_task.py` also scans terminal grid rows whose `ai_tools` result arrived late and sends them through the same download, validation, split, and scene-asset writeback path. This keeps slow synchronous providers from leaving storyboard scenes permanently blank after a local grid polling timeout.
- Before dispatching the split step, the downloaded grid is checked by `utils.image_grid_validator.validate_grid_image()`. If the geometry is not a valid 2x2/3x3 grid, the grid generation is retried up to 2 times. Only after those retries fail are the related batch items marked failed, allowing the whole storyboard image batch job to finish instead of binding bad cell crops.
- At the start of every scheduler tick, `StoryboardAgentCliService._process_one_image_batch_job()` reconciles running batch items before checking dependencies. It completes items whose bound `storyboard_scene_asset` now has a result URL, fails items whose bound asset failed, and for quality first-frame grids checks `extra_json.grid_task_id`: terminal grid failures (`FAILED`, `TIMEOUT`, `CANCELLED`, `DOWNLOAD_FAILED`) or completed grids without successful split/writeback mark the owning batch item failed with `grid_first_frame_failed`. As a last-resort stale guard, any item that remains `running` for more than `StoryboardAutoGenerateConstants.BATCH_RUNNING_ITEM_TIMEOUT_SECONDS` is marked failed with `batch_item_running_timeout`, so dependent items cannot wait forever.
- If the user deletes all scenes or re-splits the script while a quality first-frame grid batch is still active, pending batch items may point to `storyboard_scene` rows that no longer exist. `StoryboardFirstFrameGridService` now marks those items failed with `scene_deleted` instead of silently filtering them out. This lets the old batch reach a terminal state and prevents it from blocking the next `speed` / `balanced` / `quality` auto-generation request with `active_batch_exists`.

Inserted scenes that have no parsed group metadata inherit the previous scene's group. If the first scene has no group metadata, it uses a temporary manual group.

Existing completed scenes participate in dependencies. For example, if A1 already has a first frame and A2 is missing, A2 can reference A1 without regenerating A1. Existing running scenes also participate; dependent scenes wait until their selected asset has a result URL.

### Status Response Fields

`GET /api/storyboard/image-batches/{batch_id}/status` returns aggregated progress fields computed live from `items[]`, so callers do not need to recount items themselves:

| Field | Meaning |
|-------|---------|
| `total` | Total batch item count. |
| `pending` | Items still waiting to be submitted (planned, not yet pushed to the generation chain). |
| `running` | Items currently being generated. |
| `completed` | Items with a successful result. |
| `failed` | Items that errored out. |
| `skipped` | Items skipped this round (`already_ready`, `already_running`, `limit_reached`, `missing_first_frame`, `missing_audio`, …). |
| `progress` | `completed / total` rounded to 4 decimals (`0` when `total == 0`). |
| `submitted_count` | **Planned count** for this round (`pending` + `running` at plan time). Fixed once written; does not change across scheduler ticks. Use `pending`/`running`/`completed` to follow live progress. |
| `completed_count` / `failed_count` / `skipped_count` | Legacy snake_case mirrors of `completed` / `failed` / `skipped` (kept for backward compatibility). |
| `status` | Job-level status name: `pending` / `running` / `completed` / `failed` / `partial`. |
| `items[]` | Per-scene detail (`status`, `plan_status`, `project_ids`, `result_url`, `error_code`, …). |

Polling rule of thumb: keep polling until `status` is terminal (`completed` / `failed` / `partial`) **and** there are no `pending`/`running` items.

### 诊断日志（排查链式参考未生效）

批量调度链路（`services/storyboard_agent_cli_service.py`）输出结构化诊断日志，可在 `logs/app.*.log` 中检索以下 tag 排查"前一分镜未作为参考图"类问题：

| Tag | 位置 | 作用 |
|-----|------|------|
| `[batch-plan]` | `_plan_image_batch_items` 末尾 | 规划出的依赖图：每个分镜的 group/status/dep_scene/result_url，确认同组串联链是否建对 |
| `[batch-create]` | `auto_generate_missing_images` 建 item 时 | 每个 item 的 dependency_item_id 是否成功解析 |
| `[batch-tick]` | `_process_one_image_batch_job` 每轮开始 | 本轮各 item 状态快照（pending/running/completed/failed + 依赖项） |
| `[batch-dep]` | 依赖检查处 | **核心**：pending item 的依赖项状态与 result_url 取值——`reference_url=None (依赖完成但无结果URL！)` 的 WARNING 即为链式参考丢失的直接证据 |
| `[batch-submit]` | 提交后 | 实际提交的 mode 与 source_image——`source_image=None (⚠️未使用前一分镜)` 的 WARNING 表示该分镜未带前帧参考 |

排查步骤：复现问题后 `grep "batch-dep\|batch-submit" logs/app.*.log`，定位目标分镜 item 编号，查看其依赖项在提交时刻的状态与 result_url 是否为空。

## Frontend Behavior

`web/js/storyboard/auto_missing_images.js` exposes two entry points:

- `autoGenerateMissingFirstFrames()`: used on first page load and after script splitting. It first attempts to recover a stored active batch, then falls back to the existing first-open auto-submit behavior.
- `autoCompleteMissingFirstFrames()`: used by the visible title-bar button. It submits only scenes that still do not have a first frame and are not already pending/running in the current batch.

`web/js/storyboard/bootstrap.js` calls it after the storyboard is loaded and rendered. `web/js/storyboard/events.js` also calls it after `generate-from-script-confirm` succeeds and `loadStoryboardData(response)` has written the newly split scenes into state. Both paths use the browser user's normal API wrapper, so the request carries the current `Authorization` header and is handled as a user/cgi call.

Both timeline and grid views render the same `renderAutoCompleteHeader()` control in their title area:

- Timeline: `分镜序列 · {total} 个分镜 · {missing} 个待生成 [自动补全未生成分镜]`
- Grid: `故事板总览 · {total} 个分镜 · {missing} 个待生成 [自动补全未生成分镜] [时间轴]`

The button is driven by `state.autoImageBatch`, not by ad-hoc DOM state:

- no active batch and missing first frames: `自动补全未生成分镜`;
- `submitting=true`: `正在提交补全任务`;
- active `pending/running` batch: `补全中 {completed}/{target}`;
- no missing frames: `分镜已全部生成`.

Running buttons use `aria-disabled="true"` and `data-batch-locked="true"` instead of native `disabled`, so a duplicate click can show a clear message without submitting a second request. The target count excludes `already_ready` and `limit_reached` batch items; progress is computed only from real current-round targets (`plan_status in {pending, already_running}`).

Thumbnail status is derived through `getFirstFrameDisplayStatus(scene)`:

- `ready`: existing `scene.firstFrameUrl`;
- `running` / `pending`: current batch item or scene task status is active;
- `failed`: current batch item failed and the scene still has no image;
- `missing`: no image and no active generation.

This selector is shared by timeline thumbnails, grid cards, title counters, and the auto-complete button, so partial/failed batches return the remaining blank scenes to a clickable completion state.

The split-script dialog exposes two choices:

- **Image model**: a `<select>` rendered by `renderImageModelConfig()`, sharing the same `state.selectedImageTaskId` as the right-side "model config" dialog (`data-action="open-model-config"`). Changes are persisted to storyboard `config_json` via `persistUiConfig()` and sent as `task_type` when auto-generating missing first frames, so the user can pre-pick the model that the post-split auto batch will use without leaving the dialog.
- **Sequence mode**: `speed`, `balanced`, or `quality`. The selected value is stored in `state.autoImageSequenceMode`, persisted in storyboard `config_json`, and sent as `sequence_mode` when auto-generating missing first frames.

In community edition, clicking `quality` in the empty-storyboard split dialog shows a blocking alert: "效果模式仅商业版支持，请购买商业版后使用". The selection remains on the previous allowed mode and is not persisted.

When submitting an automatic or manual completion batch, the frontend calls:

```js
api.autoGenerateMissingImages(storyboardId, {
  asset_type: 'first_frame',
  mode: 'auto',
  ratio: state.workflowRatio,
  task_type: state.selectedImageTaskId,
  sequence_mode: state.autoImageSequenceMode,
});
```

The frontend intentionally does **not** send `limit`. The backend treats an omitted `limit` as "no cap" and plans all missing scenes in one batch (`UNLIMITED_BATCH_LIMIT`); per-tick throughput is still paced by the scheduler, so an uncapped batch does not overload the system. Passing a concrete `limit` (the old behavior `limit: missing.length`) was removed because it interacts badly with `MAX_BATCH_LIMIT=20`: when an episode has ≥ 20 missing scenes, the value gets clamped to 20 and any scene beyond the 20th is permanently marked `limit_reached`/`skipped` with no retry. `missing.length` is also computed from the partially-loaded frontend state, so it could undercount scenes that have not rendered yet. The video batch (`autoGenerateMissingVideos`) follows the same rule.

Submitted or already-running scenes are passed to the existing polling function, so the UI uses the same task-status refresh path as manual generation. `pollImageBatchStatus(batchId, callbacks)` also applies batch item updates directly to `state.autoImageBatch`, writes `result_url` / `asset_id` back to the matching scene, and locally refreshes the title header and affected thumbnails.

### 批次恢复、去重标志位与重置

为避免页面刷新/重复加载时对同一个 storyboard 反复提交自动批量任务，`autoGenerateMissingFirstFrames()` 使用 `sessionStorage` 的 `storyboard_auto_missing_images_{storyboardId}` 保存可恢复批次，而不是旧版布尔标志。值为 JSON：

```json
{
  "version": 2,
  "storyboardId": 16,
  "batchId": 38,
  "targetSceneIds": [544, 545, 546],
  "updatedAt": "2026-07-11T10:00:00.000Z"
}
```

恢复时前端只信任 `batchId`，会重新请求 `GET /api/storyboard/image-batches/{batch_id}/status`：

- if the batch is still `pending/running`, the UI restores `state.autoImageBatch`, locks the button, and continues polling;
- if the batch is terminal, the cache is cleared and remaining blank scenes become manually completable;
- if the cached value is legacy `'1'`, invalid JSON, or belongs to a different storyboard, it is deleted and the current missing-frame check runs normally;
- if a submit receives HTTP `409 active_batch_exists`, the frontend reads `active_batch_id` (or `payload.active_batch_id` if a nested payload is returned), takes over that batch, and polls it instead of creating a duplicate job.

由于该缓存以 `storyboardId` 为 key，而「删除所有分镜后重新拆分」时 `storyboardId` 不变、分镜集合却被重建，因此 `events.js` 在 `generate-from-script-confirm` 成功后、调用 `autoGenerateMissingFirstFrames()` 之前，会先调用 `resetAutoMissingImagesFlag(storyboardId)` 清除缓存并重置内存中的 `autoImageBatch`，保证重新拆分后总能重新触发一次自动生成。

## Auth Boundary

Storyboard-level HTTP routes parse the real user from `Authorization: Bearer <auth_token>` and overwrite any caller-provided `user_id`. The route bodies call the shared command service through `asyncio.to_thread()`, keeping synchronous database and service work off the FastAPI event loop.

## 首帧图 CDN 分发（带宽优化）

宫格拆分生成的首帧单图默认只存本地 `upload/storyboard/first_frame/`，前端访问时由本机静态文件直接回源，业务机承担全部图片带宽。在云端部署（`server.is_local=false`）下可通过七牛云图床分发降低业务机带宽。

### 触发条件

同时满足以下两项才会为新生成的首帧单图建立 CDN 映射：

1. `server.auto_upload_to_cdn = true`（CDN 总开关，`config_prod.yml` / `system_config` 表）
2. `file_storage.qiniu_long_term` 的 `access_key` / `secret_key` / `bucket_name` / `cdn_domain` 配置完整

任一不满足时，不建映射、走本地静态文件，行为与未启用 CDN 完全一致。

### 工作机制

接入点位于宫格拆图 pipeline driver（`task/pipeline_drivers/storyboard_grid_split_driver.py`），每成功创建一张首帧单图资产后调用 `_ensure_asset_media_mapping(...)`：

1. 在 `media_file_mapping` 表建记录：
   - `entity_type = MediaFileEntity.STORYBOARD_SCENE_ASSET`(=6)
   - `source_id = storyboard_scene_asset.id`
   - `local_path = upload/storyboard/first_frame/xxx.png`（相对路径，无前导 `/`）
   - `policy_code = MEDIA_CACHE`，`label = first_frame`
2. 调 `CDNUtil.trigger_cdn_upload(mapping_id, local_path)` **异步**上传到七牛云 `qiniu_long_term` 桶（非阻塞，线程池执行）。
3. 回写 `storyboard_scene_asset.media_mapping_id`（新字段，见迁移 `no_115_20260713_asset_media_mapping_id`）。

之后前端访问 `/upload/storyboard/first_frame/xxx.png` 时，`cdn_redirect_middleware`（`server.py`）按 `local_path_hash` 查到该映射，**302 重定向**到七牛云签名 URL（28 小时有效），浏览器直接从 CDN 拉取，业务机不再承担该图片的下行带宽。

### 关键设计点

- **前端无需改动**：中间件 302 对前端完全透明，`<img src="/upload/...">` 浏览器自动跟随重定向。这与 `video_workflow.html` 用 `/api/proxy-image` 代理是两种不同架构，storyboard 走中间件方案，不需要在前端拼接 CDN 域名。
- **宫格整图不上 CDN**：`upload/storyboard/temp/` 下的宫格整图是中间产物，拆分后用户看不到，保持本地存储。
- **幂等**：按 `local_path_hash` 查已有 active mapping，命中则复用、不重建、不重传。
- **非阻塞**：CDN 建映射 / 上传失败只记 `warning` 日志，绝不影响 asset 创建、选中、batch 回写的主流程。
- **仅增量生效**：本次改动只作用于新生成的首帧图；已生成的历史首帧图未建立 CDN 映射，仍走本地静态文件。

### 相关参考

- `docs/backend/download_queue_decouple.md` —— 视觉/视频任务的标准 CDN 上传链路（`update_with_cdn_sync`）
- `docs/backend/image_url_expiry_refresh.md` —— CDN 签名 URL 过期恢复与降级原则
