# 角色引用改造：以 ID 为权威源 + 合并阶段 token 重拼

> 状态：方案设计（待实施）
> 关联问题：剧本拆分段生成阶段 `character_name_mismatch` 硬校验频繁卡死任务
  （如 `角色 char_010 名称必须为"卢卡莫德里奇"，实际为"莫德里奇"`）
> 关联生产任务：task 218

## 一、问题本质

角色在 prompt 文本里用 `【【角色名】】` token 引用，**身份靠"名字字符串"承载**。
这把一个本应确定性的"身份标识"问题，退化成了"LLM 能否逐字拼写长字符串"的
概率问题，而 LLM 恰恰最不擅长逐字复现长名字。

### 1.1 现状链路（脆弱点）

```
DB 角色全名 "卢卡莫德里奇"
  → prompt 要求 LLM 写 【【卢卡莫德里奇】】
  ← LLM 写成 【【莫德里奇】】（中文语境通行简称，语言习惯滑回）
  → 段生成硬校验：actual("莫德里奇") != expected("卢卡莫德里奇")
     → 严格全等，报 character_name_mismatch
     → 3 轮重试（每轮都反馈了正确名字）LLM 仍大概率写简称
     → 任务 paused，resume 清零重试仍复现，用户难以脱困
  → 即使绕过校验，生图阶段：_resolve_prompt_characters 提取"莫德里奇"
     → CharacterModel.get_by_name(world_id, "莫德里奇") 精确等值查询
     → 查不到（DB 只有"卢卡莫德里奇"）→ 角色参考图静默丢失
     → 生图无该角色形象（静默劣化，不报错）
```

### 1.2 为什么质检反馈救不了

质检错误**确实**喂给了 LLM（`_build_qc_feedback` → `qc_retry_block`），但：
1. 这是**语言习惯冲突**不是逻辑错误——LLM 在中文语境天然倾向用"莫德里奇"；
2. 单段一次报 **40+ 条**同类错误（name_mismatch / prompt_name_invalid /
   missing_from_image / missing_from_video），feedback 截断到前 40 条，
   关键信息被淹没；
3. 校验**零容错**——只要一个镜头的 `【【】】` 没写全名就整轮 fail。

### 1.3 根本缺陷

角色引用**不应依赖名字字符串**。系统手里明明有稳定、唯一、确定性的
`character_db_id`（DB 主键）和 `char_010`（段内 ID），却让 LLM 在自然语言里
拼写中文名字，下游再用这个名字精确反查 DB——一来一回全靠字符串匹配。

> 关键事实：`characters_present` / `focus_character_ids` / `dialogue.character_id`
> 这些**结构化字段早就用 ID 了**（`char_010`），完全可靠。唯一没用 ID 的是
> `opening_frame_description` 等**给下游生图模型看的自然语言文本**里的
> `【【角色名】】` token。

## 二、方案核心思路

**承认 LLM 写不对全名是常态，把"拼写全名"的职责从 LLM 转移到后端确定性兜底。**

LLM 只需写"画面里这个角色在哪、什么姿态"（它擅长的），身份由
`characters_present` 的 `char_010` 决定（确定性的）。后端在合并阶段用 ID 的
权威全名，**强制覆盖** token 里 LLM 写的任何内容（全名/简称/错字都被纠正）。

下游生图拿到的还是 `【【卢卡莫德里奇】】`（它需要的人类可读形式），但这个
token 是后端拼的，不是 LLM 写的——100% 可靠。

```
LLM 输出: characters_present=["char_010"]
         opening_frame_description="中景：【【莫德奇】】在左侧..."
                                      ↑ LLM 写错（少字），无所谓

合并阶段重拼:
  char_010 → DB → 全名"卢卡莫德里奇"
  → 把【【莫德奇】】强制改成【【卢卡莫德里奇】】

下游生图: "中景：【【卢卡莫德里奇】】在左侧..."
  → get_by_name("卢卡莫德里奇") ✅ 命中，参考图正确挂载
```

**为什么不靠"简称子串匹配"（如"莫德里奇"是"卢卡莫德里奇"的子串）？**
那只是把严格全等的门槛降低，仍是概率问题——LLM 写成"莫德奇""小魔"或错别字
照样崩。只有"用 ID 反查全名再强制覆盖"才是确定性的，不依赖 token 里的名字
字符串能否匹配到什么。

## 三、关键架构约束（已查实）

改造前必须理解数据流，它决定了重拼逻辑能放在哪、不能放在哪。

### 3.1 ID 在"发布"环节被丢弃

```
拆分阶段 (script_split_task)          发布阶段              生图阶段 (storyboard_scene)
──────────────────────────         ─────────────         ─────────────────────────
final_result_json                  prompt_payload        prompt_json
  shot.characters_present ───────►  (char_id 被丢!) ───►  只剩 character_desc
  = ["char_010"]                   只留 character_desc       (名字顿号拼接串)
  characters[].character_db_id     = "卢卡莫德里奇"        【【卢卡莫德里奇】】文本
  (char_010 → db_id 4771)                                  没有 char_id！没有 db_id！
```

- `storyboard_scene.prompt_json` **没有** `characters_present` / `character_id`，
  发布时（`api/storyboard.py:685-707` 的 `prompt_payload`）只把名字拼成
  `character_desc` 顿号串，ID 全丢。
- `storyboard_scene` 表也**没有版本字段**能区分新旧格式。

**结论：重拼必须放在合并阶段（ID 还在时），不能放生图阶段（拿不到 ID）。**
这与已确认的实施取向一致——"合并阶段就重拼"。

### 3.2 合并阶段数据齐全

`merged`（`_merge_segments` 产出，`script_split_engine.py:1517`）同时握有：
- `merged.characters[].id`（如 `char_010`）+ `merged.characters[].character_db_id`（如 `4771`）
- `shot_groups[].shots[].characters_present`（如 `["char_010"]`）
- shot 文本字段里的 `【【名】】` token

重拼所需的"ID → 权威全名"映射链路完整，可在此环节确定性覆盖 token。

### 3.3 下游消费链路（保持不动）

`services/storyboard_agent_cli_service.py`：
- `_resolve_prompt_characters`（:3354）：从 `【【名】】` 提取名字 →
  `CharacterModel.get_by_name` 精确等值反查 DB → 拿角色记录（含参考图）。
- 查不到则**静默跳过**，角色既无参考图也不进图例（静默劣化，不报错）。

改造后这些环节**保持不变**——它们消费的是已重拼的正确全名文本，自然受益，
无需改动。

## 四、详细改动设计

### 4.1 新增 token 重拼工具

**文件**：`services/script_split_registry.py`（与既有 ID 重写工具同模块）
**新增公开函数**：`rewrite_character_tokens_by_id(parsed) -> parsed`

逻辑：
1. **建索引**：`parsed["characters"]` → `{char_id: canonical_name}`。
   实体 name 即真源（合并阶段已收敛，见 `_merge_entity_collection`）；
   带 `character_db_id` 的优先用契约快照的 `canonical_name`（若有）。
2. **遍历 shot**：对每个 `shot_groups[].shots[]`：
   - 取 `shot.characters_present`（char_id 列表，权威在场角色）。
   - 对 4 个文本字段（复用 `script_split_character_contract._VISUAL_PROMPT_FIELDS`：
     `opening_frame_description`/`scene_detail`/`description`/`action`）做 regex 重写：
     - `re.sub(r"【【([^】]+)】】", replacer, text)` 逐 token 处理。
     - **重写策略**（位置对齐 + 兜底）：
       - 收集该字段所有 token 及其位置；
       - 收集该 shot 的 present 角色全名列表；
       - **优先**：token 名已等于某 present 角色全名 → 保留（幂等，避免重复改）；
       - **次选**：token 名未匹配 → 按出现顺序与"剩余未匹配的 present 角色"
         一一对齐，强制改成对应全名；
       - **兜底**：token 数 ≠ present 数（LLM 漏写/多写），无法对齐的 token
         保持原样，仅 `logger.warning` 记录，不破坏语义。
3. **同步处理 dialogue**：`shot.dialogue[].character_name` 若含 `【【】】`
   token，按 `dialogue.character_id` 反查全名重写（dialogue 的 character_id
   是可靠的）。
4. **原地修改并返回** `parsed`（与 `renumber_entities_by_name` 风格一致）。

**复用既有资产**：
- `script_split_character_contract._VISUAL_PROMPT_FIELDS`（字段名常量，:22）
- `_apply_id_map_inplace`（:132）的"递归遍历"思路——但 token 重写是针对
  `【【】】` 内部 regex sub，需新写 replacer，不直接复用该函数。

### 4.2 合并阶段接入重拼

**文件**：`services/script_split_engine.py`，函数 `_finalize_merge`（:1189 附近）

在 `_merge_segments` 之后、`sanitize_parsed_*` 系列之后（sanitize 只清 id
引用不动文本，安全），插入：
```python
from services.script_split_registry import rewrite_character_tokens_by_id
merged = rewrite_character_tokens_by_id(merged)
```

**位置选择**：放在 `if strategy.parallel_enabled` 分支**之外**（:1213 之前或
:1227 之后），保证 speed / quality 两条路径都走（speed 同样有 LLM 写错名字
的问题）。

### 4.3 放宽名字硬校验

**文件**：`services/script_split_character_contract.py:223-234`

`character_name_mismatch` 判定改造：
```python
# 旧：严格全等
if actual_name != expected_name:
    errors.append(_hard_error("character_name_mismatch", ...))

# 新：有 db_id（身份已由 DB 锁定）即放行，合并阶段会重拼纠正
if actual_name != expected_name:
    if db_id and expected_name:
        # 身份确定，名字写错会被合并阶段 rewrite_character_tokens_by_id 纠正
        # 不报 mismatch，避免 LLM 语言习惯导致的死循环
        logger.info("角色 %s 名字'%s'≠真源'%s'，有 db_id 将由重拼纠正",
                    character_id, actual_name, expected_name)
    else:
        errors.append(_hard_error("character_name_mismatch", ...))
```

同理放宽 `character_prompt_name_invalid`（:280-296）：token 名不全等但能从
该 shot 的 `characters_present` 唯一确定角色时，认可（合并会重拼）。

**保持不动**：
- `character_missing_from_image_prompt` / `character_missing_from_video_prompt`
  （:324-343）：这是结构性校验（角色必须在场），重拼不改变"在不在场"。
- `character_db_id_unknown` / `character_name_alias_ambiguous` 等真正不可恢复
  的错误：保持硬门禁。

**测试同步**：`tests/services/test_script_split_character_contract.py` 中约 8 处
相关断言需调整——把"严格全等报错"的预期改为"有 db_id 即通过"。

### 4.4 文档同步

- 本文档（`docs/backend/character_reference_by_id_design.md`）
- `docs/script/script_parser_incremental_split_design.md`：角色引用规则章节，
  说明"身份以 ID 为权威源，合并阶段 token 重拼"。

## 五、历史数据兼容策略（核心）

**原则：新逻辑只让事情变好，不让历史数据变得更糟。**

| 情况 | 数据状态 | 兼容方式 | 结果 |
|---|---|---|---|
| **① 旧拆分任务未发布** | `final_result_json` 在（含 ID + token） | 发布时走新重拼 | ✅ 自动修复 |
| **② 旧任务已发布、final_result_json 未清** | scene 已落库 + 上游在 | 重新发布时重拼 | ✅ 修复 |
| **③ 旧 scene、final_result_json 已清/任务已删** | 只剩 `prompt_json`（无 ID） | 维持现状 | ⚠️ 不变更糟 |

### 5.1 情况①②：ID 还在，自动修复

合并阶段重拼对所有走拆分的任务生效。旧任务只要 `final_result_json` 还在
（`script_split_engine.py:408-413` 的 `clear_final_result` 未触发），
重新走发布即可重拼。新发布的 scene token 即为正确全名。

### 5.2 情况③：无 ID 兜底，维持现状

只剩 `storyboard_scene.prompt_json`（token 文本，无 char_id）的老 scene，
无法走 ID 反查重拼。此时：
- **保留** `services/storyboard_reference_prompt_service.py:253-271`
  `extract_storyboard_reference_names`（基于 `【【...】】` regex 抽名字）
  + `CharacterModel.get_by_name` 精确反查路径，作为兜底。
- 行为与改造前**完全一致**：名字对得上则挂参考图，对不上则静默跳过
  （参考图缺失），**不引入新回归**。

不强制迁移这类数据——它们在旧逻辑下能跑（生图可能丢角色形象，但本就是
现状），新逻辑不触碰它们。

### 5.3 不新增版本字段的理由

考虑过给 `prompt_json` 加 `ref_schema_version` 区分新旧，但：
- 情况③靠"final_result_json 是否存在"自然区分（在则重拼，不在则走旧路径），
  无需额外版本字段；
- 加字段需迁移老数据（回填困难，老数据本就无 ID），收益不大。

故采用"启发式判断"（数据里有无 ID 可重拼）而非版本字段。

## 六、不改动项

- **生图环节**（`_compose_image_prompt`/`_resolve_prompt_characters`/
  `storyboard_reference_prompt_service`）：保持现状，消费已重拼文本，自然受益。
- **token 格式**（`【【名】】`）：不改成 `【【id】】`。下游生图模型需要人类
  可读名字（它看不懂 `char_010`），改成 ID 引用需动生图驱动、prompt 模板、
  所有示例，改动过大且收益不增量（重拼已解决）。
- **character_card 表结构**：不加 alias/简称字段。用 ID 兜底已足够，
  无需用户维护别名（用户维护别名本身也是负担，且未必维护全）。
- **LLM prompt 模板**：不改动"要求 LLM 用全名"的指令（保持质量导向），
  只是后端不再依赖 LLM 真的写对。

## 七、验证方案

### 7.1 真实数据复跑
用 task 218 真实段数据复跑合并：
- 合并后所有 shot 的 `【【】】` token 均为 DB 全名（"卢卡莫德里奇"而非"莫德里奇"）；
- 放宽校验后段生成阶段不再报 `character_name_mismatch`；
- 任务能跑通合并 → 发布 → 生图全流程。

### 7.2 单元测试
- `tests/services/test_script_split_registry.py`：新增 `rewrite_character_tokens_by_id`
  测试覆盖：
  - 简称/错字被纠正为全名（task 218 场景）；
  - token 数 == present 数的位置对齐；
  - token 数 ≠ present 数的兜底（保持原样 + warning）；
  - dialogue.character_name token 重写；
  - 幂等性（已是全名的不重复改）。
- `tests/services/test_script_split_character_contract.py`：调整约 8 处断言
  （"严格全等报错" → "有 db_id 即通过"），新增"无 db_id 仍报 mismatch"用例。
- `enterprise/tests/services/test_script_split_quality.py`：确认合并重拼不破坏
  quality 流程（已修的 merge 收敛 + 新增重拼叠加）。
- `tests/services/test_script_split_engine.py`：确认 `_finalize_merge` 接入重拼
  后全流程正常。

### 7.3 风险点回归
- 放宽校验后，确认"有 db_id 即放行"不会让真正错误的角色蒙混——有 db_id 意味着
  身份由 DB 锁定，名字错会被重拼纠正，下游不受影响。
- 重拼 M≠N 兜底靠位置启发式，极端情况可能误对齐，但兜底是"保持原样 + warning"，
  不比现状差。

## 八、实施顺序建议

1. **先做 4.1 重拼工具 + 4.2 合并接入**（核心，独立可验证）——用 task 218
   数据验证 token 被纠正。
2. **再做 4.3 放宽校验**（依赖 4.1，否则放宽后下游名字仍错）——放开段生成
   卡点，task 218 能跑通。
3. **最后 4.4 文档同步**（本文档 + incremental_split_design.md）。

每步独立验证，避免一次大改难以定位问题。

## 九、相关文件索引

- `services/script_split_registry.py` — 新增 `rewrite_character_tokens_by_id`
  （:132 `_apply_id_map_inplace`、:302 `renumber_entities_by_name` 为参考范式）
- `services/script_split_engine.py` — `_finalize_merge`（:1189）接入重拼
- `services/script_split_character_contract.py` — 放宽 `character_name_mismatch`
  （:223-234）、`_VISUAL_PROMPT_FIELDS`（:22）
- `services/storyboard_agent_cli_service.py` — `_resolve_prompt_characters`（:3354，
  下游消费，不动）
- `api/storyboard.py` — `prompt_payload`（:685-707，发布丢 ID 的根因，不动）
- `model/storyboard_scene.py` — `prompt_json` 列（:346，无 ID 无版本）
- `tests/services/test_script_split_character_contract.py` — 约 8 处断言调整
- `tests/services/test_script_split_registry.py` — 新增重拼测试
