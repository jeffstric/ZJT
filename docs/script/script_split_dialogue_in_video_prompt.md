# 剧本拆分：视频提示词必须包含完整对白

## 问题

拆分后分镜的 `video_prompt` 经常只有「大声呵斥 / 嘴巴大张 / 训斥声」等动作概括，缺少剧本台词原文，例如：

- 视频提示词：`【【赵志高】】……嘴巴大张……训斥声在大堂里回荡`
- 剧本台词：`赵志高（瞪眼）：你也没好到哪去！去，把仓库那堆杂物搬了！`

台词虽可能已写入结构化 `dialogue[]`（供 TTS / 对口型），但**展示与视频生成用的 `video_prompt` 不拼接 dialogue**，导致用户侧看不到完整对话。

## 根因

| 层 | 原状 |
|---|---|
| LLM 提示词 | 只要求对白进 `dialogue[]`，强调「写可见动作」，未要求 `description/action` 逐字引用台词 |
| 组装层 | `video_prompt = description + scene_detail + action + 镜头运动 + 叙事目的`，不含 dialogue |
| 质检 | 不检查视频提示词是否含台词 |

## 三层加固

### 1. LLM 提示词硬规则

- `llm/script_parser.py` user prompt：新增 **7.2 视频提示词必须含完整对白**
- `script_writer_core/skills/script-parser/SKILL.md`：新增 **18.1** 同规则
- 要求：`dialogue[].text` 非空时，必须在 `description` 和/或 `action`（可选 `scene_detail`）中**逐字**写出完整台词
- 推荐格式：`【【角色名】】说："完整台词原文"`
- 首帧 `opening_frame_description` 不强制写台词

### 2. 组装层幂等兜底

`api/storyboard.py` → `build_storyboard_scenes_from_parsed_script`：

1. 先拼基础视频提示词；
2. 对每条非空台词做规范化匹配；
3. 若某句尚未出现在提示词中，追加：

```text
对话：
【【赵志高】】：「你也没好到哪去！去，把仓库那堆杂物搬了！」
```

4. 若 LLM 已写入完整台词，则**不重复**追加。

相关 helper：

- `_normalize_dialogue_text_for_match`
- `_format_dialogues_for_video_prompt`

### 3. 质检规则 `DIALOGUE_NOT_IN_VIDEO_PROMPT`

`llm/script_split_qc_agent.py` → `run_rule_qc`：

- 对本镜头每条 `dialogue[].text`，检查是否出现在 `description + scene_detail + action`（与组装源一致，不含首帧）
- 规范化后子串匹配；漏写 → `severity=error`，`code=DIALOGUE_NOT_IN_VIDEO_PROMPT`
- 经现有 `QcReport.format_for_prompt` 注入 `qc_retry_block` 触发重拆

## 验收

1. 含对白剧本拆分后，`video_prompt` 可见完整台词（LLM 写入或组装兜底）。
2. 「dialogue 有台词、description/action 无台词」→ QC 失败并报 `DIALOGUE_NOT_IN_VIDEO_PROMPT`。
3. 台词已在 description 中时：QC 通过，组装不重复追加。

## 相关测试

- `tests/llm/test_script_split_qc_agent.py`：漏写/含台词/引号变体/无对白
- `tests/storyboard/test_storyboard_generate_from_script.py`：组装兜底与幂等
