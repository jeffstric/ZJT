# 剧本拆分 · 总分镜时长控制

> 测试移交文档：[script_split_total_duration_control_test_plan.md](./script_split_total_duration_control_test_plan.md)
> （分层测试步骤、验收标准、存量失败基线；其中旧口径公式已被本文档取代）

## 背景

剧本拆分（storyboard「从剧本生成分镜」与 video_workflow 剧本节点「拆分幕」）的时长约束曾只有
`max_group_duration`（每个分镜组内镜头时长总和上限）。其后加入的「总分镜时长」控制最初以
**整篇剧本非空白字符数 ÷ 朗读速率** 作为基准：描写文字（场景、动作、神态）也被算成朗读时间，
基准时长严重虚高（实测某任务基准 231 秒，而实际台词仅约 74 秒），拆分结果总时长超出预期。

现改为**台词锚定**：时长预估的文本来源是「阶段一规划 LLM 顺手提炼的台词」（LLM 抽文本准、
数数字不准 → 抽取交给 LLM，数字数与换算全部是后端确定性代码）；启发式行过滤降级为纯兜底。

## 概念与公式

| 概念 | 定义 |
|------|------|
| 段台词时长 | 阶段一规划输出的该段 `dialogue_text` 非空白字符数 ÷ 混合朗读速率 |
| 混合朗读速率 | CJK 4.5 字/秒、拉丁 11 字符/秒，按 CJK 字符占比线性混合（`_script_duration_rate_per_second`） |
| 对白占比 | 台词占成片总时长的经验比例（`TOTAL_DURATION_DIALOGUE_SHARE = 0.6`，可配） |
| 段级预算 | 倍率 × 段台词字数 ÷ 混合速率 ÷ 对白占比，注入该段拆分 prompt 预算块 |
| 目标总时长 | 倍率 × 全部镜头台词总时长 ÷ 对白占比（`enforce_total_duration_limit` 锚点） |
| 逐镜锚定 | 有对白镜头 duration = max(台词朗读秒数, 2s)；无对白镜头保留 LLM 预估 |

常量全部位于 `config/constant.py` `ScriptSplitConstants`：
`SCRIPT_DURATION_CJK_CHARS_PER_SECOND`、`SCRIPT_DURATION_LATIN_CHARS_PER_SECOND`、
`SCRIPT_DURATION_MIN_SECONDS`（估算下限 10s）、`SCRIPT_DURATION_DIALOGUE_SHOT_MIN_SECONDS`
（有对白镜头时长下限 2s）、`TOTAL_DURATION_DIALOGUE_SHARE`（对白占比 0.6）、
`TOTAL_DURATION_MULTIPLIER_MIN/MAX`（0.5~10）、`TOTAL_DURATION_TOLERANCE`（容差 0.15）、
`TOTAL_DURATION_SHOT_MIN_SECONDS`（无对白镜头压缩下限 1.5s）、
`TOTAL_DURATION_SHOT_EXPAND_MAX_SECONDS`（放大单镜头上限 10s）、
`TOTAL_DURATION_EXPAND_MAX_ITERATIONS`、`TOTAL_DURATION_SEGMENT_BUDGET_MIN_SECONDS`（段预算下限 3s）、
`TOTAL_DURATION_MERGE_MAX_ITERATIONS`。

## 台词文本来源与三级回退

```
① 阶段一规划 segments[].dialogue_text（llm/script_segment_planner.py 输出 schema 新增字段：
   该段全部台词/旁白逐字原文拼接，不含角色名/语气标注/画面描写；无台词段输出空字符串。
   随 segment_plan_json 持久化，validate_segment_plan 对该额外字段天然容忍）
   ↓ 字段缺失（如企业版 quality 模式 prompt_override 不输出该字段）
② 启发式行过滤 estimate_script_dialogue_seconds（llm/script_parser.py）：
   逐行跳过空行、[ / 【 / # / 场景编号 开头行、整行括号包裹行、
   「时间/地点/人物/场景/幕/场/章节/备注/BGM/音效 + 冒号」头部行；
   「角色：台词」行只数第一个冒号后的正文；无冒号非括号行只数成对引号
   （“”、"…"、「」、『』）内的文字，该行无引号则整行计入
   ↓ 整篇零匹配
③ 旧口径 estimate_script_duration_seconds（整篇非空白字符 ÷ 混合速率）
```

段预算与总时长目标都遵守该回退链；段级另有一条规则：规划**明确输出空台词**的段
（`dialogue_chars=0`）直接走旧公式（该段靠画面/动作撑时长，不能用台词口径算出 0 预算）。

## 参数流转

```
前端 totalDurationMultiplier（0/1/2/3）
  ├─ storyboard：POST /api/storyboard/{id}/generate-from-script  body.total_duration_multiplier
  └─ video_workflow：POST /api/parse-script                      body.total_duration_multiplier
→ request_config["total_duration_multiplier"]（JSON 字段，无需迁移；0=不限制）
→ _normalize_request_config 归一化为 float 并夹紧（active_key 幂等不漂移）
→ engine 逐段下发预算 + 合并后逐镜锚定与归一化
```

## 三层执行（按顺序）

### 1. 段级预算注入 prompt（引导 LLM）

`services/script_split_engine.py::step_generate_segment` 在倍率 > 0 时先用
`_segment_plan_dialogue_chars` 从阶段一规划取该段 `dialogue_text` 的非空白字符数
（缺失走启发式、空台词段走旧公式；段被 `SEGMENT_MAX_SOURCE_CHARS` 切成多个 part 时按
part 原文字符占比分摊基段台词字数），再调
`compute_segment_duration_budget_seconds(script, segment, multiplier, dialogue_chars=...)`
得到预算，传给 `parse_script_to_shots(duration_budget=...)`。user prompt 顶部注入
「本段总时长预算·硬性约束」块：预算值（注明按本段台词量估算、台词必须逐字完整呈现）、
±15% 目标区间、建议镜头数量区间（`预算÷6 ~ 预算÷3`），以及**达成方式引导**：
增加总时长靠拆出更多镜头而不是拉长单镜头（单镜头保持 3~8 秒正常叙事节奏）。
镜头组时长上限（`max_group_duration`）同时生效。

### 2. 合并阶段：逐镜台词锚定 + 确定性归一化（硬兜底，双向）

`step_merge` 中、倍率 > 0 时，先无条件执行
`apply_dialogue_matched_shot_durations(merged)`：有对白镜头
`duration = round(max(台词朗读秒数, 2s), 1)`，无对白镜头保留 LLM 预估；
再按 `compute_total_duration_target_seconds` 的三级口径（结构化对白 Σ>0 → 启发式 →
旧口径）计算目标并调 `enforce_total_duration_limit(parsed, target_seconds, max_shot_seconds)`，
位于 `reorganize_shot_groups` **之前**、`renumber_global` 之前：

1. 总时长在 `target × (1±15%)` 区间内 → 不干预；
2. 超上限 → 所有镜头 duration 等比压缩，单镜头下限 = max(1.5s, 该镜头台词朗读秒数)
   （台词必须念完）；压缩后仍超限 → 迭代把全局最短镜头并入同组相邻镜头
   （`_merge_shot_into`：视频侧文本与 dialogue 追加合并、首帧保留在前镜头、
   duration 取 max），直到达标或无可合并镜头；因台词下限压不到目标时接受超出，
   报告 `dialogue_floor_exceeded_seconds`；
3. 低于下限 → 所有镜头 duration 等比放大；单镜头超过 `max_shot_seconds`
   （= `TOTAL_DURATION_SHOT_EXPAND_MAX_SECONDS` 10s，与 prompt 的 3~8 秒正常节奏配套：
   **增加总时长靠增加镜头数而非拉长单镜头**）时截断，保证随后 `reorganize_shot_groups`
   能按组上限重新拆组；镜头数不足、全顶上限仍低于下限时接受差额，报告
   `shortfall_seconds`（镜头数量只能由 LLM 拆出，由第 1 层建议镜头数区间引导）。

归一化必须先于 reorganize：放大后组内总时长会超组上限，由 reorganize 拆组恢复；
压缩方向只减时长不会破坏组上限。兜底合并减少镜头数、拆组增加组数后均由
`renumber_global` 重排编号。配音完成后 `task/audio_task.py` 仍用真实 TTS 时长覆盖
scene.duration（本方案不涉及）。

### 3. 结果汇报

归一化报告写入 `final_result.metadata.total_duration_control`：
`{multiplier, estimated_script_seconds, dialogue_matched_shots, dialogue_seconds_total,
target_source(shots/heuristic/full_text), target_seconds, total_before, total_after,
applied, direction(none/compress/expand), scaled, merged_shots, shot_max_capped,
shortfall_seconds, dialogue_floor_exceeded_seconds}`，并记录 engine info 日志。

## 前端界面

| 页面 | 位置 | 行为 |
|------|------|------|
| storyboard.html | 拆分弹窗「镜头组时长」下方「总分镜时长」下拉 | 打开弹窗时懒加载剧本正文（`fetchScriptContent`），按同规则展示估算 hint；选择随 `config_json` 持久化 |
| video_workflow.html | 剧本节点参数区「镜头组时长」下方同款下拉 + hint | 估算基于节点 textarea 内容实时更新；倍率存 `node.data.totalDurationMultiplier`，随工作流序列化，重载后由 `workflow.js createScriptNodeWithData` 恢复选中项 |

前端估算函数 `estimateScriptDurationSeconds`（导出与函数名不变）内部改为与后端
`estimate_script_dialogue_seconds` 相同的启发式行过滤（含头部关键词、引号规则、零匹配回退）：
- 提取到台词（对白口径）：hint 显示「剧本对白估算约 X × N倍 → 目标总分镜时长约 Y」，
  其中 Y = X × N ÷ 对白占比（前端 `DIALOGUE_SHARE_OF_TOTAL=0.6`，与后端常量同值）；
- 整篇零匹配（回退整篇估算）：hint 维持「剧本估算约 X」、Y = X × N（旧口径）。

三处人工保持同步：`web/js/storyboard/render.js`、`web/js/script_node.js`、
`llm/script_parser.py`，修改规则或速率常量时需三处同改。

## 测试

- `tests/llm/test_script_split_total_duration.py`：整篇估算（中/英/空文本/空白忽略）、
  启发式行过滤（标记/括号/头部关键词剔除、冒号后正文、引号式台词、零匹配回退）、
  段预算（台词字数口径、空台词段回退旧公式、启发式兜底、下限与零倍率）、
  逐镜锚定（覆盖/保留/多角色求和/2s 下限）、总目标三级口径回退、
  归一化（容差内不干预/等比压缩/台词下限不穿透/超限差额上报/兜底合并保内容/
  单镜头组只压缩/零目标 no-op/等比放大/放大截断与差额汇报）、
  engine 段台词字数查找（含 part 分摊）、倍率归一化（engine + api）。
- `tests/js/test_storyboard_script_split_static.js` §10：前后端接入点静态断言。
