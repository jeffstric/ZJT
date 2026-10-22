# 数字人分段任务 compose_job 重构方案

> 状态：P1 已实施（2026-10-21）/ P2 已实施（2026-10-21 晚，history 与 detail/timeline 经确认不做）
> 相关代码：`server.py:5184`（H3 端点）、`task/compose_task.py`（编排主循环）、`model/compose_jobs.py`、`task/visual_drivers/digital_human_minimax_h3_runninghub_v1_driver.py`、`task/visual_task.py`、`task/scheduler.py`

## 1. 背景与问题

MiniMax H3 数字人口播 >15s 时走分段生成（每段 4-15s，多个 RunningHub 任务并行出片后 ffmpeg 拼接）。当前实现是 **sync_mode 全流水线**：`submit_task` 在一次调用内完成"上传角色图 → 并发提交各段 → 每 20s 轮询各段直至 SUCCESS → 下载 → 拼接"，单次独占 5 分钟以上。

调度侧 `generate_video` job 每 5 秒、`max_instances=1`、串行处理任务（`task/visual_task.py:1229 process_task_with_retry`）。因此一个分段数字人任务会把**整张生成队列**（图片编辑/文生图/视频等所有任务）堵住，实测两个数字人任务曾让队列排队约 29 分钟（2026-10-21 日志）。

## 2. 目标与非目标

**目标**
- 分段数字人任务不再独占 `generate_video` 调度槽，全队列恢复并发。
- 计费模型不变：每段 ai_tools 独立计费、独立退费；compose_job 不碰钱。
- 前端零改动（任务 id 不透明字符串传输，`web/js/pages/digital_human.js:211` 已确认）。

**非目标**
- 不改 RunningHub 驱动协议、不改槽位/密钥池限流。
- 本期不改前端历史页 UI（段记录可见，用 extra_config 标记区分）。

## 3. 总体设计

把"请求/编排/结果"与"执行"分离：

```
POST /api/digital-human-minimax-h3 (口播>15s)
  └─ 校验 → 逐段：扣费 → 建段 ai_tools(type=35, 标准非分段) + tasks 行
       └─ 建 compose_job(status=PENDING, segment_ids=[...]) → 返回 {"project_id": "compose_<id>"}
            │
            ├─ 各段：走 TASK_TYPE_GENERATE_VIDEO 标准异步生命周期（现有驱动非分段路径，零改动）
            │      提交返 taskId → 5s 轮询 → download_queue 下载 → CDN
            │
            └─ 新调度 job：compose 专用主循环 process_compose_jobs（task/compose_task.py，见 4.3）每 5s
                   └─ 全部段 COMPLETED 且本地文件就绪 → ffmpeg 拼接 → compose_job.result_url → CDN
```

- **段 = 标准 ai_tools**：`type=35`、`duration`=段时长、`audio_path`=段音频文件、`image_path`=角色图、`extra_config={"compose_id":N,"seg_index":i,"dh_segment":true}`。不写入 `dh_segments`，因此驱动走非分段分支（`driver.py:707` 立即返回 taskId），无需改驱动。
- **compose_job = 纯编排器**：不计费、不退费，只聚合段状态、触发拼接、持有最终结果。

## 4. 详细设计

### 4.1 新表 compose_jobs

按 AGENTS.md 规矩：`python scripts/new_migration.py add_compose_jobs`（下一编号 `no_155`），model 文件 `model/compose_jobs.py`，表名 `compose_jobs`，字段 `create_at/update_at`。

```sql
CREATE TABLE `compose_jobs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `status` tinyint NOT NULL DEFAULT 0 COMMENT '0-待拼接 1-拼接中 2-完成 -1-失败',
  `segment_ai_tool_ids` text COMMENT '有序段 ai_tools.id JSON 数组',
  `params` text COMMENT '编排参数快照：prompt/ratio/max_edge 等 JSON',
  `result_url` text,
  `media_mapping_id` int DEFAULT NULL,
  `message` varchar(500) DEFAULT NULL,
  `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_status_create` (`user_id`,`status`,`create_at`)
);
```

### 4.2 端点改造（server.py:5184 digital_human_minimax_h3_generate）

分段分支（`segment_audio` 非空）改为：

1. 保留现有校验（段 4-15s、总数 8-600s、段数与文件一致，:5217-5259）。
2. 落盘段音频（复用 :5274-5281）得到 `segment_paths`。
3. **逐段循环**：`get_computing_power(duration=段时长)` 计价（:5287 同款）→ 余额校验（:5293-5317 同款，按总价一次校验）→ 扣费（:5297-5334 同款，每段独立 transaction_id）→ `AIToolsModel.create(type=35, duration=段时长, audio_path=段文件, extra_config={compose_id 占位/seg_index/dh_segment})` → `TasksModel.create(generate_video)` → `PipelineProcessor.attach_param_prepare_if_needed`（与现状一致；type 35 当前无 param_prepare 步骤，no-op）。扣费为逐段串行 perseids 请求，段数多时接口耗时上升（600s/15s = 40 段 ≈ 40 次请求），一期接受串行，必要时改 `asyncio.gather` 并发（各段独立 transaction_id，天然幂等）。
4. 全部段创建成功后建 `compose_jobs` 记录（`segment_ai_tool_ids` 有序），回写各段 extra_config 的 `compose_id`；**建 compose 之前任一段失败**：已创建的段标记 FAILED、**其 tasks 行同步置 FAILED**（否则调度器仍会捡起 QUEUED 的段继续驱动已标失败的段），并走标准退费（复用 `resolve_refund_amount` 循环，幂等），返回失败。
5. 返回 `{"project_id": f"compose_{compose_id}", ...}`（结构不变，:5368-5374）。

非分段请求（≤15s）路径完全不动。

### 4.3 调度：compose 专用主循环（不复用 process_task_with_retry）

⚠️ 评审修正：原设想 `partial(process_task_with_retry, COMPOSE_JOB, process_compose_job)` 直接复用——**不成立**。`process_task_with_retry` 不是通用编排器，它把 `task.task_id` 硬编码为 `ai_tools.id`：

- `visual_task.py:1417` `AIToolsModel.get_by_id(task.task_id)`：compose id 为小整数，**会撞上无关用户的 ai_tools 行**（并据其 type 误判 RunningHub 槽位逻辑）；撞不上则 `continue`，compose 任务永远不被处理。
- 过期分支（:1282-1283）与超重试分支（:1344-1345）会对撞号行执行 `status=FAILED` + 退费——**误改误退无关用户任务**；`AIToolsLogModel.log` / `still_polling` 判断同样落在错误记录上。

**采用**：`task/compose_task.py` 独立主循环 `process_compose_jobs()`（模式参照 token_task 自带循环）：

- 复用纯函数（从 visual_task 导入）：`_check_task_expiration`、`calculate_next_retry_delay`；超限判断用 compose 自己的上限常量。
- 复用 tasks 表行：`task_type='compose_job'`、`task_id=compose_jobs.id`，`try_count` / `next_trigger` / 状态机字段通用（`list_by_type_and_status` 自带 `next_trigger <= NOW()` 过滤，退避天然生效）。
- 自己实现：过期/超限分支的 compose 收尾（compose_jobs.status=-1 + tasks 置 FAILED + message），**不触碰 ai_tools**；轮询等待的日志文案自己写（"等待段完成"）。
- `config/constant.py` `TaskType` 枚举加 `COMPOSE_JOB = 'compose_job'`；compose 重试上限用独立常量 `COMPOSE_JOB_MAX_RETRY_COUNT`（config/constant.py）——compose 的 try_count 同时被「等段」与「补段」消耗，沿用 `task_queue.max_retry_count`（默认 30）容易过早判死。

```python
scheduler.add_job(
    func=process_compose_jobs,
    trigger=IntervalTrigger(seconds=5), id='compose_job',
    max_instances=1, coalesce=True, replace_existing=True)
```

### 4.4 compose 状态机（task/compose_task.py 新文件）

主循环 `process_compose_jobs()` 遍历 `TasksModel.list_by_type_and_status('compose_job')`，逐单调用 `_process_one_compose(task)`（`task.task_id` = compose_jobs.id）：

| 段状态扫描结果 | compose 行为 |
|---|---|
| 全部 COMPLETED 且 `result_url` 已落本地（`/upload/` 前缀且文件存在） | 拼接（4.6，线程池执行）→ compose_jobs.status=2 + **tasks 行置 COMPLETED** → 触发 CDN（4.7）→ 结束 |
| 有段 RUNNING/PENDING（含 download_queue 下载中） | 只重排 `next_trigger`（10s 后复查），**不消耗 try_count**、不写失败文案 |
| 有段终态 FAILED | 缺口补段（见 4.5）；compose 自身 try_count 超过 `COMPOSE_JOB_MAX_RETRY_COUNT` → compose_jobs.status=-1 + tasks 行置 FAILED |
| **段 FAILED 且 message 命中内容审核**（友好前缀或分类器识别） | **整单快速 FAILED，不补段**——补段用相同 prompt/图/音频必然再次审核失败，空转只产生计费流水（已实施 2026-10-21，见 8.6）；原因透传给 get-status（`is_content_violation=true`） |
| **段 COMPLETED 但 `result_url` 非 `/upload/` 前缀（下载兜底残留）** | 有限次 compose 侧自行下载（复用 `download_and_cache`，落成本地 `/upload/` 路径后参与拼接）；仍失败 → 该段标 FAILED + 退费，转入上一行"缺口补段" |
| 段记录缺失（人工删除等） | 记异常日志，按 FAILED 处理（走缺口补段） |

⚠️ 实施修正（等待语义）：原表述为"返回 False（标准退避）"——实际实现中**等待不消耗 try_count**。原因：段平均 4-10 分钟，若等待也计次，指数退避下 30 次预算会在段跑完前耗尽（schedule 5s + 退避封顶 96s ≈ 1 小时内必死）。现实现把重试预算只用于"补段 / 拼接失败"等真实动作，等待仅重排 `next_trigger`（`ComposeJobConstants.WAIT_RESCHEDULE_SECONDS`）。

文件就绪判据：段 `status=2` 且 `result_url.startswith('/upload/')` 且 `os.path.exists`——因为段完成的瞬间 result_url 还是远端 URL，要等 download_queue 落盘。

⚠️ 评审修正（兜底残留分支，上表第 4 行）：`download_queue_task.py:197-224`（注释"达 max_try：用 remote_url 兜底 COMPLETED（H3）"）在段下载重试耗尽后，**仍把段置 COMPLETED 且 result_url 保持远端 URL，此后无任何代码再改写该字段**。若状态机缺此分支，compose 会既不判"就绪"也不判"缺口"，空转到 try_count 耗尽 → 整单 FAILED，而所有段其实都成功了。又因段下载反复失败常见原因是远端 URL 过期，自行下载也可能 404，故有限次后必须降级为缺口补段（重新生成），不得无限重试下载。

⚠️ 评审修正（收尾责任）：`process_task_with_retry` 体系里 tasks 行的终态由各处理函数内部自己置（见 `_submit_new_task:527`）——compose 主循环同样如此：**成功路径必须自行把 tasks 行置 COMPLETED，失败终态置 FAILED**，否则任务行永远留在 status=1 被反复调度、重复拼接。

⚠️ 评审修正（拼接执行方式）：ffmpeg 拼接（timeout=600s）不占调度线程——提交到模块级长寿 `ThreadPoolExecutor`（AGENTS.md R9/R10：禁 `with` 上下文管理器、`future.result` 必须显式 `timeout=`；超时常量入 config/constant.py）。

### 4.5 失败与重试语义（已确认的产品规则）

- 段终态失败 → 该段**自动退费**（现有 `process_task_with_retry` 超重试分支原样生效），已成功段扣费保留（缺段拼不出成片也接受）。
- **compose 级重试**：compose 返回 False 走标准退避后，下轮扫描发现"有缺口"（FAILED 段，含 4.4 兜底残留降级来的段）→ 为缺口段**新建补段 ai_tools + tasks**（重新计费）。补段失败再退再补，直到 compose 自身 try_count 超过 `COMPOSE_JOB_MAX_RETRY_COUNT` → 整单 FAILED。
- **补段顺序维护**：补段新 ai_tools id **按 seg_index 原位替换** `segment_ai_tool_ids` 对应槽位——禁止尾部追加（会打乱拼接顺序）。安全性依赖 compose job `max_instances=1` 的串行前提：同一 compose 不会并发补段。
- 断点续跑天然获得：COMPLETED 段不动，只补缺口段。

### 4.6 驱动代码调整与清理

- `_concat_and_store(project_id, seg_files)`（driver.py:567）拼接逻辑直接复用（compose 侧以 `compose_{id}` 作 project_id 落盘 `upload/cache/`）。可提升为模块级函数或 compose_task 持有 driver 实例调用。
- **删除 sync_mode 全套死代码**：`_submit_segments_async`/`_run_one_segment`/`_wait_and_download_segment`/`_SEGMENT_EXECUTOR`/`_SegmentedCongestedError`/`_SegmentedPipelineError`/`SEGMENT_*` 常量、`submit_task` 的 `dh_segments` 分支（:715-725），以及上一轮遗留的不可达聚合代码 `_lookup_segment_task_ids`/`_check_segmented_status`/`_save_segment_task_ids`（:453-565）和 `check_status` 里对应分支（:840-849）。
- `DigitalHumanSegmentConstants`（config/constant.py:2108 附近）同步删除；保留 `split_audio_into_segments`（`utils/audio_segment_util.py:75`，TTS 切分仍在用）。

### 4.7 CDN

- `model/media_file_mapping.py` `MediaFileEntity` 加 `COMPOSE_JOB = 8`（同步 `get_entity_name`/`from_entity_name` 两个 dict，:27/:42；entity_type 是 int 无 FK，**无需迁移**）。
- 拼接完成后按 `model/ai_tools.py:684` 同款逻辑建 mapping + `CDNUtil.trigger_cdn_upload`。
- 评审补充（段 CDN 浪费）：段完成走 `update_by_project_id_with_cdn_sync`，enable_cdn 开启时**每段都会建 mapping + 触发 CDN 上传**——段是中间产物，40 段即 40 次无谓上传。
- **已实施（2026-10-21 P2）**：`model/ai_tools.py` 新增 `is_segment_ai_tool()`；`update_by_project_id_with_cdn_sync()` 对 `extra_config.dh_segment=true` 的记录**早退**——只更新状态/`result_url`，不建 mapping、不触发 CDN。判定集中在模型层，download worker 与任何调用方零改动。

### 4.8 API 适配层（前端契约不变）

统一 resolver（新 `api/task_ref.py` 或在 server.py 内）：

```python
def resolve_task_ref(task_id: str) -> TaskRef  # "compose_123" → compose_jobs；其余 → ai_tools
```

| 接口 | 适配 |
|---|---|
| `GET /api/get-status/{id}`（server.py:2352） | ✅ P1 已实现：`compose_` 前缀分发到 `_get_compose_status_payload`，聚合各段：未终态→"RUNNING"，终态 FAILED→"FAILED"（reason 取 compose.message），拼接完成→"SUCCESS"（results 取 compose result_url + CDN 状态，CDN 查询走 COMPOSE_JOB entity 的 mapping）；逗号分隔混合 id 已支持 |
| `GET /api/ai-tools/history`（server.py:4240） | ❌ **不改造（用户 2026-10-21 确认）**：段记录（type=35，各 15s）在数字人历史页可见，视为可接受；成片不进历史，仅提交当次页面可获取。若后续要合并：段排除须在 SQL 层完成（`list_by_user` 是 SQL 分页，应用层过滤会破坏分页），compose_jobs 映射为同构记录（`compose_<id>`）按时间混排 |
| `GET /api/ai-tools/detail/{id}`、`/api/ai-tools/{id}/timeline` | ❌ **无需适配（2026-10-21 复核结论）**：全仓（web/script_writer_core/auto_test/enterprise/api）零调用方，仅有文档提及，`compose_` 前缀触发 422 在实际链路上不可达。管理后台排障走的是另一个接口 `/api/admin/ai-tools/timeline`（api/admin.py:481），其 `project_id` 参数本就是 `str` 且用 `list_by_project_id` 查询，**接口层天然支持 `compose_<id>`**，无需改造 |
| `GET /api/download` | 零改动（文件路径直出） |

### 4.9 日志

`ai_tools_log` 只挂段记录（天然有）。compose 自身状态变迁写 `compose_jobs.message` 字段 + 应用日志；如需独立审计，二期再加 compose 日志表（本期不做）。

补充（2026-10-21 复核）：管理后台时间线 `/api/admin/ai-tools/timeline` 支持按 `project_id` 字符串查询，因此只需在状态机关键节点补 `AIToolsLogModel.log(None, <event>, project_id='compose_<id>')`，接口与前端零改动。

**已实施（2026-10-21 P2）**：`task/compose_task.py::_compose_event()` 按上述方式落事件，事件类型复用既有 `AIToolsLogEvent` 枚举：

| 节点 | 事件 | 关键 detail |
|---|---|---|
| 编排开始处理（QUEUED→PROCESSING） | `task_started` | `segments` |
| 段下载兜底残留自愈成功 | `download_completed` | `segment_id` / `local_url` |
| 自愈失败降级为补段（已退费） | `upstream_failed` | `segment_id` / `attempts` |
| 补段扣费未成功 | `exception` | `seg_index` / `power` / `transaction_id` |
| 补段建记录失败（已原额退） | `exception` | 同上 + `error` |
| 补段成功 | `pipeline_step` | `seg_index` / `segment_ai_tool_id` / `duration` / `power` |
| 补段轮次（成功/全失败） | `retry_scheduled` / `exception` | `gaps` / `segment_ids` / `try_count` |
| 开始拼接 | `pipeline_step` | `segments` / `seg_files` |
| 拼接失败待重试 | `exception` | `concat_attempts` / `error` |
| 终态成功 | `task_completed` | `result_url` / `media_mapping_id` |
| 终态失败 | `max_retry_exceeded` | 原因 |

后台查询：`GET /api/admin/ai-tools/timeline?project_id=compose_<id>`。注意 `ai_tool_id` 列为空是预期（compose 在 ai_tools 无记录）。

## 5. 兼容性

- **无生产存量**：本方案未发布，不存在线上在途分段任务，无需数据迁移与灰度。
- 开发环境在途分段任务：P1 实施前执行清理脚本 `scripts/cleanup_dh_segment_tasks.py`（新增）——把 `extra_config LIKE '%dh_segments%' AND status IN (0,1)` 的 ai_tools 置 FAILED、对应 tasks 行置 FAILED、按 `resolve_refund_amount` 幂等退费。否则删掉驱动 `dh_segments` 分支（4.6）后，这些残留任务会被调度器按单段路径错误重提（`_resolve_duration` 把总时长回退成 DEFAULT_DURATION=10，给上游提交错误任务）。
- 营销 agent 链路（`script_writer_core/digital_human_tts_tools.py` 上传 `segment_audio`）走同一端点，自动切换到 compose 流程，无改动。
- 非分段数字人（≤15s）完全不受影响。

## 6. 分期实施

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0（先行止血，可选） | `generate_video` 主循环把分段数字人提交转交专用 worker 线程（抽 `_process_single_video_task` + 模块级单线程 executor + 进程内认领表） | 图片编辑任务不再被数字人堵 >1 个调度周期 |
| P1 核心 ✅ | 迁移 no_155 + model；端点改造；`compose_job` 调度注册（专用主循环）；`process_compose_jobs`（聚合/兜底残留自愈/补段/拼接）；get-status resolver；开发环境清理脚本 `scripts/cleanup_dh_segment_tasks.py` | 已完成，见第 8 节（单测 7 例 + lint 全绿） |
| P2 收尾 | history 合并（SQL 层排除段）；detail/timeline 适配；删除 sync_mode 死代码与常量；段 CDN 上传抑制优化；`docs/` 同步；补段计费单测 | 历史页只见整单；清理脚本执行后 CI 通过 |

## 7. 风险

- **计费循环原子性**（4.2 第 4 步）：逐段扣费建记录中途失败需回滚已建段（标记 FAILED + tasks 行同步置 FAILED + 退费，幂等）。扣费本身是 fire-and-forget（失败仅记日志），余额校验是实际闸门，与今天语义一致。
- **补段重试的计费**：默认补段重新计费（新记录）。若产品希望"同一段不重收"，需引入仅限补段的免计费标记——列为评审决策点。
- **15s 段 OOM 降档重切**（原 `SEGMENT_FALLBACK_MAX_SEG`）：本期降级为"普通补段重试"，重切段长逻辑放 P2 评估。
- **get-status 多 id 查询**：`:2352` 支持逗号分隔多 id，resolver 需支持混合 id（段 id 与 compose id 同现于营销批量轮询）。

## 8. 实施记录（P1，2026-10-21）

### 8.1 变更文件

| 文件 | 改动 |
|---|---|
| `alembic/versions/no_155_20261021_add_compose_jobs.py` | 新建 `compose_jobs` 表（create_at/update_at、`concat_attempts` 熔断计数、`idx_user_status_create`） |
| `model/compose_jobs.py` | `ComposeJob` / `ComposeJobModel`（create/get_by_id/update/update_segment_ids/list_by_user/list_by_status）+ 末尾 `CREATE_TABLE_SQL` |
| `model/__init__.py` | 导出 `ComposeJobModel` / `ComposeJob` / `ComposeJobStatus` |
| `config/constant.py` | `TaskType.COMPOSE_JOB`、`TASK_TYPE_COMPOSE_JOB`、`ComposeJobStatus`（0/1/2/-1）、`ComposeJobConstants`（`PROJECT_ID_PREFIX`、`POLL_INTERVAL_SECONDS`、`WAIT_RESCHEDULE_SECONDS`、`MAX_RETRY_COUNT=100`、`SEGMENT_REMOTE_DOWNLOAD_MAX_ATTEMPTS=3`、`SEGMENT_HEAL_PER_ROUND=2`、`CONCAT_MAX_ATTEMPTS=3`、`CONCAT_TIMEOUT_SECONDS=600`、`CONCAT_EXECUTOR_MAX_WORKERS=2`） |
| `model/media_file_mapping.py` | `MediaFileEntity.COMPOSE_JOB = 8`（同步 `get_entity_name` / `from_entity_name`） |
| `server.py` | H3 端点分段分支改走 `_submit_segmented_digital_human`（逐段扣费/建记录/入队 + 建 compose_jobs + 失败回滚）；新增 `_get_compose_status_payload`，`get-status` 按 `compose_` 前缀分发（支持逗号分隔混合 id） |
| `task/compose_task.py` | 新增 compose 专用主循环 `process_compose_jobs`（状态机/补段/兜底自愈/线程池拼接/CDN/终态收尾） |
| `task/scheduler.py` | 注册 `id='compose_job'`（5s，`max_instances=1`） |
| `scripts/cleanup_dh_segment_tasks.py` | 开发环境旧分段在途任务清理（默认 dry-run，`--execute` 生效，`--skip-refund` 只关不退） |
| `tests/task/test_compose_task.py` | 状态机 + 计费 18 例单测（等待不计次、原位补段、兜底降级、拼接终态、终态幂等、超限失败、记录缺失、音频失效快速失败、拼接熔断/退避；补段：先扣费后建段、扣费失败不建段、建记录失败按原流水号退回、参数缺失不扣费、`deduct`/`increase` 契约、零算力短路） |
| `tests/model/test_ai_tools_segment_cdn.py` | 段 CDN 抑制 4 例（判定函数、段更新不建 mapping、普通记录行为不变） |

### 8.2 实现期发现并修正的问题

1. **`TasksModel.update_by_task_id(compose_id)` 会误改段任务行**：该接口只按 `task_id` 过滤、不带 `task_type`，而 `compose_jobs.id` 与 `ai_tools.id` 可能取到同一数值（`tasks.task_id` 对两者都是 int）。compose 侧所有调度行更新一律改用主键：`TasksModel.update(task.id, ...)`。
2. **等待分支不能计 try_count**（见 4.4 实施修正）。
3. **提交期回滚的扣费闭环**：逐段"先扣费 → 再建记录"，回滚按 `refund-{原流水号}` 原额退回（幂等）；若段记录已建（含 tasks 行）则先置双方 FAILED，避免调度器继续驱动已废弃的段。
4. **兜底残留自愈计数落段 `extra_config.compose_download_attempts`**（不新增表字段），超过 `SEGMENT_REMOTE_DOWNLOAD_MAX_ATTEMPTS` 才降级补段。

### 8.3 P1 复查（2026-10-21 晚，二次核验）

| 问题 | 修法 |
|---|---|
| 兜底自愈只走 `download_and_cache`，媒体缓存未启用时恒返回 None → 被判"不可本地化"→ **触发付费重生成** | 增加 `_download_remote_to_upload_cache`（requests 直连落 `upload/cache`）作为兜底；缓存可用时仍优先走 cache manager |
| 自愈是同步 HTTP 下载，一轮 40 段全残留会把调度线程堵数十分钟（`max_instances=1` 全线停摆） | 新增 `SEGMENT_HEAL_PER_ROUND=2`，每轮限量；`seg.result_url` 同步内存对象，避免白等一轮 |
| 拼接失败与补段共用 100 次预算 → 确定性拼接错误（坏文件/缺音轨）在退避封顶下空转数小时 | 新增 `compose_jobs.concat_attempts` 列 + `CONCAT_MAX_ATTEMPTS=3` 独立熔断；补段成功即清零；拼接失败**不写** `try_count` |
| 段音频/角色图是 `upload/temp` 临时文件，被清理后补段会「扣费→建段→失败→退费」反复空转直到预算耗尽 | 补段前校验 `segment_paths[idx]` / `params.image_url` 是否仍落盘；缺失直接整单 FAILED 并给出可读原因（不扣费） |
| `compose_jobs.message` 为 varchar(500)，异常栈直接写入会 `Data too long` → 终态写库失败 → 任务被反复调度 | `_finish_compose` 统一截断 497+`...` |
| 段 `extra_config` 脏 JSON 会让 `json.loads` 抛错并计次 | 统一走 `_seg_extra()` 容错解析 |
| compose COMPLETED 但 `result_url` 为空时报 SUCCESS 空结果（前端白屏） | `get-status` resolver 降级为 FAILED + 可读原因 |

### 8.4 P2 范围与实施结果（2026-10-21 晚）

| 项 | 状态 | 说明 |
|---|---|---|
| `/api/ai-tools/history` 合并 | ❌ 不做（用户确认） | 段记录在历史页可见可接受；代价是分段单成片只在提交当次页面可见，历史页仅存各段片段 |
| `detail` / `timeline` 的 compose 适配 | ❌ 取消（核实） | 全仓零调用方；后台排障接口 `api/admin.py:481` 的 `project_id` 本就是 `str` + `list_by_project_id`，天然支持 `compose_<id>` |
| compose 日志插桩 | ✅ 已实施 | `_compose_event()`：`AIToolsLogModel.log(None, event, project_id='compose_<id>', ...)`，复用既有 `AIToolsLogEvent` 枚举（后台中文标签无需改动）。覆盖：开始处理、自愈成功、自愈降级退费、补段成功/失败/扣费未成功/建记录失败、拼接开始/失败、终态（成功/失败） |
| 驱动 `dh_segments` 死代码删除 | ✅ 已实施 | 驱动 965 → 474 行（-22.3K 字符）：删 `_SEGMENT_EXECUTOR`、`_SegmentedPipelineError`、`_SegmentedCongestedError`、15 个分段方法（提交/轮询/下载/断点续跑/拼接/重提/降档）、`submit_task` 的 `dh_segments` 分支、`check_status` 的分段聚合分支，以及失效 import（`asyncio`/`os`/`subprocess`/`time`/`ThreadPoolExecutor`/ffmpeg 路径/`DigitalHumanSegmentConstants`）；`config/constant.py` 删除 `DigitalHumanSegmentConstants` |
| 段 CDN 上传抑制 | ✅ 已实施 | `model/ai_tools.py::is_segment_ai_tool()` + `update_by_project_id_with_cdn_sync()` 早退：段只更新状态，不建 mapping、不触发 CDN（40 段 = 40 次无谓上传 + 40 条 mapping） |
| 补段计费单测 | ✅ 已实施 | 8 例：先扣费后建段（流水号一致）、扣费失败不建段、建记录失败按原流水号退回、参数缺失不扣费、`deduct`/`increase` 契约、零算力短路 |
| 15s 段 OOM 降档重切 | ✅ 无需做 | 段现在是标准单段任务，失败走普通任务重试/退费；旧驱动内的降档重切逻辑已随分段流水线一并删除 |

### 8.5 验证

- `python -m py_compile`（全部改动文件）通过
- `scripts/lint_blocking_calls.py` 0 error；`scripts/lint_migration_names.py` 通过（单 head、no_155）
- `pytest tests/task/test_compose_task.py` **18 passed**（状态机 10 例 + 补段计费 8 例）
- `pytest tests/model/test_ai_tools_segment_cdn.py` **4 passed**（段 CDN 抑制）
- `pytest tests/drivers/test_digital_human_minimax_h3_runninghub_v1_driver.py` **4 passed**（旧分段流水线用例随代码删除）
- `pytest tests/api/test_digital_human_h3_duration_validation.py` **13 passed**（分段提交断言 `project_id=compose_<id>`）
- `pytest tests/task/test_compose_task.py tests/test_server_helpers.py` 41 passed

### 8.6 第三轮复查修复（2026-10-21）

1. **审核类确定性失败快速终止**（Bug A）：段因内容审核失败时，补段用相同 prompt/角色图/音频必然再次失败。原实现会空转最多 100 轮（每轮扣费→失败→退费，资金不丢但产生约 200 条流水 + 数小时假 RUNNING）。现识别 `message` 命中审核（友好前缀 `is_content_moderation_user_message` + 原始上游文案 `classify_content_moderation` 双通道）→ 整单立即 FAILED，不补段不扣费，原因透传。
2. **get-status 违规标记**（Bug B）：compose FAILED 分支原硬编码 `is_content_violation: False`，现与普通任务路径一致，按 `is_content_moderation_user_message(reason)` 计算，前端可正常走内容违规 UI。
3. **自愈下载半截文件清理**（Bug C）：直连下载异常时删除残留的 partial 文件。
4. 新增单测 3 例（审核快速失败/原始文案识别/普通失败仍补段），compose 套件累计 21 passed。

### 8.7 复查确认无问题的项

- `get-status` resolver 按 `compose_jobs.status` 聚合（非段状态）→ 补段期间不误报 FAILED
- `_check_task_expiration` 为纯函数（无副作用），compose 复用安全
- `AIToolsLogModel.log(ai_tool_id=None)` 允许空段 id，事件枚举全部存在
- `list_by_type_and_status` 含 `next_trigger <= NOW()` 过滤；`tasks.next_trigger` 默认 CURRENT_TIMESTAMP，建行即可被调度
- CWD 相对路径 `upload/cache` 与旧驱动 `_concat_and_store`/media_cache 默认约定一致（CWD=项目根是全仓既有部署假设）
- 段 CDN 抑制早退路径仍正常更新 status/result_url（`update_by_project_id`）
- `completed_time`/`extra_config`/`message` 均在 `AIToolsModel.update` 白名单
