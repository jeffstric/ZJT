---
name: storyboard-agent-api
description: Use when Codex needs to operate this project's storyboard automation API or CLI as an agent: exchange an agent token for auth_token, discover worlds/scripts/characters/locations/props, create or split storyboard scenes, batch-generate missing storyboard images, generate scene images/videos, query generation status, or bind generated ai_tools projects back to storyboard assets.
allowed-tools: Read, Terminal
---

# Storyboard Agent API

Use this skill to operate the storyboard automation surface from another agent.

## Rules

- Prefer HTTP APIs when the server is running; use CLI only when working inside the project workspace or when HTTP is unavailable.
- Never pass tokens in URLs. Put short-lived auth in `Authorization: Bearer <auth_token>`.
- Never trust or invent `user_id` for HTTP calls. HTTP routes resolve the real user from `Authorization` and overwrite body `user_id`.
- Do not bypass the command API by editing database rows or calling low-level services for generation. Generation must go through the shared command/service path so billing and task binding remain intact.
- For batch image generation, call `auto-generate-missing-images`; it submits each missing scene through the existing `generate_image()` path, so computing power is deducted by the existing image endpoints.
- Treat task statuses `0` and `1` as running. Status `2` means completed; negative values mean failed/cancelled/timeout.

## Connection Package

At the start, the agent does not know the server URL or token. Ask the user to open the ZhiJuTong home page, click the agent icon next to the username, and paste the copied connection package.

The package should include:

```json
{
  "base_url": "https://example.com",
  "agent_token": "zjt_agent_xxx",
  "api_version": "storyboard-agent-api/v1",
  "app_version": "1.0.0",
  "environment": "dev"
}
```

Do not guess protocol, host, or port. Use the `base_url` exactly as provided by the user.

## API Version

This skill supports `api_version = "storyboard-agent-api/v1"`.

Before making calls:

1. Parse `base_url`, `agent_token`, `api_version`, and `environment` from the user's connection package.
2. If `api_version` is missing or different from `storyboard-agent-api/v1`, tell the user this skill may not match the server API and ask for an updated skill or compatible connection package before running generation.
3. For v1, use the fixed endpoint paths below relative to `base_url`; the connection package does not need to provide full endpoint URLs.
4. Treat `environment` as the backend configuration environment. HTTP calls do not need extra environment setup; CLI fallback must set `comfyui_env` to this value before running commands.

Fixed v1 endpoint paths:

- `POST /api/agent-auth/exchange`
- `GET /api/storyboard/agent/schema`
- `POST /api/storyboard/agent/commands/{command}`
- `POST /api/storyboard/{storyboard_id}/auto-generate-missing-images`
- `GET /api/storyboard/image-batches/{batch_id}/status`
- `GET /api/storyboard/{storyboard_id}/task-status?asset_type=first_frame`
- `GET /api/script-split/tasks/{task_id}` — poll split task status
- `GET /api/script-split/tasks/{task_id}/result` — fetch final result (409 unless completed)
- `POST /api/script-split/tasks/{task_id}/resume` — resume a paused / waiting_auth task
- `POST /api/script-split/tasks/{task_id}/cancel` — cooperatively cancel a running task

All `status_url` / endpoint paths above are **relative** to `base_url`; prepend `base_url` when calling.

## Auth

If the user gives a connection package or agent token, exchange it first:

```bash
curl -s -X POST "$BASE_URL/api/agent-auth/exchange" \
  -H "Content-Type: application/json" \
  -d '{"token":"<agent_token>","device_uuid":"storyboard-agent"}'
```

Use the returned `auth_token` for all later calls:

```bash
AUTH="Authorization: Bearer <auth_token>"
```

If the user already gives a short-lived `auth_token`, skip exchange and use it directly.

## Discover Commands

```bash
curl -s "$BASE_URL/api/storyboard/agent/schema" -H "$AUTH"
```

The shared command endpoint is:

```text
POST /api/storyboard/agent/commands/{command}
```

## Discover Available LLM Models

`split-from-script` **requires** an explicit `model` parameter (the CLI `--model` flag is also required). Before calling split, query the available LLM models and pick one — the response gives you the exact `name` / `model_id` / `vendor_id` triple to pass through, plus pricing for comparison:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/list-llm-models" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{}'
```

Each item in `models[]` looks like:

```json
{
  "model_id": 11,
  "name": "deepseek-v4-flash",
  "vendor_id": 4,
  "vendor_name": "volcengine",
  "context_window": 128000,
  "supports_thinking": true,
  "supports_vl": false,
  "pricing": {
    "input_threshold": 40000,
    "output_threshold": null,
    "cache_read_threshold": null,
    "input_price_per_million": 1.0,
    "output_price_per_million": null,
    "cache_read_price_per_million": null
  }
}
```

Notes:
- Only vendors with a configured API key and `enabled=1` models are returned, so the list is already filtered down to models the server can actually route to. If a gateway is network-unreachable the split task will still pause with `plan_call_failed` — prefer vendors known to be reachable in the current environment (e.g. `volcengine`, `aliyun`, `zjt_api`, `ollama`).
- Use the **name** as `model`, and optionally pass `model_id` + `vendor_id` to pin the exact route (recommended when the same model name is served by multiple vendors).
- CLI equivalent: `python -m scripts.storyboard_agent_cli list-llm-models --user-id 1`.

## Discover Worlds And Scripts

Before asking the user for IDs, discover available project context:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/list-worlds" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"page":1,"page_size":20}'
```

World responses show only a `story_outline` preview by default: first 50 characters plus last 50 characters, with `story_outline_preview` and `story_outline_truncated`. To read the full story outline, pass `include_full_story_outline:true`.

After the user chooses a world, read scripts and reusable assets:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/world-context" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"world_id":1,"page_size":100}'
```

`world-context` 的 `scripts`、`characters`、`locations`、`props` 都是分页对象，
不是数组。真实列表统一位于 `.data`：

```json
{
  "scripts": {"total": 2, "page": 1, "page_size": 100, "data": []},
  "characters": {"total": 4, "page": 1, "page_size": 100, "data": []},
  "locations": {"total": 3, "page": 1, "page_size": 100, "data": []},
  "props": {"total": 5, "page": 1, "page_size": 100, "data": []}
}
```

Use `get-script` only when full script content is needed:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/get-script" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"script_id":20}'
```

Granular read-only commands are also available: `list-world-scripts`, `list-world-characters`, `list-world-locations`, and `list-world-props`. Script lists omit `content` by default and include `content_length`; pass `include_content:true` only when the response needs full script text. Any command that includes a `world` object accepts `include_full_story_outline:true`.

## Common HTTP Workflows

Create or reuse a storyboard from a script:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/create-storyboard-from-script" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"script_id":20,"title":"optional"}'
```

创建命令可选传 `model`、`model_id`、`vendor_id`。未传时，新故事板继承当前用户
在该世界最近保存的拆分模型偏好；没有偏好时使用服务端默认模型。解析结果写入
`storyboard.config_json.selectedScriptSplitLlmModel`，后续 `split-from-script` 无需重复传模型。

**⚠️ 画风与构图不可通过本命令修改**：`style` / `style_reference_image` / `composition_preference`
/ `workflow_ratio` 四个参数已从命令层移除（即使传入也会被忽略）。这四项属于**世界级一致性资产**，
由世界表的 `visual_style` / `composition_preference` 自动继承到同世界的所有故事板，保证多集画风
一致。若需调整画风/构图/画幅，请让用户在世界设置页修改，不要按分镜方案（如 A/B/C 版本）差异化
覆盖——否则同世界不同集会出现画风不一致。

Split linked script into storyboard scenes:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/split-from-script" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"storyboard_id":10,"model":"deepseek-v4-flash","model_id":11,"vendor_id":4,"max_group_duration":15}'
```

`model` is **required** on the CLI/agent path (the server no longer falls back to a default model here). Call `list-llm-models` first to pick a reachable model, and pass `model_id` + `vendor_id` to pin the exact route when the same name is served by multiple vendors.

This is an **asynchronous** command. It creates a persistent split task and returns immediately with `task_id` and `status_url` (it does **not** block for the ~7-minute LLM parse).

### Poll split tasks

`status_url` is a **relative** path like `/api/script-split/tasks/215`; prepend `base_url` when polling. Note the two response envelopes differ: the `split-from-script` command returns `{success, task_id, status_url}` (agent-command envelope), while `GET /api/script-split/tasks/{id}` returns `{code:0, data:{...}}` (split-task envelope) — read `data` for the status object.

The status object fields (in `data`):

| field | meaning |
|-------|---------|
| `status` | task state machine value (see below) |
| `phase` | sub-stage within a status (e.g. `planning`, `segment_generation`, `publishing`) |
| `progress` | 0-100, monotonically increasing |
| `message` | human-readable Chinese phase text (also surfaces to UI; not for programmatic decisions) |
| `poll_after_ms` | suggested poll interval (default 3000) |
| `error_code` | the `last_error_code` that caused paused/failed; `null` when none |
| `error_message` | the detailed error text (e.g. `403 Client Error: Forbidden for url: ...`); `null` when none |
| `resumable` | boolean — `true` only for `paused` / `waiting_auth` |
| `resume_hint` | actionable hint keyed off `error_code` (e.g. `llm_gateway_error: ...`, `auth_expired: ...`); `null` when not resumable |

**Task state machine — three groups:**

1. **Terminal (stop polling):** `completed` / `failed` / `cancelled`. After `completed`, fetch results via `GET /tasks/{id}/result` or call `list-scenes`.
2. **Resumable (stop polling, act first):** `paused` / `waiting_auth`. `resumable=true`. Read `error_code` + `resume_hint` to decide whether to `resume`, ask the user to fix the root cause, or `cancel`.
3. **In-progress (keep polling):** `queued` / `planning` / `generating` / `merging` / `validating` / `publishing` / `cancelling`.

**Critical:** do NOT loop forever on `paused`/`waiting_auth` — they are not terminal but they will not self-resolve. When you see `resumable=true`, stop polling and act on the error.

Polling pseudocode:

```
loop:
    resp = GET $BASE_URL/api/script-split/tasks/<task_id>      # {code:0, data:{...}}
    st = resp.data
    if st.resumable:                                            # paused / waiting_auth
        decide_action(st.error_code, st.resume_hint)            # resume / ask user / cancel
        break
    if st.status in (completed, failed, cancelled):
        break
    sleep(st.poll_after_ms)
```

### Resume a paused / waiting_auth task

`POST /api/script-split/tasks/{task_id}/resume`. The server gates resume by `error_code`:

- **Blocked error codes** (`plan_call_failed`, `plan_timeout`, `step_watchdog_timeout`, `new_root_location_forbidden`, `location_parent_invalid`): the root cause is an external dependency (LLM gateway / worker) or a hard gate (missing scene assets). A blind retry would loop back to `paused`, so the server **rejects** resume with HTTP 409 + `{error_code, resume_hint}`. After you confirm the root cause is fixed (e.g. LLM key restored, scene assets added), retry with `{"force": true}` in the body. (`location_parent_conflict` is no longer blocked: since 2026-07-30 a parent mismatch on an explicit-id or exact-name DB match is auto-aligned to the database hierarchy with a warning instead of pausing the task; fuzzy name matches with a different parent stay unbound as new scenes.)
- **`waiting_auth`**: resume requires a fresh `auth_token`. First `POST /api/agent-auth/exchange` to get a new token, then call resume with the `Authorization: Bearer <new_token>` header. Without a token, resume returns 409.
- **Other codes** (`plan_failed`, `segment_qc_failed`, `segment_max_retries`, `segment_repeatedly_interrupted`, ...): content-validation failures — resume is allowed directly (no `force` needed).

When resume returns 409, **do not retry it in a tight loop** — read `error_code`/`resume_hint`, surface the cause to the user, and only resume again once the cause is addressed.

### Cancel a task

`POST /api/script-split/tasks/{task_id}/cancel`. Cooperative cancel: sets `cancel_requested`, transitions to `cancelling`, and the worker finalizes to `cancelled` at the next checkpoint (the in-flight LLM call is not hard-killed). Use this to abandon a stuck task before re-splitting.

### Reusing a storyboard with a stuck split task

If `create-storyboard-from-script` returns an existing storyboard (`created:false`) whose split task is stuck in `paused`, do not hammer resume blindly. Either (a) `cancel` the stuck task then call `split-from-script` again (the active_key is released on terminal status, allowing a new task), or (b) inspect `error_code` first and resume with `force:true` only after the root cause is fixed.

### error_code quick reference

| error_code | group | Agent action |
|------------|-------|--------------|
| `plan_call_failed` | external | LLM gateway error (403/5xx). Ask user to check API key/quota/network, then `resume` with `force:true`. |
| `plan_timeout` | external | LLM call timed out. Check model availability, then `resume` with `force:true`. |
| `step_watchdog_timeout` | external | Worker step exceeded wall-clock budget. Check worker/LLM responsiveness, then `resume` with `force:true`. |
| `waiting_auth` | auth | Token expired. `POST /api/agent-auth/exchange`, then `resume` with new `Authorization`. |
| `new_root_location_forbidden` / `location_parent_*` | hard gate | Script references a top-level scene not modeled in DB. Ask user to add the scene in the script-authoring page, then `resume` with `force:true`. |
| `plan_failed` | content | Plan validation failed (retryable). `resume` directly. |
| `segment_qc_failed` / `segment_max_retries` / `segment_repeatedly_interrupted` | content | Segment-level validation failures (retryable). `resume` directly. |
| `empty_script` / `invalid_*` | terminal | Already `failed`; will not appear in `paused`. Re-create the task after fixing the script. |

Once the task reaches `completed`, list scenes:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/list-scenes" \
  -H "$AUTH" -H "Content-Type: application/json" -d '{"storyboard_id":10}'
```

During the publishing phase the worker also **auto-submits dialogue voiceover tasks** for dialogues that have text and a valid character voice reference — the split task only reaches `completed` once all eligible dialogues have been queued for TTS (TTS itself runs asynchronously via the audio scheduler). You do **not** need to call a separate audio command after split; poll the per-scene `task-status` endpoint to follow TTS progress.

On the **CLI / agent command path** (`POST /api/storyboard/agent/commands/split-from-script` and `python -m scripts.storyboard_agent_cli split-from-script`), `model` is **required** — the server will reject the call with `missing_parameter` if it is absent. Always call `list-llm-models` first to pick a reachable model.

The internal worker (used by `POST /api/storyboard/{id}/generate-from-script` and resume) still reads `storyboard.config_json.selectedScriptSplitLlmModel` when no model is supplied; `create-storyboard-from-script` seeds that field. `selectedScriptSplitLlmModel` may be either a string (`"deepseek-v4-pro"`) or an object (`{"model":"deepseek-v4-pro","model_id":1008,"vendor_id":10}`); the server unpacks the object and routes to the exact vendor/model. The legacy `force_overwrite_subscene_grids` field is accepted for compatibility but no longer takes effect.

List scenes after splitting:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/list-scenes" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"storyboard_id":10}'
```

Insert a new scene after an existing scene:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/insert-scene" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"storyboard_id":10,"after_scene_id":123,"title":"Reaction shot","duration":4.5,"prompt_json":{"scene_desc":"A quiet reaction shot."},"video_prompt":"Hold on the character reaction."}'
```

Use `after_scene_id` for "insert after this scene". `before_scene_id`, `prev_id`, and `next_id` are also accepted for precise placement. If no placement is provided, the scene is appended to the storyboard.

Update editable fields of an existing scene (only provided fields are written; omitted fields are left untouched). When `duration` changes, the storyboard's `total_duration` is recomputed:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/update-scene" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"scene_id":123,"duration":8,"title":"Reaction shot"}'
```

Updatable fields: `duration` (decimal seconds, clamped to a minimum of 1), `title`, `prompt_json` (JSON object), `video_prompt`, `video_type`, `video_config_json` (JSON object), `difficulty` (易/中/难, normalized via `SceneDifficulty`), `act_name` (act/shot-group name). Selected asset pointers (`selected_first_frame_id`, etc.) are not patched here — use `bind-projects` or the asset select endpoints instead.

Batch-generate missing first-frame images:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/10/auto-generate-missing-images" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"asset_type":"first_frame","mode":"auto","sequence_mode":"balanced"}'
```

`limit` semantics: **omit `limit` (or pass `limit=0`) to plan ALL missing scenes in one batch** — this is the recommended way to "generate images for this episode". The scheduler still paces per-tick submission, so an uncapped batch will not overload the system. Passing a positive `limit` caps the number of *planned* scenes; excess scenes are marked `limit_reached`/`skipped` within this batch and need a later request. A positive `limit` is clamped to `[1, 20]` (`MAX_BATCH_LIMIT`).

When `task_type` is omitted, the server uses `storyboard.config_json.selectedImageTaskId`. Pass `task_type` only to intentionally override the storyboard image workflow/model choice.

`sequence_mode` controls previous-frame references:

- `balanced` is the default: groups can run concurrently, but scenes inside one group wait for and reference the previous scene image.
- `quality` runs one global chain and references the previous scene even across group boundaries.
- `speed` submits all missing images without previous-frame references.

The response includes `batch_id` and a fixed `submitted_count` (the **planned count** for this round, not a live submission counter). Poll the orchestration batch when the request returns a `batch_id`:

```bash
curl -s "$BASE_URL/api/storyboard/image-batches/<batch_id>/status" -H "$AUTH"
```

The status response carries aggregated fields computed from `items[]`, so you do not need to recount items yourself: `total`, `pending`, `running`, `completed`, `failed`, `skipped`, and `progress` (= `completed / total`). `submitted_count` mirrors the fixed planned count. Keep polling until `status` is terminal (`completed` / `failed` / `partial`) and `pending` + `running` are both `0`.

You can also query it through the command endpoint:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/storyboard-image-batch-status" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"batch_id":88}'
```

Query all scene image statuses in a storyboard:

```bash
curl -s "$BASE_URL/api/storyboard/10/task-status?asset_type=first_frame" -H "$AUTH"
```

首帧结果 URL 位于 `scenes[].selected_assets.first_frame.result_url`：

```json
{
  "success": true,
  "storyboard_id": 10,
  "scenes": [
    {
      "scene_id": 123,
      "selected_assets": {
        "first_frame": {
          "id": 900,
          "ai_tool_id": 501,
          "status": 2,
          "message": "done",
          "result_url": "https://example.com/upload/storyboard/first_frame/example.png",
          "ai_tool": {"id": 501, "status": 2}
        },
        "last_frame": null,
        "video": null
      }
    }
  ]
}
```

Generate a single scene image:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/generate-image" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"scene_id":123,"mode":"auto","asset_type":"first_frame","ratio":"16:9","count":1}'
```

Generate a scene video:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/generate-video" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"scene_id":123,"mode":"image_to_video","image_mode":"first_last_frame","duration_seconds":5}'
```

Query one scene status:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/task-status" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"scene_id":123,"asset_type":"first_frame"}'
```

## CLI Fallback

Run from the project root:

Set the environment from the connection package first:

```powershell
$env:comfyui_env="<environment>"
```

```bash
export comfyui_env="<environment>"
```

```bash
python -m scripts.storyboard_agent_cli auto-generate-missing-images \
  --storyboard-id 10 \
  --user-id 1 \
  --auth-token "<auth_token>" \
  --asset-type first_frame \
  --limit 5 \
  --sequence-mode balanced
```

Useful CLI commands:

```bash
python -m scripts.storyboard_agent_cli list-worlds --user-id 1
python -m scripts.storyboard_agent_cli world-context --world-id 1 --user-id 1
python -m scripts.storyboard_agent_cli world-context --world-id 1 --user-id 1 --include-full-story-outline
python -m scripts.storyboard_agent_cli get-script --script-id 20 --user-id 1
python -m scripts.storyboard_agent_cli list-scenes --storyboard-id 10 --user-id 1
python -m scripts.storyboard_agent_cli insert-scene --storyboard-id 10 --user-id 1 --after-scene-id 123 --title "Reaction shot" --duration 4 --prompt-json '{"scene_desc":"A quiet reaction shot."}'
python -m scripts.storyboard_agent_cli update-scene --scene-id 123 --user-id 1 --duration 8 --title "Reaction shot"
python -m scripts.storyboard_agent_cli scene-context --scene-id 123 --user-id 1
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --auth-token "<auth_token>"
python -m scripts.storyboard_agent_cli storyboard-image-batch-status --batch-id 88 --user-id 1
python -m scripts.storyboard_agent_cli storyboard-task-status --storyboard-id 10 --user-id 1 --asset-type first_frame
```

## Polling

After submitting generation, poll status every 3-5 seconds. Stop when no selected asset has status `0` or `1`, or after a reasonable cap such as 5 minutes. Return `project_ids`, `asset_ids`, selected asset IDs, result URLs, and failures to the user.

## Error Handling

- `missing_auth_token` or `invalid_auth_token`: ask for a valid agent token or auth_token.
- `missing_project_ids`: submission failed before creating generation tasks.
- `invalid_asset_type`: use `first_frame`, `last_frame`, or `video` depending on command.
- `not_found`: verify storyboard or scene ID.
- Failed generation statuses should be reported with `message`/`error` from the status payload.
