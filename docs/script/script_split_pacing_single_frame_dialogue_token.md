# 剧本拆分 · 分镜节奏权重 / 首帧单一画面 / 台词内角色标记

> 分支 develop_f1181。三个拆分质量问题一次修复，全部为提示词引导 + 确定性兜底，不改数据结构与接口。

## 问题与修复

### 1. 分镜密度未随剧情权重变化（重点不细、过渡拖沓）

**现象**：重点剧情与过渡情节分镜密度接近——过渡情节（赶路/场景转换/纯交代）被拆出反应镜头、多角度、氛围空镜，稀释镜头预算；重点剧情反而节拍不足。

**修复**（提示词层，两处同文案）：

- `script_writer_core/skills/script-parser/SKILL.md` 新增第 2.1 条「分镜密度必须匹配剧情权重·硬性规则」：重点剧情（冲突/转折/高潮/关键对白）详细拆分；过渡情节压缩为 1 个 2~4 秒镜头或并入相邻镜头，禁止单独拆反应/多角度/空镜；判断标准 = 删掉该镜头观众是否遗漏关键信息。
- `llm/script_parser.py` user prompt 第 3 条「分镜设计质量要求」加入同规则 + 正反例。
- 总时长预算块（`duration_budget_block`）的「达成方式」句去掉"过渡镜头"字样并加"镜头优先拆在重点剧情上"；**同步更新 multi_reference 分支对该句的 `replace` 匹配串**（两处必须逐字一致，否则参考生视频模式的文案改写静默失效）。

### 2. 画面提示词出现多个画面 → 生图宫格/多格拼图

**现象**：`opening_frame_description`（首帧生图提示词）出现"先…再…接着…"“随后镜头转向…"等先后多画面描述，文生图模型画出宫格图。

**修复**（提示词 + 生图链路兜底）：

- SKILL.md 第 11 条新增「单一画面·硬性规则」：ofd 只描述**同一个定格瞬间的单幅静止画面**，严禁先后多个动作瞬间/多个并列画面；动态过程属于视频侧字段。
- user prompt 第 6 条（ofd 要求）与 `JSON_FORMAT_EXAMPLE` 的 ofd 字段说明同步。
- 生图提交口统一追加**单幅画面守卫**（`services/storyboard_reference_prompt_service.py::append_single_frame_guard`，幂等）：`画面要求：单幅静止画面，只呈现一个定格瞬间的完整构图；禁止宫格、多格拼图、分屏、对比图、连环画式多个画面。` 挂载点：
  - `services/storyboard_agent_cli_service.py::generate_image` 文生图 / 参考生图两分支（单镜生图最终出口，含用户自定义 prompt）；
  - `services/storyboard_agent_image_tool.py`（批量补图工具包装器）。
  - 视频侧不加守卫（视频本应含动态）。

### 3. 台词引号内的角色名被加【【】】→ 误判在场角色

**现象**：台词原文（如 `"小李，你给我站住！"`）里的名字被模型加成 `【【小李】】`。台词里被喊到/被谈及的名字**不代表该角色出现在分镜画面中**，但下游 `extract_storyboard_reference_names` 按【【】】提取角色挂参考图，造成幽灵在场角色 + 参考图污染；未登记短名还会触发角色契约校验 `character_prompt_name_invalid`。

**修复**（提示词 + 后处理兜底）：

- SKILL.md 第 14 条新增「台词原文例外·硬性规则」+ 正反例：台词引号内部的角色名保持纯文本；【【】】只标记真正出现在画面中的角色描写与 `dialogue.character_name` 说话人字段。
- user prompt 第 7 条（含正反例）、7.2 条（完整对白规则）、`JSON_FORMAT_EXAMPLE` 的 description / dialogue.text 字段说明同步。
- 确定性兜底：`llm/script_parser.py::sanitize_dialogue_text_tokens` 在 parse 后处理链（location 清洗之后）无条件剥离 `dialogue[]/dialogues[].text` 内的 `【【…】】` 标记（纯台词字段内任何标记都应是纯文本，安全）；日志落 `script_parser_*_07b_dialogue_text_sanitized.json`。画面/动作描写字段中的标记不受影响。

## 注意事项

- `duration_budget_block` 与 multi_reference `replace` 是**双处文案联动**，今后改动该句必须两处同步（本次已同步）。
- SKILL.md 支持用户在「技能配置」中自定义覆盖；自定义用户不会自动获得新规则，如需生效须更新其自定义技能内容。
- 存量已拆分任务的 dialogue.text 不回溯清洗，仅新生成结果生效。

## 验证

- 单测：`tests/llm/test_script_parser_dialogue_text_sanitizer.py`（新增）、`tests/services/test_storyboard_reference_prompt_service.py`（追加 guard 用例）、`tests/services/test_storyboard_agent_image_tool.py`（断言更新为含守卫）。
- 本地 13008 全栈实测拆分剧本验证节奏/首帧/台词三处效果（见分支提交记录）。
