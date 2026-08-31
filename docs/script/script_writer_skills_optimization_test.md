# 剧本创作智能体优化 — 本 issue 测试内容

- 日期：2026-08-30
- 范围：`script_writer_core` 技能/SOP/工具链路本轮全部改动，含二次复查发现并修复的两个缺陷
- 配套文档：[AI 介入程度调查](ai_intervention_level_investigation.md)、[宫格图生成逻辑（质检闭环章节）](../image/grid_image_generation_logic.md)

## 0. 前置条件

| 项 | 要求 |
|----|------|
| 数据库迁移 | 已执行 `alembic upgrade head`（新增 `20260830_ds_vision`：deepseek-v4-flash-vision-exp 模型 + 计费） |
| DeepSeek 配置 | `llm.deepseek.api_key` 已配置（热更新或 config） |
| 测试账号 | 算力充足；建议准备一个可破坏的测试 world |
| 坏图样本 | `G:\code\宫格图测试\拆分结果\宫格图7\处理前\shot4.png`（一格双人 + 边缘裁切的污染图），用于人工构造坏图场景 |

---

## 1. deepseek-v4-flash-vision-exp 模型接入（任务0）

| # | 测试项 | 步骤 | 预期 |
|---|--------|------|------|
| 1.1 | 迁移幂等 | `alembic upgrade head` 后重复执行 | 无报错；`model` 表仅一条 `deepseek-v4-flash-vision-exp`，`supports_vl=1`；`vendor_model` 计费 input=40000 / out=20000 / cache=2000000 |
| 1.2 | 模型可见 | 管理后台模型列表 / 前端 LLM 模型下拉 | 出现 deepseek-v4-flash-vision-exp，计费单价与 deepseek-v4-flash 一致 |
| 1.3 | 客户端路由 | 用该模型发起一次普通对话 | 工厂按 `deepseek` 前缀路由到 DeepSeekOpenAIClient；`_MODEL_NAME_MAP` 正常透传；无 404 |
| 1.4 | 计费 | 对话后查看算力流水 | 按 deepseek-v4-flash 同价扣减（1 点=0.04 元换算） |

## 2. 资产创建一步到位（默认/简洁档）（任务1、2）

三个工作流（新建 sop-new-script / 续写 sop-continue-script / 拆分 sop-split-script）行为一致，以新建为例：

| # | 测试项 | 步骤 | 预期 |
|---|--------|------|------|
| 2.1 | 角色卡直通形象 | 介入程度=**标准**，走新建剧本流程到角色卡步骤 | 角色卡创建后仅**一条简要展示消息**（含"如需调整可随时告诉我"提示），**同一轮**立即调用 character-image-designer，中间无任何 ask_user |
| 2.2 | 生成范围 | 同上 | 为**所有** `reference_image` 为空的角色批量生成（4宫格），已有图角色跳过；音色同步生成 |
| 2.3 | 场景道具直通 | 流程走到场景/道具步骤 | 同 2.1/2.2 逻辑，直连 location-prop-image-designer，无 ask_user |
| 2.4 | 大纲/剧本确认保留 | 观察全流程 | 大纲确认、剧本确认（拆分流程含拆分结果确认）仍正常 ask_user，未被一步到位波及 |
| 2.5 | 用户反悔通道 | 角色形象生成完成后输入"把角色A改成女性" | PM 重新调用 character-creator 修改，并重新生成该角色形象 |
| 2.6 | 创建失败重试 | 构造角色创建为空（如提示词异常） | PM 重新调用 character-creator，最多 3 次后向用户报告 |
| 2.7 | 进度展示 | 观察进度条 | 进度列表中**不再出现**"确认角色卡/确认场景道具"两个节点 |

## 3. AI 介入程度三档联动（二次需求）

| # | 测试项 | 步骤 | 预期 |
|---|--------|------|------|
| 3.1 | 精细档·角色确认 | 介入程度=**精细·多确认**，走到角色卡步骤 | ① PM 先 `ask_user` 确认角色卡满意度（满意/不满意）；② 满意后 `ask_user` 多选**需要生成形象的角色**（仅列缺图角色）；③ 按所选列表调用 character-image-designer。**不会**跳过提问直接生成 |
| 3.2 | 精细档·不满意分支 | 3.1 第①步选"不满意"并输入修改意见 | 重新调用 character-creator 修改后回到确认步骤 |
| 3.3 | 精细档·场景道具确认 | 介入程度=精细，走到场景/道具步骤 | 同 3.1 的两步确认逻辑 |
| 3.4 | 简洁档 | 介入程度=**简洁·少提问**，全流程 | 除大纲、剧本定稿外无 ask_user；资产创建一步到位；决策自行完成并在进度消息说明理由 |
| 3.5 | 标准档 | 介入程度=标准 | 行为与 2.x 一致（不注入指令，SOP 默认） |
| 3.6 | 切档即时生效 | 同一会话先精细跑一段，切标准后发新消息 | 新任务行为按标准档执行（指令随每条消息重新注入） |
| 3.7 | 刷新恢复 | 切档后刷新页面 | localStorage 恢复上次选择，发送参数与界面一致 |
| 3.8 | 非法值容错 | 用脚本直接 POST `intervention_level: "haha"` | 后端日志出现"非法 intervention_level 已忽略"，任务按标准档正常执行 |
| 3.9 | 指令落库 | 精细档发消息后查 `chat_messages` 表该任务的 initial user 消息 | 消息开头含 `[系统指令·AI介入程度：精细·多确认]`（验证幂等键未吞掉指令——二次复查修复点①） |

## 4. 宫格切分污染检测与坏图清理（任务3）

| # | 测试项 | 步骤 | 预期 |
|---|--------|------|------|
| 4.1 | VL 模型强制生效 | 用户前端选择**非 VL 模型**（如 deepseek-v4-flash），走到最终资产检查 | asset-readiness-checker 实际使用 VL 模型（`use_config_model` 修复——二次复查修复点②；模型解析顺序：用户 VL 偏好 > 默认 deepseek-v4-flash-vision-exp，见第 5 节）；日志可见"Expert asset-readiness-checker 使用 VL 模型"及解析出的 vendor_id/model_id |
| 4.2 | 合格图通过 | 正常生成资产后触发 asset-readiness-checker | 专家对每个有图资产调用 fetch_image_as_base64 看图；合格图标 ✅，不删除 |
| 4.3 | 污染图识别 | 手工把某角色 JSON 的 `reference_image` 换成 shot4.png 可访问的 URL（或替换本地文件），触发检查 | 专家识别为污染（一格双人/边缘裁切），**自动调用 delete_asset_reference_image** 删除；报告"参考图质量检查详情"表中列出该资产与原因 |
| 4.4 | 删除后状态 | 4.3 后读取该角色 JSON | `reference_image` 为空串；新增 `reference_image_quality_log` 数组记录 action/reason/deleted_image_url/deleted_at；图片文件本身未被物理删除 |
| 4.5 | 重新生成闭环 | 4.3 后按报告提示选择补全 | PM 调用 character-image-designer 重新生成该角色（删除后回到缺图状态，4宫格覆盖保护不再拦截）；生成后可复查 |
| 4.6 | 工具参数校验 | 直接调工具传 `asset_type: "foo"` / 不存在的名字 | 返回 success=False 及明确错误信息；`reference_image` 已为空时返回 `already_empty: true`，不报错 |
| 4.7 | 三类资产 | 对场景、道具分别构造坏图 | 删除逻辑同样生效（location/prop 文件名 sanitize 规则与 update_*_json 一致） |
| 4.8 | 风格瑕疵不误删 | 图片仅画风轻微偏差 | 专家不删除，仅在报告中提示（删除仅限明显污染） |
| 4.9 | 计费正确 | 4.1 场景下检查算力流水 | 质检专家的 LLM 调用按 deepseek-v4-flash-vision-exp 的 model_id 计费，而非用户会话模型单价（vendor_id/model_id 同步解析修复点②的验证） |

## 5. VL 模型偏好（用户级，画风识别与资产检查共用）

| # | 测试项 | 步骤 | 预期 |
|---|--------|------|------|
| 5.1 | 默认选中 | 新世界（无偏好）打开剧本创作页 →「世界」tab | 识别模型下拉默认选中 **deepseek-v4-flash-vision-exp**（前提：DeepSeek 已配密钥且迁移已执行）；不可用时按 推荐⭐ → 第一个 回落 |
| 5.2 | 切换即保存 | 在识别模型下拉切换到其他 VL 模型（如 doubao-seed-2-0-pro） | Network 面板可见 POST `/api/style-models/preference`（200）；`user_preferences` 表出现 `pref_type='vl_model'` 记录，config_value 含 {model, model_id, vendor_id} |
| 5.3 | 偏好恢复 | 5.2 后刷新页面重新进入「世界」tab | 下拉恢复为上次选择的模型（GET `/api/style-models` 返回 saved_preference） |
| 5.4 | 资产检查跟随偏好 | 5.2 后触发 asset-readiness-checker | 质检专家使用**用户偏好的 VL 模型**（日志"Expert asset-readiness-checker 使用 VL 模型: doubao-..."），计费按该模型单价 |
| 5.5 | 偏好失效回落 | 把偏好指向的模型在管理后台停用后触发质检 | 自动回落 agents_config 默认 deepseek-v4-flash-vision-exp；默认也不可用时回退用户会话模型并打 warning |
| 5.6 | 参数容错 | POST 保存接口缺 world_id / model | 返回 400 与明确错误；不写库 |

## 6. 回归项（本轮改动可能波及的既有功能）

| # | 测试项 | 预期 |
|---|--------|------|
| 5.1 | 图片/视频/音频上传后发消息 | 媒体标签 `[图片N]（URL:...）` 注入正常（pm_agent.execute 该段代码被触碰过，已跑单测 test_pm_agent_message_queue 通过） |
| 5.2 | 其他专家模型跟随 | 非 use_config_model 专家（story-writer 等）仍使用用户会话模型，切换模型后生效 |
| 5.3 | PM 专家转发 | 既有单测 `tests/script_writer_core/test_pm_agent_expert_forwarding.py` 通过（已验证 5 passed） |
| 5.4 | ask_user 挂起恢复 | 精细档下 ask_user 等待回复→回复→继续执行，链路正常（verification_answer 不走 create_task，不受介入指令影响） |
| 5.5 | 长文本剧本 | >5000 字剧本拆分：get_long_user_input 透传正常（介入指令拼接不影响 process_long_input 判定，指令 <500 字） |
| 5.6 | 营销会话（marketing） | 营销任务不带 intervention_level → 默认 balanced，行为不变 |
| 5.7 | lint | `scripts/lint_blocking_calls.py` 无 error 级违例（已验证） |

## 7. 二次复查发现并已修复的缺陷（测试重点回归）

| # | 缺陷 | 根因 | 修复 | 对应测试 |
|---|------|------|------|---------|
| ① | 介入指令会被幂等键吞掉 | PM 内存历史与 API 层 chat_messages 持久化共用 `task:{id}:user:initial` 幂等键；若指令由 PM 侧拼接，后写的含指令消息被去重跳过，DB 构建上下文丢失指令 | 指令改在 **API 层 create_agent_task** 拼入 user_message（与 `[用户视频偏好]` 同模式），内存/DB/AgentTask 三处一致 | 3.9 |
| ② | 专家配置的 VL 模型被覆盖 | `pm_agent._handle_agent_call` 无条件用 `self.model`（用户会话模型）覆盖 agents_config 的专家模型 → 资产检查专家可能拿到非 VL 模型，看图失效；且 vendor_id/model_id 仍是用户模型的，路由与计费错位 | 新增 `use_config_model` 配置项：该标志专家强制使用 VL 模型（优先用户 VL 偏好，见第 5 节），并新增 `ModelModel.get_by_name` + `_resolve_model_routing` 按模型名解析正确 vendor_id/model_id；两级回落（偏好失效→默认→用户模型） | 4.1、4.9、5.4、5.5 |

## 8. 改动文件清单（本 issue 全量）

**后端代码**
- `config/constant.py`：DEEPSEEK_V4_FLASH_VISION_EXP 常量；INTERVENTION_LEVEL_* 常量与指令文本；VL_MODEL_PREFERRED_DEFAULT
- `llm/openai_deepseek.py`：模型名映射
- `alembic/versions/20260830_add_deepseek_v4_flash_vision_exp.py`：迁移（revision `20260830_ds_vision`）
- `api/script_writer.py`：TaskCreateRequest.intervention_level；校验与指令拼接（create_agent_task）；get/set_vl_model_preference；/style-models 返回 saved_preference + vl_model_default；POST /style-models/preference
- `model/user_preferences.py`：PREF_TYPE_VL_MODEL 常量 + 表注释同步（无表结构变更，无需迁移）
- `model/model.py`：ModelModel.get_by_name
- `script_writer_core/agents/task_manager.py`：AgentTask.intervention_level 字段与透传
- `script_writer_core/agents/pm_agent.py`：介入档位记录；use_config_model 专家 VL 模型解析（_get_vl_model_for_expert + _resolve_model_routing，用户偏好优先）
- `script_writer_core/agents/tool_executor.py`：delete_asset_reference_image 注册（tool_map + mcp_tool_names）
- `script_writer_core/mcp_tool.py`：delete_asset_reference_image 实现 + MCP_TOOLS schema
- `script_writer_core/config/agents_config.json`：asset-readiness-checker 换 VL 模型 + use_config_model + 两个新工具

**前端**
- `web/js/script_writer.js`：loadStyleModels 优先选中已存偏好/VL 默认（fetch 带 world_id）；识别模型切换即保存（onStyleModelChange → POST /api/style-models/preference）

**技能提示词**
- `script_writer_core/skills/script-orchestrator/SKILL.md`：一步到位原则（含精细模式例外）、坏图重生成路由、进度模板
- `script_writer_core/skills/script-orchestrator/sops/sop-new-script.md` / `sop-continue-script.md` / `sop-split-script.md`：4.3/5.3 一步到位 + 精细模式例外；4.5/5.5 任务描述双模式
- `script_writer_core/skills/asset-readiness-checker/SKILL.md`：五步检查法（新增第三步参考图内容质量检查）

**文档**
- `docs/script/ai_intervention_level_investigation.md`、`docs/image/grid_image_generation_logic.md`、`docs/doc_index.md`、本文件
