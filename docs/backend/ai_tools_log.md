# ai_tools_log 任务事件日志

## 背景

排查任务 `ai_tools.id=9475` 时发现：数据库里只有最终状态（`ai_tools` 一行 + `tasks` 一行），中间的提交、每次轮询、下载、CDN、重试调度都只存在于易过期、难检索的文本日志（`logs/app.*.log`）里。一次"13 分钟轮询静默"几乎不可见（藏在 `apscheduler ... skipped: maximum number of running instances reached` 噪声中）。

为此新增 `ai_tools_log` 表：**只增不改**，记录每个 `ai_tools` 任务从创建到终态的每一个关键事件（含每一次状态轮询），可通过 `ai_tool_id` 或冗余的 `project_id` 一条 SQL 拉出完整时间线。

## 表结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint PK | 自增 |
| `ai_tool_id` | int | 关联 `ai_tools.id` |
| `user_id` | int | 冗余，便于按用户排查 |
| `project_id` | varchar(100) | 冗余上游任务 ID（Duomi 等），可直接定位 |
| `event_type` | varchar(48) | 事件类型，见下表 |
| `status_from` / `status_to` | tinyint | `ai_tools.status` 变更前后 |
| `implementation` | int | 冗余实现方 ID |
| `try_count` | int | 冗余重试次数 |
| `message` | varchar(500) | 简短描述 |
| `detail` | json | 详细上下文（上游响应 / URL / 耗时等） |
| `duration_ms` | int | 本事件耗时（毫秒），如下载/上传耗时 |
| `create_at` | timestamp(3) | 事件发生时间（**毫秒精度**） |

索引：`idx_atool_create(ai_tool_id, create_at)`、`idx_project_id`、`idx_event_create(event_type, create_at)`、`idx_create_at`。

建表 SQL：`model/ai_tools_log.py` 末尾 `CREATE_TABLE_SQL`；迁移脚本：`alembic/versions/no_101_20260701_create_ai_tools_log.py`。

## 事件类型

| event_type | 含义 | detail 示例 |
|---|---|---|
| `record_created` | ai_tools 记录创建 | `{type, ratio, duration}` |
| `task_started` | 调度器接管，status→PROCESSING | `{task_table_id, try_count}` |
| `slot_delayed` | RunningHub 槽位已满，延迟 | `{delay_seconds}` |
| `implementation_selected` | 选用驱动/实现方 | `{impl_name, impl_id}` |
| `submitted` | 提交到上游，拿到 project_id | `{project_id, driver}` |
| `status_check` | **每次状态轮询（含 running）** | `{state, progress, message, error}` |
| `upstream_succeeded` | 上游返回成功 | `{result_url}` |
| `upstream_failed` | 上游返回失败/错误 | `{error, error_type}` |
| `download_started` | 开始下载结果文件 | `{source_url, media_type}` |
| `download_completed` | 下载/缓存完成 | `{source_url, final_url}`, `duration_ms` |
| `cdn_uploaded` | 七牛 CDN 上传完成 | `{mapping_id, result_url}` |
| `retry_scheduled` | 失败，安排重试 | `{try_count, delay_seconds, next_trigger}` |
| `max_retry_exceeded` | 超过最大重试次数，终态失败 | — |
| `task_completed` | 任务终态成功 | `{result_url}` |
| `exception` | 流程中出现未预期异常 | `{error}` |

> `status_check` 是核心：**每次轮询写一行**。`create_at` 之间出现大间隔即"轮询静默/调度积压"的直接证据。

## 埋点位置

- `model/ai_tools.py`：`record_created`（`create` / `create_with_pipeline_steps`，事务提交后写）、`cdn_uploaded`（`update_with_cdn_sync` / `update_by_project_id_with_cdn_sync`）。
- `task/visual_task.py`：
  - `_submit_new_task`：`implementation_selected` / `upstream_failed` / 同步路径 `download_started`+`download_completed`+`task_completed` / `submitted` / `exception`。
  - `_check_task_status`：**`status_check`（每次）** / `upstream_succeeded` / `upstream_failed` / `exception`。
  - `_handle_task_success`：`download_started` + `download_completed` + `task_completed`。
  - `process_task_with_retry`：`max_retry_exceeded` / `slot_delayed` / `task_started` / `retry_scheduled`（失败退避 + 异常退避）。

写入遵循 `model/ai_tools_log.py` `AIToolsLogModel.log()`：**best-effort**（永不抛异常）、**独立连接单条 INSERT**（不并入业务事务，避免随业务回滚），符合 CLAUDE.md 非阻塞规则。

## 查询接口

### 用户端（仅本人）

```
GET /api/ai-tools/{ai_tool_id}/timeline?user_id=&auth_token=
```

- 鉴权：`@require_permission("ai_tools:view_history")`，与 `/api/ai-tools/history` 一致。
- 归属校验：`user_id` 与 `record.user_id` 不符返回 403；记录不存在返回 404。
- 返回：`{success, data:{ai_tool_id, project_id, status, timeline:[...]}}`，时间升序。

### 管理端（不限用户）

```
GET /api/admin/ai-tools/timeline?ai_tool_id=&project_id=
```

- 鉴权：管理员（`require_admin`）。
- 支持按 `ai_tool_id` 或 `project_id` 查询；用 `asyncio.to_thread` 包同步查询（非阻塞）。

**后台管理入口**：`/admin` → 侧边栏「任务时间线」页（`web/admin.html` + `web/js/admin.js`）。下拉选择按 `project_id` 或 `ai_tool_id` 查询，回车/点搜索即可看到该任务完整事件表（时间 / 事件 / 描述 / 耗时 / 可展开 detail）。

## 前端入口

`web/index.html` 注册全局组件 `<timeline-modal>`（自管数据获取与渲染，毫秒级时间轴 + detail 可折叠）。以下 7 个历史页面均在历史项中加入"查看时间线"按钮：

`DigitalHuman`、`VideoRemix`、`VideoEnhance`、`ImageEdit`、`TextToImage`、`ImageToVideo`、`AIVideoGen`。

i18n 键（`web/i18n/locales/{zh-CN,en}/index.json`）：`view_timeline` / `task_timeline` / `no_timeline_records` / `event` / `timeline_loading`。

## 排查示例（以 9475 为例）

直接用 `project_id` 拉出完整时间线，无需翻日志文件：

```sql
SELECT create_at, event_type, message, duration_ms, detail
FROM ai_tools_log
WHERE project_id = '3053709b-583a-d433-536b-2c4b8ee5e657'
ORDER BY create_at;
```

预期链路：
```
record_created → task_started → implementation_selected → submitted
→ status_check(多次, running) → upstream_succeeded
→ download_started → download_completed → cdn_uploaded → task_completed
```

`status_check` 行之间的 `create_at` 间隔即轮询节奏；若出现十几分钟无 `status_check`，即可定位为"轮询静默/调度积压"。

## 范围说明

- 仅对新任务生效（历史任务无日志）；如需补量可写一次性回填脚本。
- append-only 会增长，后续可加按 `create_at` 的定期归档/清理任务。
- `pipeline_step` 事件为预留；流水线步骤状态变更已在 `ai_tool_pipeline_steps` 表记录。
