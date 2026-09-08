# 剧本拆分 · 总分镜时长控制

> 测试移交文档：[script_split_total_duration_control_test_plan.md](./script_split_total_duration_control_test_plan.md)
> （分层测试步骤、验收标准、存量失败基线）

## 背景

剧本拆分（storyboard「从剧本生成分镜」与 video_workflow 剧本节点「拆分幕」）此前唯一的时长约束是
`max_group_duration`（每个分镜组内镜头时长总和上限）。镜头数量与单镜头时长完全由 LLM 自由决定，
实际拆分结果的总时长经常达到剧本朗读时长的 3 倍以上。

本功能在拆分界面新增「总分镜时长」选项：以剧本基准时长（按字数估算的朗读时长）为单位，
限制全部分镜的总时长为 **1倍 / 2倍 / 3倍**（不限制=原有行为，默认值）。

## 概念与公式

| 概念 | 定义 |
|------|------|
| 剧本基准时长 | 剧本非空白字符数 ÷ 语种混合朗读速率；即「1倍」的秒数。中文 270 字 ≈ 60 秒 |
| 混合朗读速率 | CJK 4.5 字/秒、拉丁 11 字符/秒，按 CJK 字符占比线性混合（`_script_duration_rate_per_second`） |
| 目标总时长 | 剧本基准时长 × 倍率。1 倍≈纯朗读节奏，2~3 倍给画面呼吸留空间 |
| 段级预算 | 目标总时长按各段源文本字符占比分解到逐段 LLM 调用（段拼接≈全剧本，预算和≈目标） |

常量全部位于 `config/constant.py` `ScriptSplitConstants`：
`SCRIPT_DURATION_CJK_CHARS_PER_SECOND`、`SCRIPT_DURATION_LATIN_CHARS_PER_SECOND`、
`SCRIPT_DURATION_MIN_SECONDS`（估算下限 10s）、`TOTAL_DURATION_MULTIPLIER_MIN/MAX`（0.5~10）、
`TOTAL_DURATION_TOLERANCE`（容差 0.15）、`TOTAL_DURATION_SHOT_MIN_SECONDS`（压缩下限 1.5s）、
`TOTAL_DURATION_SHOT_EXPAND_MAX_SECONDS`（放大单镜头上限 10s）、
`TOTAL_DURATION_EXPAND_MAX_ITERATIONS`（放大缺口再分配迭代上限）、
`TOTAL_DURATION_SEGMENT_BUDGET_MIN_SECONDS`（段预算下限 3s）、`TOTAL_DURATION_MERGE_MAX_ITERATIONS`。

## 参数流转

```
前端 totalDurationMultiplier（0/1/2/3）
  ├─ storyboard：POST /api/storyboard/{id}/generate-from-script  body.total_duration_multiplier
  └─ video_workflow：POST /api/parse-script                      body.total_duration_multiplier
→ request_config["total_duration_multiplier"]（JSON 字段，无需迁移；0=不限制）
→ _normalize_request_config 归一化为 float 并夹紧（active_key 幂等不漂移）
→ engine 逐段下发预算 + 合并后归一化
```

## 三层执行（按顺序）

### 1. 段级预算注入 prompt（引导 LLM）

`services/script_split_engine.py::step_generate_segment` 在倍率 > 0 时计算
`compute_segment_duration_budget_seconds(script, segment, multiplier)`，传给
`parse_script_to_shots(duration_budget=...)`。user prompt 顶部注入
「本段总时长预算·硬性约束」块：预算值、±15% 目标区间（上下限）、
建议镜头数量区间（`预算÷6 ~ 预算÷3`，按平均 6~3 秒/镜头估算）、
**达成方式引导（最重要）**：增加总时长靠拆出更多镜头（反应/细节特写/过渡/
氛围空镜/视角切换，把动作与剧情节拍拆细），而不是拉长单个镜头——单镜头
保持 3~8 秒正常叙事节奏，禁止为凑预算拉长到 10 秒以上；只有按正常节奏拆分
后仍难达下限时才允许适当放慢关键动作与对白节奏。镜头组时长上限
（`max_group_duration`）同时生效。

### 2. 合并后确定性归一化（硬兜底，双向）

`llm/script_parser.py::enforce_total_duration_limit(parsed, target_seconds, max_shot_seconds)`，
在 `step_merge` 中 `reorganize_shot_groups` **之前**、`renumber_global` 之前调用：

1. 总时长在 `target × (1±15%)` 区间内 → 不干预；
2. 超上限 → 所有镜头 duration 等比压缩，单镜头下限 1.5s；压缩后仍超限
   （镜头过多触发下限）→ 迭代把全局最短镜头并入同组相邻镜头
   （`_merge_shot_into`：视频侧文本与 dialogue 追加合并、首帧保留在前镜头、
   duration 取 max），直到达标或无可合并镜头；
3. 低于下限（LLM 拆得比目标短，实测 2 倍节奏下 LLM 往往只拆出 0.7 倍左右，
   见 task 8 复盘）→ 所有镜头 duration 等比放大；单镜头超过 `max_shot_seconds`
   （= `TOTAL_DURATION_SHOT_EXPAND_MAX_SECONDS` 10s，与 prompt 的 3~8 秒
   正常节奏配套：**增加总时长靠增加镜头数而非拉长单镜头**，不再放宽到
   `max_group_duration`）时截断，保证随后 `reorganize_shot_groups` 能按
   组上限重新拆组恢复组内约束；镜头数不足、全顶上限仍低于下限时接受差额，
   报告 `shortfall_seconds` 如实记录（镜头数量只能由 LLM 拆出，由第 1 层
   建议镜头数区间引导）。

归一化必须先于 reorganize：放大后组内总时长会超组上限，由 reorganize 拆组恢复；
压缩方向只减时长不会破坏组上限。兜底合并减少镜头数、拆组增加组数后均由
`renumber_global` 重排编号。

### 3. 结果汇报

归一化报告写入 `final_result.metadata.total_duration_control`：
`{multiplier, estimated_script_seconds, target_seconds, total_before, total_after,
applied, direction(none/compress/expand), scaled, merged_shots, shot_max_capped,
shortfall_seconds}`，并记录 engine info 日志。

## 前端界面

| 页面 | 位置 | 行为 |
|------|------|------|
| storyboard.html | 拆分弹窗「镜头组时长」下方新增「总分镜时长」下拉 | 打开弹窗时懒加载剧本正文（`fetchScriptContent`），按同公式展示「剧本估算约 X分Y秒 × N倍 → 目标总分镜时长约 …」；选择随 `config_json` 持久化 |
| video_workflow.html | 剧本节点参数区「镜头组时长」下方同款下拉 + hint | 估算基于节点 textarea 内容实时更新；倍率存 `node.data.totalDurationMultiplier`，随工作流序列化，重载后由 `workflow.js createScriptNodeWithData` 恢复选中项 |

前端估算函数 `estimateScriptDurationSeconds` 与后端公式**人工保持同步**（三处：
`web/js/storyboard/render.js`、`web/js/script_node.js`、`llm/script_parser.py`），修改速率常量时需三处同改。

## 测试

- `tests/llm/test_script_split_total_duration.py`：估算（中/英/空文本/空白忽略）、
  段预算分解与下限、归一化（容差内不干预/等比压缩/下限保护/兜底合并保内容/
  单镜头组只压缩/零目标 no-op/等比放大到目标区间/放大单镜头截断与差额汇报/
  镜头充足时放大无差额）、倍率归一化（engine + api）。
- `tests/js/test_storyboard_script_split_static.js` §10：前后端接入点静态断言。
