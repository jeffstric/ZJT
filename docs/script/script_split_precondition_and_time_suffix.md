# 剧本拆分前置校验 + 时间后缀场景名提示词强化

> 关联：`script_split_location_prompt_fix.md`（提示词禁止假设世界资产为空）、`script_split_early_new_root_location_gate.md`（new_root_location_forbidden 门禁）

## 背景

更新提示词（禁止假设世界资产为空 + plan 注入场景列表）后，script 404（world 246）、script 341（world 252）等**仍拆分失败**，根因有二：

1. **空 world / 无图 world 的死锁**：world 252「魂穿保留记忆」`location` 表 0 条记录；LLM 必然新建顶层场景 → guard `new_root_location_forbidden` 拦截 → 任务 `paused`。提示词无法解决（guard 是代码硬门禁）。正确做法是**前置拦截**。
2. **时间后缀场景名**：world 246 LLM 产出 `现代客厅_夜晚`——给场景名加了时间后缀，违反"场景不按时间区分"。现有提示词只覆盖括号形式「（深夜版）」，未覆盖下划线形式；企业版 planner 仅 1 处提醒，社区版 script_parser 4 处。

## 改动一：前置校验（world 场景数 + 有图场景数）

**校验规则**（在创建拆分任务**之前**执行，不满足则拒绝、不创建任务）：

| 条件 | 错误码 | 提示 |
|---|---|---|
| world 下场景数 == 0 | `world_no_scene` | 当前世界没有任何场景，请先创建顶层场景 |
| world 下"有参考图的场景数" == 0 | `world_no_scene_image` | 当前世界的场景都没有参考图，请为至少一个场景补图 |

判断"有图"：`reference_image`（单图）或 `reference_images`（多图 JSON）任一非空，与 `storyboard_location_bootstrap_service._subscene_has_reference_image` 一致。**至少 1 个场景有图即放行**（不要求所有场景都有图）。

### 实现

- `model/location.py`：新增 `count_with_image_by_world(world_id) -> int`，复用 `count_by_world` 模式。
- `api/script_split.py`：
  - 新增异常类 `ScriptSplitPreconditionError(code, message)`（加入 `__all__`）。
  - 新增 `async _validate_world_scene_precondition(world_id)`：用 `asyncio.gather` + `asyncio.to_thread` 并发查两个 count（CLAUDE.md 规则 1：web 路径禁止同步 DB 阻塞）；`world_id` 缺失时跳过（cli 来源向后兼容）。
  - `create_split_task` 在 `_normalize_request_config` 之后、`compute_active_key`/`create_or_get_active` **之前**调用校验——**校验失败时不创建任务**。
- 两个调用方各自 `except ScriptSplitPreconditionError → JSONResponse(400)`（在 `except Exception → 500` 之前）：
  - `api/storyboard.py` `generate_storyboard_from_script`（`/api/storyboard/{id}/generate-from-script`）
  - `server.py` parse-script（`/api/parse-script`）

## 改动二：时间后缀场景名提示词强化（仅提示词）

- `enterprise/services/script_split_quality/planner.py`：在"同一物理地点不因时间拆成多个 location"后补"**禁止给场景 name/location_key 加任何时间或时段后缀**——下划线、连接符、括号都算（`现代客厅_夜晚`、`大堂-深夜`、`前台（深夜版）` 均违规），必须去掉后缀归并为同一场景"。
- `llm/script_parser.py`：在"禁止因时间不同复制场景"补下划线/连接符后缀同样禁止，与"匹配地点本身，忽略时间后缀"呼应。

## 边界

- 本改动只阻止"空 world / 完全无图 world"。若 world 有场景、有图，但某剧本场景与 DB 场景**命名不一致**（如剧本"现代客厅" vs DB"小明房间_现代"），仍可能命中 guard 暂停——这属于命名匹配问题，后续可考虑放宽 `location_structure_guard._unique_name_match` 的语义匹配。
- 前置校验不替代 guard；guard 仍是结构硬门禁（防 LLM 污染场景库）。前置校验只是把"明显无法拆分"的情况提前拦截，改善体验。

## 验证

- 单测：`pytest tests/api/test_script_split_resume.py enterprise/tests/services/test_script_split_quality.py -q`
  - 前置校验 4 例（world_id 缺失跳过、空 world、无图 world、有图放行）
  - 企业版 plan prompt 含"现代客厅_夜晚"禁止文案
- CI：`python scripts/lint_blocking_calls.py`（校验函数 DB 查询走 `asyncio.to_thread`）
- 端到端（开发库）：world 252（空）发拆分 → 立即 400 + `world_no_scene`；world 全无图 → 400 + `world_no_scene_image`；两入口（storyboard generate-from-script、server parse-script）均返回 400 而非 500。
