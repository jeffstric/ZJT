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

Split linked script into storyboard scenes:

```bash
curl -s -X POST "$BASE_URL/api/storyboard/agent/commands/split-from-script" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"storyboard_id":10,"max_group_duration":15}'
```

When `model` is omitted, the server uses `storyboard.config_json.selectedScriptSplitLlmModel`, then falls back to the server default.

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

Batch-generate missing first-frame images:

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

Query all scene image statuses in a storyboard:

```bash
curl -s "$BASE_URL/api/storyboard/10/task-status?asset_type=first_frame" -H "$AUTH"
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
