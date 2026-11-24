# 剧本拆分 · 分镜节奏权重 / 首帧单一画面 / 台词内角色标记 / 手部动作预算 / 场景图纯环境

> 分支 develop_f1181。三个拆分质量问题一次修复，全部为提示词引导 + 确定性兜底，不改数据结构与接口。
> 第 4 节（手部动作预算/肢体结构）与第 5 节（场景图无人空镜）由 develop_f1168 追加（2026-11-24，任务移交文档 `storyboard_hand_guard_prompt_task.md` 及后续口头需求）。

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

### 4. 动作描述自相矛盾（双手+另一只手）→ 生图多手畸变（develop_f1168）

**现象**：拆分 LLM 在同一镜头的 description / action / opening_frame_description 里写出「双手撑着伞，用另外一只手推开门」——双手（2）+ 另一只手（1）= 3 只手，生图模型忠实复现必出多手。已核查两条链路（`llm/script_parser.py`、`services/storyboard_reference_prompt_service.py`）此前均无任何肢体正确性约束；火山 `images/generations` 接口无 negative_prompt，只能正向 prompt 约束。

**修复**（两层：拆分侧防「写错」+ 生图侧防「画错」）：

- 拆分侧：user prompt 第 3 条「分镜设计质量要求」新增**「手部动作预算制（单人单镜最多两只手）」**规则（紧邻「画面内容必须写可见动作」）：写含手部动作的描述前先盘点每只手在做什么；已写「双手/两手+动作X」后严禁再出现「另一只手/又用一手+动作Y」；出路只有单手改写或拆镜头（含正反例）。配套在多人对话拆分示例区追加 ✓ 正确5（opening_frame_description 带手部预算的 few-shot 呼应）。按移交文档边界要求，**不加** system prompt / SKILL.md 覆盖链（具体字段规则住用户提示模板规则区），**不做** LLM 输出后的自然语言数手拦截器。
- 生图侧：`config/constant.py` 新增 `STORYBOARD_LIMB_INTEGRITY_GUARD_TEXT`（`人物肢体结构准确：单个人物只出现两只手，每只手五根手指；画面中不得出现多余的手臂、手指或肢体。`），`services/storyboard_reference_prompt_service.py::append_limb_integrity_guard`（幂等，与单幅画面守卫同构），在全部三个生图入口与单帧守卫级联：`append_limb_integrity_guard(append_single_frame_guard(append_storyboard_visual_suffix(...)))`
  - `services/storyboard_agent_image_tool.py`（批量补图工具包装器）；
  - `services/storyboard_agent_cli_service.py::generate_image` 文生图 / 参考生图两分支。
  - 海外/网关供应商走同一生图入口自动获得守卫文本，无需单独适配。

> **边界（2026-11-24 用户否决，勿再引入）**：曾在 `script_split_qc_agent.py` 加过 `HAND_BUDGET_CONTRADICTION` 正则质检（「双手」类+「另一只手」类标记共现检测），用户明确否决——正则匹配自然语言中的语义内容（手数/矛盾）没有意义，防「写错」只能靠拆分 prompt 规则，防「画错」只能靠生图守卫，两层足够。

### 5. 场景参考图被画成有人场景（develop_f1168，2026-11-24 追加）

**现象**：场景描述若带人物活动（如剧本写"守卫把守的大门"，LLM 把它写进 location.description），会被原样拼进场景生图 prompt，生图模型把人画进场景参考图；场景图作为子场景 i2i / 首帧参考链的输入，人物污染会向下游扩散。此前全链路（组装模板/宫格提交层/抽取规则）均无任何「无人」约束。

**修复**（两层）：

- 抽取侧：user prompt 模板 locations 字段指导改为**只写无人环境**——顶层/子场景 description「严禁写任何人物、角色活动或人形身影」，atmosphere「只写光线、色调与情绪，不写任何人物」；环境声示例「行人脚步声」改为「雨滴声」（避免人物词汇拼进生图 prompt）。
- 生图侧守卫：`config/constant.py` 新增 `SCENE_NO_PEOPLE_GUARD_TEXT`（`纯环境空镜：画面中不出现任何人物、人形轮廓、手部或身体局部；仅呈现场景空间、物品与光照本身。`），`services/storyboard_reference_prompt_service.py::append_scene_no_people_guard`（幂等，与既有守卫同构），在场景 prompt 唯一组装源 `services/storyboard_location_bootstrap_service.py` 的 `_compose_root_location_prompt`（顶层 t2i）/`_compose_subscene_prompt`（子场景 i2i）尾部幂等追加。enterprise 质检前置（`location_references.py::_submit_ready_layer`）复用同一 bootstrap 服务，自动覆盖；黑色占位格不追加（无场景内容）。

## 注意事项

- `duration_budget_block` 与 multi_reference `replace` 是**双处文案联动**，今后改动该句必须两处同步（本次已同步）。
- SKILL.md 支持用户在「技能配置」中自定义覆盖；自定义用户不会自动获得新规则，如需生效须更新其自定义技能内容。
- 存量已拆分任务的 dialogue.text 不回溯清洗，仅新生成结果生效。

## 验证

- 单测：`tests/llm/test_script_parser_dialogue_text_sanitizer.py`（新增）、`tests/services/test_storyboard_reference_prompt_service.py`（追加 guard 用例）、`tests/services/test_storyboard_agent_image_tool.py`（断言更新为含守卫）。
- 第 4 节（develop_f1168）：`tests/services/test_storyboard_reference_prompt_service.py`（`test_append_limb_integrity_guard_appends_and_is_idempotent`）、`tests/services/test_storyboard_agent_image_tool.py` / `tests/storyboard/test_storyboard_agent_cli_service.py`（三生图入口守卫断言）、`tests/llm/test_script_parser_scene_grouping.py`（`test_prompt_contains_hand_action_budget_rule`）。
- 第 5 节（develop_f1168）：`tests/services/test_storyboard_reference_prompt_service.py`（`test_append_scene_no_people_guard_appends_and_is_idempotent`）、`tests/services/test_storyboard_location_bootstrap_service.py`（`TestSceneNoPeopleGuardInComposedPrompts` 根/子场景组装守卫断言）、`tests/llm/test_script_parser_scene_grouping.py`（`test_prompt_requires_scene_description_without_people`）。
- 本地 13008 全栈实测拆分剧本验证节奏/首帧/台词三处效果（见分支提交记录）。
