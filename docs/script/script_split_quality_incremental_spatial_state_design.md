# 效果模式剧本拆分：增量空间状态设计（B+）

## 1. 文档状态

- 状态：评审修订完成，待用户确认
- 日期：2026-07-17
- 适用范围：效果模式（`sequence_mode=quality`）
- 核心代码边界：`enterprise/services/script_split_quality/`
- 社区版影响：仅增加可选策略钩子，不承载效果模式实现

## 2. 背景

当前效果模式要求分镜 LLM 在长 JSON 中同时完成：镜头创作、全量空间状态抄写、ID 复用、首尾契约匹配、段内移动声明和引用白名单校验。历史错误高度集中在以下类型：

- `quality_continuity_in/out_mismatch`
- `ref_prop_unknown` / `ref_anchor_unknown`
- `quality_undeclared_spatial_change`
- `location_id_not_reserved`
- 长输出导致的超时、截断和多轮修正失败

问题不是单纯的模型能力不足，而是“高维硬约束 × 重复状态输出 × 提示盲区 × 规划波动”叠加。当前实现还存在两处规则错位：

1. 规划提示要求所有相邻段 `continuity_out == continuity_in`，但编译器实际只对 `mode=inherit` 强制。
2. `inherit` 段提示模型以真实 `upstream_spatial_handoff` 为准，但段级 validator 仍同时校验规划期 `continuity_in/out`，形成双重真源。

## 3. 目标与非目标

### 3.1 目标

1. LLM 负责镜头艺术设计和明确发生的空间变化，不再逐镜重复完整世界状态。
2. 后端确定性继承未变化状态，并为每个镜头生成完整规范快照。
3. 下一镜头和下一依赖段始终接收上一镜头的真实完整快照。
4. 降低输出 token、漏字段、ID 幻觉和无意义 QC 重试。
5. 保持现有发布、宫格生图、首帧生成和 handoff 消费方看到的仍是完整 `spatial_layout`。
6. 独立 segment 保持并发；存在空间继承的 segment 保持串行。

### 3.2 非目标

- 后端不解析自然语言来猜测角色是否离开、移动或拿起道具。
- 后端不决定景别、机位、构图、表演和可见主体。
- 本方案不改变速度/均衡模式。
- 本方案不把效果模式核心代码下沉到社区目录。
- 本期不引入新的数据库表；状态继续保存在任务检查点和分镜 JSON 中。

## 4. 方案选择

### 4.1 备选方案

| 方案 | 做法 | 结论 |
|---|---|---|
| A：逐镜完整快照 | 每个镜头都让 LLM 输出所有角色、道具和位置 | 重复字段多，仍容易漏写、超时和前后矛盾 |
| B：纯增量 | LLM 只输出变化，后端仅保存增量 | 下游需要理解增量，兼容成本高 |
| B+：增量输入、完整落盘 | LLM 输出艺术意图和变化；后端物化完整快照 | **采用**，兼顾低负担、可追溯和下游兼容 |

### 4.2 核心原则

> LLM 负责变化，后端负责状态；每个镜头保存完整快照，跨 segment 传递真实快照。

## 5. 总体架构

```text
阶段一规划
  输出：实体、空间目录、segment、依赖、独立段初始状态、计划变化
                              ↓
阶段二 LLM
  输出：镜头艺术字段 + 可见实体 + 当前镜头状态变化
                              ↓
企业版空间状态物化器
  读取上一个规范快照 → 应用变化 → 补齐未变化/画外实体/稳定 ID
                              ↓
确定性校验 → 可选 QC Agent
                              ↓
保存完整 spatial_layout + 最后一镜真实 handoff
```

通用引擎只增加可选策略钩子：

```python
strategy.materialize_segment_result(parsed, segment_context)
```

社区策略保持 no-op；效果模式实现位于：

```text
enterprise/services/script_split_quality/spatial_state.py
enterprise/services/script_split_quality/spatial_materializer.py
enterprise/services/script_split_quality/spatial_validator.py
```

## 6. 阶段一规划契约

### 6.1 新计划版本

新任务使用 `schema_version=3`。旧的 v2 计划由兼容适配器读取，不要求正在执行的旧任务重新规划。

v3 不再要求 LLM 为每个 segment 重复输出完整 `continuity_in` 和 `continuity_out`：

- `mode=none`：输出 `initial_spatial_state`。
- `mode=inherit`：不输出入点状态，运行时从真实上游 handoff 获取。
- 所有段：输出 `planned_state_changes`，作为剧情规划和 QC 参考。
- `continuity_out` 由阶段二真实镜头快照产生，不再作为规划期硬真源。

示例：

```json
{
  "schema_version": 3,
  "spatial_state_version": 1,
  "segments": [
    {
      "segment_id": "seg_0002",
      "block_ids": ["blk_004", "blk_005"],
      "spatial_dependency": {
        "mode": "inherit",
        "from_segment_id": "seg_0001",
        "camera_pose_policy": "reference",
        "reason": "人物仍在酒店走廊连续行动"
      },
      "planned_state_changes": [
        {
          "change_id": "chg_0001",
          "entity_type": "character",
          "entity_key": "character:林晓",
          "operation": "move",
          "block_id": "blk_005",
          "to": {
            "space_unit_id": "spatial:高级套房走廊",
            "container_id": "container:room_708_door",
            "slot_id": "door_front"
          }
        }
      ]
    }
  ]
}
```

### 6.2 规划提示修正

规划提示必须写死：

1. 只有 `mode=inherit` 才要求空间继承；`mode=none` 允许硬切、时间跳跃和独立人物线。
2. `inherit` 的入点由运行时真实 handoff 决定，不要求规划器猜测完整入点布局。
3. 规划器只声明剧情明确发生的变化，不规划每个镜头的构图、可见性和坐标抄写。
4. 单段仍受 1500 字硬上限约束，同时增加较短的软目标；跨地点或预计镜头明显过多时优先继续分段。
5. `spatial_world` 没有 anchor 时明确表示 anchor 可省略，不能诱导阶段二自造 ID。
6. **先登记 `spatial_world.space_units[].containers[].slots`（或 anchors），再写 `initial_spatial_state`**；引用 ID 必须可被 `SpatialCatalog` 解析。
7. `container_id` 禁止填 `character:*` / `prop:*` / `space_unit:*` / `spatial_unit:*`；空间单元与容器不得混用。
8. present 实体必须有 `container_id+slot_id` 或已登记 `anchor_id`；禁止只写 `space_unit_id`。
9. 手持/佩戴道具：物理落点仍用场景 container+slot（可与持有人同槽），另写 `holder_character_id`；禁止 `container_id=character:xxx`。
10. 提示中提供可复制的正确 few-shot 与错误对照（见 `enterprise/services/script_split_quality/planner.py`）。

## 7. 阶段二增量输出

### 7.1 LLM 负责的字段

LLM 继续输出现有镜头艺术字段：

- `opening_frame_description`
- `scene_detail`
- `characters_present`
- `shot_type` / `camera_movement`
- 对话、动作、声音和情绪
- 相机与构图相关字段

效果模式新增质量专用临时字段 `spatial_intent`。可见性继续使用镜头已有的 `characters_present` 和 `props_present`；不在 `spatial_intent` 中重复定义任何 `visible_*` 字段：

```json
{
  "characters_present": ["char_001"],
  "props_present": ["prop_003"],
  "spatial_intent": {
    "state_changes": [
      {
        "change_id": "chg_0001",
        "entity_type": "prop",
        "entity_id": "prop_003",
        "operation": "pickup",
        "from": {
          "container_id": "container:tea_table",
          "slot_id": "table_center"
        },
        "to": {
          "holder_character_id": "char_001"
        }
      }
    ]
  }
}
```

`spatial_intent` 是 LLM 原始响应的中间格式。物化完成后，发布结果仍以完整 `spatial_layout` 为准；原始 intent 只保存在日志或诊断字段中。

可见性真源固定如下：

- 角色：`characters_present` 是唯一真源；物化器禁止读取其他角色可见性列表。
- 道具：`props_present` 是唯一真源；物化器禁止读取其他道具可见性列表。
- 文本描述与结构化可见性冲突时，确定性物化使用结构化字段，并产生 `spatial_visibility_text_conflict` warning 交给 QC Agent 判断，不从文本反向改状态。

### 7.2 支持的变化操作

首期支持：

- 角色：`enter`、`move`、`exit`
- 道具：`pickup`、`put_down`、`transfer`、`move`

每个变化必须包含稳定实体 ID、操作类型和目标；`from` 可省略，由后端用当前规范状态补齐并校验。后端不从 `action`、`scene_detail` 或对白中推断变化。

### 7.3 提示词必须包含的正例

提示词增加一个简短 few-shot，明确区分“出镜表”和“世界状态表”：

```text
上一镜头：林晓在沙发左侧，陈总在沙发右侧。
当前镜头：林晓面部特写，陈总未出镜，且没有离开声明。

正确：characters_present 只写林晓；state_changes 为空。
后端会把陈总作为 offscreen_continuity 保留在沙发右侧。
禁止：为了让陈总不出镜而声明陈总离开或删除其物理位置。
```

同时明确：

- `characters_present` 是可见名单，不是完整世界状态。
- 不需要重复输出未变化角色的位置。
- 变化目标必须优先使用下发的规范 ID。
- 合法 anchor 为空时省略 `anchor_id`，禁止自造。
- 不允许只写中文 `area/name` 代替已有的规范 `container_id`；如果不知道目标 ID，应省略变化并让 QC 指出，而不是编造。

### 7.4 段内提示投影格式

阶段二每个 segment 仍只调用一次 LLM，不进行逐镜网络请求。提示上下文不得重复注入上一镜完整嵌套 `spatial_layout`；统一投影为紧凑的扁平状态：

```json
{
  "previous_state": {
    "char_001": ["present", "spatial:hotel_suite", "container:sofa", "left"],
    "char_002": ["present", "spatial:hotel_suite", "container:sofa", "right"],
    "prop_003": ["present", "spatial:hotel_suite", "container:tea_table", "table_center"]
  },
  "allowed_ids": {
    "space_units": ["spatial:hotel_suite"],
    "containers": ["container:sofa", "container:tea_table"],
    "slots": ["left", "right", "table_center"]
  },
  "previous_camera_summary": {
    "space_unit_id": "spatial:hotel_suite",
    "shot_type": "中景",
    "axis": "sofa_front"
  }
}
```

字段顺序固定，软描述按预算裁剪；禁止把完整上游 `shot_groups` 或完整嵌套 layout 重复塞给模型。这样同时降低输入和输出 token，而不是只降低输出。

## 8. 规范空间状态

### 8.1 内部扁平状态

后端内部使用扁平规范状态，避免直接在嵌套 containers 中做差异合并：

```json
{
  "schema_version": 1,
  "entities": {
    "char_001": {
      "entity_type": "character",
      "presence": "present",
      "space_unit_id": "spatial:hotel_suite",
      "container_path": ["location:hotel_suite", "container:sofa"],
      "container_id": "container:sofa",
      "slot_id": "left",
      "position_3d": {"x": -0.4, "y": 0.2, "z": 0.0}
    },
    "prop_003": {
      "entity_type": "prop",
      "presence": "present",
      "space_unit_id": "spatial:hotel_suite",
      "container_path": ["location:hotel_suite", "container:tea_table"],
      "container_id": "container:tea_table",
      "slot_id": "table_center",
      "holder_character_id": null
    }
  }
}
```

`presence` 仅允许 `present`、`absent`、`exited`；`holder_character_id` 与 container/slot 归属互斥。`container_path` 保存多层容器的稳定路径，`container_id` 始终等于终端容器。

`visibility` 不属于永久物理状态，而是当前镜头属性。角色 `presence=present` 但不在 `characters_present` 时，物化结果写入：

```json
{
  "visibility": "offscreen",
  "framing_role": "offscreen_continuity"
}
```

### 8.2 坐标规则

- 已有 `position_3d` 且未移动：原样继承。
- 变化目标给出 `position_3d`：校验后更新。
- 目标 slot 或 anchor 在空间目录中有固定坐标：必须确定性派生，不能继续留空。
- 无坐标依据：保留 `space_unit_id/container_id/slot_id`，`position_3d` 留空；不得生成伪坐标，同时产生 `spatial_position_3d_unavailable` warning。
- `position_3d` 为空时，首帧投影按现有逻辑退回结构化 `screen_position/slot` 和相机文本摘要；不得把该 fallback 视为与 3D 投影等价。
- 监控 present 实体缺少 `position_3d` 的比例，作为独立质量指标。

原因：`enterprise/services/storyboard_spatial/projection.py` 只有在实体坐标（或 anchor 坐标）及 camera pose 完整时才能推导画面左右；坐标缺失虽然不应伪造，但会降低首帧投影稳定性。

### 8.3 独立段初始状态硬门禁

`mode=none` 的 `initial_spatial_state` 是独立段的物理真源，必须在计划编译阶段完成校验，不能拖到阶段二：

- 本段开场仍处于场景中的每个角色必须恰好出现一次。
- 每个 present 实体必须包含合法 `space_unit_id`。
- 位置必须采用以下两种形式之一：
  - 合法 `container_id + slot_id`；
  - 合法 `anchor_id` 或明确的 `loose_position`。
- 实体、容器、槽位和 anchor 必须能在 `SpatialCatalog` 唯一解析。
- 同一角色不得同时占用 container slot 和 loose position。
- 无法唯一解析时规划修正，不允许带着稀疏或漂移 ID 的初始状态进入阶段二。

## 9. 状态物化算法

### 9.1 镜头顺序物化

每个 segment 按镜头顺序执行：

1. 选择初始状态：
   - `inherit`：上游最后镜头真实 handoff。
   - `none`：计划中的 `initial_spatial_state`。
2. 将当前 `characters_present` 和 `visible_*_ids` 视为画面可见性，不视为空间移动。
3. 规范化 `spatial_intent.state_changes` 中的实体和目标引用。
4. 对每个变化检查实体当前状态、操作合法性和目标唯一性。
5. 按顺序应用合法变化；未变化实体原样继承。
6. 将当前规范状态物化为完整 `spatial_layout`：
   - 可见实体叠加当前镜头姿态、屏幕位置和构图字段。
   - 未出镜但仍 present 的角色写成 `offscreen_continuity`。
   - 已退出实体不写入当前物理布局。
7. 保存当前完整快照，作为下一镜头基线。
8. segment 最后一镜快照作为真实 `upstream_spatial_handoff`。

状态转换必须是纯函数：

```python
next_state, diagnostics = apply_spatial_intent(
    previous_state,
    spatial_intent,
    spatial_catalog,
)
```

相同输入必须得到相同输出，不能调用 LLM，也不能读取隐式进程状态。

### 9.2 状态操作语义

`state_changes` 严格按数组顺序应用。同一镜头存在多个变化时，后一个操作读取前一个操作已经提交的状态。

| 操作 | 前置条件 | 状态结果 |
|---|---|---|
| `enter` | 实体当前为 absent/exited | 设置为 present 并写入目标；角色手持道具随角色进入 |
| `move` | 实体当前为 present | 先清除旧 container/slot/anchor/坐标，再写入完整目标；跨 `space_unit` 同样处理 |
| `exit` | 实体当前为 present | 设置为 exited 并清除场内位置；仍由该角色持有的道具一同退出并保留 holder 关系 |
| `pickup` | 道具 present、无其他 holder，角色 present | 清除道具原 container/slot，写入 `holder_character_id` |
| `put_down` | 道具 holder 是指定角色 | 清除 holder，写入目标 container/slot |
| `transfer` | 道具 holder 与 `from` 一致，目标角色 present | 原子替换 holder，禁止复制道具 |

补充规则：

- 角色跨空间移动时，其手持道具自动跟随，不需要为每个手持道具重复写 `move`。
- 角色 `exit` 前若同镜头先执行 `put_down/transfer`，按数组顺序以最新持有关系为准。
- 段内硬切到新空间必须显式提供成组的 `exit/enter/move`；若变化规模过大，规划器应优先拆成新的 `mode=none` segment。
- `planned_state_changes.change_id` 是期望覆盖标识，不要求与镜头 intent 一一强制消费；同一 `change_id` 最多消费一次。到对应 `block_id` 后仍未消费时产生 `spatial_planned_change_missing` warning，交给 QC Agent 判断，后端不得替模型自动执行该变化。
- 未列入计划但结构合法的变化允许应用，同时产生 `spatial_unplanned_change` warning。
- 姿态、表情、朝向和屏幕位置变化不是物理 state change，由 LLM 每镜输出，不改变 container/slot。
- 同一实体在任一快照中只能有一个物理归属：container slot、loose position、holder 三者互斥。

### 9.3 物化字段矩阵

| `spatial_layout` 字段 | LLM 职责 | 后端职责 | 发布结果 |
|---|---|---|---|
| `camera_pose` / `camera_anchor` | 每镜艺术设计 | 校验引用、保留；只把上一镜相机作为摘要参考 | 使用当前镜 LLM 值 |
| `screen_composition` / `screen_axis_mapping` | 每镜艺术设计 | 规范化，不参与物理状态继承 | 使用当前镜值 |
| `space_unit_refs` | 无需重复抄写 | 从规范状态与当前场景确定性汇总 | 后端生成 |
| `location_path` | 可提供剧情路径提示 | 按场景注册表和 container path 规范化 | 后端生成规范 ID 路径 |
| `containers` | 不输出完整集合 | 按规范状态分组重建；terminal `container_id` 唯一 | 后端生成 |
| `containers[].slots` | 仅提供当前可见实体的姿态/构图软字段 | 物化所有 present 实体的 slot，补 offscreen | 后端生成完整集合 |
| `loose_positions` | 仅为无 container/slot 的明确目标提供 intent | 与 container slot 做互斥校验后物化 | 后端生成 |
| `position_3d` | 仅在明确变化且剧本/目录有依据时给出 | 未变化继承；slot/anchor 有坐标时派生 | 完整则写入，未知则 warning + 留空 |
| `physical_position` / `position_basis` | 可为当前可见实体补充 | 未变化继承；catalog 有定义时派生 | 合并后的规范值 |
| `screen_position` / `pose` | 当前镜头输出 | 3D 投影可覆盖 screen_position；不继承过期姿态 | 当前镜可见实体使用 |
| `visibility` / `framing_role` | 由 `characters_present` 间接决定可见角色 | 未出镜 present 角色写 `offscreen/offscreen_continuity` | 后端统一生成 |
| `continuity.unchanged_slots` | 不输出 | 由相邻规范状态 diff 生成 | 后端生成 |
| `continuity.changed_positions` | 不再作为 v3 输入 | 由已接受的 `spatial_intent.state_changes` 转换，供旧下游兼容 | 过渡期后端单向生成 |
| `spatial_intent` | 只输出状态变化 | 消费后从发布结构移除，原文写日志 | 不发布 |

多层容器使用 `container_path` 表达从空间单元到终端容器的稳定路径；扁平状态保存完整 path 和终端 `container_id`。物化时按 path 分组重建，禁止同一实体同时出现在父容器、子容器和 `loose_positions`。

## 10. 空间目录与 ID 规范化

新增 `SpatialCatalog`，从以下真源构建：

- `compiled_registry.characters/locations/props`
- `spatial_world.space_units/anchors`
- 独立段 `initial_spatial_state`
- 上游真实 handoff

目录至少提供：

- 合法 `space_unit_id`
- 合法 `container_id`
- 合法 `(container_id, slot_id)`
- 合法 `(space_unit_id, anchor_id)`
- 名称/area 到规范 ID 的别名索引

规范化规则：

1. 已提供合法 ID：直接使用。
2. ID 缺失但名称命中一个**显式登记别名**：自动回写规范 ID，并记录 `spatial_alias_normalized` 信息。
3. 名称匹配多个目录项：不猜测，产生 `spatial_reference_ambiguous`。
4. anchor 不存在且不影响物理位置：删除非法可选 anchor，记录 warning。
5. 必需的 space/container 不存在：产生 error。

别名匹配只允许标准化后的精确匹配（去首尾空白、统一大小写和全半角）；禁止编辑距离、包含关系、关键词或向量近似匹配，避免“唯一但错误”的静默绑定。别名必须来自数据库实体名、规划期登记名或人工维护的 alias，不从本轮 LLM 自由文本自动扩充。

若计划存在尚未覆盖的 `planned_state_changes`，而对应剧情 block 已生成完毕且 intent 为空，必须产生 `spatial_planned_change_missing`。这用于捕获“禁止编造 ID 后模型干脆不移动”的软偏差，不能只依赖引用错误下降判断质量。

## 11. 校验与 QC 分层

### 11.1 执行顺序

```text
LLM 原始结果
  → 通用角色/场景/道具 sanitizer
  → 企业版空间物化器
  → 确定性结构与状态校验
  → enable_qc=true 时调用 QC Agent
  → 保存完整候选
```

QC Agent 必须检查物化后的完整结果，避免“QC Agent pass，但规则校验看到另一份数据”的双标准。

### 11.2 自动修复，不占 QC 轮次

以下属于确定性补全：

- 未变化实体继承。
- 未出镜角色补为 `offscreen_continuity`。
- 唯一别名映射到规范 ID。
- 缺失的 `from` 从当前状态补齐。
- 可选非法 anchor 删除。
- 容器相同且 slot 未变化时继承缺失字段。

### 11.3 Warning

- `spatial_alias_normalized`
- `spatial_optional_anchor_dropped`
- `spatial_unplanned_change`：变化不在阶段一计划中，但结构合法；交给 QC Agent 结合剧本判断，不由确定性规则直接拒绝。
- `spatial_planned_change_missing`：对应剧情 block 已完成但计划变化未被 intent 覆盖。
- `spatial_position_3d_unavailable`：实体物理归属明确，但没有坐标或 anchor 坐标可用于投影。
- `spatial_visibility_text_conflict`：结构化可见性与镜头文本不一致。
- 规划期目标状态与真实末镜不同：记录诊断，不再作为双重硬约束。

### 11.4 Error

- `spatial_reference_ambiguous`
- `spatial_entity_unknown`
- `spatial_transition_invalid`
- `spatial_destination_missing`
- `spatial_prop_ownership_conflict`：同一道具出现多个 holder/容器归属，或转移来源不匹配。
- `quality_cross_segment_spatial_mismatch`：下游首镜没有继承真实 handoff，且没有合法变化。
- `quality_segment_has_no_shots`

### 11.5 强制接纳

空间 QC 达到上限后继续遵循现有“采用最后一个可解析候选”策略，但规范状态不能被破坏：

- 非法变化不写入规范状态。
- 保留上一份最后有效状态并标记 `_spatial_degraded=true`。
- 下一依赖段继承真实有效快照，而不是规划猜测值。
- handoff 必须携带 `_spatial_degraded`、被忽略的 change ID 和关键 diagnostics 摘要；下游提示明确告知该状态已降级，禁止把它伪装成无异常基线。
- degraded 状态可以继续传播以避免任务卡死，但每经过一个 inherit 边都累计 `degraded_hops`；日志和任务进度暴露该值，便于发现长链空间状态停滞。
- JSON/场景层级等既有 non-forceable 结构错误仍按原硬门禁处理。

## 12. 与现有 validator 的调整

1. `validate_spatial_contract()` 不再要求每个镜头由 LLM 自行重复完整位置。
2. `inherit` 段首镜只比较真实 handoff，不再同时比较规划期 `continuity_in`。
3. 末镜以物化后的真实状态为准；规划期 `continuity_out` 在 v3 中取消。
4. `quality_undeclared_spatial_change` 改为读取明确 delta；不再通过比较两份可能不完整的嵌套布局猜测移动。
5. `_shot_positions()` 必须保留 `position_3d`，修复当前跨段比较无法取得坐标的问题。
6. `ref_anchor_unknown` 对可选 anchor 降为可自动清理的 warning；必需空间引用仍为 error。

### 12.1 现有模块替换关系

| 现有模块 | v2 任务 | v3 任务 |
|---|---|---|
| `contract.py` | 保留现有 v2 编译和 `continuity_in/out` | 新增 v3 编译、`initial_spatial_state` 硬校验和计划变化规范化 |
| `spatial_handoff.py` | 从旧完整 layout 提取 | 从已物化最后镜提取规范状态、完整 layout、degraded 与 diagnostics |
| `validator.py` | 保留旧 continuity 校验 | 只保留通用工具；v3 进入新的 `spatial_validator.py` |
| `storyboard_spatial.repair_spatial_layout_continuity` | 继续作为旧路径兜底 | **不再执行**；由 materializer 完整替代，禁止二次补写 |
| `continuity.changed_positions` | 继续读取 LLM 旧输出 | 不作为输入；由 accepted intent 单向生成兼容字段 |

### 12.2 调用边界

`segment_context` 增加 `spatial_state_version=1`。通用 `llm/script_parser.py` 看到该标志时跳过旧 `repair_spatial_layout_continuity()`，但不包含任何效果模式状态机实现；解析结果返回 engine 后，再由 enterprise strategy 调用 materializer。

禁止以下半新半旧顺序：

```text
旧 repair → 新 materializer → 旧 continuity validator
```

v3 唯一合法顺序是：

```text
通用 sanitizer → enterprise materializer → v3 deterministic validator → QC Agent
```

旧 v2 检查点在整个生命周期始终走 v2 路径，不做运行中升级，也不把旧 `changed_positions` 临时转换后写回 v3。新旧逻辑以 plan 版本一次性分流，避免恢复任务时切换语义。

## 13. 并发与 handoff

- `mode=none`：使用独立初始状态，可与其他 ready 段并发。
- `mode=inherit`：必须等待 `from_segment_id` 完成并取得最后镜完整快照。
- 并发段只共享只读全局 registry 和 catalog，不共享可变状态。
- 每个 segment 的状态机从独立初始快照开始，避免跨协程写同一对象。
- handoff 必须来自已物化并校验后的最后镜，不得从 LLM 原始输出直接抽取。
- handoff 保存完整规范快照供后端使用，但注入下游 LLM 时按 §7.4 投影成扁平紧凑状态，不直接注入完整嵌套 layout。
- handoff 必须携带 `_spatial_degraded`、`degraded_hops` 和 diagnostics 摘要；下游仍以该真实有效状态为基线，并在提示中看到降级原因。

## 14. 兼容与发布

### 14.1 旧任务

- v2 计划继续走旧契约适配器。
- v2 运行中 checkpoint 不升级；任务从规划到发布始终使用创建时的 plan/schema 版本。
- 已有 `spatial_layout` 的历史结果不回填、不迁移。
- 新建 quality 任务使用 v3 + `spatial_state_version=1`。

### 14.2 下游兼容

- 发布前已经物化为完整 `spatial_layout`。
- 宫格生图、首帧队列、分镜编辑器和视频生成无需理解 `spatial_intent`。
- 日志同时保存原始 intent、物化后结果和 diagnostics，方便排查。

### 14.3 失败回滚

新计划带版本字段。若需回滚，只停止生成 v3 计划；v2 读取路径保留一个发布周期，不需要回滚数据库。

## 15. 测试设计

### 15.1 单元测试

- 特写镜头漏掉未离开角色，自动补为 offscreen。
- 未变化角色、道具和 `position_3d` 跨镜继承。
- `pickup/put_down/transfer/move/enter/exit` 状态转换。
- 多变化严格顺序、跨 space move 清旧 slot、角色 exit 时手持道具跟随。
- 道具唯一归属：禁止同时处于 holder、container slot 和 loose position。
- 唯一别名自动规范化；多义别名拒绝猜测。
- 空 anchor 列表时省略 anchor 不报错，自造 anchor 被清理。
- 非法变化不污染上一份规范状态。
- 同一输入重复执行得到完全一致输出。
- container path、loose position 和 nested container 的互斥物化。
- catalog 有 slot/anchor 坐标时强制派生 `position_3d`；无依据时 warning 且不伪造。

### 15.2 集成测试

- `none → inherit → inherit` 严格按真实 handoff 串行。
- 两个 `none` 段并发时状态互不污染。
- QC Agent 接收到物化后的完整 JSON。
- QC 耗尽强制接纳后，下一段继承最后有效状态。
- degraded handoff 的标志、诊断和 `degraded_hops` 能传到下游。
- v2 检查点可恢复，新 v3 任务不进入旧双重校验。
- 发布后的每个镜头仍包含完整 `spatial_layout`。
- v3 路径不调用旧 repair，`changed_positions` 只由 materializer 单向生成。

### 15.3 回归测试

- 速度/均衡模式提示词与结果不变。
- 场景层级硬门禁不变。
- 对话语言 QC、实体 ID 校验和发布流程不变。

## 16. 验收标准

1. quality 模式不再因未出镜但未离开的角色产生 `char_xxx:missing`。
2. `inherit` 段不存在 handoff 与规划期 continuity 的双重真源。
3. LLM 原始输出中未变化空间字段显著减少，发布结果仍为完整快照。
4. `ref_anchor_unknown` 不再因空白名单和可选 anchor 大量触发重试。
5. 单段平均输出 token 和空间类 QC 重试次数较上线前下降。
6. 跨段首镜仍能从上游最后镜恢复角色、关键道具和稳定位置。
7. 所有效果模式核心状态机、物化和校验代码均位于 enterprise 目录。
8. 监控每镜 LLM 输入/输出字符数以及 spatial 字段占比，确认输入没有因重复完整快照膨胀。
9. 监控 `spatial_alias_normalized`、`spatial_unplanned_change`、`spatial_planned_change_missing` 和 `_spatial_degraded` 发生率。
10. 监控 present 实体缺少 `position_3d` 的比例及其首帧投影 fallback 比例。

`location_id_not_reserved` 属于并发 registry/ID 预留问题，不把它作为本方案的直接成功指标；仅确认本方案不会增加该错误，根治仍由实体 ID 预留方案负责。

## 17. 实施顺序

1. 先实现 `SpatialCatalog`、规范状态、纯函数转换和黄金测试，不改 LLM 提示。
2. 增加 v3 计划 Schema、`initial_spatial_state` 编译期校验与 v2 固定分流。
3. 实现镜头级 intent 物化、字段矩阵覆盖和完整 `spatial_layout` 回写。
4. 立即联调 `none → inherit → inherit`、degraded handoff 和并发隔离。
5. 接入 quality strategy 钩子；同一改动中替换旧 repair/validator 路径并修复 `_shot_positions.position_3d`。
6. 更新阶段一、阶段二和 QC 提示词、扁平上下文投影及日志。
7. 完成单元、集成和回归测试，以新任务启用 v3，观察错误码、重试次数、token、degraded 与无 3D 比例。

## 18. 实现状态（2026-07-17）

本方案已完成代码接入。实际调用顺序固定为：

```text
阶段一 v3 规划
  → L0 规划编译：对照世界场景树绑定 locations + 新顶层硬门禁
  → 阶段二 LLM 输出艺术字段 + spatial_intent
  → enterprise materializer 按镜头应用规范状态机
  → L1 场景结构硬门禁（locations + space_unit/registry 引用）
  → 段级/跨段确定性校验
  → enable_qc 控制的规则 QC
  → 保存完整 spatial_layout 与规范 handoff
  → 全段完成后 L2 合并全量结构校验（兜底）
```

新顶层提前门禁细节见 `docs/script/script_split_early_new_root_location_gate.md`。

实现边界：

- `enterprise/services/script_split_quality/spatial_state.py`：`SpatialCatalog`、初始状态规范化及 `enter/move/exit/pickup/put_down/transfer` 纯函数状态转换。
- `enterprise/services/script_split_quality/spatial_materializer.py`：使用 `characters_present`/`props_present` 作为唯一可见性真源，保留摄影机与表演字段，确定性生成完整布局和兼容 `changed_positions`。
- `enterprise/services/script_split_quality/contract.py`：按 `schema_version` 固定分流；v2 不升级，v3 编译 `initial_spatial_state` 与 `planned_state_changes`。
- `enterprise/services/script_split_quality/strategy.py`：构建紧凑上下文、真实 handoff、物化钩子和诊断日志。
- `services/script_split_engine.py`：只调用通用策略钩子，不包含效果模式状态机；物化严格早于全部校验与 QC。
- `llm/script_parser.py`：`spatial_state_version=1` 时输出/记录原始 intent 并跳过旧空间 repair。

v3 检查点会保留 `_spatial_final_state`、`_spatial_diagnostics`、`_spatial_degraded` 和 `_spatial_degraded_hops`，供依赖段恢复和 handoff 使用；合并器只发布实体、空间世界和 `shot_groups`，这些内部字段不会进入最终故事板结果。

诊断语义：

- 非法引用或状态变化产生 error，该变化被跳过，最后有效状态不受污染，并标记 degraded。
- 合法但未规划的变化产生 `spatial_unplanned_change` warning，仍按实际镜头应用。
- 规划变化未被任何镜头消费产生 `spatial_planned_change_missing` warning；后端不会替模型执行。
- `spatial_*` warning 会并入规则 QC 报告供观察和后续智能 QC 判断，但 warning 本身不把 `report.passed` 改为 false。
- `planned_state_changes.change_id` 仅用于覆盖核对，`continuity.changed_positions` 只从实际接纳的 intent 单向生成。

日志位于 `logs/script_parser/`：

- `*_08_spatial_intent_raw.json`：LLM 清洗后的 v3 原始 intent。
- `script_split_task_*_spatial_materialized.json`：后端物化后的完整段 JSON。
- `script_split_task_*_spatial_diagnostics.json`：状态机与计划覆盖诊断。
- 既有 `*_01_system_prompt.txt`、`*_02_user_prompt.txt`、`*_03_qc_*` 保持不变。

验证结果：聚焦的契约、状态机、物化、handoff、引擎顺序、提示词与日志测试 79 项通过；扩展的拆分任务、租约恢复、空间投影、首帧宫格与 enterprise 服务测试 98 项通过。静态编译、阻塞调用红线检查和两个仓库的 `git diff --check` 均通过；阻塞检查仍会报告项目原有 R5 advisory warning，但没有新增 R4/R6 违规。
