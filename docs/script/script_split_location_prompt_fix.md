# 剧本拆分提示词强化：禁止假设世界资产为空 + plan 阶段注入已有场景列表

> 关联设计：`script_split_early_new_root_location_gate.md`（`new_root_location_forbidden` 门禁）
> 关联设计：`script_parser_incremental_split_design.md`（分段拆分总设计）

## 背景与根因

开发环境（`config_dev.yml`，`edition.mode=enterprise`）下，多个剧本拆分任务（如 storyboard 24/script 404「现代客厅」、storyboard 13/script 290「林越的房间（现代）」）持续在 `new_root_location_forbidden` 错误码下 **paused（暂停，非 failed）**。

经 `logs/llm.<日期>.log` 核实（注意：初判"提示词没提供场景信息"是错误的）：

- **segment 阶段提示词**（`llm/script_parser.py`，社区版+企业版共用）**已注入完整的【数据库已有场景列表】**（含真实 ID/名称/描述）。
- **企业版 plan 阶段提示词**（`enterprise/services/script_split_quality/planner.py`）要求"复用已有场景、严禁规划新顶层场景"，**但完全没有注入已有场景列表**——因为策略接口 `build_planning_prompt(anchors, max_output_tokens)` 不接收 `db_locations`。
- LLM 的 thinking 原文暴露：明明拿到列表却自我推翻——*"世界上可能没有预先存在的资产。我们假设这是独立剧本，没有预置世界资产…所以所有 location 都是新建的顶层场景"*，进而创建 DB 不存在的顶层场景，被 `services/location_structure_guard.py` 的 `validate_segment_new_roots` 严格匹配（精确名/前后缀且唯一）拦下。

## 本次改动（提示词层面）

### 1. 企业版 plan prompt 注入已有场景列表（核心）

策略接口扩展为接收已加载的 `db_locations`（仅做字符串拼接，无同步 DB 调用，不阻塞事件循环）：

- `services/script_split_strategy.py` `StandardScriptSplitStrategy.build_planning_prompt` 增加参数 `db_locations: Optional[List[Dict]] = None`（社区版 plan 为 schema v1 纯分段，不产 location，仍返回 `None`）。
- `enterprise/services/script_split_quality/strategy.py` `QualityScriptSplitStrategy.build_planning_prompt` 透传 `db_locations`。
- `enterprise/services/script_split_quality/planner.py` `build_quality_planning_prompt(anchors, max_output_tokens, db_locations=None)`：
  - 非空时在 `entities` 规则前注入【已有场景列表】（树形缩进，格式与 `llm/script_parser.py` 的 `format_location_tree` 一致）。
  - 顶部追加"禁止假设世界资产为空"硬前提。
  - 为空（新世界确实无场景）时显式告知"允许登记新顶层场景"，避免 LLM 凭空假设资产缺失后乱建。
- `services/script_split_engine.py` `step_plan` 调用时传入第 277 行已通过 `_load_current_db_locations`（`asyncio.to_thread`）异步加载的 `db_locations`。

### 2. plan + segment 两处提示词加"禁止假设世界资产为空"硬前提

- `enterprise/services/script_split_quality/planner.py`（plan，术语用 `location_key`/`parent_location_key`）。
- `llm/script_parser.py`（segment，术语用 `location_db_id`/`parent_id`）。

文案要点：禁止声称"世界资产为空/没有预置世界资产/独立剧本无资产"；剧本中每个地点必须先在【已有场景列表】按"名称+描述语义相似"复用；列表非空时不得新建无父级顶层场景。

## 接口契约

```python
# services/script_split_strategy.py
def build_planning_prompt(
    self,
    anchors: List[Dict[str, Any]],
    max_output_tokens: int,
    db_locations: Optional[List[Dict[str, Any]]] = None,  # 新增，默认 None 向后兼容
) -> Optional[str]
```

- 社区版 `StandardScriptSplitStrategy`：忽略 `db_locations`，始终返回 `None`（使用 `llm/script_segment_planner.py` 的默认 plan prompt）。
- 企业版 `QualityScriptSplitStrategy`：将 `db_locations` 注入 plan prompt。
- `db_locations` 元素结构：`{"id", "name", "description", "children": [...]}`，来自 `LocationModel.get_tree_by_world(world_id, limit)`。

## 边界（提示词无法覆盖，列为后续）

当剧本出现 DB **确实没有**且无法复用的顶层场景（如 world 244 穿越前"林越的房间（现代）"，DB 仅有天玄宗修仙场景），即便提示词完美，LLM 仍无法复用，会被 guard 拦下。该结构性死锁需要后续在以下层面解决（**本次未做**）：

- guard 容错：`services/location_structure_guard.py` 的 `_unique_name_match` 放宽语义/别名匹配，或段级把"疑似新顶层"降级为可恢复暂停而非硬失败。
- 产品层：双世界等"DB 必然缺场景"的剧本，允许带标记创建新顶层场景并引导用户确认，而非一律暂停。

## 验证

- 单测：`pytest enterprise/tests/services/test_script_split_quality.py tests/services/test_script_split_planner.py -q`
- CI：`python scripts/lint_blocking_calls.py`（确保 prompt 构造无阻塞调用违例）
- 端到端：开发环境对 world 246/script 404、world 244/script 290 重跑拆分，观察 plan prompt 是否出现【已有场景列表】+ 硬前提，LLM thinking 不再出现"假设没有预置世界资产"。
