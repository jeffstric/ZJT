# 效果模式剧本拆分：增量空间状态设计（B+）

## 1. 文档状态

- 状态：设计已确认，待实施
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

## 7. 阶段二增量输出

### 7.1 LLM 负责的字段

LLM 继续输出现有镜头艺术字段：

- `opening_frame_description`
- `scene_detail`
- `characters_present`
- `shot_type` / `camera_movement`
- 对话、动作、声音和情绪
- 相机与构图相关字段

效果模式新增质量专用临时字段 `spatial_intent`：

```json
{
  "spatial_intent": {
    "visible_character_ids": ["char_001"],
    "visible_prop_ids": ["prop_003"],
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
      "container_id": "container:sofa",
      "slot_id": "left",
      "position_3d": {"x": -0.4, "y": 0.2, "z": 0.0}
    },
    "prop_003": {
      "entity_type": "prop",
      "presence": "present",
      "space_unit_id": "spatial:hotel_suite",
      "container_id": "container:tea_table",
      "slot_id": "table_center",
      "holder_character_id": null
    }
  }
}
```

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
- 目标 slot 在空间目录中有固定坐标：可以确定性派生。
- 无坐标依据：保留 `space_unit_id/container_id/slot_id`，`position_3d` 留空；不得生成伪坐标。

## 9. 状态物化算法

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
2. ID 缺失但名称只匹配一个目录项：自动回写规范 ID，并记录 `spatial_alias_normalized` 信息。
3. 名称匹配多个目录项：不猜测，产生 `spatial_reference_ambiguous`。
4. anchor 不存在且不影响物理位置：删除非法可选 anchor，记录 warning。
5. 必需的 space/container 不存在：产生 error。

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
- 规划期目标状态与真实末镜不同：记录诊断，不再作为双重硬约束。

### 11.4 Error

- `spatial_reference_ambiguous`
- `spatial_entity_unknown`
- `spatial_transition_invalid`
- `spatial_destination_missing`
- `quality_cross_segment_spatial_mismatch`：下游首镜没有继承真实 handoff，且没有合法变化。
- `quality_segment_has_no_shots`

### 11.5 强制接纳

空间 QC 达到上限后继续遵循现有“采用最后一个可解析候选”策略，但规范状态不能被破坏：

- 非法变化不写入规范状态。
- 保留上一份最后有效状态并标记 `_spatial_degraded=true`。
- 下一依赖段继承真实有效快照，而不是规划猜测值。
- JSON/场景层级等既有 non-forceable 结构错误仍按原硬门禁处理。

## 12. 与现有 validator 的调整

1. `validate_spatial_contract()` 不再要求每个镜头由 LLM 自行重复完整位置。
2. `inherit` 段首镜只比较真实 handoff，不再同时比较规划期 `continuity_in`。
3. 末镜以物化后的真实状态为准；规划期 `continuity_out` 在 v3 中取消。
4. `quality_undeclared_spatial_change` 改为读取明确 delta；不再通过比较两份可能不完整的嵌套布局猜测移动。
5. `_shot_positions()` 必须保留 `position_3d`，修复当前跨段比较无法取得坐标的问题。
6. `ref_anchor_unknown` 对可选 anchor 降为可自动清理的 warning；必需空间引用仍为 error。

## 13. 并发与 handoff

- `mode=none`：使用独立初始状态，可与其他 ready 段并发。
- `mode=inherit`：必须等待 `from_segment_id` 完成并取得最后镜完整快照。
- 并发段只共享只读全局 registry 和 catalog，不共享可变状态。
- 每个 segment 的状态机从独立初始快照开始，避免跨协程写同一对象。
- handoff 必须来自已物化并校验后的最后镜，不得从 LLM 原始输出直接抽取。

## 14. 兼容与发布

### 14.1 旧任务

- v2 计划继续走旧契约适配器。
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
- 唯一别名自动规范化；多义别名拒绝猜测。
- 空 anchor 列表时省略 anchor 不报错，自造 anchor 被清理。
- 非法变化不污染上一份规范状态。
- 同一输入重复执行得到完全一致输出。

### 15.2 集成测试

- `none → inherit → inherit` 严格按真实 handoff 串行。
- 两个 `none` 段并发时状态互不污染。
- QC Agent 接收到物化后的完整 JSON。
- QC 耗尽强制接纳后，下一段继承最后有效状态。
- v2 检查点可恢复，新 v3 任务不进入旧双重校验。
- 发布后的每个镜头仍包含完整 `spatial_layout`。

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

## 17. 实施顺序

1. 增加 v3 计划 Schema 与 v2 兼容适配器。
2. 实现 `SpatialCatalog`、规范状态和纯函数转换。
3. 实现镜头级 intent 物化和完整 `spatial_layout` 回写。
4. 接入 quality strategy 钩子，调整 validator 执行顺序。
5. 更新阶段一、阶段二和 QC 提示词及日志。
6. 增加单元、集成和回归测试。
7. 以新任务启用 v3，观察错误码、重试次数、输出 token 和平均耗时。
