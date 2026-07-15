# 剧本拆分质检

## 概述

在「从剧本生成分镜」时可开启 **拆分质检**：每个语义分段生成后，先执行实体/空间引用校验，再交给 `qc_agent` 执行现有规则质检；不通过时带着「上一轮结果 + 问题列表」只重拆当前段。最多 N 轮仍不通过时，强制采用最后一轮已经成功解析的完整 JSON，继续后续拆分、合并和发布，避免单段质检永久阻塞任务。

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

启用 `llm/script_parser.py` 的 `ENABLE_SCRIPT_PARSER_LOGGING` 后，发生质检重试时会在 `logs/script_parser` 额外生成：

- `script_parser_{timestamp}_03_qc_feedback.json`：原始结构化质检反馈；`QcReport` 会转换为字典，纯文本反馈保存到 `text` 字段。
- `script_parser_{timestamp}_03_qc_retry_prompt.txt`：实际注入用户提示词的质检重试块，包含格式化反馈和上一轮压缩 JSON。

原有 `script_parser_{timestamp}_02_user_prompt.txt` 继续保存最终完整用户提示词。文件统一使用 UTF-8，日志不写入 `auth_token`、请求头或其他认证信息；关闭解析日志或没有重试上下文时不会生成上述两个 `_03` 文件。

段级业务校验失败后，下一轮会携带最近一次可解析的当前段完整 JSON，不再使用 `{}` 丢失上一轮结果。重试输出必须包含 `characters`、`locations`、`props`、`spatial_world` 和 `shot_groups`。

## 质检耗尽

达到 `qc_max_rounds` 后仍未通过时，当前段保存为 `completed`，采用最后一轮已经成功解析的完整 JSON。最后一轮质检问题继续保存在 `script_split_segment.validation_errors`，每项带 `_forced_accept=true`，日志同时记录任务 ID、段序号、轮数和问题 code，便于追踪“未通过 QC 但按上限规则采用”的结果。

对于升级前已经因 `segment_qc_failed` 留下的耗尽检查点，只要其中存在完整的 `parsed_result_json`，调度器会直接强制接纳该候选，不再额外调用 LLM，也不会再次进入同一暂停状态。

强制接纳只适用于“已经获得合法候选，但业务质检仍未通过”。模型超时、调用异常、认证失败、用户取消或没有合法 JSON 候选时，仍按原有执行失败重试和暂停规则处理。
