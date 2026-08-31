---
name: sop-new-script
description: 新建剧本工作流，从零开始创作完整剧本，包括大纲生成、剧本编写、合规检查、角色创建、场景道具创建、形象生成和资产就绪检查。
---

# 新建剧本工作流

## 适用场景
用户需要从零开始创作完整的剧本，包括大纲、剧本内容、角色卡、场景道具等全套资产。

## 流程图

```
剧本架构师（环境分析+需求收集）
    ↓
plot-analyzer（确定故事大纲）
    ↓
验证大纲是否生成 ← ─┐
    ↓                │
    ├─ 已生成 → 继续  │
    └─ 未生成 → 重新调用 plot-analyzer ──┘
    （最多循环3次）
    ↓
用户确认大纲 ← ─┐
    ↓            │
    ├─ 满意 → 继续 │
    └─ 不满意 → 重新调用 plot-analyzer ──┘
    ↓
story-writer（编写剧本内容）
    ↓
用户确认剧本 ← ─┐
    ↓            │
    ├─ 满意 → 继续 │
    └─ 不满意 → 重新调用 story-writer ──┘
    ↓
content-compliance-checker（剧本检查）← ─┐
    ↓                                    │
    ├─ 通过 → 继续                        │
    └─ 不通过 → 返回 story-writer 修改 ──┘
    （最多循环3次）
    ↓
character-creator（创建角色卡）
    ↓
验证角色卡已创建 ← ─┐
    ↓                │
    ├─ 已创建 → 简要展示后继续 │
    └─ 未创建 → 重新调用 character-creator ──┘
    （最多循环3次）
    ↓
character-image-designer（立即为所有缺图角色生成形象+音色，无需用户选择）
    ↓
location-creator（创建场景和道具）
    ↓
验证场景和道具已创建 ← ─┐
    ↓                    │
    ├─ 已创建 → 简要展示后继续 │
    └─ 未创建 → 重新调用 location-creator ──┘
    （最多循环3次）
    ↓
location-prop-image-designer（立即为所有缺图场景道具生成形象，无需用户选择）
    ↓
asset-readiness-checker（资产就绪检查）
```

## 进度显示

```
【新建剧本进度】
✅ 感知环境
✅ 收集需求
✅ 需求分流
🔄 生成故事大纲
⏳ 确认大纲
⏳ 编写剧本
⏳ 确认剧本
⏳ 合规检查
⏳ 创建角色卡
⏳ 角色形象设计
⏳ 创建场景道具
⏳ 场景道具形象设计
⏳ 资产就绪检查
```

## 详细步骤

1. **调用 plot-analyzer**
   - 任务：根据用户需求确定故事大纲
   - 输入：用户需求、风格、集数
   - 输出：完整的故事大纲（包含每集的核心情节）

1.5. **验证大纲是否生成（关键步骤）**
   - **必须执行**：调用 `read_world(limit=500)` 查看大纲是否已经生成并保存
   - **注意**：使用 `limit` 参数限制返回字符数，避免token过度消耗
   - **检查逻辑**：
     - 如果 `read_world()` 返回的 `story_outline` 字段为空或不存在 → 大纲未生成
     - 如果 `story_outline` 字段有内容 → 大纲已生成
   - **处理流程**：
     - 如果大纲未生成：重新调用 plot-analyzer，提醒其必须调用 `update_world()` 保存大纲
     - 如果大纲已生成：进入步骤1.6（用户确认）
     - 最多重试3次，如果仍未生成，向用户报告问题

1.6. **用户确认大纲（关键步骤）**
   - **必须执行**：向用户展示生成的大纲，并询问是否满意
   - **展示内容**：
     - 使用 `read_world()` 获取 `story_outline` 字段的完整内容
     - 清晰地向用户展示大纲的各个部分（标题、集数、每集梗概等）
   - **询问用户**：
     - 先向用户展示大纲内容（标题、集数、每集梗概等），然后调用：
     ```
     ask_user(
       question: "【故事大纲已生成】\n\n<展示大纲内容>\n\n请问您对这个大纲是否满意？",
       options: ["满意，继续", "不满意，需要修改"]
     )
     ```
   - **处理用户反馈**：
     - **如果用户选择"满意，继续"**：继续步骤2（调用 story-writer）
     - **如果用户选择"不满意，需要修改"**：
       1. 用户会在自由输入中说明修改意见
       2. 重新调用 plot-analyzer，并在 `task_description` 中明确说明用户的修改要求
       3. 返回步骤1.5重新验证大纲
   - **注意事项**：
     - 必须等待用户明确回复后才能继续
     - 不要假设用户满意，必须得到明确确认
     - 如果用户提出修改意见，要完整传递给 plot-analyzer

2. **调用 story-writer**
   - 任务：根据大纲编写剧本内容
   - 输入：故事大纲、用户需求
   - 输出：剧本文件（JSON格式）

2.5. **用户确认剧本（关键步骤）**
   - **必须执行**：向用户展示生成的剧本，并询问是否满意
   - **展示内容**：
     - 使用 `list_scripts()` 和 `get_script()` 获取生成的剧本内容
     - 展示剧本的关键信息：标题、集数、每集梗概或部分内容
   - **询问用户**：
     - 先向用户展示剧本摘要或部分内容，然后调用：
     ```
     ask_user(
       question: "【剧本已生成】\n\n<展示剧本摘要或部分内容>\n\n请问您对这个剧本是否满意？",
       options: ["满意，继续", "不满意，需要修改"]
     )
     ```
   - **处理用户反馈**：
     - **如果用户选择"满意，继续"**：继续步骤3（调用 content-compliance-checker）
     - **如果用户选择"不满意，需要修改"**：
       1. 用户会在自由输入中说明修改意见
       2. 重新调用 story-writer，并在 `task_description` 中明确说明用户的修改要求
       3. 返回本步骤重新确认剧本
   - **注意事项**：
     - 必须等待用户明确回复后才能继续
     - 不要假设用户满意，必须得到明确确认
     - 如果用户提出修改意见，要完整传递给 story-writer

3. **调用 content-compliance-checker（循环检查）**
   - **第一步：调用 content-compliance-checker 进行审核**
     ```
     call_agent(
       AgentName: "content-compliance-checker",
       task_description: "请审核剧本的合规性和质量，检查是否包含违规内容、角色一致性、大纲一致性以及每集末尾的钩子设计"
     )
     ```

   - 检查项：
     - 是否包含真实国家名称
     - 是否包含黄赌毒内容
     - 是否包含极端封建迷信
     - 角色一致性
     - 大纲一致性
     - 每集末尾是否有吸引人的钩子

   - **检查完成后的处理流程**：
     a. 使用 `get_script_problem(limit=200)` 获取审核结果
     b. 检查返回的 `verdict` 字段：
        - `verdict: true` → 剧本通过，继续下一步
        - `verdict: false` → 剧本有问题，需要修改

   - **如果不通过（verdict: false）**：
     - 使用 `get_script_problem()` 获取完整审核结果，提取 `problem` 字段的内容
     - 调用 story-writer 修改剧本，**必须**使用 `conversation_history` 参数传递问题：
       ```
       call_agent(
         AgentName: "story-writer",
         task_description: "请根据审核报告修改剧本，解决发现的问题",
         conversation_history: [
           {
             "role": "user",
             "content": <直接将 get_script_problem 返回的 problem 字段内容放在这里>
           }
         ]
       )
       ```
     - 最多循环6次

   - **如果通过或达到最大次数**：继续下一步

4. **调用 character-creator**
   - ⚠️ **执行要求**：必须立即调用 `call_agent(AgentName: "character-creator", ...)`，不要只说"正在执行"
   - 任务：为剧本中的角色创建详细角色卡
   - 输入：剧本内容
   - 输出：角色JSON文件（包含性格、习惯、关系网）

4.3. **验证角色卡并简要展示（默认不询问满意度）**
   - **⚠️ 一步到位原则（必须遵守）**：角色卡创建完成后，**不要询问用户是否满意、不要让用户选择生成哪些角色**，直接简要展示后立即进入步骤4.5 调用 character-image-designer
   - **⚠️ 精细模式例外（介入程度=精细·多确认时必须执行）**：若本任务的用户消息前带有「[系统指令·AI介入程度：精细·多确认]」标记，则本步骤不一步到位，恢复确认流程：
     1. 先调用 `ask_user` 展示角色清单，确认角色卡是否满意：`options: ["满意，继续", "不满意，需要修改"]`（不满意 → 收集修改意见，重新调用 character-creator 后回到本步骤）
     2. 满意后调用 `ask_user` 让用户选择需要生成形象的角色：`options` 只列 `reference_image` 为空的角色，`multiSelect: true`
     3. 按用户选择进入步骤4.5，此时任务描述改为"请为以下角色生成形象设计图：[用户选择的角色列表]"
   - **必须执行**：验证角色卡已创建并向用户简要展示
   - **验证逻辑**：
     - 调用 `list_character_jsons()` 获取所有角色列表
     - 如果列表为空 → 重新调用 character-creator（最多3次）
     - 如果列表非空 → 继续
   - **展示内容**（单条消息，展示后立即调用下一步，不等待用户回复）：
     ```
     【角色卡已创建】共[N]个角色：
     - 角色A：一句话简介（身份/性格）
     - 角色B：一句话简介
     ...
     💡 正在为缺少形象的角色自动生成形象图和音色，如需调整角色卡可随时告诉我
     ```
   - **说明**：角色卡详情用户可在左侧文件面板查看；若用户后续对角色卡不满意，可随时提出，PM 会重新调用 character-creator 修改后重新生成形象

4.5. **调用 character-image-designer（为所有缺图角色生成形象）**
   - **⚠️ 执行要求**：步骤4.3展示完成后，**必须在同一轮对话中立即调用** `call_agent(AgentName: "character-image-designer", ...)`，不要等待用户回复
   - 任务：为**所有缺少 `reference_image` 的角色**生成形象设计图和音色
   - 输入：角色JSON文件
   - 输出：角色参考图像 + 参考音频
   - 说明：character-image-designer 会自动扫描缺图角色并批量生成，无需人工圈定名单；生成完成后同步为缺少音色（`default_voice`）的角色生成参考音频。**精细模式下**若步骤4.3用户已选定角色列表，则改为只为该列表生成
   - **生成方式**：使用4宫格批量生成（每次4个角色），自动切分后保存
   - **任务描述（默认/简洁模式）**：
     ```
     call_agent(
       AgentName: "character-image-designer",
       task_description: "请扫描所有角色，为所有缺少 reference_image 的角色生成形象设计图。

       要求：
       1. 使用4宫格批量生成方式（详见character-image-designer技能说明）
       2. 只为缺少 reference_image 的角色生成图像，已有形象的跳过
       3. 先调用 read_world() 获取 visual_style，按画风选择模板：写实用摄影术语，动漫用 reference sheet 术语
       4. 确保角色形象与角色卡描述一致"
     )
     ```
   - **任务描述（精细模式，用户已选定角色时）**：`task_description: "请为以下角色生成形象设计图：[用户选择的角色列表]。要求同上（4宫格批量、只为指定角色生成、按画风选模板）"`
   - ⚠️ **完成后不要说"正在执行：调用 location-creator"**，直接进入步骤5立即调用

5. **调用 location-creator**
   - ⚠️ **执行要求**：必须立即调用 `call_agent(AgentName: "location-creator", ...)`，不要只说"正在执行"
   - 任务：创建剧本中的场景和道具
   - 输入：剧本内容
   - 输出：场景和道具JSON文件

5.3. **验证场景和道具并简要展示（默认不询问满意度）**
   - **⚠️ 一步到位原则（必须遵守）**：场景和道具创建完成后，**不要询问用户是否满意、不要让用户选择生成哪些**，直接简要展示后立即进入步骤5.5 调用 location-prop-image-designer
   - **⚠️ 精细模式例外（介入程度=精细·多确认时必须执行）**：若本任务的用户消息前带有「[系统指令·AI介入程度：精细·多确认]」标记，则本步骤恢复确认流程：
     1. 先调用 `ask_user` 展示场景和道具清单，确认是否满意：`options: ["满意，继续", "不满意，需要修改"]`（不满意 → 收集修改意见，重新调用 location-creator 后回到本步骤）
     2. 满意后调用 `ask_user` 让用户选择需要生成形象的场景和道具：`options` 只列 `reference_image` 为空的项目，`multiSelect: true`
     3. 按用户选择进入步骤5.5，此时任务描述改为只为用户选定的场景和道具生成
   - **必须执行**：验证场景和道具已创建并向用户简要展示
   - **验证逻辑**：
     - 调用 `list_location_jsons()` 和 `list_prop_jsons()` 获取列表
     - 如果两者都为空 → 重新调用 location-creator（最多3次）
     - 如果任一非空 → 继续
   - **展示内容**（单条消息，展示后立即调用下一步，不等待用户回复）：
     ```
     【场景和道具已创建】共[M]个场景、[N]个道具：
     - 场景：场景A、场景B、...
     - 道具：道具X、道具Y、...
     💡 正在为缺少形象的场景和道具自动生成形象图，如需调整可随时告诉我
     ```
   - **说明**：若用户后续对场景/道具不满意，可随时提出，PM 会重新调用 location-creator 修改后重新生成形象

5.5. **调用 location-prop-image-designer（为所有缺图场景道具生成形象）**
   - **⚠️ 执行要求**：步骤5.3展示完成后，**必须在同一轮对话中立即调用** `call_agent(AgentName: "location-prop-image-designer", ...)`，不要等待用户回复
   - 任务：为**所有缺少 `reference_image` 的场景和道具**生成形象设计图（**精细模式下**若步骤5.3用户已选定列表，则只为该列表生成）
   - 输入：场景和道具JSON文件
   - 输出：场景和道具参考图像
   - **生成方式**：使用4宫格批量生成（每次4个场景/道具），自动切分后保存
   - **任务描述（默认/简洁模式）**：
     ```
     call_agent(
       AgentName: "location-prop-image-designer",
       task_description: "请扫描所有场景和道具，为所有缺少 reference_image 的场景和道具生成形象设计图。

       要求：
       1. 使用4宫格批量生成方式（详见location-prop-image-designer技能说明）
       2. 只为缺少 reference_image 的场景和道具生成图像，已有形象的跳过
       3. 为场景生成detailed location design reference sheet风格的设计图
       4. 为道具生成detailed prop design reference sheet风格的设计图
       5. 确保形象与描述一致"
     )
     ```
   - **任务描述（精细模式，用户已选定项目时）**：`task_description: "请为以下场景和道具生成形象设计图：场景=[列表]，道具=[列表]。要求同上"`

6. **调用 asset-readiness-checker**
   - 说明：在所有资产创建完成后，调用资产就绪检查专家进行最终检查
   - ⚠️ **执行要求**：必须立即调用，不要只说"正在执行"
   - **任务描述**：
     ```
     call_agent(
       AgentName: "asset-readiness-checker",
       task_description: "请检查当前所有资产的完备性，包括角色（reference_image 和 default_voice）、场景（reference_image）、道具（reference_image），以及世界画风（visual_style）和构图倾向（composition_preference）的合理性和精简性。同时提醒用户点击提交数据按钮。"
     )
     ```
   - 专家会生成完整的检查报告并展示给用户
   - 如果报告中有画风/构图问题，使用 `update_world()` 修正后重新检查
