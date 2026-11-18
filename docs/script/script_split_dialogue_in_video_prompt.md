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

## video_workflow 前端组装层的重复问题与去重（2026-11，develop_f1181）

7.2 规则让 LLM 把台词逐字写进 `description/action` 后，video_workflow 前端把
`dialogue[]` 结构化字段又**整份渲染**为「对话：」行（`convertVideoPromptToText`），
同一句台词在发给视频模型的提示词里出现两次。线上案例：video_workflow id=13 分镜9，
动作内 `说道："物业现在招保安都不挑人了？…"` 与 `对话：【【苏雨晴】】: 物业现在…` 重复。

后端 storyboard 组装层本就有幂等兜底（见上），前端此前没有——补齐为双层：

| 层 | 位置 | 策略 |
|---|---|---|
| 结构化（新节点） | `web/js/nodes.js` `convertVideoPromptToText` | 台词归一化后已完整出现在 `description/scene_detail/action` 中的条目不再渲染；全部重复则整行不输出 |
| 文本级（存量节点） | `web/js/utils.js` `dedupeVideoPromptDialogue` | 「对话：/Dialogue:」行内逐条判定，重复条剔除、全重复整行移除；兼容分号多条与中英标签 |

挂载点（均 `typeof` 守卫）：

- `shot_frame_video_generator.js` 提交生视频前（存量文本兜底）
- `nodes.js` 组合多镜头视频拼接处（JSON 走结构化、文本走兜底）
- `shot_frame_node.js` 提示词展示（`renderCharImages`）与放大编辑器打开时
  （用户保存后干净文本落库自愈）、违规改写提交前

归一化 helper：`normalizeDialogueTextForMatch`（剔除标记/引号/标点/空白，保留
CJK/字母数字）。过短台词（归一化后 <4 字符，如「嗯」）不参与去重防误伤；
台词不在正文中时保留（维持 7.2「完整对白可可见」意图）。`dialogue[]` 结构化
字段本身不动，TTS/对口型不受影响。
