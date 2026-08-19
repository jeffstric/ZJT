---
name: storyboard-agent-api
description: Use when Claude Code needs to operate this project's storyboard automation API or CLI as an agent: exchange agent tokens, discover worlds/scripts/characters/locations/props, call storyboard command endpoints, create/split storyboard scenes, batch-generate missing storyboard images, generate scene images/videos, poll task status, and report results without bypassing auth or computing-power deduction.
allowed-tools: Read, Bash
---

# Storyboard Agent API

This skill lets Claude Code operate storyboard automation through the supported agent-facing APIs.

## Non-Negotiable Rules

- Prefer HTTP when the backend server is available.
- Use CLI only from the project root as a local fallback.
- Never put tokens in URLs. Use `Authorization: Bearer <auth_token>`.
- Never rely on body `user_id` for HTTP calls. The backend resolves the real user from the auth token.
- Never create generation tasks by writing database rows directly. Always use `generate-image`, `generate-video`, or `auto-generate-missing-images`.
- Batch image generation must use `auto-generate-missing-images`; it calls the same `generate_image()` path as the frontend and preserves computing-power deduction.
- Poll status after submission. Status `0` or `1` is running, `2` is complete, negative values are failures.

## Connection Package

At the start, Claude Code does not know the server URL or token. Ask the user to open the ZhiJuTong home page, click the agent icon next to the username, and paste the copied connection package.

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

> ⚠️ `api_version` is a **version label, NOT a URL path prefix**. Never prepend `storyboard-agent-api/v1` to request paths. All endpoints below already start with `/api/` — call them relative to `base_url` as-is. Prepending the version string hits the SPA catch-all and returns a misleading `404`/`405` instead of the real API.

Before making calls:

1. Parse `base_url`, `agent_token`, `api_version`, and `environment` from the user's connection package.
2. If `api_version` is missing or different from `storyboard-agent-api/v1`, tell the user this skill may not match the server API and ask for an updated skill or compatible connection package before running generation.
3. For v1, use the fixed endpoint paths below relative to `base_url` (they already include the `/api/` prefix); the connection package does not need to provide full endpoint URLs. Do **not** prepend `api_version` to these paths.
4. Treat `environment` as the backend configuration environment. HTTP calls do not need extra environment setup; CLI fallback must set `comfyui_env` to this value before running commands.

Fixed v1 endpoint paths:

- `POST /api/agent-auth/exchange`
- `GET /api/storyboard/agent/schema`
- `POST /api/storyboard/agent/commands/{command}`
- `POST /api/storyboard/{storyboard_id}/auto-generate-missing-images`
- `GET /api/storyboard/image-batches/{batch_id}/status`
- `GET /api/storyboard/{storyboard_id}/task-status?asset_type=first_frame`

## Authentication

When given a connection package or agent token, exchange it:

```bash
curl -s -X POST "$BASE_URL/api/agent-auth/exchange" \
  -H "Content-Type: application/json" \
  -d '{"token":"<agent_token>","device_uuid":"claude-code-storyboard-agent"}'
```

Store the returned short-lived token conceptually as:

```bash
AUTH="Authorization: Bearer <auth_token>"
```

If the user provides an `auth_token` directly, use it as `AUTH` and skip exchange.

## HTTP Calls

List supported commands:

```bash
curl -s "$BASE_URL/api/storyboard/agent/schema" -H "$AUTH"
```

Discover worlds before asking for script/storyboard IDs:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/list-worlds" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"page":1,"page_size":20}'
```

World responses show only a `story_outline` preview by default: first 50 characters plus last 50 characters, with `story_outline_preview` and `story_outline_truncated`. To read the full story outline, pass `include_full_story_outline:true`.

Read scripts, characters, locations, and props under one world:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/world-context" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"world_id":1,"page_size":100}'
```

Read full script content only when needed:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/get-script" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"script_id":20}'
```

Other read-only discovery commands: `list-world-scripts`, `list-world-characters`, `list-world-locations`, `list-world-props`. Script lists omit `content` by default and include `content_length`; pass `include_content:true` only when full text is needed. Any command that includes a `world` object accepts `include_full_story_outline:true`.

Create or reuse storyboard:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/create-storyboard-from-script" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"script_id":20}'
```

Split script into storyboard scenes:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/split-from-script" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"storyboard_id":10,"model":"deepseek-v4-flash","model_id":11,"vendor_id":4,"max_group_duration":15}'
```

`model` is **required** on the CLI/agent path — the server no longer falls back to a default model here. Call `list-llm-models` first to pick a reachable model, and pass `model_id` + `vendor_id` to pin the exact route when the same name is served by multiple vendors. If the storyboard already has scenes, it returns `scenes_exist`; create a new storyboard from the script or clear existing scenes first.

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
  -d '{"storyboard_id":10,"after_scene_id":123,"title":"Reaction shot","duration":4,"prompt_json":{"scene_desc":"A quiet reaction shot."},"video_prompt":"Hold on the character reaction."}'
```

Use `after_scene_id` for "insert after this scene". `before_scene_id`, `prev_id`, and `next_id` are also accepted for precise placement. If no placement is provided, the scene is appended to the storyboard.

Generate missing first-frame images for the storyboard:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/10/auto-generate-missing-images" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"asset_type":"first_frame","mode":"auto","limit":5,"sequence_mode":"balanced"}'
```

When `task_type` is omitted, the server uses `storyboard.config_json.selectedImageTaskId`. Pass `task_type` only to intentionally override the storyboard image workflow/model choice.

`sequence_mode` controls previous-frame references:

- `balanced` is the default: groups can run concurrently, but scenes inside one group wait for and reference the previous scene image.
- `quality` runs one global chain and references the previous scene even across group boundaries.
- `speed` submits all missing images without previous-frame references.

The response includes `batch_id`. Poll the orchestration batch when the request returns a `batch_id`:

```bash
curl -s "$BASE_URL/api/storyboard/image-batches/<batch_id>/status" -H "$AUTH"
```

You can also query it through the command endpoint:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/storyboard-image-batch-status" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"batch_id":88}'
```

Read storyboard-wide generation status:

```bash
curl -s "$BASE_URL/api/storyboard/10/task-status?asset_type=first_frame" -H "$AUTH"
```

Generate one image:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/generate-image" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"scene_id":123,"mode":"auto","asset_type":"first_frame","count":1}'
```

Generate one video:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/generate-video" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"scene_id":123,"mode":"image_to_video","image_mode":"first_last_frame","duration_seconds":5}'
```

Read one scene status:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/task-status" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"scene_id":123,"asset_type":"first_frame"}'
```

## CLI Fallback

Use only when inside this repo and the Python environment is usable:

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

Other useful commands:

```bash
python -m scripts.storyboard_agent_cli list-worlds --user-id 1
python -m scripts.storyboard_agent_cli world-context --world-id 1 --user-id 1
python -m scripts.storyboard_agent_cli world-context --world-id 1 --user-id 1 --include-full-story-outline
python -m scripts.storyboard_agent_cli get-script --script-id 20 --user-id 1
python -m scripts.storyboard_agent_cli list-scenes --storyboard-id 10 --user-id 1
python -m scripts.storyboard_agent_cli insert-scene --storyboard-id 10 --user-id 1 --after-scene-id 123 --title "Reaction shot" --duration 4 --prompt-json '{"scene_desc":"A quiet reaction shot."}'
python -m scripts.storyboard_agent_cli scene-context --scene-id 123 --user-id 1
python -m scripts.storyboard_agent_cli generate-image --scene-id 123 --user-id 1 --auth-token "<auth_token>"
python -m scripts.storyboard_agent_cli storyboard-image-batch-status --batch-id 88 --user-id 1
python -m scripts.storyboard_agent_cli storyboard-task-status --storyboard-id 10 --user-id 1 --asset-type first_frame
```

## Polling And Reporting

After generation submission, poll every 3-5 seconds until no task is running or a reasonable timeout is reached. In the final response, include submitted scene IDs, `project_ids`, selected asset IDs, ready result URLs, and any failed scene errors.

## Common Errors

- `missing_auth_token` / `invalid_auth_token`: request a valid agent token or auth_token.
- `not_found`: verify storyboard or scene ID.
- `invalid_asset_type`: use `first_frame`, `last_frame`, or `video`.
- `missing_project_ids`: generation did not create backend tasks; report the submission payload/error.
- Running tasks with no result URL yet should be reported as pending, not as failure.
