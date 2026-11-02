# 智能体 CLI 直接生图接口

## 概述

用户从首页「智能体连接」弹窗（`web/index.html` 头像旁按钮）复制的 CLI 连接信息（提示文案 + `agent_token` JSON 块），直接粘贴给本接口即可生图，无需手动拆 token 或先调 exchange。支持指定模型（如 `moss`）或用用户的 CLI 媒体偏好，文生图 / 图生图参数与平台前端一致。

- **端点**：
  - `POST /api/agent-auth/generate-image` — 提交生图（或 `wait=true` 同步等待结果）
  - `POST /api/agent-auth/image-status` — 按 `project_id` 轮询结果
- **代码**：`api/agent_auth.py`（端点）+ `services/agent_image_service.py`（编排）
- **认证**：agent_token（从连接信息自动提取）→ `AgentAuthService.exchange_token` 换 auth_token，全程服务端内存传递，不回传给调用方
- **计费**：与平台前端文生图/图生图同链路（`mcp_tool.generate_text_to_image` / `edit_image`），按所选模型 `computing_power` 预扣算力

## 请求体（generate-image）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `connection_info` | string | 二选一 | 粘贴的连接信息全文（服务端配平提取 JSON 块，取 `agent_token` / `token` 键） |
| `agent_token` | string | 二选一 | 已有明文 agent_token 时直接传 |
| `prompt` | string | ✅ | 提示词（文生图为画面描述；图生图为编辑指令） |
| `model` | string | ❌ | 模型名 / key / short_key / 任务 id（如 `moss`、`qwenimage2.1`、`53`）。缺省：用户 CLI 媒体偏好（首页弹窗「CLI 媒体偏好」tab，surface=storyboard_cli）→ 平台默认文生图模型 |
| `world_id` | int | ❌ | 世界 ID。缺省取用户最近更新的第一个世界（无世界且未传则报 `world_required`） |
| `mode` | string | ❌ | `auto`（默认，按有无参考图自动分流）/ `text_to_image` / `image_edit` |
| `reference_image` | string | ❌ | 图生图参考图 URL，多张英文逗号分隔。有值 → 图片编辑链路 |
| `ratio` | string | ❌ | 比例（`9:16` / `16:9` / `1:1` 等），缺省 `9:16` |
| `image_size` | string | ❌ | 分辨率档位 `1K`/`2K`/`3K`/`4K`（按模型支持范围，moss 为 1K/2K/4K） |
| `count` | int | ❌ | 生成张数 1-4（默认 1） |
| `wait` | bool | ❌ | `true` 时同步轮询首个 project 到终态（默认 false 立即返回 project_ids） |
| `wait_timeout` | int | ❌ | 同步等待上限秒（默认 180，最大 600；超时返回 `submitted` + `wait_timeout=true`，可继续用 image-status 轮询） |

### 响应（提交成功）

```json
{
  "success": true,
  "mode": "text_to_image",
  "world_id": 1,
  "project_ids": [501],
  "status": "submitted",
  "task_type": 53,
  "model_used": "moss",
  "model_key": "moss",
  "provider": "runninghub",
  "computing_power_per_image": 1,
  "computing_power_total": 1,
  "image_size_used": "2K",
  "poll_hint": {
    "interval_seconds": 3,
    "endpoint": "POST /api/agent-auth/image-status",
    "body": {"project_id": 501}
  }
}
```

`wait=true` 且完成时追加：`status`（`completed`/`failed`）、`result`（含 `result_url`）。

## 请求体（image-status）

| 字段 | 说明 |
|------|------|
| `connection_info` / `agent_token` | 与生图请求一致的凭据字段（二选一） |
| `project_id` | 生图返回的 project_ids 之一 |

### 响应

```json
{
  "success": true,
  "project_id": 501,
  "status_code": 2,
  "status": "COMPLETED",
  "terminal": true,
  "result_url": "https://..."
}
```

`terminal=true` 表示终态（COMPLETED=2 / FAILED=-1）；归属校验失败（非本人任务）返回 404 防枚举。

## 错误码

| error_code | HTTP | 说明 |
|------------|------|------|
| `missing_agent_token` | 400 | 连接信息里没解析到 agent_token |
| `invalid_agent_token` | 401 | agent_token 无效或过期（透传 exchange） |
| `prompt_required` | 400 | prompt 为空 |
| `invalid_mode` | 400 | mode 非法 |
| `invalid_count` | 400 | count 不在 1-4 |
| `reference_not_allowed` | 400 | mode=text_to_image 却带参考图 |
| `reference_required` | 400 | mode=image_edit 但没带参考图 |
| `model_not_found` | 400 | model 参数无法反查到任务配置 |
| `model_disabled` | 400 | 模型已禁用 |
| `model_mode_unsupported` | 400 | 模型不支持该模式（如 **moss 仅文生图**，带参考图会报此错并提示） |
| `world_not_found` / `world_forbidden` / `world_required` | 404/403/400 | 世界校验 |
| `submission_failed` | 400 | 提交链路失败（如算力不足，透传原因） |
| `missing_project_ids` | 502 | 提交成功但上游未返回任务 ID |
| `project_not_found` | 404 | project 不存在或不属于当前用户 |

## 典型调用

```bash
# 1) 粘贴整段连接信息 + 指定 moss 文生图（异步提交）
curl -s -X POST "$BASE_URL/api/agent-auth/generate-image" \
  -H "Content-Type: application/json" \
  -d '{
    "connection_info": "<首页复制的完整连接信息文本>",
    "prompt": "一只戴墨镜的橘猫，赛博朋克风格",
    "model": "moss",
    "ratio": "9:16",
    "image_size": "2K"
  }'

# 2) 同步等待出图（最长 180 秒）
#    追加 "wait": true

# 3) 图生图（qwenimage2.1 等支持编辑的模型）
#    追加 "reference_image": "https://.../a.png"（mode=auto 自动分流）

# 4) 轮询结果
curl -s -X POST "$BASE_URL/api/agent-auth/image-status" \
  -H "Content-Type: application/json" \
  -d '{"connection_info": "<同上>", "project_id": 501}'
```

## 实现要点

- **连接信息解析**：`_extract_balanced_json_objects` 用引号状态机做括号配平提取，容忍粘贴文本前后的中文说明与不配平伪 JSON（跳过而非报错）
- **非阻塞红线**：exchange / 生图提交 / 状态查询均为同步 DB/HTTP 调用，端点内一律 `asyncio.to_thread` 包装；`wait` 轮询在 async 层 `asyncio.sleep` + `to_thread` 逐次查（AGENTS.md 红线 1）
- **常量**：轮询间隔 / 等待上限 / 张数上限在 `config/constant.py`（`AGENT_CLI_IMAGE_*`）
- **模型校验**：`UnifiedConfigRegistry.matches_identifier` 口径反查；按 `category`/`categories` 校验模式能力，moss（TaskTypeId.MOSS_IMAGE=53，仅 `TEXT_TO_IMAGE`）带参考图会被拒绝
- **默认模型**：`MediaGenerationPreferenceService.get_profile(surface=storyboard_cli, image, mode)` → `DEFAULT_TEXT_TO_IMAGE_TASK_ID`

## 单元测试

```bash
python -m pytest tests/services/test_agent_image_service.py tests/api/test_agent_auth_api.py -v
```

覆盖：连接信息 JSON 提取（真实样例/纯 JSON/无 JSON/括号不配平/字符串内花括号）、模型解析与模式校验、参数校验、世界归属、提交参数透传、CLI 偏好默认模型、状态归属隔离（防枚举）、端到端 TestClient 调用。
