# 前端内容违规识别与提醒弹框（P2 兜底层）

> 上层设计见 `docs/image/content_moderation_error_design.md`（方案 A+D）。
> 本文档记录 2026-08-30 基于 30 天真实日志的特征提取，以及前端「内容违规提醒」的落地实现。

## 1. 日志证据（/nas/tmp/api_request_log/ 2026-08-01 ~ 2026-08-30，270MB / 30 文件）

任务级失败藏在 `data.state` / `data.msg` / `message` / `error_message` 字段中（顶层 `code`/`msg` 恒为成功）。
30 天内各供应商内容审核拒绝话术及出现次数：

| 供应商 / 渠道 | 原始话术（节选） | 30 天次数 | 携带字段 |
|---|---|---|---|
| Grok（grok-video-channel / grok_huimengi_v1） | `Content security audit did not pass \| 内容安全审查未通过` | 5225 | `error_message` |
| Gemini duomi（gemini_duomi_v1） | `任务执行失败: gemini blocked: finish_reason:STOP (candidate stopped before producing an image)` | 29 | `data.msg` |
| GPT Image（duomi_gpt_image / gpt_image_common_site） | `Your request was rejected by the safety system. (request id: ...)` | 29 | `data.msg` / `message` |
| Gemini 网关 | `Gemini image generation blocked [IMAGE_OTHER]: ...copyright or trademark...` | 28 | `message` |
| Gemini 网关 | `The generated images appear to be unsafe. Try modifying the prompts or the seeds.` | 62+20 | `message` / 其它字段 |
| Gemini 网关 | `Gemini image generation blocked [IMAGE_SAFETY]: ...` | 10 | `message` |
| Gemini 网关 | `Gemini image generation blocked [PROHIBITED_CONTENT / IMAGE_PROHIBITED_CONTENT]` | 5+2 | `message` |
| 火山 Seedream / Seedance | `InputImageSensitiveContentDetected.PrivacyInformation: The input image may contain real person.` | 数十 | `data.msg` |
| 火山 Seedance | `InputVideoSensitiveContentDetected(.PrivacyInformation): ...sensitive information...` / `OutputVideoSensitiveContentDetected` | 数十 | `data.msg` |
| 火山 Seedance | `OutputAudioSensitiveContentDetected.PolicyViolation`（版权） | 少量 | `data.msg` |
| Gemini duomi | `任务执行失败: sensitive_words_detected` / `任务执行失败: The provided prompt is considered unsafe...` | 1+1 | `data.msg` |

**必须排除的误报**（同为任务失败，但不是内容违规）：

- `AI服务繁忙，请稍后重试` / `抱歉，系统繁忙，请稍后重试` / `抱歉，任务处理遇到了一点小问题`
- `图片大小超过 10MB` / `exceeds limit (N > 10485760)`
- `Total reference images and elements cannot exceed 4, got 5.`
- `模型 grok-video-channel 并发上限(10)已达` / `无可用渠道` / `APIKEY_TASK_NOT_FOUND`
- `图片下载HTTP错误` / `The model load is too high` / `未知原因,可能是当前官方算力问题`

**特别注意**：原始日志中 `blocked` / `审核` / `拦截` / `违规` 的裸命中大量来自**用户提示词正文**
（如 "roads blocked by debris"）。因此英文特征只匹配完整短语（`generation blocked`、`safety system` 等），
绝不允许裸 `blocked` 作为触发词。

## 2. 前端模块：`web/js/content_violation.js`

普通 `<script>`（非 ES module），video_workflow 与 storyboard 两个页面共用，挂载 `window.ContentViolation`：

| API | 说明 |
|---|---|
| `isViolation(text)` | 是否命中内容违规特征。优先走后端友好文案快速通道（`内容审核未通过` 前缀），再匹配英文/中文特征表 |
| `describe(text)` | 生成友好中文文案；非违规返回 `null`；已是「内容审核未通过…」开头的不二次包裹。模板与后端 `_SOURCE_HINT_MESSAGES` 同源（prompt / reference_image / output / copyright / general 五类），并解析 `safety_violations=[...]` 与 Gemini `[REASON]` 标签为中文 |
| `notify(key, text, opts)` | 命中违规时弹出「⚠️ 内容违规提醒」弹框（友好文案 + 可展开的原始错误 + 「我知道了」按钮，z-index 100001，样式自注入无外部依赖）；返回是否实际弹出 |
| `_resetForTest()` | 测试辅助：重置去重状态 |

### 2.1 去重（防连环弹窗）

- **同 key 冷却**：同一任务/分镜资产（key 如 `wf:{project_id}`、`sb:{scene_id}:video`）120s 内只提醒一次；
- **全局冷却**：任意两个弹框间隔 8s，批量生成（几十个分镜同时失败）不会连环弹；
- key 表超过 500 条时整体清空（冷却语义等价于全部过期，防内存增长）。

### 2.2 特征表与后端同源

英文特征（小写匹配）：`safety system` / `safety policy` / `safety_violations` / `moderation_blocked` /
`invalid_prompt` / `content policy` / `content_filter` / `content moderation` / `content security` /
`data_inspection_failed` / `sensitive content` / `sensitive information` / `sensitivecontent` /
`sensitive_words` / `image generation blocked` / `generation was stopped` / `generation blocked` /
`candidate stopped before producing` / `prohibited content` / `prohibited material` / `policy violation` /
`image_safety` / `image_other` / `image_prohibited` / `copyright` / `trademark` / `appear(s) to be unsafe` /
`considered unsafe` / `real person` / `gemini blocked`。

中文特征：`内容审核` / `内容安全` / `敏感内容` / `敏感信息` / `违禁` / `违规` / `审核未通过` / `审核不通过` / `版权` / `商标`。

## 3. 接入点

### 3.1 video_workflow.html（工作流页）

- `video_workflow.html`：在 `api.js` 之前加载 `<script src="/js/content_violation.js">`；
- `web/js/api.js` `checkVideoStatus`（所有节点的统一状态轮询收口：图生视频 / 图像 / 视频 / 全景 / 剧本 / 分镜帧 / 数字人 / 运镜）：
  多任务与单任务两个分支中，任一任务 `FAILED` 且 `error` 命中违规 → `notify('wf:{project_id}', error)`；
- `web/js/api.js` `pollTaskStatus`（TTS / 对白等旁路轮询）：`onFailed` 前对 `reason || error || message` 做违规提醒；
- `web/js/nodes.js` `friendlyContentModerationMessage`：委托 `window.ContentViolation.describe`（特征表更完整、文案与后端严格对齐），
  模块不存在时（如 Vitest 环境）回退本地规则。节点上的 `✗ 生成失败: …` 行内文案因此也自动获得新特征覆盖。

### 3.2 storyboard.html（故事板页，此前无任何审核处理，失败候选只显示「生成失败」）

- `storyboard.html`：module 引导前加载 `content_violation.js` 普通 script；
- `web/js/storyboard/polling.js` `applyTaskStatus`（4s 分镜任务轮询）：
  - 记录 `scene.firstFrameError / lastFrameError / videoError`，候选项 `upsertSceneCandidateFromTask` 记录 `candidate.error`；
  - 资产 `status === -1` 且 `error` 命中违规 → `notify('sb:{scene_id}:{first_frame|last_frame|video}', error)`；
  - 配音失败（`d.status === -1 && d.error`）→ `notify('sb:{scene_id}:audio:{dialogue_id}', error)`；
- `web/js/storyboard/render.js` `renderCandidatePlaceholder(status, kind, error)`：
  失败且命中违规时占位符文案为「生成失败：内容违规」，`title` 悬浮展示友好原因；
- `web/js/storyboard/events.js`：单条视频生成提交 catch、批量视频生成提交 catch —— 提交阶段即被内容安全拒绝时弹框提醒。

## 4. 后端规则补齐（`utils/content_moderation_error.py`）

按「后端归一为主」原则，把 30 天日志中**未被改写**的 duomi/Gemini 话术补入 `_MODERATION_MESSAGE_MARKERS`：

- `sensitive_words`（`任务执行失败: sensitive_words_detected`）
- `unsafe`（`The generated images appear to be unsafe.` / `The provided prompt is considered unsafe...`）
- `content security`（`Content security audit did not pass` 纯英文形态）
- `gemini blocked` / `candidate stopped before producing`（`gemini blocked: finish_reason:STOP ...`）

来源提示（`_MESSAGE_SOURCE_HINTS` prompt 段）同步新增 `sensitive_words` / `considered unsafe` /
`candidate stopped before producing`，保证上述样本落「提示词」类文案而非通用类。
修复前约 33 次/月的 duomi 违规会以原始英文透传到前端，修复后全部归一为「内容审核未通过…」中文。

## 5. 测试

- 前端：`web/tests/content_violation.test.js`（56 用例）—— 30 天日志全部真实话术的正例、
  繁忙/限额/基础设施错误的反例（含提示词正文 `blocked` 误报用例）、`describe` 五类文案模板、
  弹框渲染/关闭/去重冷却/回调。
- 后端：`tests/utils/test_content_moderation_error.py` 新增 `TestDuomiAndGrokLogPatterns`（8 用例）——
  Grok 中英/纯英文、duomi 三类 Gemini 话术的来源分类与文案、9 条非违规话术不误判。

## 6. 边界与不做的事

- 只在**任务失败**路径提醒，提交成功后的进行中状态不弹框；
- 不改动失败任务本身的展示逻辑（行内错误文案、候选占位符的既有行为保留）；
- 不处理 `web/js/pages/*`（index.html 页面，非本次范围）；
- 弹框纯展示，不内嵌「降低违规」改写入口（方案 D 入口在既有节点/分镜降低违规联动中）。
