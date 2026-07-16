# 效果模式 Segment 空间依赖调度设计

## 1. 文档状态

- 状态：设计已确认，尚未实施
- 日期：2026-07-16
- 适用范围：企业版效果模式（`sequence_mode=quality`）的阶段二剧本分镜解析
- 相关流程：`step_plan → step_generate_segment → step_merge → step_publish`
- 相关文档：
  - `docs/script/script_parser_incremental_split_design.md`
  - `docs/storyboard/storyboard_quality_strict_act_sequence_design.md`

## 2. 背景与问题

效果模式当前采用两阶段拆分：

1. `step_plan` 由 LLM 将剧本规划为多个语义 segment，同时生成全局实体、`spatial_world` 和各段的 `continuity_in/state_changes/continuity_out`。
2. `step_generate_segment` 每批最多并发调用 3 个 `parse_script_to_shots`，生成每段的完整 `shot_groups`。

现有并发实现假设阶段一空间契约足以维持段间连续性。实际并非如此。阶段一契约当前主要描述角色的：

- `space_unit_id`
- `container_id`
- `slot_id`

而阶段二实际生成的 `spatial_layout` 还包含：

- `space_unit_refs`
- `camera_pose`
- `camera_anchor`
- `location_path`
- `containers`、`slots`
- `position_3d`
- `physical_position`
- `position_basis`
- `loose_positions`
- 镜头外角色状态
- `continuity.unchanged_slots`
- `continuity.changed_positions`
- `screen_axis_mapping`
- `screen_composition`
- `visibility`、`framing_role`、`pose`

效果模式并发子任务目前还会主动清空 `previous_tail_summary`，并把 `continuity_state` 替换为阶段一规划契约。因此，下一个 segment 无法看到上一个 segment 实际生成的机位、空间容器、角色三维位置和镜头外连续性。

这会造成以下问题：

- 同一走廊或房间中的角色左右关系发生跳变。
- 容器、槽位或空间锚点被重新发明。
- 上一段仍在空间中的镜头外角色在下一段消失。
- 下一段无法参考上一段真实机位选择新的合理机位。
- 合并阶段只能事后修复部分字段，无法可靠恢复生成时已经丢失的空间语义。

## 3. 设计目标

1. 由阶段一决定 segment 之间是否存在实际空间继承关系。
2. 没有空间依赖的 segment 继续并发，保留效果模式的性能收益。
3. 存在空间依赖的 segment 必须等待上游 segment 完成。
4. 下游调用 `parse_script_to_shots` 前，必须取得上游最后镜头实际生成的完整 `spatial_layout`。
5. 角色、道具、容器、空间锚点和物理位置保持连续。
6. 上游 `camera_pose` 只作为参考，下游允许根据剧情调整机位、景别和构图。
7. 依赖错误、循环依赖或无可运行节点必须明确失败，不能永久等待。
8. 效果模式专属判断、契约编译和校验实现必须位于 `enterprise/`。
9. 不改变 `speed`、`balanced` 模式的现有串行行为。

## 4. 非目标

- 不要求相邻 segment 使用相同相机坐标或相同景别。
- 不要求所有效果模式 segment 全部串行。
- 不把合并阶段修复作为主要连续性来源。
- 不修改后续首帧宫格严格按幕串行的既有设计。
- 不为本方案新增数据库表或字段。

## 5. 核心方案

阶段一输出空间依赖图，阶段二执行依赖感知调度。

```text
阶段一规划 segment + spatial_dependency
                ↓
后端编译并校验有向无环依赖图
                ↓
阶段二寻找当前 ready segments
├─ 无依赖：立即 ready
├─ 依赖已 completed：提取实际 spatial handoff 后 ready
└─ 依赖未完成：waiting
                ↓
每轮最多并发 3 个 ready segments
                ↓
段完成后写入完整 parsed_result_json
                ↓
下一调度周期解锁依赖该段的下游 segment
```

同一批次内不会同时执行具有上下游关系的两个 segment。即使上游在本批次中先返回，下游也必须等待下一次调度周期，以数据库完成检查点作为唯一就绪依据。

## 6. 阶段一规划契约

### 6.1 Segment 新增字段

无空间继承关系：

```json
{
  "segment_id": "seg_0003",
  "spatial_dependency": {
    "mode": "none",
    "reason": "时间跳跃后的独立场景，与前序空间无连续关系"
  }
}
```

需要继承上游实际空间：

```json
{
  "segment_id": "seg_0002",
  "spatial_dependency": {
    "mode": "inherit",
    "from_segment_id": "seg_0001",
    "camera_pose_policy": "reference",
    "reason": "人物仍在高级套房走廊中连续行动"
  }
}
```

### 6.2 字段含义

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `mode` | string | 只允许 `none` 或 `inherit` |
| `from_segment_id` | string | `mode=inherit` 时必填，必须引用更早的 segment |
| `camera_pose_policy` | string | `mode=inherit` 时固定为 `reference` |
| `reason` | string | 必填，说明为何继承或为何可独立并发 |

### 6.3 规划判断原则

以下情况应输出 `inherit`：

- 人物仍处于同一房间、走廊、车辆或连续物理空间。
- 行为从上一段末尾直接延续。
- 下一段需要知道上段角色、道具或镜头外角色的实际位置。
- 虽然切换了局部空间，但移动关系来自上段，例如从走廊进入同一套房。
- 无法可靠判断是否独立时，保守选择继承。

以下情况可以输出 `none`：

- 明确的时间跳跃。
- 完全独立的地点和人物线。
- 蒙太奇中的互不依赖片段。
- 新场景不需要前序人物、道具或空间状态。

`from_segment_id` 可以指向任意更早的 segment，不要求只能指向紧邻前段。这样可以表达 `seg_001 → seg_003` 的空间延续，同时允许中间的 `seg_002` 属于独立人物线。

## 7. 计划编译和依赖校验

企业版 `compile_quality_plan()` 负责把 LLM 输出编译为稳定契约。

必须校验：

1. 首个 segment 只能使用 `mode=none`。
2. `mode=inherit` 必须提供 `from_segment_id`。
3. 依赖目标必须存在。
4. 依赖目标必须位于当前 segment 之前，禁止向后依赖。
5. 依赖图必须无环。
6. `camera_pose_policy` 只允许 `reference`。
7. `reason` 不允许为空。

非法计划产生 `quality_plan_invalid`，由阶段一在规划重试预算内重新生成，不能把错误留到阶段二形成永久等待。

### 7.1 不兼容旧计划（开发阶段）

当前处于开发阶段，**不处理旧数据兼容**。已经持久化但缺少 `spatial_dependency` 字段的旧 quality 计划直接视为非法：

- `compile_quality_plan()` 检测到任意 segment 缺少 `spatial_dependency` 时，报 `quality_plan_invalid`。
- 旧任务需要重新触发规划（删除任务重新提交，或后续提供显式迁移脚本）以生成带 `spatial_dependency` 的新计划。

这样避免引入"首段 none、后续 inherit"的保守兼容默认值——该默认值会把所有旧任务退化成串行，且开发阶段没有线上旧任务需要保护。后续若需上线兼容，再单独设计迁移策略（如按 continuity 链启发式回填 `spatial_dependency`）。

## 8. 阶段二依赖感知调度

### 8.1 Ready 条件

segment 满足以下**全部**条件时为 ready：

1. **自身状态为 pending**（`status == SEGMENT_STATUS_PENDING`）。`completed`/`generating`/`failed` 状态的段**绝不**进入 ready 集合——尤其 `failed` 段不得被反复当 ready 重试。
2. 依赖条件满足（二选一）：
   - `mode=none`；或
   - `mode=inherit`，且 `from_segment_id` 对应检查点状态为 `completed`，并存在可读取的 `parsed_result_json`。

> **⚠️ 不得复用 `get_uncompleted()`：** 该方法（`model/script_split_segment.py:182`）的 SQL 是 `status != 'completed'`，会把 `failed`/`generating` 段也取出来。`select_ready_segments` 的输入必须是 `ScriptSplitSegmentModel.get_all(task_id)`（返回**全部**状态的段），然后在策略层显式按 `status == pending` 过滤。

以下情况不能运行：

- 自身非 pending（completed/generating/failed）；
- 上游为 `pending/generating/failed`；
- 上游标记 `completed` 但缺少合法 `parsed_result_json`；
- 依赖目标不存在。

### 8.2 调度算法

每次 `_step_generate_parallel_batch()`：

1. 用 `ScriptSplitSegmentModel.get_all(task_id)` 读取当前任务的**全部** segment 检查点（含 completed/failed，供依赖判定）。**不要用 `get_uncompleted()`**——它无法区分 failed 与 pending。
2. 交给企业版策略 `select_ready_segments(plan, all_segments, limit)` 计算 ready 集合（内部按 §8.1 过滤：仅 `status==pending` 且依赖已满足）。
3. **入口分流（关键，避免误 FAILED）**：按 ready 集合与全量段状态决定动作，**绝不复用旧的 `if not segments: step_merge` 路径**：
   - `ready 非空`：按 `segment_index` 稳定排序，取前 `QUALITY_SEGMENT_PARALLELISM` 个，`asyncio.gather()` 并发执行。
   - `ready 为空 且 全部 segment 已 completed`（`len(completed) == total`）：调 `step_merge(task)`。
   - `ready 为空 且 仍有 pending/generating 段`（段在等待上游）：**直接 return，不调 `step_merge`**，让出 tick 等下一调度周期。
   - `ready 为空 且 存在 failed 段导致无法推进`：抛 `quality_dependency_blocked`（见 §8.3）。
4. 本批次完成后统一根据数据库真实状态更新进度。
5. 下一调度周期重新计算依赖。

> **⚠️ 为何不能复用旧路径**：现状 `engine.py:610-612` 是 `if not segments: await step_merge(task); return`，而 `step_merge`（`engine.py:674`）在 `len(completed) != expected` 时抛 `invalid_segment_checkpoint_state`，该错误码在 `task/script_split_task.py:79-83` 属于 terminal_codes → **直接 STATUS_FAILED**。新逻辑下"ready 为空但段在 waiting"是正常状态，若误走 step_merge 会把正常等待的任务判成 FAILED。必须在上游分流，不能依赖 step_merge 兜底。

示例：

```text
seg_1: none
seg_2: inherit(seg_1)
seg_3: none
seg_4: inherit(seg_2)

第一批：seg_1 + seg_3
第二批：seg_2
第三批：seg_4
```

### 8.3 无 Ready 节点

若仍有未完成 segment，但 ready 集合为空：

- 存在合法的未完成上游（pending/generating）：正常等待，不报错，`_step_generate_parallel_batch` 直接 return 让出 tick；
- 所有依赖都指向终态异常（failed）或缺失检查点：抛出 `quality_dependency_blocked`；
- 检测到不可能推进的依赖图：抛出 `quality_dependency_deadlock`。

不得通过空批次反复占用任务而没有状态变化。

## 9. 运行时 Spatial Handoff

### 9.1 数据来源

当下游依赖上游时，从上游 `parsed_result_json` 提取：

- 最后两个实际镜头，作为叙事和构图尾部参考；
- 最后一个镜头的完整 `spatial_layout`；
- 上游 segment ID 和最后镜头 ID；
- 阶段一为下游声明的 `continuity_in/state_changes/continuity_out`。

运行时交接结构：

```json
{
  "source_segment_id": "seg_0001",
  "source_shot_id": "s001",
  "spatial_layout": {
    "schema_version": 2,
    "space_unit_refs": ["spatial:高级套房走廊"],
    "camera_pose": {},
    "camera_anchor": {},
    "location_path": [],
    "containers": [],
    "loose_positions": [],
    "continuity": {}
  },
  "inheritance_policy": {
    "camera_pose": "reference"
  }
}
```

该结构由后端从已保存的真实结果生成，不允许阶段一 LLM 伪造具体值。

### 9.2 上下文字段

下游 `parse_script_to_shots` 接收：

```python
segment_context["previous_tail_summary"] = upstream_tail_shots
segment_context["continuity_state"] = extracted_actual_continuity
segment_context["upstream_spatial_handoff"] = handoff
```

效果模式不再无条件执行：

```python
segment_context["previous_tail_summary"] = []
```

无依赖 segment 仍使用空的运行时 handoff，只接收阶段一全局注册表、`spatial_world` 和自身规划契约。

### 9.3 上下文大小控制

必须保留完整的结构化 ID、空间单元、容器、槽位、`position_3d` 和连续性数据。若交接 JSON 超过提示词预算，只能确定性压缩软描述字段，例如：

- `description`
- `screen_composition`
- `pose`
- 冗长的 `reason/notes`

禁止截断或删除：

- 实体 ID
- `space_unit_refs`
- `location_path`
- `container_id/location_id/prop_id`
- `slot_id`
- `position_3d`
- `physical_position`
- `continuity.changed_positions`
- 镜头外角色身份

结构化压缩阈值作为常量放在 `config/constant.py`，禁止直接对 JSON 字符串做中间截断，避免生成非法 JSON。

## 10. 继承策略

### 10.1 硬连续性字段

在没有对应 `state_changes` 的情况下，下游首镜头必须继承：

- 当前 `space_unit_refs`
- `location_path`
- 角色和道具所在容器
- `space_unit_id`
- `slot_id`
- `position_3d`
- `physical_position`
- `position_basis`
- 镜头外角色仍然存在的空间状态
- 已经发生的移动结果

`position_3d` 比较使用小范围数值容差，默认每个轴绝对误差不超过 `0.05`，避免 LLM 浮点格式差异造成误判。

### 10.2 参考字段

下列字段作为参考，不要求逐字段相等：

- `camera_pose`
- `camera_anchor`
- `screen_axis_mapping`
- `screen_composition`
- `screen_position`
- `pose`
- `visibility`
- `framing_role`
- 景别、焦距和相机运动

提示词必须明确说明：可以更换机位和构图，但新机位必须建立在同一物理空间状态上，不能通过改变相机来重置角色位置。

### 10.3 允许的空间变化

阶段一 `state_changes` 是硬连续性字段发生变化的唯一授权来源。若某角色或道具存在对应变化声明，下游可以改变其空间单元、容器、槽位或位置；未声明的跳变必须被质检拒绝。

## 11. 提示词设计

### 11.1 与已提交的 spatial_contract_block 的关系（避免职责重叠）

提交 `96e09165` 已在 `llm/script_parser.py` 的 `segment_context_block` 中为 quality 模式增加了 `spatial_contract_block`，它基于**阶段一 plan 契约**（`continuity_in/out`、`spatial_world`、`global_registry`）生成 5 项硬约束：

1. 首镜头入点必须逐字段等于 `continuity_in`
2. 末镜头出点必须逐字段等于 `continuity_out`
3. 段内变化仅允许 `state_changes`
4. 合法空间引用清单（space_unit_id / anchor_id）
5. 全局资产真源（characters/locations/props）

本方案引入的 `upstream_spatial_handoff`（来自**上游段真实生成结果**）与上述 ①② 项**数据来源不同但职责重叠**：前者是规划期 LLM 的猜测值，后者是上游实际产出的真实值。二者同时作为硬约束下发，必然在依赖段产生矛盾。

**必须按段依赖类型分叉**，而非同时下发两套硬约束：

| 段类型 | 入点/出点硬约束来源（①②项） | 其他约束（③④⑤项） |
| --- | --- | --- |
| `mode=none`（无依赖） | 仍用 `spatial_contract_block` 的 `continuity_in/out`（无真实 handoff 可用） | 复用 `spatial_contract_block`，不变 |
| `mode=inherit`（依赖上游） | **改用 `upstream_spatial_handoff` 的真实 spatial_layout**，`continuity_in/out` 契约降级为参考 | 复用 `spatial_contract_block`，不变 |

即：`upstream_spatial_handoff` 只**替代** `spatial_contract_block` 的 ①②项（入点/出点位置硬约束），不重复 ③④⑤项（state_changes、合法引用清单、全局资产真源对所有段都适用，且数据源相同）。

### 11.2 依赖段（mode=inherit）的 handoff 提示词块

当 `segment_context["upstream_spatial_handoff"]` 存在时，用以下块**替换** `spatial_contract_block` 的 ①②项（首/末镜头入点出点约束）：

```text
【上游 Segment 实际空间交接 · 硬连续性基线】

以下 JSON 来自依赖 segment 最后镜头的真实生成结果，不是规划猜测。
本段**首镜头**每个在场角色的物理位置必须继承上游最后镜头的实际布局。

1. 角色、道具、容器、槽位和三维位置是连续性基线。
2. 未在本段 state_changes 声明的物理状态不得改变。
3. camera_pose/camera_anchor 只作为参考，你可以根据当前剧情调整机位。
4. 调整机位不得改变角色的真实物理位置。
5. 不得重复生成上游镜头。
```

随后附加完整的 `upstream_spatial_handoff` JSON。

### 11.3 冲突处理：以 handoff 为准（不报错卡住）

阶段一 `continuity_in/out` 契约是规划期 LLM 的猜测值，`upstream_spatial_handoff` 是上游段真实生成的结果。两者不一致时（这很常见，因为规划期未必想清楚镜头级细节），**以 handoff 为准**：

- 依赖段的首/末镜头位置硬约束**始终取 handoff 的真实值**，不取 `continuity_in/out` 契约值。
- 不再向模型下发 `continuity_in/out` 作为硬约束（已由 §11.1 分叉规则保证）。
- 后端**不报** `quality_dependency_contract_conflict`——该错误码在本方案中废弃，因为"真实值优先于猜测值"已从源头消除矛盾，没有需要模型抉择的冲突。

跨段校验器（§12）对比的是"上游最后镜头实际布局" vs "下游首镜头实际布局"，与 `continuity_in/out` 契约无关；契约仅用于无依赖段的单段质检（沿用已提交的 `spatial_contract_block` 逻辑）。

## 12. 跨 Segment 空间校验

企业版新增跨段校验器，对比：

- 上游最后镜头实际 `spatial_layout`
- 下游首镜头实际 `spatial_layout`
- 下游阶段一 `state_changes`

### 12.1 规范化比较

先把复杂布局规范化为实体物理状态表：

```json
{
  "char_001": {
    "space_unit_id": "spatial:高级套房走廊",
    "container_key": "location:高级套房走廊",
    "slot_id": "走廊中部",
    "position_3d": {"x": -0.3, "y": 0.2, "z": 0.5},
    "physical_position": {
      "row": "front_group",
      "side": "walkway_left"
    }
  }
}
```

容器优先使用稳定 ID；历史数据没有 `container_id` 时，使用 `container_type + location_id/prop_id + name + area` 生成稳定比较键。

### 12.2 校验规则

- 无变化声明的实体必须保持硬字段一致。
- 有变化声明的实体必须能从上游状态解释到下游状态。
- 镜头外角色可以改变 `visibility`，但不能无理由丢失物理状态。
- 相机坐标、景别和屏幕位置不参与硬相等比较。
- 下游引用的空间单元和锚点必须存在于全局 `spatial_world`。

失败错误码：

- `quality_cross_segment_spatial_mismatch`
- `quality_dependency_source_missing`

> `quality_dependency_contract_conflict` 已在 §11.3 废弃：依赖段的入点/出点硬约束始终取上游真实 handoff，阶段一 `continuity_in/out` 契约降级为参考，不存在需要模型抉择的冲突。

这些错误进入现有段级 QC 修正循环；达到 QC 上限后仍遵循“采用最后一个可解析候选”的既有策略，并保留 `_forced_accept=true` 供后续诊断。

## 13. 检查点、重试与恢复

- 依赖就绪只读取数据库中 `completed` 的上游检查点。
- 上游生成失败但保留可解析候选时，按现有策略强制接纳后可以解锁下游。
- 上游没有任何可解析候选并进入 `paused` 时，下游保持未开始，不得绕过依赖。
- 用户恢复任务后仍从依赖图重新计算 ready 集合。
- 下游修正重试每次重新从上游完成检查点构造 handoff，不能依赖进程内缓存。
- 用户取消任务时，迟到的并发结果继续按现有规则丢弃。

无需新增数据库字段：

- 依赖关系保存在 `segment_plan_json`。
- 上游实际布局保存在现有 `parsed_result_json`（handoff 从这里提取，见 §9.1）。
- `continuity_out_json` 保存真实出点状态（来自 `_extract_continuity_out(parsed)`，从最后镜头提取，是真实值）。
- `continuity_in_json` 当前语义为**阶段一规划契约值**（parallel 路径 `engine.py:575` 写入 `contract.continuity_in`），**不是真实入点**。本方案不改变该字段语义，真实入点状态不单独持久化——跨段校验（§12）在运行时从上游 `parsed_result_json` 实时提取 handoff 进行比对，不依赖 `continuity_in_json`。若后续需要持久化真实入点，应新增字段而非复用 `continuity_in_json`，避免破坏既有 plan 契约语义。

## 14. 合并阶段

`step_merge` 继续按 `segment_index` 合并结果，并运行全局空间连续性修复。但合并修复只作为防御层：

- 可以补充同一物理位置的稳定槽位字段。
- 可以补充镜头外连续性角色。
- 不得用后处理伪造未生成的跨段空间关系。
- 不得覆盖阶段二跨段校验已经确认的实际布局。

## 15. 企业版代码边界

效果模式专属实现放置在：

```text
enterprise/services/script_split_quality/
├── contract.py                 # 编译和校验 spatial_dependency
├── planner.py                  # 阶段一依赖规划提示词
├── strategy.py                 # ready 选择、handoff 构建入口
├── dependency_scheduler.py     # 依赖图和 ready 计算
├── spatial_handoff.py          # 提取与结构化压缩
└── validator.py                # 段内及跨段空间校验
```

核心仓库只负责：

- 读取通用 segment 检查点。
- 调用企业版策略取得 ready segments。
- 对 ready segments 使用现有 `asyncio.gather()`。
- 把策略生成的上下文传给 `parse_script_to_shots`。
- 保存成功、失败和进度检查点。

不得把效果模式的依赖判断、空间字段继承规则或跨段校验细节放入通用调度器。

## 16. 可观测性

每个调度批次记录：

- `task_id`
- ready segment IDs
- waiting segment IDs
- 每个 waiting segment 的依赖目标及目标状态
- 实际并发数量
- handoff 来源 segment/shot
- handoff 原始大小和压缩后大小
- 跨段校验错误码和字段路径

建议日志示例：

```text
[quality-segment-deps] task=39 ready=[seg_0001,seg_0003] waiting={seg_0002:seg_0001}
[quality-spatial-handoff] task=39 target=seg_0002 source=seg_0001/s014 bytes=8231
```

日志中不得记录鉴权 token。

## 17. 测试方案

### 17.1 计划契约测试

1. `mode=none` 编译成功。
2. `mode=inherit` 且目标存在、位于前序时编译成功。
3. 缺少目标、向后引用、未知模式和循环依赖均失败。
4. 缺少 `spatial_dependency` 字段的 segment 编译失败（不兼容旧计划，见 §7.1）。

### 17.2 调度测试

1. 无依赖的多个 segment 最多并发 3 个。
2. `seg_2 → seg_1` 时，不能与 `seg_1` 同批运行。
3. `seg_1` 完成后下一 tick 才允许 `seg_2`。
4. 独立 `seg_3` 可以和 `seg_1` 同批执行。
5. 无 ready 且依赖不可恢复时产生明确错误。

### 17.3 Handoff 测试

1. 从上游最后镜头提取完整 `spatial_layout`。
2. 下游上下文包含真实 `previous_tail_summary`。
3. ID、槽位、`position_3d`、镜头外角色在结构化压缩后仍存在。
4. `camera_pose` 被标记为参考而非硬复制。
5. 重试时从数据库重新构造相同 handoff。

### 17.4 跨段校验测试

1. 未声明变化的角色换槽位时失败。
2. `position_3d` 在容差内通过，超出容差失败。
3. 声明 `state_changes` 后允许对应角色移动。
4. 更换 `camera_pose` 不触发失败。
5. 镜头外角色改变可见性但保留位置时通过。
6. 镜头外角色无理由消失时失败。

### 17.5 回归测试

- `speed/balanced` 行为不变。
- quality 单段任务正常运行。
- quality 全独立段仍可并发。
- quality 全依赖链退化为严格串行。
- segment 重试、强制接纳、暂停和恢复逻辑不变。
- 后续首帧宫格仍严格按幕串行。

## 18. 验收标准

1. 阶段一的每个新 quality segment 都有合法 `spatial_dependency`。
2. 存在依赖关系的两个 segment 从不同时调用 `parse_script_to_shots`。
3. 下游提示词包含上游最后镜头的真实完整空间交接。
4. 下游可以改变 `camera_pose`，但不能无声明改变角色物理位置。
5. 没有依赖的 segment 仍能维持最多 3 个并发。
6. 缺少 `spatial_dependency` 的旧计划在编译期即失败（不静默并发，见 §7.1）。
7. 依赖错误不会造成永久 `generating` 或空调度循环。
8. 所有效果模式专属实现位于 `enterprise/`。
9. 文档、单元测试、集成测试和阻塞调用检查全部通过。

## 19. 已确认的设计决策

- 阶段一负责决定是否需要继承实际空间布局。
- 阶段二根据依赖图选择可并发的 segment。
- 依赖下游必须等待上游检查点完成。
- 下游接收上游最后镜头的完整 `spatial_layout`。
- 角色、道具、容器、锚点和物理位置属于硬连续性。
- `camera_pose` 和构图属于参考信息，允许下一段调整。
- 无依赖段允许并发，不采用全局强制串行。

## 20. 已知约束与实现陷阱

### 20.1 看门狗与单段墙钟上限（现状代码结构，本方案不改变）

worker 单步看门狗为 `WORKER_STEP_TIMEOUT_SECONDS=360s`（`task/script_split_task.py:39-42`，`asyncio.wait_for` 包住整个 `_advance_one_step`）。但一个 parallel_child 段在一个 tick 内跑**两个串行的 wait_for**：

1. `parse_script_to_shots`：timeout = `LLM_CALL_TIMEOUT_SECONDS=330s`（`engine.py:411`）
2. 段级 QC `run_script_split_qc`：timeout = `WORKER_STEP_TIMEOUT_SECONDS=360s`（`engine.py:1037`）

因此单段墙钟理论上限 = 330 + 360 = **690s**，超过 360s 看门狗。当 LLM 偏慢（接近 330s）时，看门狗会先触发，把任务误杀进 `paused(step_watchdog_timeout)`。

**缓和因素**：当前 QC `use_llm=False`（`engine.py:1027`，纯规则校验，正常毫秒级），实际触发概率低。这是**现有代码就有的结构**，本方案不改变 timeout 值，也不引入新风险。实现时知晓即可；若要根治，应将段级 QC 的 timeout 调整为独立的小值常量（如 30s），而非复用 `WORKER_STEP_TIMEOUT_SECONDS`。该项不在本方案范围。

### 20.2 接口命名：build_runtime_segment_context 是新建，不是改造现有

代码中已存在两个名字相近的方法，切勿混淆：

- `strategy.build_segment_context(plan, segment_id)`（`enterprise/services/script_split_quality/strategy.py:22`）：返回**静态** dict（`global_registry/spatial_world/spatial_contract`），不读数据库上游检查点。
- `_build_segment_context(task, seg, registry)`（`services/script_split_engine.py:977`）：私有助手，返回 `previous_tail_summary/continuity_state/accepted_registry` 等。

方案 Task 2 产出的 `build_runtime_segment_context` **在当前代码中不存在**（全仓 grep 零命中），是**新建**接口。它的职责（按依赖类型构造 `upstream_spatial_handoff`）与上述两者都不同：需要读数据库上游 `parsed_result_json`。实现时建议作为 `QualityScriptSplitStrategy` 的新方法，由 `_step_generate_parallel_batch` 在选中 ready 段后调用，**取代** parallel_child 路径现有的 `strategy.build_segment_context` 调用（`engine.py:309`）。不要试图扩展现有 `build_segment_context` 承担运行时 handoff 职责——它是纯函数、无 DB 读取，混淆会破坏其可测试性。

