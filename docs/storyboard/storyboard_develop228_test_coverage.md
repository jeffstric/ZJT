# develop_228 分支测试覆盖清单

> 适用分支：`develop_228`（基准 `master`）
> 文档定位：基于本分支代码改动与暂存区状态，整理**单元测试 / 前端测试 / 端到端测试**需要覆盖的用例清单。
> 配套设计文档：
> - [`docs/script/script_parser_incremental_split_design.md`](../script/script_parser_incremental_split_design.md)（核心：剧本分段拆分与断点续传）
> - [`docs/storyboard/storyboard_design.md`](./storyboard_design.md)（故事板整体架构）
>
> 本文档只列**需要测什么**（用例清单 + 输入要点 + 期望 + mock 策略）。
>
> ✅ **测试已落地**（2026-07-14）：本清单中绝大多数用例已实现并通过。新增测试文件见文末
> [附录 B：已实现测试文件清单](#附录-b已实现测试文件清单)，运行方式见各章末尾。

---

## 0. 莫开始前：先确认前置条件

> ⚠️ 本分支的多个核心新文件当前在 `git status` 中显示为 **untracked（未 `git add`）**，仅 `no_115` 迁移脚本与 `test_script_split_migration.py` 是 staged。测试落地前**必须先确认**以下文件已纳入版本控制，否则 `import` 会失败：

| 类别 | 文件 |
| --- | --- |
| 迁移脚本 | `alembic/versions/no_114_20260713_scene_audio_embedded.py`、`alembic/versions/no_116_20260713_asset_media_mapping_id.py` |
| API | `api/script_split.py` |
| LLM | `llm/script_segment_planner.py`、`llm/script_split_qc_agent.py` |
| 服务编排 | `services/script_split_engine.py`、`services/script_split_planner.py`、`services/script_split_registry.py`、`services/script_split_strategy.py` |
| 任务 | `task/script_split_task.py` |
| 模型 | `model/script_split_task.py`、`model/script_split_segment.py` |

迁移链依赖（revision / down_revision）：
- `no_114` revision=`20260713_scene_audio_embed`，down_revision=`20260707_scene_diff_act`
- `no_115` revision=`20260714_script_split`，down_revision=`20260713_scene_audio_embed`（即 no_114）
- `no_116` revision=`20260713_asset_media_map`，down_revision=`20260714_script_split`（即 no_115）

链序：`… → 20260707_scene_diff_act → no_114 → no_115 → no_116(head)`。若 `no_114` / `no_116` 未提交，`no_115` 的 down_revision 找不到上游、head 不含 `no_116`，`alembic upgrade head` 会断链。

---

## 1. 测试体系总览

项目存在**四套相互独立的测试体系**：

| 体系 | 目录 | 框架 | 运行方式 | CI 是否运行 | 本次相关 |
| --- | --- | --- | --- | --- | --- |
| Python 单元/集成 | `tests/` | pytest（DB 测试基类继承 `unittest.TestCase`） | `python3 scripts/testing/run_unit_tests.py` | ✅ 部分（见 §1.2 盲区） | `tests/storyboard/`、`tests/llm/`、`tests/services/` |
| JS 纯函数测试 | `web/tests/*.test.js` | Vitest（jsdom） | `npm run test:ci` | ✅ | storyboard 拆分进度 / 会话状态 / 质检徽章 |
| Node 静态回归脚本 | `tests/js/*.js` | Node 原生 `assert` + `fs.readFileSync` | 手动 `node tests/js/test_xxx.js` | ❌ | `test_storyboard_candidate_asset_urls.js`、`test_storyboard_timeline_card_static.js` |
| E2E 端到端 | `auto_test/e2e/` | pytest + Playwright | 本地手动 `pytest auto_test/e2e` | ❌ | storyboard 编辑器 / 拆分全流程 |

### 1.1 Python 测试的三种 mock 风格

写用例时按目标层级选用：

1. **`monkeypatch` + 手写 Fake 类**（storyboard 服务测试主流）：构造 `FakeSceneModel` / `FakeStoryboardModel` 等 `@staticmethod` 桩类，被测服务通过依赖注入接收。参考 `tests/storyboard/test_storyboard_agent_cli_service.py` 的 `patched_storyboard_cli` fixture。
2. **`unittest.mock.patch` + `MagicMock`**：驱动集成测试 Mock 第三方 HTTP。参考 `tests/driver_integration/`、`tests/drivers/`。
3. **`DatabaseTestCase` 事务隔离**：连真实测试库（库名强制以 `_test`/`_unittest` 结尾），`setUp` 开事务、`tearDown` 回滚。参考 `tests/base/base_db_test.py`。CRUD / 模型层测试走这条。

### 1.2 现有 CI 覆盖盲区（重要）

> 🔴 本次新增/修改的 storyboard 测试**当前不会被 CI 执行**，文档第 5 章给出补齐建议。

- CI 的 `unit_tests` job 用 `scripts/testing/test_discovery.py` 的 `CATEGORY_PATTERNS` 发现测试，该字典**只包含**：`crud, cdn, utils, config, drivers, driver_integration, auth, reference_images, stats, llm, agents, services, script_writer_core, enterprise, model, task, db_connection`。
- **缺失分类**：`storyboard`、`api`、`frontend`、`script`、`scripts`。因此：
  - 本次新增的 `tests/storyboard/test_script_split_migration.py`
  - 修改的 `tests/storyboard/test_storyboard_agent_cli_service.py`、`test_storyboard_agent_command_service.py`、`test_storyboard_agent_image_chat.py`
  - 全部 `tests/js/*.js`（不在 `vitest.config.js` 的 `include`，也不在任何 npm script）
  
  **均不在 CI 自动执行范围内**，属"本地回归脚本"。

---

## 2. 单元测试用例清单（Python）

每条用例格式：**用例名** ｜ 输入要点 → 期望 ｜ mock 策略。

### 2.1 数据库迁移与模型层（`model/script_split_*.py` + 迁移脚本）

| # | 用例 | 输入要点 | 期望 | mock 策略 |
| --- | --- | --- | --- | --- |
| 2.1.1 | 迁移链完整可升级 | `alembic upgrade head`（含 no_114→no_115→no_116） | 全部成功，无断链 | `DatabaseTestCase`，真实测试库 |
| 2.1.2 | 迁移幂等建表守卫 | 对已存在表/列/索引重复跑 no_115 | `_table_exists`/`_column_exists`/`_index_exists` 短路，不报错 | 复用已有 `tests/storyboard/test_script_split_migration.py` 的 `_RecordingConnection` 模式，二次执行 |
| 2.1.3 | 迁移 SQL 子句闭合 | no_115 中 `script_split_task_id` / `source_shot_key` 的 `COMMENT ... AFTER` | `COMMENT` 在 `AFTER` 子句之前正确闭合，无语法错误 | 已有 `test_script_split_migration.py` 覆盖，正则断言 |
| 2.1.4 | `script_split_task` 表结构 | 建表后查 information_schema | 含 `active_key`（UNIQUE）、`status`/`phase`/`progress`、`segment_plan_json`、`current_segment_index`/`total_segment_count`/`completed_segment_count`、`accepted_registry_json`、`continuity_state_json`、`final_result_json`、`auth_token`、`cancel_requested`、`worker_id`/`lease_until` | `DatabaseTestCase` |
| 2.1.5 | `script_split_segment` 表结构 | 建表后查 | 含 `task_id`（FK CASCADE）、`segment_index`/`segment_id`（双 UNIQUE）、`source_block_ids`/`source_content`/`source_sha256`、`status`、`attempt_count`、`raw_response`、`parsed_result_json`、`validation_errors`、`continuity_in_json`/`continuity_out_json` | `DatabaseTestCase` |
| 2.1.6 | `storyboard_scene` 新增字段与唯一键 | 迁移后查 | 含 `script_split_task_id`、`source_shot_key`，且 `uk_storyboard_scene_split_source(task_id, source_shot_key)` 存在 | `DatabaseTestCase` |
| 2.1.7 | `create_or_get_active` 新建 vs 命中 | 同一 `active_key` 首次/二次提交 | 首次 `is_new=True`；二次 `INSERT IGNORE` 后 rowcount 区分，返回同 task_id | `DatabaseTestCase`，注意双连接陷阱（用 Model 层方法建依赖） |
| 2.1.8 | `update_status` 终态释放 | 把 status 置为 `completed`/`failed`/`cancelled` | `active_key` 置 NULL、`worker_id`/`lease_until` 释放 | `DatabaseTestCase` |
| 2.1.9 | `claim_next_task` 租约抢占 | 多条 queued 任务、`lease_until IS NULL` | 事务 + `FOR UPDATE`，仅一条被认领、写 `worker_id`/`lease_until` | `DatabaseTestCase`，注意并发场景用单线程模拟 `lease_until` 判定 |
| 2.1.10 | `get_all` / `get_completed` 必须 `fetch_all=True` | 已有若干 segment 检查点 | 显式 `fetch_all=True` 时返回真实列表；不传时 `execute_query()` 默认不抓取 → 返回空列表（**回归保护，防 `invalid_segment_checkpoint_state` 误报**） | `DatabaseTestCase`；这是设计文档强调的高危点 |
| 2.1.11 | `to_public_status` 不泄露 token | 任一任务记录 | 返回 dict 中**不含** `auth_token`、`final_result_json`（大字段走 result 端点） | 纯函数，直接调 |
| 2.1.12 | `reset_retry_budget` 行为 | 一个 failed 段（含候选 JSON） | `_call_failure_count` 与 `_qc_round` 归零，**保留** `parsed_result_json`（候选 JSON）作为修复上下文 | `DatabaseTestCase` |

### 2.2 剧本分段规划（`services/script_split_planner.py` / `registry.py` / `strategy.py`）

| # | 用例 | 输入要点 | 期望 | mock 策略 |
| --- | --- | --- | --- | --- |
| 2.2.1 | `anchorize_script` 稳定锚点 | 同一剧本文本两次调用 | 生成的 block_id 序列完全一致（确定性） | 纯函数 |
| 2.2.2 | `validate_segment_plan` 覆盖性 | plan 的 block 并集 ≠ 原文全部 block | 报缺失 block 错误 | 纯函数，构造缺 block 的 plan |
| 2.2.3 | `validate_segment_plan` 顺序/连续性 | plan 内 block 出现两次或跨段乱序 | 报重复/乱序错误 | 纯函数 |
| 2.2.4 | `plan_to_segments` 切分 | 合法 plan | 输出 segment 列表，每段 `source_content` ≤ `SEGMENT_MAX_SOURCE_CHARS=1500` | 纯函数 |
| 2.2.5 | `AcceptedRegistry` 实体 ID 复用 | 段间出现同名角色/场景 | 复用首次分配的全局 ID，不重复分配 | 纯函数，跨段喂入 |
| 2.2.6 | `validate_segment_entities` ID 策略 | 段内引用未注册 ID | 报未注册错误 | 纯函数 |
| 2.2.7 | `validate_segment_spatial_references` 逐路径 | shot 引用场景地点路径不存在 | 逐路径报错，定位到具体 shot/location | 纯函数 |
| 2.2.8 | `renumber_global` 镜号重排 | 多段合并后的 shots | 镜号/组号/总时长全局连续重排 | 纯函数 |
| 2.2.9 | `StandardScriptSplitStrategy` 串行 | 社区版默认 | 按 segment_index 顺序串行返回 | 纯函数 |
| 2.2.10 | `get_script_split_strategy("quality")` 社区版抛错 | 社区版调用 quality | 抛 `StoryboardEnterpriseFeatureRequired` | monkeypatch 让 enterprise 包延迟导入失败 |

### 2.3 `llm/script_parser.py` 改动

| # | 用例 | 输入要点 | 期望 | mock 策略 |
| --- | --- | --- | --- | --- |
| 2.3.1 | `strict_json=True` 截断必重试 | 模型返回截断 JSON | **不**走末尾补括号修复，直接判定失败触发重试 | mock LLM client 返回截断串 |
| 2.3.2 | `strict_json=False` 补全后继续后处理 | 模型返回可补全的截断 JSON | 补全成功**不再提前 return**，继续走完整后处理（renumber 等） | mock LLM client |
| 2.3.3 | `segment_context` 约束当前段 | 传入 `segment_id/index/total` + `accepted_registry` | 模型 prompt 含段约束，只为当前段生成分镜、复用全局 ID | mock LLM client，断言 prompt 文本 |
| 2.3.4 | `previous_parsed_result` + `qc_feedback` 注入 | 传入上一轮 JSON + QcReport | prompt 含 `qc_retry_block` 重拆要求 | mock LLM client，断言 prompt |
| 2.3.5 | `presentation` 字段 digital_human | 单说话角色剧本 | 模型返回 `presentation=digital_human` | mock LLM client |
| 2.3.6 | `presentation` 字段强制 video | dialogue 中 ≥2 说话角色 | 系统 prompt 第 19 条规则要求 `presentation=video` | 断言 prompt 规则文本 |
| 2.3.7 | `validate_parsed_script` 校验协议 | 传入 `shot_groups[].shots[]` 结构 | 正确校验嵌套结构（修正了原来错误校验扁平 `shots` 的 bug） | 纯函数 |
| 2.3.8 | `_save_log_file_async` 异步落盘 | 触发日志写入 | 用 `asyncio.to_thread`，不阻塞事件循环 | mock `asyncio.to_thread`，断言被调 |

### 2.4 LLM 客户端（`llm/base_llm_client.py` / `openai_base_client.py` / `gemini_client.py` / `ollama_client.py` / `llm_client_factory.py`）

| # | 用例 | 输入要点 | 期望 | mock 策略 |
| --- | --- | --- | --- | --- |
| 2.4.1 | `normalize_finish_reason` Gemini | `MAX_TOKENS` | 归一化为 `length` | 纯函数 |
| 2.4.2 | `normalize_finish_reason` OpenAI/Ollama | `length` / `stop` | 小写原样返回 | 纯函数 |
| 2.4.3 | `is_truncated` 属性 | `finish_reason="length"` / `"stop"` | length → True；stop → False | 纯函数 |
| 2.4.4 | OpenAI client HTTP 超时 | 构造 client | `_build_openai_client` 设 `timeout=LLM_HTTP_TIMEOUT_SECONDS` | mock openai client 构造，断言 timeout 参数 |
| 2.4.5 | `call_api` 透传 finish_reason | OpenAI 响应 | `Choice.finish_reason` 透传到返回的 `Choice` | mock HTTP 响应 |
| 2.4.6 | `get_llm_client` model 为 dict 拍平 | 传入 `{model, model_id, vendor_id}` | 拍平为字符串模型名，不触发 Gemini URL 404 | 纯函数 |

### 2.5 任务编排引擎 engine（`services/script_split_engine.py`）— 重点

| # | 用例 | 输入要点 | 期望 | mock 策略 |
| --- | --- | --- | --- | --- |
| 2.5.1 | `step_plan` 成功 | task 处于 planning | 调 `plan_segments`，成功后 `replace_all` 写全部 segment，转 generating | mock `plan_segments` 返回合法 plan |
| 2.5.2 | `step_plan` 已有计划跳过 | task 已有 segment_plan_json | **不**重复调 LLM，直接转 generating（断点续传） | mock `plan_segments`，断言未被调 |
| 2.5.3 | `step_plan` 重试上界 | 连续 `PLAN_MAX_RETRIES=3` 次失败 | 抛 `TaskPaused`，task 进 paused | mock `plan_segments` 抛错 3 次 |
| 2.5.4 | `step_generate_segment` 一 tick 一次 LLM | 一个未完成段 | 单次 tick 仅调一次 `parse_script_to_shots`，通过后 commit 到 registry + 保存检查点 + completed+1 + 进度落在 10%~84% | mock `parse_script_to_shots` |
| 2.5.5 | `step_generate_segment` LLM 超时 | 单次调用超过 `LLM_CALL_TIMEOUT_SECONDS=480` | 抛超时，`_call_failure_count` +1，不进 failed | mock `parse_script_to_shots` sleep |
| 2.5.6 | 段级 QC 失败计数独立 | QC 失败 | `_qc_round` +1，与 `_call_failure_count` 独立预算；达上限进 paused | mock QC 返回 issue |
| 2.5.7 | `step_merge` 合并 | 全段 completed | 合并 + 全局资产清理 + 空间修复 + renumber + 存 `final_result_json`，转 publishing | mock registry/renumber |
| 2.5.8 | `step_publish` storyboard 幂等 | source_type=storyboard、无已发布分镜 | `count_scenes_by_split_task`=0 → `build_storyboard_scenes_from_parsed_script` → `create_scenes(script_split_task_id=task.id)`，写 `source_shot_key` | mock model 层 |
| 2.5.9 | `step_publish` 重复发布幂等 | 已有同 `script_split_task_id` 的 scenes | 不重复插入，直接 completed | mock `count_scenes_by_split_task`>0 |
| 2.5.10 | `step_publish` 非 storyboard | source_type=video_workflow/cli | 直接 completed，不调 create_scenes | mock |
| 2.5.11 | `step_publish` 冲突 | 存在手工分镜 | 报 `publish_conflict` | mock 已有非拆分来源 scenes |
| 2.5.12 | 异常映射 terminal_codes | `EngineError(code=invalid_segment_checkpoint_state/invalid_task_state/empty_script)` | 进 **failed** | 纯逻辑 |
| 2.5.13 | 异常映射非 terminal | `EngineError` 其他 code | 进 **paused**（保留检查点） | 纯逻辑 |
| 2.5.14 | `_step_generate_parallel_batch` quality 并发 | quality 模式 | 一批最多 `QUALITY_SEGMENT_PARALLELISM=3` 段并发生成 | mock `parse_script_to_shots`，断言并发数 |

### 2.6 worker（`task/script_split_task.py`）

| # | 用例 | 输入要点 | 期望 | mock 策略 |
| --- | --- | --- | --- | --- |
| 2.6.1 | 单 tick 正常推进 | queued/planning/generating/publishing 各一 | `claim_next_task` → `asyncio.wait_for(_advance_one_step, WORKER_STEP_TIMEOUT_SECONDS=360)` → `release_lease` | mock engine step 方法 |
| 2.6.2 | watchdog 超时进 paused | 单步超过 360s | 进 **paused 保留检查点**（不进 failed） | mock `_advance_one_step` sleep > timeout |
| 2.6.3 | `CancelledByUser` 映射 | engine 抛 `CancelledByUser` | task 进 cancelled | mock engine 抛异常 |
| 2.6.4 | `WaitingAuth` 映射 | engine 抛 `WaitingAuth` | task 进 waiting_auth | mock engine 抛异常 |
| 2.6.5 | `TaskPaused` 映射 | engine 抛 `TaskPaused` | task 进 paused | mock engine 抛异常 |
| 2.6.6 | 租约续期/释放 | tick 结束 | `release_lease` 被调（或异常时也释放） | mock model 层 |
| 2.6.7 | 协作式取消 | task `cancel_requested=True` 且当前有 LLM 调用 | 当前调用结束后丢弃响应，进 cancelled | mock `is_cancel_requested` 返回 True |
| 2.6.8 | 无任务时空转 | 无 queued 任务 | 不报错，快速返回 | mock `claim_next_task` 返回 None |

### 2.7 API 端点（`api/script_split.py` / `server.py` / `api/storyboard.py`）

| # | 用例 | 输入要点 | 期望 | mock 策略 |
| --- | --- | --- | --- | --- |
| 2.7.1 | `POST /api/parse-script` 返回 202 | 合法剧本 + 算力充足 | 返回 **202** + `{task_id, status_url}`，**不** `await parse_script_to_shots()` | monkeypatch `create_split_task` |
| 2.7.2 | `POST /api/storyboard/{id}/generate-from-script` 返回 202 | 空故事板 | 返回 **202** + `{task_id, status_url}`，删除了原同步 QC/parse/资产化内联逻辑 | monkeypatch |
| 2.7.3 | `compute_active_key` 幂等键 | 同 user+source+sha256+config | 相同输入产生相同 key | 纯函数 |
| 2.7.4 | `create_split_task` 命中 paused 自动恢复 | 同 active_key 已有 paused 任务 | 返回原 task_id，状态恢复为 queued/generating | monkeypatch model `get_active_by_key` |
| 2.7.5 | `create_split_task` 命中 waiting_auth 自动恢复 | 同 active_key 已有 waiting_auth 任务 | 用当前 token 刷新，恢复 | monkeypatch |
| 2.7.6 | `create_split_task` 命中执行中任务不重置 | 同 active_key 已有 generating 任务 | 返回原 task_id，**不**重置状态/进度 | monkeypatch |
| 2.7.7 | `_normalize_request_config` model dict 拍平 | `selectedScriptSplitLlmModel` 为 dict | 拍平为字符串，防 Gemini 404 | 纯函数 |
| 2.7.8 | `sequence_mode=quality` 校验 | 社区版传 quality | 报错（quality 仅商业版） | monkeypatch enterprise 检测 |
| 2.7.9 | `GET /tasks/{id}` 权限校验 | `X-User-Id` ≠ task.user_id | 返回 403 | monkeypatch model |
| 2.7.10 | `GET /tasks/{id}/result` 状态校验 | task 非 completed | 返回 **409** | monkeypatch model 返回 paused |
| 2.7.11 | `GET /active-task` 刷新恢复 | source_type+source_id+source_node_key | 返回活跃任务（若有） | monkeypatch |
| 2.7.12 | `POST /resume` 三路径 | task 处于 paused（publishing/generating/queued 不同检查点） | 按检查点决定恢复目标，重置当前段重试周期计数 | monkeypatch |
| 2.7.13 | `POST /cancel` 协作式取消 | 任一非终态 task | 置 `cancel_requested=True`，不强杀线程 | monkeypatch |
| 2.7.14 | 新增端点存在性 | `/auto-generate-missing-videos`、`/scene/{id}/video-type`、`/export-job/{id}` | 路由注册成功（源码断言） | 静态：读 `api/storyboard.py` 断言装饰器 |

### 2.8 CLI 服务（`services/storyboard_agent_cli_service.py` / `storyboard_agent_command_service.py`）

| # | 用例 | 输入要点 | 期望 | mock 策略 |
| --- | --- | --- | --- | --- |
| 2.8.1 | `split_from_script` 异步不阻塞 | 合法 storyboard_id | 立即返回 `{task_id, status_url, status:"queued"}`，**不**同步阻塞数分钟 | monkeypatch `create_split_task`；已有 `test_storyboard_agent_cli_service.py` 覆盖 |
| 2.8.2 | `split_from_script` 前置校验 | storyboard 不存在 / 已有分镜 / script_id 无效 / 内容空 | 分别报 `not_found` / `scenes_exist` / `invalid_script` / `empty_script` | monkeypatch |
| 2.8.3 | `_resolve_split_model_context` 解包 dict | `config_json.selectedScriptSplitLlmModel={model, model_id, vendor_id}` | 返回三元组，不把 dict repr 当模型名 | 纯函数 |
| 2.8.4 | `auto-generate-missing-videos` 命令分发 | agent 命令 | 注册并分发到 `auto_generate_missing_videos()` | 已有 `test_storyboard_agent_command_service.py` 模式 |
| 2.8.5 | `update-scene` 透传 audio_embedded | 命令含 audio_embedded | 透传到 model 层 | monkeypatch |

### 2.9 配套功能（列出要点）

> 这些是本批次同提交但与拆分核心相对独立的功能，按需补测。

| # | 用例 | 要点 |
| --- | --- | --- |
| 2.9.1 | 数字人双模型路由 | `WAN_MAX_SPEECH_DURATION_SECONDS=1.0` 阈值：≤1s 走 Wan2.2，>1s 走 LTX2.3（`StoryboardDigitalHumanConstants`） |
| 2.9.2 | `auto_generate_missing_videos` 批次编排 | `_plan_video_batch_items` / `_process_one_video_batch_job` / `_summarize_batch_items`，复用 image batch 编排表 asset_type=video |
| 2.9.3 | 故事板导出 | ffmpeg 导出 + 字幕烧录（`StoryboardExportConstants` / `StoryboardSubtitleConstants`），导出任务查询 `/export-job/{id}` |
| 2.9.4 | `media_file_mapping` 实体类型 | 新增 `STORYBOARD_SCENE_ASSET=6`，CRUD 覆盖（走 `tests/crud/`） |
| 2.9.5 | `audio_embedded` 字段透传 | `storyboard_scene.audio_embedded` 默认 1（数字人），`add_scene`/`update_scene` 透传 |
| 2.9.6 | `digital_human_runninghub_v1_driver` 改动 | 驱动单元/集成测试（`tests/drivers/`、`tests/driver_integration/`），mock 第三方 HTTP |
| 2.9.7 | `config/constant.py` 常量完整性 | `ScriptSplitConstants` / `ScriptSplitQcConstants` 关键值（重试上界、超时层级 HTTP<LLM call<worker step<lease、轮询间隔）存在且符合层级关系 |
| 2.9.8 | scheduler 注册 | `task/scheduler.py` 含 `process_script_split_tasks` job（IntervalTrigger `SCHEDULER_INTERVAL_SECONDS=5`，`max_instances=1`，`coalesce=True`）—源码断言 |

---

## 3. 前端测试用例清单（JS）

### 3.1 Vitest 纯函数测试（`web/tests/*.test.js`，CI 运行）

| # | 用例 | 输入要点 | 期望 | 备注 |
| --- | --- | --- | --- | --- |
| 3.1.1 | `applyGenerateProgressStatus` 进度归一化 | 46.4 / 180 / 空 message | 46.4→46（取整）；180→100（封顶）；空 message→兜底文案 | 已有 `storyboard_script_split_progress.test.js` 部分覆盖，补全边界 |
| 3.1.2 | `pollScriptSplitTask` 终态停止 | status=completed/failed/cancelled | 停止轮询，清理 timer | mock fetch |
| 3.1.3 | `pollScriptSplitTask` completed 取 result | status=completed | 调 `/result` 端点取大 JSON | mock fetch |
| 3.1.4 | `pollScriptSplitTask` 网络错误退避 | fetch reject | 指数退避，不立即重试 | mock fetch 连续 reject |
| 3.1.5 | `pollScriptSplitTask` timer 去重 | 重复启动同一 taskId | 不创建多个 timer | mock |
| 3.1.6 | `startSceneAgentRun`/`finishSceneAgentRun` 按分镜隔离 | 同一 storyboard 多分镜并发 | session 按分镜隔离，不串台 | 已有 `storyboard_agent_session_state.test.js` 范式 |
| 3.1.7 | stale taskId 不误杀新任务 | 旧 taskId 完成回调到达时已切新任务 | 不清空新任务的 running 标记 | 同上 |
| 3.1.8 | `initStateFromUrl` 参数规范化 | URL 含 userId/authToken | 规范化到 state，token **不**入 URL（从 localStorage 读） | 纯函数 |
| 3.1.9 | `syncVideoMediaFromScene`/`buildVideoSlotUrls` | scene 含多视频槽位 | 正确同步媒体栈 | 纯函数 |
| 3.1.10 | 自动补全 session 恢复 | sessionStorage 有批次状态 | 页面刷新后恢复批次 | mock sessionStorage |
| 3.1.11 | 自动补全 409 接管 | 后端返回 409 active_batch | 接管已有批次而非新建 | mock fetch 409 |
| 3.1.12 | playback 状态机 idle→playing→paused→ended | toggle-play 序列 | 状态正确切换 | 纯函数 |
| 3.1.13 | playback sceneSpan 截断 | 超长分镜时长 | 按 sceneSpan 截断定位播放头 | 纯函数 |
| 3.1.14 | 字号档位 -2…+8 | agent-chat-font-up/down | 档位循环/封顶 | 纯函数 |
| 3.1.15 | `@`提及解析 | 输入含 `@角色名` | 解析为 mention 对象 | 纯函数 |

### 3.2 源码字符串断言测试（防回归，Node `assert` 或 Vitest）

> 参考 `tests/js/test_storyboard_*.js` 与 `web/tests/storyboard_*_badge*.test.js` 的模式：`fs.readFileSync` 读源码 + 正则断言。

| # | 用例 | 断言目标 |
| --- | --- | --- |
| 3.2.1 | 进度条 ARIA | `render.js` 含 `role="progressbar"` + `aria-valuenow="${progressPercent}"` + `generate-progress-percent` 类名 |
| 3.2.2 | 质检「限时免费」徽章 | `render.js` 中「质检最大循环次数」标题后紧跟「限时免费」徽章（已有 `storyboard_script_split_qc_free_badge.test.js`） |
| 3.2.3 | 时间轴徽章用 scene.title | `render.js` 用 `scene.title` 而非 `scene.id`（已有 `storyboard_timeline_badge_title.test.js`） |
| 3.2.4 | `polling.js` 导出 | 含 `pollScriptSplitTask` 函数签名 |
| 3.2.5 | `events.js` 关键 data-action | 含 `generate-from-script-confirm`、`generate-from-script-cancel`、`toggle-enable-script-split-qc`、`close-generate-progress`、`retry-generate-progress` |
| 3.2.6 | `storyboard.css` 关键规则 | 含 `.generate-progress-track`、进度卡片样式 |
| 3.2.7 | `storyboard.html` 骨架 | 含 `<div id="app">` 加载态壳 |
| 3.2.8 | `api.js` 拆分接口封装 | 含 `getScriptSplitTaskStatus` / `getScriptSplitTaskResult` / `requestSplit` / `applyTaskStatus` |
| 3.2.9 | `script_split_task.js` 节点持久化 | 含 splitTask 状态保存/恢复逻辑 |
| 3.2.10 | 候选资产 URL | `render.js`/`events.js` 候选资产 URL 规范化（已有 `test_storyboard_candidate_asset_urls.js`） |
| 3.2.11 | 时间轴卡片静态结构 | 时间轴卡片 DOM 结构（已有 `test_storyboard_timeline_card_static.js`） |
| 3.2.12 | 模型配置 4 tab | `render.js` 含 dialogue/image/video/script-split 四个 tab |

### 3.3 可测但当前未覆盖的交互点（按优先级补）

从 `events.js` 70+ `data-action` 中选出最值得补纯函数/状态机测试的子集：

- **P0**：`generate-from-script-confirm`（提交异步任务）、`close-generate-progress`/`retry-generate-progress`（进度弹框）、刷新恢复活跃任务
- **P1**：`auto-complete-missing-frames`/`auto-complete-missing-videos`（批次状态机 + session 恢复）、`request-video-type-switch`/`confirm-video-type-switch`（视频类型切换）、`reorderScene`（拖拽排序 sortOrder 二分）
- **P2**：`toggle-play`（播放）、`send-ai`（AI 对话）、`export-full`/`export-scenes`（导出）、字号档位、`@`提及

---

## 4. 端到端测试用例清单（Playwright，`auto_test/e2e/`）

> 框架：pytest + Playwright，独立 `pytest.ini` / `conftest.py` / `requirements_e2e.txt`。Mock 方式：`mock_mode` fixture 开后端 `test_mode.enabled` 挡板（媒体走 mock URL、重置算力），`page.route()` 拦截网络请求 fulfill 假响应。

### 4.1 剧本拆分全流程

| # | 用例 | 步骤要点 |
| --- | --- |
| 4.1.1 | 空故事板拆分完整链路 | 进入空故事板 → 配置弹框（max_group_duration/force_medium_shot/no_bg_music/split_multi_dialogue + 质检开关）→ POST → 202 → 四阶段进度轮询（planning 0-10% / generating 10-85% / merging 85-95% / publishing 95-100%）→ completed → 自动重载分镜 → 触发自动补全首帧 |
| 4.1.2 | 真实进度非伪造 | 断言进度条数值随 completed_segments/total 变化，**非**定时器线性递增 |
| 4.1.3 | 进度弹框 ARIA | 断言 `role="progressbar"` + `aria-valuenow` 存在 |
| 4.1.4 | 发布后分镜渲染 | completed 后分镜列表非空，镜号连续 |
| 4.1.5 | 质检开关生效 | 开启 enable_qc + max_rounds=2 → 段级 QC 触发 |
| 4.1.6 | 视频工作流拆分节点 | 剧本节点点「拆分幕」→ 任务进度 → 完成 |

### 4.2 断点续传与恢复

| # | 用例 | 步骤要点 |
| --- | --- | --- |
| 4.2.1 | 页面刷新恢复 | 拆分进行中刷新页面 → `GET /active-task` 查到活跃任务 → 恢复轮询（**不**重新弹配置框） |
| 4.2.2 | 服务重启从检查点恢复 | 模拟 worker 中断重启 → 从第一个未完成段继续，已完成段不重做 |
| 4.2.3 | paused 后点继续 | 段失败达上限进 paused → 前端显示「继续」按钮 → 点继续 → resume → 恢复 |
| 4.2.4 | waiting_auth resume | token 失效进 waiting_auth → 用当前登录 token 调 resume → 恢复 |
| 4.2.5 | 协作式取消 | 进行中点取消 → 当前 LLM 调用结束后进 cancelled → 进度停止 |

### 4.3 故事板编辑器关键交互

| # | 用例 | 步骤要点 |
| --- | --- | --- |
| 4.3.1 | 分镜 CRUD | 新增/编辑/复制/删除/插入分镜 |
| 4.3.2 | 时间轴/grid 切换与播放 | 切换视图、toggle-play、键盘左右切镜、页面隐藏停播 |
| 4.3.3 | AI 助手对话生图 | send-ai 发消息、@提及、候选图片选择 |
| 4.3.4 | 自动补全首帧 | 触发批次 → 状态角标（待生成/排队中/生成中/生成失败）→ 完成 |
| 4.3.5 | 自动补全视频 | 同上，asset_type=video |
| 4.3.6 | 视频类型切换 | 普通视频 ↔ 对口型 |
| 4.3.7 | 导出 | export-full/export-scenes + 字幕烧录选项 |
| 4.3.8 | 模型配置 | 4 tab（dialogue/image/video/script-split）切换保存 |

### 4.4 视频工作流拆分节点

| # | 用例 | 步骤要点 |
| --- | --- | --- |
| 4.4.1 | 拆分幕按钮 | 点「拆分幕」→ 任务提交 → 进度 |
| 4.4.2 | 拆分幕+宫格按钮 | 点「拆分幕+宫格生图」→ 拆分完成后触发宫格 |
| 4.4.3 | 节点状态持久化 | 刷新后节点恢复 splitTask 状态与轮询 |

---

## 5. CI 集成建议与覆盖盲区（重点）

### 5.1 现状

| 盲区 | 根因 | 影响 |
| --- | --- | --- |
| `tests/storyboard/*.py` 不被执行 | `scripts/testing/test_discovery.py` 的 `CATEGORY_PATTERNS` 缺 `storyboard` 分类 | 本次核心的 `test_script_split_migration.py` + 3 个修改的 storyboard 测试 **不跑** |
| `tests/api/*.py` 不被执行 | 同上缺 `api` 分类 | API 端点测试不跑 |
| `tests/frontend/*.py` 不被执行 | 同上缺 `frontend` 分类 | HTML 源码断言不跑 |
| `tests/js/*.js` 不被执行 | 不在 `vitest.config.js` 的 `include`（仅 `web/**/*.test.js`），也不在任何 npm script | 38 个静态回归脚本全靠手动 |
| 测试"静默消失"不告警 | `npm run test:ci` 带了 `--passWithNoTests`；`run_unit_tests.py` 对缺失分类也不报错 | 即使本该跑的用例因分类缺失/路径不匹配而一个都没执行，CI 仍绿，**无任何信号**——这是最隐蔽的危害 |
| 迁移链断链风险 | `no_114`/`no_116` 当前 untracked | 若未提交，`alembic upgrade head` 失败 |
| E2E 无 CI | `auto_test/e2e/` 独立项目 | 全靠本地手动 |

### 5.2 建议（不在本次执行，仅记录）

1. **`test_discovery.py` 增分类**（低风险）：在 `CATEGORY_PATTERNS` 增加 `storyboard`、`api`。storyboard 测试不连库（用 Fake Model），加入 CI 风险低。
2. **`tests/js/*.js` 加聚合 runner**：在 `package.json` 加 `"test:static": "node scripts/run_static_js_tests.js"`，遍历 `tests/js/*.js` 逐个 `node` 执行，接入 CI `frontend_tests` job。
3. **E2E 维持本地**：记录在 `auto_test/e2e/README.md`，按需手动跑（依赖真实服务 + 浏览器）。
4. **迁移链回归入 CI**：把 `test_script_split_migration.py` 纳入（依赖建议 1），防止 untracked 迁移导致断链。

### 5.3 优先级排序

| 优先级 | 范围 | 理由 |
| --- | --- | --- |
| **P0** | 迁移链完整性（2.1.1-2.1.6）、幂等提交（2.7.3-2.7.6）、断点续传（2.1.10、2.5.2、4.2.*）、worker watchdog（2.6.2）、两个入口返回 202（2.7.1-2.7.2） | 数据安全 / 核心业务正确性 / 防止数据丢失 |
| **P1** | engine 状态机（2.5.*）、权限校验（2.7.9）、finish_reason 归一化（2.4.1-2.4.3）、strict_json（2.3.1-2.3.2）、前端轮询（3.1.2-3.1.5） | 功能正确性 / 跨供应商兼容 |
| **P2** | 配套功能（2.9.*）、前端交互（3.3.*、4.3.*）、源码断言（3.2.*） | 体验 / 防回归 |

---

## 6. 附录：测试运行速查

### 6.1 Python 单元测试

```bash
# 全量（CI 方式，需 Docker + 测试库）
python3 scripts/testing/run_unit_tests.py

# 单分类（本地，需 config_unit.yml + TEST_DB_* 环境变量）
pytest tests/storyboard/ -v
pytest tests/llm/ -v
pytest tests/services/ -v

# 单文件
pytest tests/storyboard/test_script_split_migration.py -v
```

测试库配置：`tests/base/db_test_config.py`，强制库名以 `_test`/`_unittest` 结尾（`zjt_unittest`），来自 `config_unit.yml` + 环境变量 `TEST_DB_*`。

### 6.2 前端测试

```bash
# Vitest（CI 方式）
npm run test:ci

# Vitest 单文件 / watch
npx vitest run web/tests/storyboard_script_split_progress.test.js
npx vitest

# Node 静态回归（手动）
node tests/js/test_storyboard_candidate_asset_urls.js
node tests/js/test_storyboard_timeline_card_static.js
```

### 6.3 E2E

```bash
cd auto_test/e2e
pip install -r requirements_e2e.txt
playwright install chromium
pytest -m "e2e and p0" -v
```

### 6.4 测试数据准备要点

- **Python 纯单元测试**：用 `monkeypatch` + 手写 Fake 类（`SimpleNamespace` 造数据），不连库不连 LLM。参考 `tests/storyboard/test_storyboard_agent_cli_service.py` 的 `patched_storyboard_cli` fixture。
- **Python DB 测试**：继承 `DatabaseTestCase`，事务隔离。注意双连接陷阱：`insert_fixture()`（测试连接）与 Model 层 `create()`（连接池）事务互不可见，混用时用 Model 层方法建依赖。
- **E2E**：用 `mock_mode` fixture 开后端挡板，`page.route()` 拦截第三方请求。
- **LLM Mock**：storyboard 测试完全不调真实 LLM；LLM 客户端测试 mock HTTP 层（参考 `tests/llm/`）。

---

## 附录 B：已实现测试文件清单

> 以下测试文件已落地并通过本地验证（2026-07-14）。运行命令见 §6。

### Python 单元测试（121 passed）

| 文件 | 覆盖章节 | 用例数 | 说明 |
| --- | --- | --- | --- |
| `tests/storyboard/test_script_split_planner.py` | §2.2 | 29 | anchorize/validate_segment_plan/plan_to_segments/AcceptedRegistry/validate_segment_entities/spatial_references/renumber_global/strategy 纯函数 |
| `tests/storyboard/test_script_split_llm.py` | §2.3 / §2.4 | 28 | normalize_finish_reason/is_truncated/get_llm_client dict 拍平/validate_parsed_script/presentation+strict_json 提示词断言 |
| `tests/storyboard/test_script_split_engine.py` | §2.5 | 15 | 异常类/step_plan（跳过/空剧本/取消/鉴权/重试耗尽/成功）/step_publish（非 storyboard/幂等/冲突/缺 id/无 result） |
| `tests/storyboard/test_script_split_worker.py` | §2.6 | 20 | 单 tick/watchdog 超时进 paused/异常映射（cancelled/waiting_auth/paused/terminal→failed/未知→failed）/状态机分发/_transition_to_cancelled/make_scheduler_job |
| `tests/storyboard/test_script_split_api.py` | §2.7 | 27 | compute_active_key/_normalize_request_config/_resume_target_state/GET tasks 权限+404/GET result 409/GET active-task/POST resume/POST cancel |
| `tests/storyboard/test_script_split_migration.py` | §2.1 | 2 | 迁移 SQL COMMENT/AFTER 闭合回归（分支原有） |

运行：`.venv/Scripts/python.exe -m pytest tests/storyboard/test_script_split_*.py -q`

### 前端测试（22 tests + 22 静态断言）

| 文件 | 覆盖章节 | 用例数 | 框架 | 说明 |
| --- | --- | --- | --- | --- |
| `web/tests/storyboard_split_state.test.js` | §3.1 | 14 | Vitest | applyGenerateProgressStatus 归一化/clampAgentChatFontStep/getAgentChatFontSizes/setAgentChatFontStep 持久化/media url helpers |
| `web/tests/storyboard_script_split_polling.test.js` | §3.1 | 8 | Vitest | pollScriptSplitTask 终态停止/completed 取 result/交互态 onPaused/网络错误退避/timer 去重/stop 清理 |
| `tests/js/test_storyboard_script_split_static.js` | §3.2 | 22 断言 | Node assert | data-action/轮询函数/API 封装/ARRIA 标记/CSS 规则/节点客户端存在性 |

运行：
- Vitest：`npx vitest run web/tests/storyboard_split_state.test.js web/tests/storyboard_script_split_polling.test.js`
- Node 静态：`node tests/js/test_storyboard_script_split_static.js`

### 端到端测试（11 tests，依赖真实服务器 + LLM）

| 文件 | 覆盖章节 | 用例数 | marker | 说明 |
| --- | --- | --- | --- | --- |
| `auto_test/e2e/test_script_split.py` | §4.1 / §4.2 | 11 | `script_split` | P0：404/400/权限隔离等不依赖 LLM 的 API 行为（7）；P1：提交 202/全流程轮询/active-task 恢复/协作式取消（4，依赖真实 LLM） |

配套改动：`auto_test/e2e/pytest.ini` 新增 `script_split` / `storyboard` 两个 marker（`--strict-markers` 要求）。

运行（需本地起服务 + 装 playwright）：
```bash
cd auto_test/e2e
pytest test_script_split.py -m "p0" -v          # 快速，不依赖 LLM
pytest test_script_split.py -m "p1" -v --timeout=300  # 全流程，依赖真实 LLM
```

### 未覆盖（后续可补）

- §2.1.1-2.1.10 的 DB 集成测试（迁移链、create_or_get_active、claim_next_task、fetch_all=True 回归）需连真实测试库，建议补到 `tests/storyboard/` 并在 CI `test_discovery.py` 增 `storyboard` 分类后纳入。
- §2.8 CLI 服务测试：`split_from_script` 异步化已在分支原有的 `test_storyboard_agent_cli_service.py` 覆盖，本批未重复。
- §2.9 配套功能（数字人路由/导出/CDN 映射）按需补，优先级 P2。
