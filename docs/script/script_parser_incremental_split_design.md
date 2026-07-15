# 剧本分段拆分与断点续传设计

## 1. 文档信息

- 日期：2026-07-13
- 状态：已实施（后端核心 + 前端适配），2026-07-14
- 核心实现：`llm/script_parser.py`
- Web 入口：`POST /api/parse-script`
- 故事板入口：`POST /api/storyboard/{storyboard_id}/generate-from-script`
- 前端入口：视频工作流剧本节点、故事板“从剧本生成分镜”弹窗

## 2. 背景与问题

当前 `parse_script_to_shots()` 将完整剧本一次性提交给大模型，并要求一次性返回包含角色、场景、道具、空间世界和全部分镜组的完整 JSON。长剧本会产生非常大的响应，存在以下问题：

1. 任意位置出现未转义引号等 JSON 语法错误，整份结果无法解析。
2. 模型达到输出上限时，最后一个镜头可能在任意字段中间被截断。
3. 当前末尾补括号修复只能处理极少数纯截断情况，无法修复前部语法错误。
4. 失败后只能重新请求完整结果，已经正确生成的几十个镜头无法复用。
5. `/api/parse-script` 和故事板生成接口需要等待整个 LLM 调用及后处理完成，容易超过浏览器、反向代理或网关超时。
6. 故事板质检重试仍要求重新输出完整 JSON，进一步放大耗时、token 消耗和失败概率。

`logs/script_parser/script_parser_20260713_221538_07_fixed_attempt.txt` 同时出现了前部未转义引号和第 64 镜中途截断，说明仅提高 `max_tokens` 或补全末尾括号无法从根本上解决问题。

## 3. 设计目标

1. 使用模型理解剧本语义并规划分段，不按固定字符数机械切割。
2. 每一段独立调用现有剧本拆分逻辑并独立验证。
3. 已通过的段持久化为检查点，失败时只重新生成当前段。
4. 服务重启、页面刷新或 HTTP 请求结束后仍可继续。
5. 两个现有入口统一改为异步任务和前端轮询。
6. 所有分段通过并完成全局合并校验后，才一次性创建前端节点或故事板分镜。
7. 最大限度复用 `llm/script_parser.py` 中已有提示词、参数、资产匹配、清理、空间连续性修复、分组重排和质检逻辑。
8. 保持最终 `parsed_data` 格式兼容现有下游。

## 4. 非目标

首版不实现 LLM 流式 NDJSON，不要求模型在一条长连接中持续推送镜头。不同供应商的流式协议差异较大，而且单条 JSON 内部仍可能发生语法错误。首版采用多次短请求，每次返回一个完整且可独立验证的 JSON。

首版不在单段完成后立即创建前端节点。前端只显示进度，最终合并校验通过后再物化节点，避免出现半成品工作流。

## 5. 总体架构

系统分为两个模型阶段和一个最终发布阶段：

```text
提交任务
  -> 阶段一：模型规划语义分段
  -> 校验并持久化分段计划
  -> 阶段二：按顺序调用现有 script_parser 生成每一段
       -> 单段解析
       -> 单段验证
       -> 保存检查点
       -> 失败时只重试当前段
  -> 合并全部分段
  -> 全局规范化与质检
  -> 发布最终结果
```

阶段一模型只决定“从哪里分段”，不生成角色、场景、道具、空间世界或具体分镜。阶段二继续使用现有剧本拆分能力，避免维护第二套分镜提示词和字段协议。

## 6. 阶段一：模型语义分段

### 6.1 稳定文本锚点

后端不决定分段边界，只对原始剧本建立稳定锚点，供模型返回可验证的边界。

锚点优先使用自然段；对没有自然段的文本，可以按现有换行、场景标记、镜头标记和完整句子建立更细粒度锚点。锚点化不得改变原文内容或顺序，也不得根据固定字符数直接决定最终分段。

示例：

```json
[
  {
    "block_id": "block_0001",
    "start_line": 1,
    "end_line": 4,
    "content_sha256": "...",
    "content": "## 场景1：星湖湾别墅·主卧 - 清晨"
  },
  {
    "block_id": "block_0002",
    "start_line": 5,
    "end_line": 12,
    "content_sha256": "...",
    "content": "晨光透过白纱窗帘……"
  }
]
```

### 6.2 分段规划提示词

规划模型获得完整锚点化剧本，并按照以下语义判断分段：

- 场景、幕、地点和时间变化。
- 一段完整的叙事动作或情绪单元。
- 对白轮次和动作—反应关系。
- 空间连续性与人物位置连续性。
- 空间布局复杂度和 JSON 输出规模。
- 不在一句对白、一个连续动作或关键转场中间切断。

不能用“每 N 个字符一段”代替语义分段规划。模型仍根据剧情语义选择主要边界；为保证后续分镜生成稳定性，每段原文同时受 1500 字硬上限约束。

规划提示词同时给出“单段最大输出 token”和“原文不超过 1500 字”。模型仍必须优先保持语义完整。后端在还原原文时执行最终硬检查：多 block 超限段优先沿 block 边界继续切细，单 block 超限时依次寻找空行、换行和句末标点，最后才按字符上限兜底。该后处理只收紧模型已经确定的段内范围，不跨模型语义边界重新组合文本。规划阶段不预估镜头数量，实际镜头数完全由后续分镜生成模型决定。

### 6.3 分段计划协议

```json
{
  "schema_version": 1,
  "segments": [
    {
      "segment_id": "seg_0001",
      "block_ids": ["block_0001", "block_0002", "block_0003"],
      "title": "主卧清晨",
      "summary": "苏晚醒来观察熟睡的林诚",
      "continuity_notes": "结束时两人仍位于主卧"
    }
  ]
}
```

### 6.4 后端计划校验

后端不替模型重新分段，只验证：

1. `segment_id` 唯一且顺序稳定。
2. 所有 `block_id` 均来自原始锚点集合。
3. 每个锚点恰好出现一次。
4. 分段顺序与原文一致。
5. 单个分段的 `block_id` 连续，不允许跨过未包含的文本。
6. 不允许空分段。

如果计划 JSON 或覆盖校验失败，只重试阶段一。规划成功后将计划持久化，正常执行路径不重复调用规划模型。1500 字硬限制在计划持久化之前完成，因此阶段二不再自动触发局部再规划，也不会删除并重建已经存在的 segment 检查点。

阶段二发生 `MAX_TOKENS`、重复截断或调用失败时，只在当前分段的有限重试范围内处理；执行失败达到上限后当前段保留为 `failed`，根任务进入 `paused`，由用户恢复后重试该段。质检失败采用不同终态：拆分与质检最多循环 `qc_max_rounds` 次，仍不通过时将最后一轮已经成功解析的完整 JSON 强制保存为 `completed`，保留带 `_forced_accept=true` 的质检问题后继续合并发布。该线性失败路径避免 `planning/replan → generating → planning` 循环和检查点重建复杂度，同时不会让非致命质检问题永久阻塞拆分。

段级生成严格遵守“一次 scheduler tick 最多一次 LLM 调用”。本轮解析成功但 QC 未通过时，segment 立即持久化最近一次完整 `parsed_result_json`、结构化 `validation_errors` 和重试计数，然后正常结束当前 tick、释放租约；下一 tick 再把这些检查点作为 `previous_parsed_result + qc_feedback` 发起一次定向修复。网络失败计数与 QC 修正轮次分别保存在错误元数据中，互不挤占预算。禁止在一个 `step_generate_segment()` 内循环发起多次模型请求，否则多轮请求会错误共享同一个 worker watchdog 时限。

## 7. 阶段二：复用现有 script_parser 逐段拆分

### 7.1 复用原则

保留 `parse_script_to_shots()` 作为核心拆分函数，不另写一套分镜字段定义。需要做的改造以参数化和函数提取为主：

1. 继续使用 `SCRIPT_PARSER_SYSTEM_PROMPT`。
2. 继续使用现有数据库角色、场景和道具加载逻辑。
3. 继续使用语言、模型、思考模式、多人对白拆分、强制中景、无背景音乐等参数。
4. 继续使用现有 JSON 示例和业务规则。
5. 继续使用 `sanitize_parsed_prop_references()`。
6. 继续使用 `sanitize_parsed_location_references()`。
7. 继续使用 `repair_spatial_layout_continuity()`。
8. 继续使用 `reorganize_shot_groups()`。
9. 继续使用 `script_split_qc_agent`，但将问题映射到对应分段后局部重试。

### 7.2 建议增加的可选上下文

为 `parse_script_to_shots()` 增加可选的分段上下文，默认值为空，保证原调用兼容：

```python
segment_context: Optional[Dict[str, Any]] = None
strict_json: bool = False
```

不新增 `retry_feedback`。分段重试复用现有的 `previous_parsed_result` 和 `qc_feedback`：

- JSON 根本无法解析时，没有合法的 previous result，只传结构化 `qc_feedback`。
- JSON 可解析但业务校验失败时，把当前段合法 JSON 作为 `previous_parsed_result`，把段级问题列表作为 `qc_feedback`。
- 全局质检定位到某段时，同样通过这两个现有参数重拆该段。

实现中，段级生成循环会保留最近一次可解析的当前段 JSON。业务校验失败后的下一轮同时传入该 JSON 和 `qc_feedback`；超时、网络失败或 JSON 解析失败不会用空值覆盖此前可用结果。重试提示要求返回包含 `characters`、`locations`、`props`、`spatial_world`、`shot_groups` 的当前段完整 JSON，而不是只返回 `shot_groups`。

现有 `qc_retry_block` 需要增加“当前为单段修复，只输出当前 segment”的模式说明，但不建立第二套反馈注入机制。

`segment_context` 包含：

```json
{
  "task_id": 123,
  "segment_id": "seg_0003",
  "segment_index": 3,
  "total_segments": 8,
  "accepted_registry": {
    "characters": [],
    "locations": [],
    "props": [],
    "spatial_world": {}
  },
  "previous_tail_summary": [],
  "continuity_state": {},
  "id_reservations": {
    "character_start": "char_007",
    "location_start": "loc_011",
    "prop_start": "prop_005"
  },
  "source_block_ids": ["block_0010", "block_0011"]
}
```

现有普通调用不传这些参数时，行为保持不变。持久化分段任务传入上下文后，提示词增加以下约束：

- 只为当前分段正文生成分镜。
- 历史摘要只用于保持连续性，不得重复生成历史镜头。
- 优先复用已接受的角色、场景、道具和空间 ID。
- 当前分段首次出现的新实体只能使用后端预留的下一段全局 ID，不能从 `char_001`、`loc_001`、`prop_001` 重新编号。
- 分镜编号可以是段内编号，最终由后端统一重排。

### 7.3 上下文控制

后续请求不携带所有历史完整 JSON，只携带：

- 已合并的精简资产注册表。
- 上一段最后一至两个镜头摘要。
- 上一段结束时的空间连续性状态。
- 已完成分段 ID。
- 当前失败段的结构化错误反馈。

这样可以利用历史记录继续生成，同时避免输入上下文随分段数量无限增长。

### 7.4 单段输出

为了最大限度复用，单段仍返回现有完整顶层格式：

```json
{
  "script_title": "...",
  "total_duration": 32,
  "style": "...",
  "characters": [],
  "locations": [],
  "props": [],
  "spatial_world": {},
  "shot_groups": []
}
```

任务从第一段开始维护唯一的 `accepted_registry`。后续模型必须直接复用其中的全局 ID；后端不在合并阶段对深层空间结构做无约束的通用 ID 重写。

实体处理规则：

1. 数据库主键相同或规范化名称相同的实体必须复用已有全局 ID。
2. 新实体只能使用当前段预留的下一组 `char_NNN`、`loc_NNN`、`prop_NNN` ID。
3. 当前段校验通过后，新实体才原子加入 `accepted_registry`，预留游标随之推进。
4. 模型给同一实体分配新 ID、复用已占用 ID，或引用未登记 ID 时，拒绝当前段并通过 `qc_feedback` 要求重输出。
5. 只在最终阶段重排 `group_id`、`shot_id` 和 `shot_number`；角色、场景、道具、空间单元、锚点和槽位 ID 一旦接受便保持稳定。

空间引用校验使用只读的“`accepted_registry` + 当前候选段顶层实体”联合视图。这样当前段新声明的角色、地点和道具可以被本段 `spatial_layout` 引用，但不会提前写入正式 registry；实体 ID 规则与空间引用规则全部通过后才执行原子提交。未在历史 registry 或当前段声明的 ID 仍按 unknown 引用拒绝。

### 7.5 `spatial_world` 与 `spatial_layout` 的统一 ID 策略

空间结构是本方案实现风险最高的部分，不能依靠一个通用递归替换器事后猜测引用含义。首版采用“模型直接复用任务级 ID + 后端逐路径验证”的方式：

1. `accepted_registry.spatial_world` 作为权威注册表随每段上下文传入。已有 `space_unit_id`、`frame_id`、`anchor_id` 的含义和坐标轴不得重定义。
2. 新空间只能追加到 `spatial_world.space_units[]`。新 `space_unit_id` 必须基于已预留的全局 owner ID，并保证任务内唯一。
3. `anchor_id` 在对应 `space_unit_id` 范围内唯一；同一空间后续段必须复用已有 anchor，不能因镜头构图变化换 ID。
4. 容器和槽位沿用已有 `prop_id/container_id/slot_id`；真实移动只能通过 `continuity.changed_positions[]` 表达。
5. 后端建立空间引用索引并逐项验证以下路径：
   - `spatial_world.space_units[].owner_id/location_ids/coordinate_frame.frame_id/anchors[].anchor_id`
   - `shot.spatial_layout.space_unit_refs[]`
   - `camera_pose.space_unit_id`
   - `camera_anchor.relative_to_character.character_id`
   - `location_path[].location_id`
   - `containers[].prop_id/container_id` 及 `slots[].space_unit_id/anchor_id/slot_id/character_id`
   - `loose_positions[].space_unit_id/anchor_id/character_id`
   - `continuity.changed_positions[].character_id/from_container_id/from_slot/to_container_id/to_slot`
6. 任一引用不存在、重复定义改变语义或坐标轴不一致时，拒绝当前段并通过 `qc_feedback` 要求模型复用正确 ID；不接受后端静默深层改写。
7. 为复用现有空间后处理，段级检查会构造“已接受结果 + 当前候选段”的临时完整数据，再调用现有 `repair_spatial_layout_continuity()`；只有候选段通过后才写入检查点。

该策略把复杂度放在明确的引用完整性校验上，避免对 `space_unit_refs`、containers、slots、loose positions 和 changed positions 做不可靠的批量重写。

## 8. 单段校验与重试

每段生成后按顺序执行：

1. JSON 语法解析。
2. 基于 `shot_groups` 的顶层必需字段验证。
3. `shot_groups`、`shots` 类型和空值验证。
4. 必填镜头字段验证。
5. 角色、场景和道具引用验证。
6. 分镜组时长验证。
7. 对话、景别、`presentation` 等现有业务规则验证。
8. 与上一段连续性状态校验。
9. 资产清理、空间修复和分组重排。

规则质检中的角色首帧检查以 `characters_present` 的全局 ID 为输入，但不直接在描述文本中搜索 `char_NNN`。执行时先合并任务级 `accepted_registry.characters` 与当前候选段的 `characters`，建立 ID 到角色名称的映射，再严格检查 `opening_frame_description` 是否包含 `【【角色名】】`。这样既保持镜头引用使用稳定 ID，也支持后续分段引用此前已经接受、当前段不再重复声明的角色。

无对白镜头占比只保留为 QC 诊断统计，不作为质检失败条件，也不再推断原剧本是否含对白。这样不会误伤压抑氛围、默剧或纯视觉叙事。质检问题进入重拆提示时必须保留原始 `severity`、`shot_ref` 和 `field`，便于模型只修复准确镜头与字段。

持久化任务使用 `strict_json=True`，不接受通过“查找最后一个 `]` 再补 `}`”得到的部分结果。语法错误和截断都必须重试当前段，防止把不完整分镜误判为成功。

合并阶段读取分段列表时，`ScriptSplitSegmentModel.get_all()` 和 `get_completed()` 必须显式使用数据库封装的 `fetch_all=True`。`execute_query()` 默认不抓取结果集；遗漏该参数会把数据库中真实存在的完成检查点误读为空列表，并错误产生 `invalid_segment_checkpoint_state: completed=0`。

现有 `validate_parsed_script()` 仍校验旧的顶层 `shots` 结构，仓库中没有其他调用方。实施时直接将它修正为当前 `characters + locations + shot_groups[].shots[]` 协议，并拆出可复用的段级/全局校验选项，不再另写一套互相漂移的验证器。

现有兼容修复分支在补括号成功后会提前 `return`，跳过资产清理、空间修复、分组重排和 metadata。实施时必须同时修正：

- `strict_json=True`：完全禁用末尾补括号，解析失败交给当前段重试。
- `strict_json=False`：保留兼容修复能力，但补全成功后只能给 `parsed_data` 赋值，必须继续执行与正常 JSON 相同的完整校验和后处理，禁止提前返回。

重试分为：

- JSON、Schema、业务错误：携带错误列表立即重试当前段。
- LLM 限流、网络异常：指数退避后重试当前段。
- 鉴权失效：任务进入 `waiting_auth`，用户恢复页面后使用新 token 继续。
- 达到单段最大尝试次数：任务进入 `paused`，保留全部已完成段。
- 模型返回 `MAX_TOKENS`、连续截断或重复校验失败：当前段在有限次数内携带反馈重试，耗尽后进入 `paused`，不重建分段计划。

单次段级 LLM coroutine 使用 `LLM_CALL_TIMEOUT_SECONDS`，底层 HTTP 使用 `LLM_HTTP_TIMEOUT_SECONDS`，整个调度步骤使用更大的 `WORKER_STEP_TIMEOUT_SECONDS`。三者满足 `HTTP < LLM call < worker step`，为异常转换、检查点写入和租约释放保留余量。worker watchdog 触发时根任务进入可恢复的 `paused` 并保留 `active_key` 和 segment 检查点，不再进入终态 `failed`。

用户点击继续后根据持久化检查点恢复：已有最终结果或发布阶段错误恢复到 `publishing`；已有分段计划恢复到 `generating`，只重试当前失败段；尚无计划才恢复到 `queued` 重新规划。对于因重试耗尽进入 `paused` 的生成阶段任务，恢复动作会先把当前未完成段的 `_qc_round` 和 `_call_failure_count` 重置为 0，开启新的重试周期；`parsed_result_json`、错误反馈和全生命周期 `attempt_count` 保留用于定向修复与诊断。显式的零值计数不会再被历史 `attempt_count` 覆盖。重试提示要求模型重新输出当前段完整 JSON，不输出 diff。

## 9. 分段合并与全局校验

全部段成功后，按 `segment_index` 合并：

1. 按 `accepted_registry` 汇总角色、场景、道具和 `spatial_world`。
2. 验证所有镜头已经直接引用任务级稳定 ID，不在此阶段深层改写空间 ID。
3. 按原文顺序拼接 `shot_groups`。
4. 统一生成 `group_id`、`shot_id` 和 `shot_number`。
5. 重新计算总时长和 metadata。
6. 再执行一次资产清理、空间连续性修复和分组重排。
7. 验证原始 `block_id` 完整覆盖。
8. 执行现有拆分质检。

场景引用清理不能只依赖分段 JSON。进入合并阶段后，worker 必须根据任务的
`world_id` 异步加载该世界的完整场景树，并把它传给
`sanitize_parsed_location_references()`：数据库中真实存在的
`location_db_id` 与对应 `shot.location_id` 必须保留；`location_db_id=null`
的新场景继续保留，交给发布阶段的场景资产化逻辑创建；只有无法在当前世界中
核实的非空数据库 ID 才按模型幻觉清除。同步数据库查询通过
`asyncio.to_thread()` 执行，不能阻塞 Web 或调度器的事件循环。

每个内部镜头在最终发布前保留来源信息：

```json
{
  "_segment_id": "seg_0003",
  "_source_block_ids": ["block_0010", "block_0011"]
}
```

质检问题由 `shot_id` 映射回分段：

- 单段字段问题只重新生成对应段。
- 跨段连续性问题从最早受影响段重新生成。
- 纯编号、排序和 metadata 问题由后端修复，不调用模型。

最终对外返回前移除内部来源字段，保持下游协议兼容。

## 10. 为什么必须改为异步任务

即使单次 LLM 调用设置了 300 秒超时，多个分段串行执行的总时间也可能达到数分钟。继续让浏览器等待一个 HTTP 请求会面临：

- 浏览器主动取消。
- Nginx、网关或负载均衡器超时。
- 应用进程重启导致连接断开。
- 用户刷新页面后无法获取已完成进度。

因此 Web 请求不能等待所有分段完成。提交接口只创建持久化任务并返回 `202`，前端定期轮询状态。

## 11. 持久化数据模型

采用专用表，不直接复用 `async_tasks`。虽然 `async_tasks` 名义上是通用异步任务表，但当前实际 driver 协议是“提交外部服务 -> 保存 `external_task_id` -> 轮询外部 `project_id` -> 产出 `result_url`”，`task/runninghub_async_task.py` 的 `DRIVER_MAP` 也只注册 RunningHub 外部任务。

剧本拆分属于内部多阶段编排，需要分段检查点、规划版本、真实进度、连续性状态、活动任务幂等键、协作式取消和故事板发布状态。若复用 `async_tasks`，仍需向通用表加入这些专属字段并改造外部 driver 生命周期，耦合成本高于专用根任务表。因此采用 `script_split_task + script_split_segment`，但调度方式复用现有 APScheduler。

### 11.1 `script_split_task`

```text
id
user_id
source_type                  video_workflow / storyboard / cli
source_id
source_node_key
active_key
script_sha256
script_content
request_config
status
phase
progress
plan_revision
segment_plan_json
current_segment_index
total_segment_count
completed_segment_count
accepted_registry_json
continuity_state_json
final_result_json
last_error_code
last_error_message
auth_token
cancel_requested
worker_id
lease_until
create_at
update_at
completed_at
```

状态：

```text
queued
planning
generating
merging
validating
publishing
completed
paused
waiting_auth
cancelling
failed
cancelled
```

`active_key` 根据用户、来源、剧本哈希和拆分配置生成，并建立 `UNIQUE KEY uk_script_split_active_key(active_key)`。任务进入 `completed/failed/cancelled` 等不可恢复终态时将 `active_key` 置为 `NULL`，利用 MySQL 允许多个 `NULL` 的特性保留历史记录。

提交接口直接尝试插入；并发冲突时通过唯一键捕获并回查已有任务，或使用不覆盖任务参数的 `INSERT ... ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)`。不能仅使用“先查询再插入”，否则并发请求仍会创建重复任务。

### 11.2 `script_split_segment`

```text
id
task_id
segment_index
segment_id
source_block_ids
source_content
source_sha256
status
attempt_count
raw_response
parsed_result_json
validation_errors
continuity_in_json
continuity_out_json
create_at
update_at
completed_at
```

唯一约束：

```text
UNIQUE(task_id, segment_index)
UNIQUE(task_id, segment_id)
```

实施时必须新增 Alembic 迁移，并同步新增 model 文件及文件末尾建表 SQL。JSON 和文本字段使用 `utf8mb4`，保证中文和表情符号安全。

两个新表统一使用 `create_at/update_at`，遵循故事板和 `download_queue` 相邻模型惯例；终态时间使用任务表中普遍存在的 `completed_at`。

## 12. APScheduler 执行与崩溃恢复

不能只使用 FastAPI `BackgroundTasks` 或内存中的 `asyncio.create_task`，因为进程重启后内存任务会丢失。也不新增独立常驻 Worker 进程。

剧本拆分消费者注册到现有 `task/scheduler.py:init_scheduler()`。由于处理函数是异步函数，注册方式沿用现有任务的 `_run_async_task` 包装，而不是让 `BackgroundScheduler` 直接调用 coroutine：

```text
script_split_job = partial(
    _run_async_task,
    process_script_split_tasks,
)
scheduler.add_job(
    script_split_job,
    IntervalTrigger(seconds=配置值),
    id="process_script_split_tasks",
    max_instances=1,
    coalesce=True
)
```

仓库根目录 `scheduler.lock` 已通过 `msvcrt.locking/fcntl.flock` 保证只有一个调度器进程运行，因此正常情况下不存在多个调度器竞争同一任务。`worker_id/lease_until` 仍按 `model/download_queue.py:claim_pending()` 的成熟模式保留，用于原子领取和调度器进程崩溃后的超时回收，而不是为了建立另一套多进程 Worker 架构。

每次 scheduler tick 最多推进一个任务的一个有限步骤：

1. 原子领取一个 `queued`、可继续或 `lease_until < NOW()` 的任务，写入 `worker_id/lease_until`。
2. 只执行规划、一个分段、合并校验或发布中的一个步骤。
3. 步骤完成后立即保存检查点并释放 `worker_id/lease_until`。
4. 下一次 tick 再推进后续步骤。

这样避免一个 APScheduler job 连续占用数十分钟，也让取消、暂停和进度查询能在段间及时生效。租约时长必须大于单步 LLM transport timeout 与外层 `wait_for` 预算，防止同一步骤尚未结束就被回收。

所有异步 Web 接口中的同步数据库访问使用 `asyncio.to_thread()`。现有同步 LLM 客户端在线程中调用，并使用 `config/constant.py` 中明确的请求超时。禁止无超时的 `Future.result()`，也不使用临时 `ThreadPoolExecutor` 包装 `asyncio.run()`。

## 13. API 设计

### 13.1 视频工作流提交

保留：

```http
POST /api/parse-script
```

响应改为：

```json
{
  "code": 0,
  "message": "剧本拆分任务已创建",
  "data": {
    "task_id": 123,
    "status": "queued",
    "status_url": "/api/script-split/tasks/123"
  }
}
```

HTTP 状态码为 `202 Accepted`。

### 13.2 故事板提交

保留：

```http
POST /api/storyboard/{storyboard_id}/generate-from-script
```

同样返回 `202` 和任务 ID。相同故事板已有活跃任务时返回原任务，而不是重复生成。

### 13.3 通用任务接口

```http
GET  /api/script-split/tasks/{task_id}
GET  /api/script-split/tasks/{task_id}/result
GET  /api/script-split/active-task?source_type={type}&source_id={id}&source_node_key={key}
POST /api/script-split/tasks/{task_id}/resume
POST /api/script-split/tasks/{task_id}/cancel
```

活跃任务查询使用独立静态路径，避免与 `/tasks/{task_id}` 的动态路由匹配顺序冲突。

通用任务接口同时支持两类调用方：Agent 使用交换后的短期 `auth_token`，通过
`Authorization: Bearer <auth_token>` 解析真实用户；浏览器继续使用
`X-User-Id`。有效 Authorization 优先于 Header；Authorization 缺失或因本地缓存
过期而无效时，合法 `X-User-Id` 仍可回退，避免影响现有页面。Agent 不发送
`X-User-Id`，因此无效 Agent Token 会返回 `401`。身份解析后仍必须校验任务所有权。

`resume` 不统一回到 `queued`：发布检查点恢复 `publishing`，分段计划检查点恢复 `generating`，无计划任务恢复 `queued`。`waiting_auth` 在刷新 token 后也遵循同一规则，避免已有计划的任务重新进入 `planning` 后空转。

故事板进度弹框中的“重试”会先回到拆分配置页。用户再次确认生成时，后端仍按 `active_key` 幂等提交：如果配置未变化且命中 `paused/waiting_auth` 任务，则刷新当前请求的 token，并复用上述检查点规则自动恢复原任务；如果命中的是正在执行的任务，则只返回原任务而不重置状态；如果配置发生变化，则 `active_key` 不同，正常创建新任务。这样既允许修改拆分配置，也不会让未修改配置的旧任务永久停留在 `paused`。

状态响应保持轻量：

```json
{
  "task_id": 123,
  "status": "generating",
  "phase": "segment_generation",
  "progress": 46,
  "completed_segments": 4,
  "total_segments": 9,
  "current_segment": 5,
  "message": "正在拆分第 5/9 段",
  "poll_after_ms": 3000
}
```

最终大 JSON 只通过 `/result` 获取，避免每次轮询重复传输完整结果。

### 13.4 协作式取消

`cancel` 接口只设置 `cancel_requested=1`，不尝试强杀正在执行同步 HTTP 请求的线程。调度步骤在以下位置检查取消标记：

- 领取任务后、调用模型前。
- 模型调用返回后、解析和保存结果前。
- 合并前和故事板发布前。

如果取消发生在单次 LLM 调用中，状态返回 `cancelling`；最迟在该调用正常返回或 transport timeout 后生效。当前响应会被丢弃，不写入已完成段，也不会启动下一段。若取消发生时任务未持有租约，worker 会在下一个 tick 领取 `cancelling` 并直接转为 `cancelled`，不能将其当作未知状态跳过。进入 `cancelled` 后清空 `active_key` 并释放 `worker_id/lease_until`。

## 14. 视频工作流剧本节点适配

`web/js/script_node.js` 中“拆分幕”和“拆分幕 + 宫格生图”目前各自包含一次完整 `/api/parse-script` 调用。实施时抽取独立文件：

```text
web/js/script_split_task.js
```

负责提交、轮询、恢复、继续、获取结果和幂等物化节点。`video_workflow.html` 只增加独立脚本引用，避免继续增加 HTML 内联逻辑。

剧本节点持久化：

```json
{
  "splitTask": {
    "taskId": 123,
    "mode": "split_and_generate_grid",
    "status": "generating",
    "progress": 46,
    "completedSegments": 4,
    "totalSegments": 9,
    "resultApplied": false,
    "postActionStarted": false
  }
}
```

任务创建成功后立即 `safeAutoSave()`。`createScriptNodeWithData()` 恢复节点时：

- 未完成任务自动恢复轮询。
- `paused` 显示“继续拆分”。
- 已完成但未应用结果时获取 `/result`。
- 已应用结果时不重复创建节点。

最终创建的幕和分镜节点记录 `scriptSplitTaskId`、`sourceSegmentId` 和稳定的 `sourceGroupKey`。如果节点物化中途刷新，重新执行时只创建缺失节点，不生成重复节点。

“拆分幕 + 宫格生图”必须等拆分结果全部应用后才启动宫格任务，并通过 `postActionStarted` 防止刷新后重复提交。

## 15. 故事板入口适配

故事板任务完成前不创建任何 `storyboard_scene`。前端轮询真实状态，不再使用固定 5 秒推进的模拟进度。

完整状态流程：

```text
planning -> generating -> merging -> validating -> publishing -> completed
```

发布阶段：

1. 再次检查故事板是否已有分镜。
2. 执行场景资产化。
3. 构造 `scenes_payload`。
4. 幂等创建分镜和对白。
5. 标记发布成功。
6. 再启动配音、子场景宫格等非关键后处理。

页面刷新后，故事板页面通过通用 active 查询接口按 storyboard ID 查找活跃任务并恢复轮询。视频工作流节点同时持久化 `task_id`；工作流重新加载时优先按该 ID 恢复，ID 丢失时再按 `source_type + source_id + source_node_key` 查找。只有发布完成后才重新加载故事板并触发自动补全首帧。

为保证发布中断后的幂等性，首版必须修改 `storyboard_scene`，不能只作为后续建议：

```text
script_split_task_id  BIGINT UNSIGNED NULL
source_shot_key       VARCHAR(128) NULL
UNIQUE KEY uk_storyboard_scene_split_source(script_split_task_id, source_shot_key)
```

`StoryboardModel.create_scenes()` 当前已经在一个数据库事务中创建 scenes 和 dialogues；实施时扩展其入参和 INSERT 字段，保证每个最终 shot 都写入稳定 `source_shot_key`。如果事务已经提交但任务状态尚未更新，发布重试先按 `script_split_task_id` 回查：

- 已存在数量及 source key 与最终结果完全一致：直接把任务推进为已发布。
- 存在用户手工分镜、其他任务分镜或集合不完整：停止发布并返回明确冲突，不静默追加重复镜头。

对应字段、唯一索引、model 属性和文件末尾 SQL 必须与任务表迁移同步更新。

### 15.1 `split-from-script` agent 命令收敛到同一 worker

`POST /api/storyboard/agent/commands/split-from-script`（`services/storyboard_agent_cli_service.py` `split_from_script`）原为同步路径，会在线程池中阻塞约 7 分钟跑完完整 LLM 拆分才返回，占用 asyncio 默认 ThreadPoolExecutor 拖垮共享线程池吞吐。现已与 `POST /api/storyboard/{id}/generate-from-script` 收敛到同一异步基础设施：

- 保留前置快速校验（storyboard 存在、已有分镜报 `scenes_exist`、`script_id` 解析、剧本内容非空）同步返回。
- 构造 `request_config`（`source=storyboard`、`storyboard_id`、模型三元组等）后调用 `api.script_split.create_split_task`（`SOURCE_TYPE_STORYBOARD`），`asyncio.run` 安全（service 已在 `to_thread` 子线程，无活动事件循环）。
- 立即返回 `{success, task_id, status_url, status:"queued"}`；LLM 解析、资产化、`create_scenes`、子场景九宫格全部由 worker 的 `step_publish` 推进（见 §15 发布阶段）。
- 调用方轮询 `GET /api/script-split/tasks/{task_id}` 直到终态，再用 `list-scenes` 查询结果。

模型解析同步修正：`config_json.selectedScriptSplitLlmModel` 在前端可能存成 dict（`{model,model_id,vendor_id}`）而非字符串。`_resolve_split_model_context` 统一解包为 `(model, model_id, vendor_id)` 三元组（逻辑与 `storyboard_first_frame_grid_service._llm_model_context` 对齐），避免旧实现 `str(dict)` 把 dict repr 当模型名拼进 Gemini URL 触发 404。异步路径另有 `api.script_split._normalize_request_config` 兜底 dict→str，但同步直调仍需此解包保证 DB 精确路由（`vendor_id`）生效。

## 16. 进度计算

进度使用真实阶段和分段数量计算：

- 语义分段规划：0%～10%。
- 逐段拆分：10%～85%。
- 合并与全局校验：85%～95%。
- 故事板发布或视频工作流结果准备：95%～100%。

逐段拆分进度根据 `completed_segment_count / total_segment_count` 计算，不使用定时器伪造。

前端按 `poll_after_ms` 轮询。建议正常状态约 3 秒；连续网络错误时指数退避，但恢复页面可立即查询一次。

故事板拆分弹框在四阶段卡片上方显示总体进度仪表：进度条和百分比直接使用状态响应的 `progress`，当前阶段文案使用 `message`。首次提交与页面刷新恢复共用 `applyGenerateProgressStatus(statusData)` 写入 UI 状态，并由现有 `pollScriptSplitTask()` 的 `onUpdate` 驱动刷新；不创建第二个定时器，也不模拟进度。前端将异常进度限制在 `0～100`，进度条提供 `role="progressbar"` 和完整 ARIA 数值。

## 17. 超时与鉴权

异步任务解决的是浏览器和网关的总请求超时。Worker 内部的每一次模型调用仍必须有明确超时，防止单段永久占用租约。

相关常量统一放入 `config/constant.py`，包括：

```text
SCRIPT_SPLIT_PLAN_MAX_RETRIES
SCRIPT_SPLIT_SEGMENT_MAX_RETRIES
SCRIPT_SPLIT_SEGMENT_MAX_OUTPUT_TOKENS
SCRIPT_SPLIT_LLM_TIMEOUT_SECONDS
SCRIPT_SPLIT_LLM_CALL_TIMEOUT_SECONDS
SCRIPT_SPLIT_WORKER_STEP_TIMEOUT_SECONDS
SCRIPT_SPLIT_TASK_LEASE_SECONDS
SCRIPT_SPLIT_SCHEDULER_INTERVAL_SECONDS
SCRIPT_SPLIT_DEFAULT_POLL_MS
SCRIPT_SPLIT_HISTORY_TAIL_SHOTS
```

`SEGMENT_MAX_SOURCE_CHARS=1500` 是不可绕过的输入硬上限，而不是主要分段算法。`TARGET_SHOTS` 和 `MAX_OUTPUT_TOKENS` 仍是给规划模型的输出软预算；后端只对模型返回的超限范围继续切细，并优先选择自然边界。

当前统一 LLM Response 没有对外保存 `finish_reason`，Gemini 客户端只在内部日志识别 `MAX_TOKENS`。实施时应在 `BaseLLMClient.Response/Choice` 中统一暴露 `finish_reason`，并让 Gemini、OpenAI 兼容客户端和 Ollama 驱动填充该字段，供 engine 精确识别截断原因。

各 provider 原始取值不一致，必须在基类层归一化，否则 engine 判断截断时要分别处理多种字符串：

- OpenAI / Ollama / OpenAI 兼容供应商：`stop`、`length`、`tool_calls`、`content_filter`。
- Gemini：`STOP`、`MAX_TOKENS`、`SAFETY` 等（驼峰 key `finishReason`，值全大写）。

统一约定：

- 字段名沿用 `finish_reason`（与 OpenAI 生态一致），取值统一为小写下划线风格。
- Gemini 驱动在 `_convert_gemini_response` 已读取 `finishReason` 的位置做映射：`MAX_TOKENS → length`、`STOP → stop`，其余按小写规则降级。
- 在 `BaseLLMClient.Choice` 上提供只读属性 `is_truncated`，返回 `finish_reason == "length"`，engine 只依赖该布尔值判断“是否因输出上限被截断”，不直接比较字符串。
- 现有 5 个 OpenAI 兼容子类（Aliyun / Volcengine / Claude / ZJT / DeepSeek）不 override `call_api` 的响应处理，基类读取 `choice.finish_reason` 后自动透传，无需逐个子类改动。

改动集中在 `base_llm_client.py`（`Choice`/`_create_response`）、`openai_base_client.py`（响应解析处）、`ollama_client.py`（响应解析处）、`gemini_client.py`（`_convert_gemini_response` 内映射并传入）约 4 个文件、15 行级改动，向后兼容，不影响现有 `response.choices[0].message.content` 调用方。

为处理 lint R5：

1. `server.py:/api/parse-script` 和 `api/storyboard.py:generate-from-script` 改为创建任务后，不再直接 `await parse_script_to_shots()`。
2. scheduler 中每个异步步骤使用 `asyncio.wait_for()` 包裹，外层超时必须大于底层 LLM HTTP transport timeout。
3. `parse_script_to_shots()` 内部的 `asyncio.to_thread(llm_client.call_api, ...)` 同样增加 `wait_for`；底层 `call_api` 增加可选 request timeout，确保外层取消前同步请求会先结束。
4. worker 步骤用 `try/finally` 释放租约、记录状态和清理本步骤资源，避免超时后遗留 processing 状态。

持久化任务需要用户 token 记录模型用量。token 不得出现在日志、任务状态或错误响应中。token 失效时进入 `waiting_auth`，前端使用当前登录 token 调用恢复接口后继续。

## 18. 代码组织建议

```text
llm/script_parser.py
    保留现有拆分提示词、LLM 调用、解析和后处理主逻辑

llm/script_segment_planner.py
    只负责模型语义分段计划及计划协议解析

services/script_split_engine.py
    两阶段编排、上下文构建、分段合并、局部重试

services/script_split_task_service.py
    任务创建、查询、恢复、取消和权限校验

task/script_split_task.py
    单次 scheduler tick 的任务领取与单步骤推进

task/scheduler.py
    注册 process_script_split_tasks IntervalTrigger

model/script_split_task.py
model/script_split_segment.py

web/js/script_split_task.js
    视频工作流剧本节点任务客户端

web/js/storyboard/api.js
    增加拆分任务状态、结果、继续和取消接口

web/js/storyboard/polling.js
    复用现有轮询基础设施，增加 pollScriptSplitTask

web/js/storyboard/state.js
    保存故事板拆分任务的当前状态
```

`parse_script_to_shots()` 保持兼容门面。普通内部调用仍可得到最终字典；两个 Web 入口改用持久化任务服务，避免 HTTP 长时间等待。

需要特别注意 `/api/parse-script` 实际定义在仓库根目录的 `server.py`，不是 `api/` 包；实施时在 `server.py` 中把原同步等待逻辑替换为任务创建。故事板侧不新增一套平行 polling 文件，而是在已有 `web/js/storyboard/polling.js` 上扩展，沿用其 4 秒轮询、失败退避和 timer 去重模式；任务恢复状态可参考 `auto_missing_images_state.js` 的 sessionStorage 与 409 接管实现。

## 19. 实施顺序

1. 先为现有 `script_parser.py` 补回归测试，再提取可复用的提示词构建、严格 JSON 解析、当前协议校验和统一后处理入口。
2. 新增任务表、分段表、故事板发布幂等字段、Alembic 迁移及 model SQL。
3. 以纯函数实现模型语义分段计划解析、覆盖校验、全局 ID 注册表和空间引用完整性校验，并用内存数据完成单元测试。
4. 实现分段上下文、现有 `qc_feedback` 局部重试及最终合并。
5. 在 `task/scheduler.py` 注册单步骤任务消费者，实现 `worker_id/lease_until` 领取和崩溃恢复。
6. 实现任务查询、结果、恢复、取消 API，并把 `server.py:/api/parse-script` 改为异步提交。
7. 适配视频工作流两个拆分按钮、节点幂等物化及工作流重载。
8. 改造故事板生成接口，在现有 `polling.js` 上接入真实进度和刷新恢复。
9. 将现有质检循环改为按来源分段局部修复，完成故事板幂等发布。
10. 运行完整自动化测试、`scripts/lint_blocking_calls.py` 并同步相关功能文档。

## 20. 测试方案

### 20.1 单元测试

- 锚点化保持原文内容和顺序。
- 模型计划覆盖所有 block，无遗漏、重复或乱序。
- 非法计划只重试规划阶段。
- 规划模型给出过大段后，后端在持久化前按自然边界收紧到 1500 字以内；阶段二不再重建计划。
- 单段 JSON 未转义引号时只重试该段。
- 单段响应中途截断时只重试该段。
- `strict_json=False` 补全成功后仍执行全部后处理，不再提前返回。
- 现有 `validate_parsed_script()` 正确校验 `shot_groups[].shots[]`。
- 新实体使用预留全局 ID，重复实体错误分配新 ID 时当前段被拒绝。
- `spatial_world/spatial_layout` 全部引用路径校验正确，未知或重定义 ID 不被静默重写。
- 合并后镜号、组号、总时长正确。
- 连续性上下文只包含受控历史摘要。
- 各 provider `finish_reason` 经基类归一化后 `Choice.is_truncated` 正确识别截断：OpenAI `"length"`、Gemini `"MAX_TOKENS"` 映射后、Ollama `"length"` 均判为截断；`"stop"` 不判为截断。

### 20.2 任务测试

- 重复提交返回同一活跃任务。
- 同配置重复提交命中 `paused/waiting_auth` 时按检查点自动恢复，命中执行中任务时不重置状态。
- 并发提交由 `active_key` 唯一索引保证只产生一条任务。
- 每段成功后立即保存检查点。
- APScheduler 每个 tick 只推进一个有限步骤，`max_instances=1/coalesce=True` 不发生重叠。
- 调度器中断后通过 `worker_id/lease_until` 从第一个未完成段恢复。
- 达到重试上限进入 `paused`。
- 同一生成 tick 最多调用一次 LLM；QC 失败候选在下一 tick 作为修复上下文恢复。
- 单次调用超时先于 worker watchdog；watchdog 触发后任务进入可继续的 `paused`。
- 执行中取消先进入 `cancelling`，当前 LLM 调用结束后丢弃响应并进入 `cancelled`。
- 新 token 可以恢复 `waiting_auth` 任务。
- 用户不能查询其他用户的任务。

### 20.3 前端与接口测试

- `/api/parse-script` 快速返回 202，不等待 LLM。
- 故事板提交快速返回 202。
- 视频工作流刷新后恢复轮询。
- 节点物化中途刷新不会重复创建。
- 两个剧本节点按钮都使用同一任务客户端。
- 宫格生图只在拆分完成后启动一次。
- 故事板完成前不产生半成品分镜。
- 故事板页面刷新后恢复真实进度。
- 故事板发布事务已提交但任务状态未更新时，按 `script_split_task_id + source_shot_key` 恢复且不重复插入。

### 20.4 回归测试

使用 `script_parser_20260713_221538` 失败样例构造回归测试：模拟某一段出现未转义引号，后续再次模拟输出截断，验证系统只重试失败段，并最终合并出完整 64 镜结果。

运行 `scripts/lint_blocking_calls.py`，确认没有异步接口调用同步阻塞函数、无超时 `Future.result()` 或违规线程池包装。

## 21. 验收标准

1. 主要分段边界由模型根据语义决定；后端保证任何实际生成段不超过 1500 字。
2. 阶段二继续使用 `parse_script_to_shots()` 的现有核心能力。
3. 任一单段失败不会重新生成已通过段。
4. Web 提交接口快速返回任务 ID。
5. 浏览器刷新和服务重启后都能恢复。
6. 两个视频工作流按钮和故事板入口都完成异步适配。
7. 全部段完成并通过全局校验前，不创建任何最终节点或故事板分镜。
8. 最终 JSON 与当前下游结构兼容。
9. 相关常量、数据库迁移、模型 SQL、测试和文档全部同步。

## 22. 第一阶段分段规划诊断日志

剧本拆分进入 `script_parser.py` 逐段生成分镜 JSON 之前，会先由
`script_segment_planner.py` 把锚点化剧本规划为连续的语义小段。该阶段的每次初始规划、
校验失败重试和局部再分段，都会在 `logs/script_parser/` 下生成一组独立日志：

```text
script_segment_planner_task_{task_id}_{plan_kind}_{timestamp}_attempt_{attempt}_01_anchors.json
script_segment_planner_task_{task_id}_{plan_kind}_{timestamp}_attempt_{attempt}_02_prompt.txt
script_segment_planner_task_{task_id}_{plan_kind}_{timestamp}_attempt_{attempt}_03_raw_response.txt
script_segment_planner_task_{task_id}_{plan_kind}_{timestamp}_attempt_{attempt}_04_parsed_plan.json
script_segment_planner_task_{task_id}_{plan_kind}_{timestamp}_attempt_{attempt}_05_validation.json
```

- `plan_kind=initial` 表示首次完整语义分段及其校验重试。
- `attempt` 从 1 开始；初始规划校验失败后递增，局部再分段使用下一次
  `plan_revision` 作为尝试序号。
- `_01` 保存本次实际送入模型的 anchors；局部再分段只包含目标 block。
- `_02` 保存最终完整 user prompt，包括上一轮校验反馈或局部再分段说明。
- `_03` 保存模型原始正文；模型调用失败或超时时为空文件。
- `_04` 仅在响应成功解析为 JSON 后存在，内容尚未经过业务覆盖校验。
- `_05` 保存 `validate_segment_plan()` 的通过状态、错误列表、结束原因和分段摘要。

所有目录创建和文件写入都通过 `asyncio.to_thread()` 离开事件循环执行。日志写入失败
只记录 warning，不改变任务原有结果；日志不记录 `auth_token`、API Key 或请求头，也不
参与断点恢复。开关 `ScriptSplitConstants.PLANNER_DIAGNOSTIC_LOGGING_ENABLED` 默认开启，
日志目录由 `ScriptSplitConstants.PLANNER_DIAGNOSTIC_LOG_DIR` 配置。

## 23. 段级 QC 诊断日志

开启 `enable_qc` 后，每一段、每一轮 QC 都在 `logs/script_parser/` 生成一组同前缀日志：

```text
script_split_qc_task_{task_id}_segment_{segment_index}_{segment_id}_{timestamp}_round_{round}_01_system_prompt.txt
script_split_qc_task_{task_id}_segment_{segment_index}_{segment_id}_{timestamp}_round_{round}_02_input.json
script_split_qc_task_{task_id}_segment_{segment_index}_{segment_id}_{timestamp}_round_{round}_03_report.json
```

- `_01_system_prompt.txt` 记录实际执行模式。当前 `script_split_qc_agent` 使用确定性规则、没有调用 LLM，因此该文件明确标记 `execution_mode=rule_only` 和“未调用 LLM”，不会伪造一份未发送的 system prompt。
- `_02_input.json` 保存本轮实际检查的段落原文、完整 `parsed_data`、任务级 `known_characters`、语言和时长参数，以及 task/segment/round 关联信息。
- `_03_report.json` 保存完整 `QcReport`，包括 `passed`、统计数据以及每条 issue 的 `severity/shot_ref/field/evidence`。
- 如果规则执行本身抛出异常，则以同前缀写入 `_03_error.json`，随后保持原异常处理流程。

QC 日志开关为 `ScriptSplitQcConstants.DIAGNOSTIC_LOGGING_ENABLED`，目录为 `ScriptSplitQcConstants.DIAGNOSTIC_LOG_DIR`，默认开启并指向 `logs/script_parser`。文件写入统一通过 `asyncio.to_thread()` 离开事件循环；失败只记录 warning，不改变 QC 结论。日志输入由明确字段组装，不写入 `auth_token`、API Key 或请求头。

## 24. 效果模式：空间契约前置与并发拆分

`sequence_mode=quality` 为商业版专属路径。第一阶段仍由 LLM 按语义边界分段，但会同时输出 schema v2 的全局实体、`spatial_world`，以及每段的 `continuity_in/state_changes/continuity_out`。后端编译稳定的全局实体 ID，并验证相邻段边界状态完全衔接；任何段的原文超过 1500 字时，规划整体重试，不再在后端生成缺少空间语义的 `_part_NN`。

schema v2 的 canonical `entities` 是对象，固定包含 `characters`、`locations`、`props` 三个数组。实体表登记剧本中的全部角色、地点和道具及描述，不重复保存角色位置；位置只由段级连续性契约表达。为兼容已持久化计划，编译器仍接受带 `character_key/location_key/prop_key` 的历史扁平数组，并在持久化前规范化为 canonical 对象。其他类型、非数组集合或无法分类的元素会产生 `quality_plan_invalid` 并重新规划，不得作为未知异常终止任务。

规划通过后，Worker 每批最多并发生成 `ScriptSplitConstants.QUALITY_SEGMENT_PARALLELISM`（默认 3）个段。每段只读取不可变的全局注册表和自身空间契约，不读取前一段临时生成结果，因此并发不会丢失真实空间连续性。段结果需满足首镜 `continuity_in`、尾镜 `continuity_out`，且段内位置变化必须在 `state_changes` 声明。批次结束后按数据库真实完成数统一更新进度，避免并发子任务互相覆盖计数。

普通 `speed/balanced` 和历史 schema v1 任务保持原串行检查点流程。效果模式的提示词、契约编译、物理状态校验及合并修复均位于 `enterprise/services/script_split_quality/`；核心仓库只保留策略门面、通用并发调度和持久化逻辑。

效果模式合并时以规划注册表为身份真源，并补充分段结果中规划遗漏的实体，不能用空的地点或道具集合覆盖有效结果。同一 ID 在分段结果中出现不同名称时，视为“酒店前台/酒店大堂”一类命名粒度差异：保留规划的 canonical ID、名称和 `entity_key`，同时吸收模型补充的描述、外观等非身份字段，镜头引用无需改写。同一名称对应不同 ID 仍以 `quality_merge_invalid` 明确失败，禁止静默生成歧义引用。
