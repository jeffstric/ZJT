---
name: sop-continue-script
description: 续写剧本工作流，在已有剧本基础上续写新集数，包括大纲补全、续集编写、合规检查、补充新角色/场景/道具、形象生成和资产就绪检查。
---

# 续写剧本工作流

## 适用场景
用户需要在已有剧本基础上续写新集数，可能需要补充新角色、新场景和新道具。

## 流程图

```
剧本架构师（环境分析+需求收集）
    ↓
判断大纲是否完整
    ↓
    ├─ 不完整 → plot-analyzer（补全大纲）
    └─ 完整 → 跳过
    ↓
story-writer（编写续集内容）
    ↓
用户确认续集剧本 ← ─┐
    ↓              │
    ├─ 满意 → 继续   │
    └─ 不满意 → 重新调用 story-writer ──┘
    ↓
content-compliance-checker（剧本检查）← ─┐
    ↓                                    │
    ├─ 通过 → 继续                        │
    └─ 不通过 → 返回 story-writer 修改 ──┘
    （最多循环3次）
    ↓
character-creator（补充新角色）
    ↓
验证角色卡已创建 ← ─┐
    ↓                │
    ├─ 已创建 → 简要展示后继续 │
    └─ 未创建 → 重新调用 character-creator ──┘
    （最多循环3次）
    ↓
character-image-designer（立即为所有缺图角色生成形象+音色，无需用户选择）
    ↓
location-creator（补充新场景和道具）
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
【续写剧本进度】
✅ 感知环境
✅ 收集需求
✅ 需求分流
🔄 检查/补全大纲
⏳ 编写续集剧本
⏳ 确认续集剧本
⏳ 合规检查
⏳ 补充新角色
⏳ 角色形象设计
⏳ 补充新场景道具
⏳ 场景道具形象设计
⏳ 资产就绪检查
```

## 详细步骤

1. **检查大纲完整性**
   - 使用 `get_outline()` 或类似工具检查
   - 如果大纲不完整 → 调用 plot-analyzer 补全
   - 如果大纲完整 → 跳过此步骤

2. **调用 story-writer（编写续集内容）**
   - 任务：根据已有剧本和大纲编写续集
   - 输入：已有剧本、大纲、用户需求
   - 输出：续集剧本文件（JSON格式）

2.5. **用户确认续集剧本（关键步骤）**
   - **必须执行**：向用户展示生成的续集剧本，并询问是否满意
   - **展示内容**：
     - 使用 `list_scripts()` 和 `get_script()` 获取生成的续集剧本内容
     - 展示续集的关键信息：新增集数、每集梗概或部分内容
   - **询问用户**：
     - 先向用户展示续集剧本摘要或部分内容，然后调用：
     ```
     ask_user(
       question: "【续集剧本已生成】\n\n<展示续集剧本摘要或部分内容>\n\n请问您对这个续集剧本是否满意？",
       options: ["满意，继续", "不满意，需要修改"]
     )
     ```
   - **处理用户反馈**：
     - **如果用户选择"满意，继续"**：继续步骤3（调用 content-compliance-checker）
     - **如果用户选择"不满意，需要修改"**：
       1. 用户会在自由输入中说明修改意见
       2. 重新调用 story-writer，并在 `task_description` 中明确说明用户的修改要求
       3. 返回本步骤重新确认续集剧本
   - **注意事项**：
     - 必须等待用户明确回复后才能继续
     - 不要假设用户满意，必须得到明确确认
     - 如果用户提出修改意见，要完整传递给 story-writer

3. **调用 content-compliance-checker（循环检查）**
   - **第一步：调用 content-compliance-checker 进行审核**
     ```
     call_agent(
       AgentName: "content-compliance-checker",
       task_description: "请审核续集剧本的合规性和质量，检查是否包含违规内容、角色一致性、大纲一致性以及每集末尾的钩子设计"
     )
     ```

   - 任务：检查续集剧本的合规性和质量
   - 检查项同工作流A

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
         task_description: "请根据审核报告修改续集剧本，解决发现的问题",
         conversation_history: [
           {
             "role": "user",
             "content": <直接将 get_script_problem 返回的 problem 字段内容放在这里>
           }
         ]
       )
       ```
     - 最多循环3次

   - **如果通过或达到最大次数**：继续下一步

4. **调用 character-creator（补充新角色）**
   - ⚠️ **执行要求**：必须立即调用 `call_agent(AgentName: "character-creator", ...)`，不要只说"正在执行"
   - 任务：为续集中的新角色创建角色卡
   - 输入：续集剧本内容
   - 输出：新角色JSON文件

4.3. **验证角色卡并简要展示（默认不询问满意度）**
   - **⚠️ 一步到位原则（必须遵守）**：角色卡创建完成后，**不要询问用户是否满意、不要让用户选择生成哪些角色**，直接简要展示后立即进入步骤4.5 调用 character-image-designer
   - **⚠️ 精细模式例外（介入程度=精细·多确认时必须执行）**：若本任务的用户消息前带有「[系统指令·AI介入程度：精细·多确认]」标记，则本步骤不一步到位，恢复确认流程：
     1. 先调用 `ask_user` 展示角色清单（新增详情+已有列表），确认角色卡是否满意：`options: ["满意，继续", "不满意，需要修改"]`（不满意 → 收集修改意见，重新调用 character-creator 后回到本步骤）
     2. 满意后调用 `ask_user` 让用户选择需要生成形象的角色：`options` 只列 `reference_image` 为空的角色，`multiSelect: true`
     3. 按用户选择进入步骤4.5，此时任务描述改为"请为以下角色生成形象设计图：[用户选择的角色列表]"
   - **必须执行**：验证角色卡已创建并向用户简要展示
   - **验证逻辑**：
     - 调用 `list_character_jsons()` 获取所有角色列表
     - 如果列表为空 → 重新调用 character-creator（最多3次）
     - 如果列表非空 → 继续
   - **展示内容**（单条消息，展示后立即调用下一步，不等待用户回复）：
     ```
     【角色卡已创建/更新】共[N]个角色（新增[X]个）：
     - 新增角色A：一句话简介
     - 新增角色B：一句话简介
     ...
     已有角色：<列出名称>
     💡 正在为缺少形象的角色自动生成形象图和音色，如需调整可随时告诉我
     ```
   - **说明**：若用户后续对角色卡不满意，可随时提出，PM 会重新调用 character-creator 修改后重新生成形象

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

5. **调用 location-creator（补充新场景和道具）**
   - ⚠️ **执行要求**：必须立即调用 `call_agent(AgentName: "location-creator", ...)`，不要只说"正在执行"
   - 任务：创建续集中的新场景和道具
   - 输入：续集剧本内容
   - 输出：新场景和道具JSON文件

5.3. **验证场景和道具并简要展示（默认不询问满意度）**
   - **⚠️ 一步到位原则（必须遵守）**：场景和道具创建完成后，**不要询问用户是否满意、不要让用户选择生成哪些**，直接简要展示后立即进入步骤5.5 调用 location-prop-image-designer
   - **⚠️ 精细模式例外（介入程度=精细·多确认时必须执行）**：若本任务的用户消息前带有「[系统指令·AI介入程度：精细·多确认]」标记，则本步骤恢复确认流程：
     1. 先调用 `ask_user` 展示场景和道具清单（新增详情+已有列表），确认是否满意：`options: ["满意，继续", "不满意，需要修改"]`（不满意 → 收集修改意见，重新调用 location-creator 后回到本步骤）
     2. 满意后调用 `ask_user` 让用户选择需要生成形象的场景和道具：`options` 只列 `reference_image` 为空的项目，`multiSelect: true`
     3. 按用户选择进入步骤5.5，此时任务描述改为只为用户选定的场景和道具生成
   - **必须执行**：验证场景和道具已创建并向用户简要展示
   - **验证逻辑**：
     - 调用 `list_location_jsons()` 和 `list_prop_jsons()` 获取列表
     - 如果两者都为空 → 重新调用 location-creator（最多3次）
     - 如果任一非空 → 继续
   - **展示内容**（单条消息，展示后立即调用下一步，不等待用户回复）：
     ```
     【场景和道具已创建/更新】共[M]个场景（新增[x]个）、[N]个道具（新增[y]个）：
     - 新增场景：场景A、场景B、...
     - 新增道具：道具X、道具Y、...
     已有场景：<列出名称>（如有）
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
