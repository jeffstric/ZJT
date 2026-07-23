# 剧本拆分质检

## 概述

在「从剧本生成分镜」时可开启 **拆分质检**：每个语义分段生成后，先执行实体/空间引用校验，再交给 `qc_agent` 执行现有规则质检；不通过时带着「上一轮结果 + 问题列表」只重拆当前段。最多 N 轮仍不通过时，普通 QC 可强制采用最后一轮已经成功解析的完整 JSON，继续后续拆分、合并和发布，避免单段质检永久阻塞任务。

角色完整名称与图片/视频提示词合法性属于独立的**角色提示词硬门禁**，不受拆分质检开关控制，也绝不允许强制接纳。详见“角色提示词硬门禁”。

默认 **关闭**。开启会 **大幅增加时间与算力**（最坏约 N 次拆分 + N 次质检）。

## 前端

拆分弹框：

- 勾选「开启拆分质检」+ 橙色提示  
- 「质检最大循环次数」1–5（默认 2），标题右侧显示“限时免费”标签；标签仅说明当前次数费用政策，不改变质检开关与循环逻辑。  

请求字段：

```json
{
  "enable_script_split_qc": true,
  "script_split_qc_max_rounds": 2
}
```

## 后端

- `api/storyboard.py`：接收并持久化质检开关和最大轮数  
- `services/script_split_engine.py`：逐段执行本地校验、`qc_agent` 和定向重试  
- `llm/script_split_qc_agent.py`：规则质检 + `QcReport`  
- `llm/script_parser.py`：`previous_parsed_result` / `qc_feedback` 注入 user prompt  
- `config/constant.py`：`ScriptSplitQcConstants`

### 质检重点

1. **语言**：对话 / 提示词是否与 `dialogue_language` / `prompt_language` 一致（中英启发式）  
2. **结构**：空首帧、多人却 digital_human、组时长超限、角色未进首帧描述等  

对白语言检查只读取 `dialogue[].text`，不会把 `opening_frame_description`、`description` 等中文画面提示误判为中文对白。中文与英语采用两级检查：较长对白逐句定位；低于单句长度阈值的短对白会在当前段内聚合后再次判断。这样在要求英语时，多条“你先走”“我不走”之类的短中文对白也会产生 `LANG_DIALOGUE_NOT_TARGET` error，并随现有 QC 反馈踢回当前段修正。要求中文时对多条短英语对白执行对称检查。没有对白的段不会触发该错误，少量专有名词或混合字符仍受比例阈值保护。

无对白镜头占比仍会写入 QC 报告的 `stats.empty_dialogue_ratio`，仅用于诊断和观测，不设通过阈值，也不会产生 `TOO_MANY_EMPTY_DIALOGUE_SHOTS` 错误。压抑氛围、默剧或纯视觉叙事可以包含任意比例的无对白镜头。

P0 以规则预检为主；LLM 语义质检可后续打开 `use_llm=True`。

### 开关语义

- `enable_qc=false`：跳过 `_validate_segment` 和 `qc_agent`，可解析结果直接保存为段检查点；网络、超时和 JSON 解析失败仍按基础容错规则重试。
- `enable_qc=true`：两套检查都执行且不短路，错误合并后一次性反馈给下一轮 LLM。
- `qc_max_rounds` 只限制已经获得可解析结果后的质检修正轮数，不吞掉网络调用重试预算。

### 质检重试日志

启用 `ScriptParserConstants.DIAGNOSTIC_LOGGING_ENABLED`（`config/constant.py`，默认关闭；模块内别名 `ENABLE_SCRIPT_PARSER_LOGGING`）后，发生质检重试时会在 `logs/script_parser` 额外生成：

- `script_parser_{timestamp}_03_qc_feedback.json`：原始结构化质检反馈；`QcReport` 会转换为字典，纯文本反馈保存到 `text` 字段。
- `script_parser_{timestamp}_03_qc_retry_prompt.txt`：实际注入用户提示词的质检重试块，包含格式化反馈和上一轮压缩 JSON。

原有 `script_parser_{timestamp}_02_user_prompt.txt` 继续保存最终完整用户提示词。文件统一使用 UTF-8，日志不写入 `auth_token`、请求头或其他认证信息；关闭解析日志或没有重试上下文时不会生成上述两个 `_03` 文件。

段级业务校验失败后，下一轮会携带最近一次可解析的当前段完整 JSON，不再使用 `{}` 丢失上一轮结果。重试输出必须包含 `characters`、`locations`、`props`、`spatial_world` 和 `shot_groups`。

## 角色提示词硬门禁

### 角色契约真值

创建拆分任务时，服务端按 `world_id` 分页读取**完整角色列表**，生成角色契约快照并持久化到任务内部配置 `_character_contract`。快照至少包含 `character_db_id` 与 `canonical_name`；例如数据库名称是 `奶昔_Milkshake`，后续只能使用该完整名称。

- 客户端传入的 `_character_contract` 会在计算幂等键前被删除，不能伪造或覆盖服务端真值。
- 解析器使用同一份任务快照提供角色上下文，避免任务执行期间角色改名导致各 segment 使用不同名称。
- 升级前的存量任务若没有快照，仅从任务已接受角色注册表构造兼容契约，不在 worker 中重新访问或改写角色库。

### 确定性校验规则

校验器不调用 LLM，也不依赖普通 QC。对于每个 segment：

1. `characters[].character_db_id` 存在时，`name` 必须与快照中的 `canonical_name` 完全一致（Unicode NFC 归一化后比较）。
2. 对 `中文名_EnglishName` 形式的库角色，`中文名` 被识别为受控短别名，不能作为新角色绕过校验。
3. 所有角色标记必须是闭合的 `【【完整角色名】】`；短名称、未知名称、空名称、首尾空格和未闭合标记均失败。
4. `characters_present` 中的每个角色必须同时出现在：
   - 图片提示词组合：`opening_frame_description + scene_detail`；
   - 视频提示词组合：`description + scene_detail + action`。

因此 `【【奶昔】】` 对应契约 `奶昔_Milkshake` 时会产生 `character_prompt_name_invalid`，并同时报告图片或视频组合缺少 `【【奶昔_Milkshake】】`。

当前版本的匹配边界如下：

- `character_db_id=null` 且名称未命中数据库角色受控短别名时，按任务内新角色处理；这里只允许拆分结果继续，不会自动向角色库新建记录。
- 只有完整双层标记 `【【名称】】` 参与角色契约匹配；普通文本或单层括号（如 `【奶昔】`）不视为已匹配的数据库角色引用。
- 上述边界是当前产品约定。未来若启用拆分过程自动创建角色，需要另行收紧新角色与数据库角色的相似名称判定。

### 三层拦截与恢复

| 阶段 | 行为 |
|------|------|
| segment 生成 | 把结构化错误反馈给当前段重生成，独立最多 3 轮；耗尽后暂停任务，错误码 `character_prompt_contract_invalid` |
| merge | 对合并、重排、全局编号后的最终提示词复检；失败时把错误映射回来源 segment、重开该段并暂停 |
| publish | 写入 `storyboard_scene` 前最后复检；失败时清空 `final_result_json`、重开来源 segment 并暂停，不允许任何非法提示词落库 |

暂停任务的状态接口会返回精简的 `validation_errors`，前端优先展示具体的 `error_message`。用户修复外部根因后可显式恢复任务；无论 `enable_script_split_qc` 是否开启，硬门禁都不能走 `_forced_accept`。

## 质检耗尽

达到 `qc_max_rounds` 后仍未通过普通 QC 时，当前段保存为 `completed`，采用最后一轮已经成功解析的完整 JSON。最后一轮普通质检问题继续保存在 `script_split_segment.validation_errors`，每项带 `_forced_accept=true`，日志同时记录任务 ID、段序号、轮数和问题 code，便于追踪“未通过 QC 但按上限规则采用”的结果。角色提示词硬门禁错误不适用本规则。

对于升级前已经因 `segment_qc_failed` 留下的耗尽检查点，只要其中存在完整的 `parsed_result_json`，调度器会直接强制接纳该候选，不再额外调用 LLM，也不会再次进入同一暂停状态。

强制接纳只适用于“已经获得合法候选，但普通业务质检仍未通过”。角色提示词硬门禁、模型超时、调用异常、认证失败、用户取消或没有合法 JSON 候选时，仍按各自的重试和暂停规则处理。
