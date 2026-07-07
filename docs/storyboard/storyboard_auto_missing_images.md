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

## Billing Boundary

`auto-generate-missing-images` does not create a separate image-generation path. It selects scenes that need an image and then calls the existing `StoryboardAgentCliService.generate_image()` method for each submitted scene.

That means billing and permission behavior remain on the existing image-generation chain:

1. `generate_image()` calls `generate_text_to_image` or `edit_image`.
2. Those tools call the existing image endpoints with `auth_token`.
3. The image endpoints perform the current auth and computing-power deduction.

The batch command requires a non-empty `auth_token`. It skips scenes that already have a result URL, skips scenes whose selected task is already pending or processing, and caps one batch with `StoryboardAutoGenerateConstants.DEFAULT_BATCH_LIMIT` / `MAX_BATCH_LIMIT`.

## Sequence Modes

`auto-generate-missing-images` creates a storyboard image batch orchestration job and returns `batch_id` immediately. The job is advanced solely by the scheduler (`task/storyboard_image_batch_task.py` → `process_image_batch_jobs`), which runs every `StoryboardAutoGenerateConstants.BATCH_SCHEDULER_INTERVAL_SECONDS` (7s). The HTTP handler intentionally does **not** advance the job synchronously: doing so would race with the scheduler and could double-submit the same pending item (producing two `ai_tools` records with identical prompts for one scene). The orchestration job never writes generation tasks directly; it calls `generate_image()` only when an item is ready.

- `speed`: submit all missing images up to `limit` without referencing neighboring frames.
- `balanced` (default): scenes in different parsed groups can submit concurrently. Within the same group, each missing scene waits for the previous scene result and then submits as `image_edit` with the previous result URL as `source_image`.
- `quality`: submit as a single global chain. Each scene waits for the previous scene across group boundaries, so B1 can reference A3.

Inserted scenes that have no parsed group metadata inherit the previous scene's group. If the first scene has no group metadata, it uses a temporary manual group.

Existing completed scenes participate in dependencies. For example, if A1 already has a first frame and A2 is missing, A2 can reference A1 without regenerating A1. Existing running scenes also participate; dependent scenes wait until their selected asset has a result URL.

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

`web/js/storyboard/auto_missing_images.js` exposes `autoGenerateMissingFirstFrames()`.

`web/js/storyboard/bootstrap.js` calls it after the storyboard is loaded and rendered. `web/js/storyboard/events.js` also calls it after `generate-from-script-confirm` succeeds and `loadStoryboardData(response)` has written the newly split scenes into state. Both paths use the browser user's normal API wrapper, so the request carries the current `Authorization` header and is handled as a user/cgi call.

The split-script dialog exposes two choices:

- **Image model**: a `<select>` rendered by `renderImageModelConfig()`, sharing the same `state.selectedImageTaskId` as the right-side "model config" dialog (`data-action="open-model-config"`). Changes are persisted to storyboard `config_json` via `persistUiConfig()` and sent as `task_type` when auto-generating missing first frames, so the user can pre-pick the model that the post-split auto batch will use without leaving the dialog.
- **Sequence mode**: `speed`, `balanced`, or `quality`. The selected value is stored in `state.autoImageSequenceMode`, persisted in storyboard `config_json`, and sent as `sequence_mode` when auto-generating missing first frames.

If the browser session has not already submitted an auto batch for that storyboard, it calls:

```js
api.autoGenerateMissingImages(storyboardId, {
  asset_type: 'first_frame',
  mode: 'auto',
  ratio: state.workflowRatio,
  task_type: state.selectedImageTaskId,
  limit: missing.length,
  sequence_mode: state.autoImageSequenceMode,
});
```

Submitted or already-running scenes are passed to the existing polling function, so the UI uses the same task-status refresh path as manual generation.

### 去重标志位与重置

为避免页面刷新/重复加载时对同一个 storyboard 反复提交自动批量任务，`autoGenerateMissingFirstFrames()` 用 `sessionStorage` 的 `storyboard_auto_missing_images_{storyboardId}` 作为一次性去重标志：请求抛异常时会清除该标志以便重试。

由于该标志以 `storyboardId` 为 key，而「删除所有分镜后重新拆分」时 `storyboardId` 不变、分镜集合却被重建，若不清除旧标志会导致新一轮自动生成被静默跳过（`return`，不报错）。因此 `events.js` 在 `generate-from-script-confirm` 成功后、调用 `autoGenerateMissingFirstFrames()` 之前，会先调用 `resetAutoMissingImagesFlag(storyboardId)` 清除旧标志，保证重新拆分后总能重新触发一次自动生成。

## Auth Boundary

Storyboard-level HTTP routes parse the real user from `Authorization: Bearer <auth_token>` and overwrite any caller-provided `user_id`. The route bodies call the shared command service through `asyncio.to_thread()`, keeping synchronous database and service work off the FastAPI event loop.
