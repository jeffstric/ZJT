# Storyboard 子场景 Location 资产化

## 目标

把 LLM 解析出的子场景（sub-scene）变成数据库里可复用的 `location` 资产，建立内部 `loc_xxx` → 真实 DB id 的映射，并回填到 `parsed_data`，使下游分镜写入的 `prompt_json.source.location_db_id` 能拿到真实 DB id。

这样分镜首帧生图就能依赖稳定的 `location.reference_image`，重新加载、后续编辑、批量分镜生成都更稳。

## 链路

```
剧本解析 (llm/script_parser.py)
  → sanitize 保留新子场景（location_db_id=null）
  → StoryboardLocationBootstrapService.bootstrap()
      - 拓扑排序（父先于子，parent_id 是真实外键）
      - LocationModel.create_or_update 入库
      - 名称冲突校验（同名不同 parent → 加后缀）
      - 回填 location.location_db_id 与 shot.db_location_id
  → build_storyboard_scenes_from_parsed_script
  → 分镜首帧生图（依赖 location.reference_image）
```

## Phase 1：解析清洗保留新子场景

`llm/script_parser.py` 的 `sanitize_parsed_location_references()` 原本只保留数据库已存在的场景，新场景/子场景（`location_db_id=null`）被无条件丢弃。

改为三分支：
1. **已匹配 DB**：写回真实 DB id（维持原逻辑）。
2. **未匹配且 `location_db_id=null`**：保留，携带 `parent_id`（内部 loc_xxx）、`level`、`description`、`atmosphere`、`environment_sound`、`background_music`，由 bootstrap 入库。
3. **编造假 id（非 null 但 DB 不存在）**：丢弃，防幻觉穿透。

调试字段：`parsed_data['metadata']['has_unpersisted_locations']` / `unpersisted_location_count`。

> shot.location_id 指向保留的新子场景时**不再被置空**。

## Phase 2：Bootstrap 入库与回填

**服务：** `services/storyboard_location_bootstrap_service.py` 的 `StoryboardLocationBootstrapService.bootstrap(parsed_data, world_id, user_id)`

### 拓扑排序
`parent_id` 是真实外键（`ON DELETE SET NULL`），必须先父后子。按 `level` 升序稳定排序。

### 同名行处理（防数据丢失）
**绝不走 `create_or_update`（`ON DUPLICATE KEY UPDATE` 会把 `reference_image`/`reference_images` 抹成 NULL）。** 策略：
1. 入库前先 `LocationModel.get_by_name(world_id, name)` 查同名行。
2. **存在且 `parent_id` 一致**（同名同父，重跑最常见场景）→ **直接复用 `existing.id`，不写任何字段**，保护已有参考图。
3. **存在但 `parent_id` 不一致**（同名异父）→ 名称追加 ` (子场景)` 后缀后用 `create` 新建，避免覆盖别人的 `parent_id`。
4. **不存在** → `LocationModel.create`（纯 INSERT）。
5. 并发唯一键冲突（极罕见）fallback：再查一次 `get_by_name` 复用 id。
6. 父场景缺失的孤儿子场景、父级环或新顶层场景 → 在任何数据库写入前抛结构硬错误，禁止降级创建。

> 关键区别：用 `create`（纯 INSERT）而非 `create_or_update`（upsert）。bootstrap 的职责是"补齐缺失的 location 资产"，不是"更新已有字段"。已有场景的 `reference_image` 等字段由九宫格回写或人工维护，bootstrap 不应触碰。

### 回填（关键，两处）
1. `location['location_db_id'] = <new db id>`
2. 每个 `shot['db_location_id'] = <resolved db id>`（`build_storyboard_scenes_from_parsed_script` 优先读 `shot.db_location_id`）

不回填会导致已建好 scene 的 `prompt_json.source.location_db_id` 一直是 null。

### 回填（关键，两处）
1. `location['location_db_id'] = <new db id>`
2. 每个 `shot['db_location_id'] = <resolved db id>`（`build_storyboard_scenes_from_parsed_script` 优先读 `shot.db_location_id`）

不回填会导致已建好 scene 的 `prompt_json.source.location_db_id` 一直是 null。

### 返回
```python
{
    'created_location_count': int,
    'reused_location_count': int,
    'id_map': {loc_xxx -> db_id},
    'warnings': List[str],
}
```

### 注入点
- **Web：** `api/storyboard.py` generate-from-script 端点，`build_storyboard_scenes_from_parsed_script` 之前，`asyncio.to_thread` 包装。
- **CLI：** `services/storyboard_agent_cli_service.py` `split_from_script()`，parse 之后、`_build_storyboard_scenes_from_parsed_script` 之前（CLI 整体已在 `to_thread` 中）。

### 不落库的字段
`atmosphere` / `environment_sound` / `background_music` / `level` 在 location 表无对应列，仅随 location dict 原样保留在 `parsed_data` 里，供九宫格 prompt 使用。

## 测试

`tests/services/test_storyboard_location_bootstrap_service.py` 覆盖：
- 解析保留 null 子场景（含 metadata 字段）
- 编造假 id 被丢弃
- 子场景入库正确写入 parent_id
- shot.db_location_id 回填
- 顶层已匹配场景复用
- **同名同父复用不清空 reference_image**（P1 数据丢失防护）
- 名称冲突（不同 parent）改名
- 孤儿子场景和新顶层场景硬拦截（数据库零写入）
- 拓扑排序父先于子
