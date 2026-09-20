# 剧本生成端时长预算方案：story-writer 按目标片长约束台词字数

> 状态：**已实施**（2026-09-19，develop_f873）
> 关联文档：[script_split_total_duration_control.md](./script_split_total_duration_control.md)
> 关联事故：2026-09-19 乌灵胶囊科普验证（storyboard 14）：剧本自述「片长：约3分钟」，
> 拆分端 declared 口径修复（ea2da2b6）后落库 198.8s 达标，但 34 条台词 TTS 真实朗读
> 393.8s（6分34秒），配音回填后成片时长仍超标注一倍以上。
> 根因在生成端：口播约 1842 字，物理朗读下限远超 180s，标注本身虚标。

## 1. 背景与问题

时长约束链路目前只有「拆分端 + 前端」两层，**生成端（story-writer）完全不知道
台词字数决定成片时长**：

| 环节 | 现状 | 问题 |
|------|------|------|
| script-orchestrator | 收集「每集时长」（推荐 1/2 分钟档）并写入 task_description | 时长只作为文案传下去，无字数含义 |
| story-writer | SKILL.md 仅有硬编码短剧经验（500-800 字/集、前30秒/100-150字） | 经验值与片长无换算关系、无语言区分、与拆分端速率常量不一致 |
| 拆分端 | `ScriptSplitConstants.SCRIPT_DURATION_CJK/LATIN_CHARS_PER_SECOND` | 常量只服务拆分，生成端不可见 |
| 前端 | render.js / script_node.js 各有一份 4.5/11.0 硬编码副本 | 已有静态防漂移断言，但数值改动需三处手同 |

复盘数据（乌灵胶囊案例，中文）：1842 字口播 ÷ 393.8s 实际 TTS ≈ 4.68 字/秒，
与拆分端常量 4.5 字/秒高度吻合——**用现有速率常量在生成端做字数预算是可靠的**。

## 2. 目标

1. 「每分钟多少字」成为**单一来源常量**，按语言（CJK/拉丁，预留扩展）区分；
2. story-writer 创作时按「目标片长 → 台词字数预算」创作并自检，超预算主动删减；
3. 剧本落盘时携带结构化字数统计，拆分端可校验「标注片长 vs 物理下限」并如实上报；
4. 全链路（生成/拆分/前端）速率口径一致，改动只动常量一处。

## 3. 常量设计（单一来源）

### 3.1 新增 `ScriptDurationRateConstants`（config/constant.py）

```python
class ScriptDurationRateConstants:
    """剧本朗读速率常量（生成端预算 / 拆分端锚定 / 前端估算三端共用）。

    修改任一数值必须同步：
    - web/js/storyboard/render.js（estimateScriptDurationSeconds）
    - web/js/script_node.js（同公式副本）
    - tests/js/test_storyboard_script_split_static.js 静态断言
    见 docs/script/script_split_total_duration_control.md「三处同步」。
    """
    _CONSTANT_GROUP = True

    # CJK（含假名）朗读速率（字/秒）。每分钟 270 字。
    CJK_CHARS_PER_SECOND = 4.5
    # 拉丁朗读速率（字符/秒，不含空格）。每分钟 660 字符。
    LATIN_CHARS_PER_SECOND = 11.0
    # 台词占成片总时长经验比例：台词预算秒数 = 片长 × 该值
    # （成片其余时长为画面描写/动作/停顿/转场，与拆分端 TOTAL_DURATION_DIALOGUE_SHARE 同源）
    DIALOGUE_SHARE = 0.6
    # 生成端允许超出预算的比例（超过即要求 story-writer 删减）
    DIALOGUE_BUDGET_TOLERANCE = 0.2
```

- `ScriptSplitConstants.SCRIPT_DURATION_CJK/LATIN_CHARS_PER_SECOND` 改为引用
  （或直接替换为）上述常量，消除双份定义；
- 语言维度沿用现有「CJK 占比线性混合」公式（对中英混排最稳），不按剧本
  `language` 字段硬选档；`language` 仅用于给 story-writer 的提示词选择
  「每分钟 N 字」的主口径表述（中文剧本 270 字/分钟、英文剧本 660 字符/分钟）。

### 3.2 共享辅助函数（新增 `utils/script_duration.py`）

```python
def rate_per_second(text: str) -> float: ...          # CJK 占比混合速率
def dialogue_char_budget(target_seconds: float) -> int:  # 台词字数预算
    # = target_seconds × DIALOGUE_SHARE × rate（按主语言口径取整）
def estimate_dialogue_seconds(text: str) -> float: ...   # 台词朗读秒数
```

`llm/script_parser.py` 现有 `_script_duration_rate_per_second` 等函数改为
薄包装，前端两处 JS 公式不变（数值随常量断言防漂移）。

### 3.3 各档位预算速查（DIALOGUE_SHARE=0.6）

| 目标片长 | 台词秒数预算 | 中文台词字数（4.5字/秒） | 英文台词字符（11字符/秒） |
|----------|--------------|--------------------------|---------------------------|
| 1 分钟   | 36s          | ≈162 字                  | ≈396 字符                 |
| 2 分钟   | 72s          | ≈324 字                  | ≈792 字符                 |
| 3 分钟   | 108s         | ≈486 字                  | ≈1188 字符                |

对照事故：1842 字 ≈ 6.8 分钟口播，注定装不进 3 分钟——这类剧本在生成端
就应被拦下删减，而不是等拆分端压缩出「假达标」。

## 4. story-writer 注入方案（script_writer_core）

### 4.1 SKILL.md 新增「片长与台词字数预算（必须遵守）」章节

放在现有「故事类型约束」之后（该章节已是上下文注入模式的先例）：

- **输入**：从任务上下文读取目标片长（orchestrator 已收集「每集时长」）与剧本语言；
- **预算公式**：`台词字数预算 = 片长(秒) × 0.6 × 速率（中文 4.5 字/秒 / 英文 11 字符/秒）`，
  直接给出 1/2/3 分钟档速查表；
- **创作规则**：
  1. 对白/旁白（口播）总字数不得超预算 × 1.2；
  2. 画面描写/动作说明不计入口播，但不得挪用台词预算来堆字数；
  3. 预算不够表达信息时，砍台词（压缩句式）而非暗示用户加片长；
  4. 交稿前**自检**：统计全部口播字数，超限必须删减后再保存；
- **元信息输出**：剧本头部元信息块必须写
  `片长：约N分钟`（declared 标注，拆分端正则已可提取）与
  `口播字数：约M字`（供拆分端一致性校验）；
- **旧经验值收敛**：现有「500-800 字/集」「前30秒/100-150字」等段落改为
  引用预算公式换算（标注「以 2 分钟档为例」），避免双口径。

### 4.2 PM/编排链路透传

`script-orchestrator` 派发 story-writer 的 task_description 已含「每集 X 分钟」，
补充固定短语（由 SKILL.md 约束承接）：

> 目标片长 [X] 分钟（台词字数预算 ≈[B] 字，见片长预算规则）

预算数值由 orchestrator 按速查表换算写入（提示词层，不需新工具调用）。

## 5. 工具层闭环（create_script_json / update_script_json）

`script_writer_core/mcp_tool.py` 保存剧本时（`language` 字段已存在）：

1. 用共享函数统计 content 的口播字数与预估朗读秒数（启发式台词过滤
   `extract_script_dialogue_text` 同规则），写入剧本 JSON：
   ```json
   "dialogue_stats": {"chars": 480, "estimated_seconds": 106.7}
   ```
2. 对照上下文中的目标片长（若可得）超预算 ×1.2 时，返回
   `warning`（不阻塞保存）：智能体收到后自行删减重存，形成反馈闭环；
3. 拆分端 `submit-to-database` / ScriptModel 落库时该字段随 JSON 透传，
   供第 6 节校验使用。

## 6. 拆分端联动（顺带修复上报缺口）

- `enforce_total_duration_limit`（llm/script_parser.py）压缩分支的兜底合并
  循环目前把 total 压进容差后**跳过** `dialogue_floor_exceeded_seconds` 检查
  （2026-09-19 验证实测：floor_sum=346.3s 未上报，报告显示假达标 198.8s）。
  修复：合并循环结束后无论是否进入容差，只要
  `dialogue_floor_sum > target_seconds` 即上报差额；
- 若剧本携带 `dialogue_stats`，规划阶段可直接给出「物理下限 vs declared」
  预检：矛盾明显（下限 > declared × 1.5）时在任务状态中提前提示
  「剧本标注片长与台词量不匹配」，不再等 TTS 回填后暴露。

## 7. 同步点与兼容性

| 位置 | 动作 |
|------|------|
| web/js/storyboard/render.js、web/js/script_node.js | 公式不动；常量数值改动时随静态断言同步 |
| tests/js/test_storyboard_script_split_static.js | 新增速率数值与预算公式防漂移断言 |
| alembic | 无表结构变更（dialogue_stats 存剧本 JSON 文件与 content 并行字段，不需迁移） |
| 三端常量引用 | ScriptSplitConstants 旧常量名保留别名一个版本，避免散落引用漏改 |

## 8. 测试计划

1. **常量/函数**：混合速率（纯中/纯英/混排）、预算换算（1/2/3 分钟档）、
   DIALOGUE_SHARE 变更影响面；
2. **SKILL.md 注入断言**：技能文本包含预算公式与速查表（防提示词漂移，
   参照 tests/js 静态断言思路）；
3. **工具层**：create_script_json 写入 dialogue_stats、超预算 warning 文案、
   中英剧本分别按 4.5/11 口径统计；
4. **拆分端回归**：事故剧本（1842 字口播 + 「片长：约3分钟」标注）预期——
   生成端拦截（或删减后通过）；拆分端 floor 上报修复后
   `dialogue_floor_exceeded_seconds` 必须出现；
5. **端到端**：按 2 分钟档生成新剧本 → 拆分（1 倍）→ TTS 回填后总时长
   落在 120s ×(1±15%)。

## 9. 实施记录

1. P1 常量收敛：`config/constant.py` 新增 `ScriptDurationRateConstants`
   （`CJK_CHARS_PER_SECOND=4.5` / `LATIN_CHARS_PER_SECOND=11.0` /
   `DIALOGUE_SHARE=0.6` / `DIALOGUE_BUDGET_TOLERANCE=0.2`），
   `ScriptSplitConstants` 旧名改为引用；新增 `utils/script_duration.py`
   （`rate_per_second` / `estimate_duration_seconds` / `estimate_dialogue_seconds` /
   `dialogue_char_budget` / `budget_tolerance_upper`），
   `llm/script_parser.py` 速率函数改为薄包装。
2. P1 floor 上报缺口修复：`enforce_total_duration_limit` 压缩分支中，
   合并把 total 压进容差（`total <= cap`）但 `dialogue_floor_sum > target_seconds`
   时，上报 `dialogue_floor_exceeded_seconds = dialogue_floor_sum - total`
   （下限与当前总时长的差额）；`total > cap` 的旧语义保持不变。
   注意 `_merge_shot_into` 对 dialogue 按 JSON 去重——完全相同文本的镜头
   合并后台词不重复累计，属正确行为。
3. P2 提示词层：`story-writer/SKILL.md` 新增「片长与台词字数预算（必须遵守）」
   章节（公式、中英速查表、创作规则、自检、元信息输出），旧硬编码字数经验
   （创作要点 / 字数控制技巧）改为引用预算；`script-orchestrator/sops/
   sop-new-script.md` 派发 story-writer 时必须透传目标片长与预算换算。
4. P2 工具层：`create_script_json` / `update_script_json` 新增可选参数
   `target_duration_seconds`（schema 同步），保存时统计口播字数写
   `dialogue_stats`（`chars` / `estimated_seconds`，可选 `target_duration_seconds` /
   `budget_chars`），超预算 ×1.2 在返回中给出 `duration_warning`（不阻塞保存）；
   台词过滤复用拆分端 `extract_script_dialogue_text`，过滤为空时回退全文口径。
5. 测试：`tests/test_script_duration_budget.py`（常量收敛、混合速率、
   1/2/3 分钟档预算、floor 缺口回归、SKILL/SOP 静态防漂移、dialogue_stats
   与 warning）。`tests/llm/test_script_split_total_duration.py` 等
   93 个时长相关用例全绿；`tests/js/test_storyboard_script_split_static.js` 通过。
6. P3 未做（后续可选）：拆分端规划阶段读取 `dialogue_stats` 做
   「declared vs 物理下限」提前预警。当前 floor 上报修复已保证超限透明。
