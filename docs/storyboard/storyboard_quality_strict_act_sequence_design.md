# 效果模式严格按幕串行生成方案

## 1. 背景

效果模式（`sequence_mode=quality`）的目标不是尽快生成全部分镜，而是优先保证跨幕的画面与空间连续性。正确的数据依赖应为：

```text
第 1 幕宫格生成并拆分回写
  -> 取得第 1 幕最后一个分镜首帧
  -> 作为连续性参考提交第 2 幕宫格
  -> 第 2 幕生成并拆分回写
  -> 取得第 2 幕最后一个分镜首帧
  -> 提交第 3 幕
  -> ...
```

2026-07-16 对故事板 26、首帧批次 63 的生产监控发现，当前实现会在等待上一幕超过
`QUALITY_PREVIOUS_REFERENCE_WAIT_MAX_TICKS` 后写入
`degraded_previous_group_reference=true`，然后不携带上一幕参考图继续提交。实际出现第 9 幕早于第 3、4、6 幕完成的情况。这种行为能缩短总耗时，但违反效果模式定义。

本次监控还发现，新建场景缺少参考图时会在等待达到上限后写入
`degraded_location_grid_reference=true`，直接降级生成分镜首帧。效果模式同样不应允许这种降级。

## 2. 目标

1. 效果模式严格按 `group_key` / 幕顺序串行，一次最多允许一个幕组进入宫格生成。
2. 后一幕提交时，必须使用前一幕最后一个分镜的已拆分首帧作为参考图。
3. 前一幕处于 `PENDING` 或 `RUNNING` 时，后一幕保持等待，不得因 tick 次数降级提交。
4. 前一幕失败、取消、超时，或完成后仍没有可用首帧时，停止后续幕，不允许无参考继续。
5. 当前幕引用的新场景/子场景没有参考图时，必须先完成场景宫格，不允许降级为纯文生图。
6. 效果模式的严格决策代码位于 `enterprise` 目录；核心目录只保留通用调度协议和持久化操作。
7. 不影响 `speed`、`balanced` 模式现有的并发和降级行为。

## 3. 非目标

- 本方案不改变剧本 LLM 分段、分镜 QC 或空间契约生成逻辑。
- 本方案不处理自动对白配音未提交问题；该问题应单独修复和验收。
- 本方案不要求新增数据库表或修改现有表结构。
- 本方案不把同一幕拆成多个并行宫格；单幕超过 9 个分镜时，仍按幕内 chunk 顺序串行。

## 4. 方案比较

### 方案 A：直接修改通用宫格服务

在 `services/storyboard_first_frame_grid_service.py` 中只选择最早的未完成幕，并删除超时降级。

优点：改动最少、实现最快。

缺点：效果模式的商业版核心规则继续留在通用目录，不符合项目对 enterprise 隔离的要求；后续容易再次把 balanced/quality 行为混在一起。

### 方案 B：Enterprise 严格策略 + 核心调度门面（推荐）

核心服务负责读取故事板、批次项和执行提交；enterprise 策略负责根据完整快照返回本 tick 唯一允许处理的幕，以及等待/失败原因。

优点：

- 满足效果模式核心代码必须放在 `enterprise` 的要求。
- 不修改表结构。
- 可以复用现有宫格提交、图片拆分和资产回写逻辑。
- `speed`、`balanced` 不受影响。
- 策略函数可用纯数据测试，容易覆盖严格串行边界。

缺点：需要增加一个小型策略接口，并调整当前服务的循环结构。

### 方案 C：新增幕级任务表和事件驱动状态机

为每一幕建立独立任务记录，完成事件负责激活下一幕。

优点：状态最明确，适合未来暂停、恢复、按幕重试和跨机器调度。

缺点：需要数据库迁移、任务恢复和历史兼容改造；以当前需求来看复杂度过高。

结论：采用方案 B。

## 5. 总体架构

### 5.1 核心层

`services/storyboard_first_frame_grid_service.py` 保留：

- 读取 storyboard、scene、batch item。
- 构建按顺序排列的幕组快照。
- 调用效果模式策略。
- 根据策略结果更新 item 状态或提交宫格。
- 调用现有 counts updater 结算批次。

核心层不再自行决定效果模式是否可以跨幕降级。

### 5.2 Enterprise 层

新增建议目录：

```text
enterprise/services/storyboard_quality_sequence/
  __init__.py
  strategy.py
  contract.py
```

职责：

- `contract.py` 定义只读快照和决策结果的数据结构。
- `strategy.py` 实现严格按幕选择算法。
- 每个 tick 最多返回一个可运行幕组。
- 返回明确的 `ready`、`waiting`、`failed` 决策及原因。

核心层通过延迟导入加载 enterprise 策略。社区版不会导入或执行商业版实现。

## 6. 幕组顺序与完成判定

### 6.1 排序

1. scene 按 `sort_order`、`id` 排序。
2. 幕组优先使用 `batch_item.group_key`。
3. 其次使用 `prompt_json.source.group_id`、`group_name`、`act_name`。
4. 缺少组信息的手工分镜继承前一个幕组；首个分镜缺少组信息时使用稳定的临时组键。

幕组顺序以其第一个 scene 的排序位置为准，不能使用字典遍历顺序或任务完成时间。

### 6.2 幕完成

一个幕组只有同时满足以下条件才算完成：

- 组内所有非 placeholder batch item 均为 `COMPLETED`。
- 每个 scene 都存在选中的 `first_frame` asset。
- asset 的 `result_url` 非空。
- 该幕最后一个 scene 的首帧 URL 可读取，能够传递给下一幕。

仅 `grid_image_tasks.status=COMPLETED` 不代表幕完成；必须等待宫格拆分和 scene asset 回写完成。

## 7. 严格调度状态机

每个调度 tick 按以下顺序执行：

```text
读取所有幕组
  -> 找到第一个未完成幕 G
  -> 检查 G 之前是否存在失败幕
       -> 是：阻断 G 及全部后续幕，结算批次失败/部分失败
  -> 检查 G 的上一幕
       -> 无上一幕：进入当前幕场景依赖检查
       -> 上一幕未完成：G 保持 PENDING，结束本 tick
       -> 上一幕完成但最后首帧 URL 缺失：记录一致性错误并停止批次
       -> 上一幕完成且 URL 有效：把 URL 作为 previous_group_reference
  -> 检查 G 使用的 location reference
       -> 已就绪：提交 G
       -> 场景宫格运行中：G 保持 PENDING，结束本 tick
       -> 缺图且没有任务：提交场景宫格；G 保持 PENDING
       -> 场景宫格终态失败：停止批次
  -> 提交 G 的一个宫格 chunk
  -> 结束本 tick，不扫描或提交后续幕
```

关键约束：即使 `QUALITY_GRID_BATCHES_PER_TICK > 1`，效果模式也只能用于同一幕内的受控 chunk；绝不能在同一 tick 提交多个不同幕组。

## 8. 上一幕参考图传递

下一幕提交宫格时，参考图必须来自上一幕最后一个 scene 的已拆分首帧：

```text
storyboard_scene.selected_first_frame_id
  -> storyboard_scene_asset.result_url
  -> previous_group_reference.url
  -> grid_image_tasks.reference_images
```

同时满足：

- URL 加入宫格生图请求的参考图列表。
- prompt 参考图说明中标明“前一幕最后一个分镜”。
- `storyboard_image_batch_item.extra_json.previous_group_scene_id` 保存来源 scene。
- `previous_group_reference_url` 保存实际使用的 URL，便于排查。
- `previous_grid_prompt_context` 可以继续作为风格和空间状态补充，但不能代替真实首帧 URL。

禁止使用整张宫格临时图作为下一幕参考；必须使用拆分后的单格首帧。

## 9. 场景与子场景依赖

效果模式下，当前幕使用的 location 没有 `reference_image` 时：

1. 查询是否存在 `item_type=5` 且状态为 queued/processing 的场景宫格任务。
2. 如果存在，当前幕严格等待。
3. 如果不存在，调用 `StoryboardLocationBootstrapService.submit_subscene_grids()` 提交场景宫格。
4. 如果是新建顶层场景且无法通过子场景宫格生成，需要走明确的顶层场景参考图生成入口。
5. 场景生成失败时停止当前批次，不允许设置 `degraded_location_grid_reference=true`。

`submit_subscene_grids()` 的调用应接入发布或首帧批次启动阶段，不能只执行 `bootstrap()` 创建数据库行。

## 10. 超时与失败语义

### 10.1 上一幕仍在运行

- 后一幕可以无限期保持 `PENDING`，但上游宫格任务本身仍受已有任务 watchdog 管理。
- `previous_group_reference_wait_count` 仅作为诊断计数，不再触发降级。
- 上游 watchdog 把任务变为失败后，再按终态失败处理。

### 10.2 上一幕终态失败

- 不提交后一幕。
- 当前及后续幕写入 `dependency_failed`。
- `failure_source=previous_group_failed`。
- 批次结算为 `failed` 或 `partial`。
- 用户点击重试后，新批次从第一个没有成功首帧的幕开始，仍按严格串行规则推进。

### 10.3 上一幕完成但首帧缺失

这是数据一致性异常，不是可降级场景：

- 等待计数达到诊断上限后标记 `previous_group_reference_timeout`。
- 不调用 `_ready_items()`，不提交下一幕。
- 禁止写入 `degraded_previous_group_reference=true`。

### 10.4 场景参考图缺失

- 有运行任务：持续等待。
- 无运行任务：主动补提场景任务。
- 场景任务终态失败：当前幕失败，后续幕依赖失败。
- 禁止写入 `degraded_location_grid_reference=true`。

## 11. 历史任务兼容

- 对尚未完成的旧 quality 批次，如果 item 已写入 `degraded_*` 但还未提交 `ai_tool_id`，清除降级标记并重新进入严格等待。
- 已经提交或完成的旧幕不回滚、不删除资产。
- 从“第一个没有完整首帧的幕”开始恢复严格串行。
- `speed`、`balanced` 继续保留现有 fallback 行为。
- 不需要数据库迁移；兼容字段继续存放在 `extra_json`。

## 12. 错误码与可观测性

建议统一使用：

| 错误码 | 含义 |
|---|---|
| `previous_group_failed` | 上一幕生成失败 |
| `previous_group_reference_timeout` | 上一幕显示完成但最终首帧 URL 缺失 |
| `location_reference_generation_failed` | 当前幕场景参考图生成失败 |
| `quality_sequence_contract_broken` | 数据状态违反严格串行契约 |

日志至少包含：

- batch id、当前幕 group key、幕序号。
- 上一幕最后 scene id、asset id、reference URL 是否存在。
- 当前决策：waiting / submit / fail。
- 等待原因和上游任务 id。
- 实际提交时使用的上一幕参考 URL。

## 13. 测试方案

### 13.1 Enterprise 策略单元测试

1. 第一幕未完成时只返回第一幕，第二幕不可运行。
2. 第一幕运行超过 30 tick，第二幕仍不可运行。
3. 第一幕完成并有拆分首帧后，第二幕变为 ready。
4. 返回给第二幕的 reference URL 必须是第一幕最后一格，不是宫格原图。
5. 第一幕失败时第二幕和后续幕返回 dependency failure。
6. 第一幕完成但 URL 缺失时不能降级提交。
7. 同一 tick 不得返回两个不同幕组。

### 13.2 核心服务集成测试

1. 构造 3 幕任务，首次 tick 只调用一次第一幕 `submit_grid_image_task`。
2. 第一幕 running 时重复 tick，不提交第二、三幕。
3. 第一幕拆分回写后，下个 tick 只提交第二幕。
4. 验证第二幕请求的 `reference_images` 包含第一幕最后首帧。
5. 第二幕失败后，第三幕永远不提交，批次能结算到终态。
6. 新子场景无图时先提交 `item_type=5`，不能提交 `item_type=8`。
7. 场景图完成后才提交当前幕首帧宫格。

### 13.3 回归测试

- `speed` 仍可全量并行。
- `balanced` 仍维持现有组内依赖行为。
- quality 单幕任务正常生成。
- quality 单幕超过 9 个分镜时，幕内 chunk 串行，不能与下一幕交叉。
- 宫格失败、下载失败、拆分失败和 scene 删除均可正常结算。
- Windows、Linux、macOS 下不依赖路径分隔符或平台特定锁。

## 14. 实施步骤

1. 在 enterprise 新增严格幕序策略及纯数据契约。
2. 先补充会复现生产并发问题的失败测试，确认当前实现会错误提交后续幕。
3. 调整 `StoryboardFirstFrameGridService.process_job()`，每个 tick 只消费策略返回的一个幕组。
4. 删除效果模式的 `degraded_previous_group_reference` 提交路径。
5. 删除效果模式的 `degraded_location_grid_reference` 提交路径。
6. 接入场景/子场景宫格自动提交，并严格等待参考图回写。
7. 增加失败传播和批次结算逻辑。
8. 更新效果模式相关文档，删除“超时后降级继续”的描述。
9. 运行定向测试、storyboard 服务回归测试和阻塞调用检查。
10. 使用独立测试故事板验证至少 3 幕：确认数据库中任意时刻只有一个幕组 running，且下一幕请求包含上一幕最后首帧 URL。

## 15. 验收标准

以下条件必须全部满足：

1. 效果模式任意时刻最多只有一个幕组的 `item_type=8` 宫格处于 queued/processing。
2. 第 N+1 幕宫格创建时间晚于第 N 幕全部 scene asset 回写时间。
3. 第 N+1 幕的 `reference_images` 包含第 N 幕最后分镜的已拆分首帧 URL。
4. 上一幕失败时，后续幕没有 `ai_tool_id`，也没有对应 grid task。
5. 新场景缺图时先完成场景参考图，不出现 `degraded_location_grid_reference=true`。
6. 运行全程不出现 `degraded_previous_group_reference=true`。
7. `speed`、`balanced` 行为和吞吐量不受影响。

