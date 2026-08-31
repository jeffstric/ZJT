# 剧本创作页 UX 增强：画风折叠 / 消息排队 / 形象图重生与历史 / 生成中标识 / 拆分分辨率

> 分支：`develop_script_writer_ux`（基于 origin/develop = c2bb4169）
> 涉及页面：`web/script_writer.html`、`web/storyboard.html`、`script_writer_core/skills/plot-analyzer/SKILL.md`

## 一、画风识别区块支持折叠/展开

「世界」tab 底部的画风识别区（`#styleRecognizeSection`）新增标题栏折叠按钮：

- 结构：主体（拖放区 + 模型选择行）包裹进 `.style-recognize-body`；折叠时隐藏主体与副标题，箭头旋转 180°。
- 状态记忆：`localStorage['script_writer_styleRecognizeCollapsed']`（`1`/`0`），刷新后恢复（`restoreStyleRecognizeCollapseState()`，首屏在 `updateStyleRecognizeVisibility('worlds')` 之后调用）。
- 与原有的 tab 级显隐（`hidden` 属性，仅世界 tab 显示）互不干扰——`hidden` 控制"是否出现"，`is-collapsed` 控制"出现时是否展开"。
- i18n：`style_recognize_collapse` / `style_recognize_expand`（title 提示随状态切换）。

## 二、plot-analyzer 提问引导画风入口

`script_writer_core/skills/plot-analyzer/SKILL.md` 的「视觉风格设定」提问模板：

- 第一步（明确画风大类）提问后新增引导：告诉用户如果不知道什么画风，可查看页面**右下角「画风识别」**上传参考图自动识别，或点击「查看更多画风」浏览画风库。
- 第二步（细化具体风格）补充：用户说不清具体风格时，提示上传图片到右下角画风识别自动回填。

## 三、AI 吞吐中用户消息排队（不打断吞吐）

此前 `sendMessage()` 在 `isProcessing === true` 时直接丢弃输入。现在：

- 用户在输入框输入并回车/点击发送时若 AI 正在吞吐：消息进入 `pendingUserMessages` 队列，并**堆叠显示在输入框上方的待发送区**（`#pendingQueueContainer`，每条带 ⏳ 与 × 移除按钮；不进聊天历史，内容再多也能看到将要发送什么）；输入框清空；**不打断当前任务**。
- 按钮触发的系统消息（如「重新生成形象图」）同样入队展示。
- 队列排空：任务进入终态（`done` / `error` / `verification_timeout` / `resetProcessingState` 兜底）后由 `schedulePendingDrain()` 延迟 400ms 按序发送；`ask_user` 验证挂起（`pendingVerificationId`）期间不排空。发送时才以正常用户气泡进入聊天历史。
- i18n：`status_message_queued` / `remove_queued_message`。

## 三b、模型选择器重构（track 徽标进 option + 生图显示算力）

- **移除** LLM / 生图两个 select 旁的「性价比 / 效果」track 按钮组（`llm-track-host` / `image-track-host` 及相关绑定函数已删除；档位信息统一由 option 文本承载）。
- LLM option：「推荐」组内条目本就带 `（性价比）/（效果）` 徽标，保持不变。
- 生图 option（bug 修复）：后端 `/api/text-to-image-models` 已返回 `computing_power` 但前端未展示；现在 option 显示 `Name（性价比 · 5算力）`（无档位则仅算力，无算力则仅档位）。
- `dataset.conciseName` 记录纯模型名：顶部 display、图标 title、`image_preferences.model_name` 快照、世界默认模型名均取 conciseName，避免把算力后缀带进提交数据。

## 四、角色形象图「重新生成」按钮

图片**预览弹窗**（`#preview-regenerate-section`，仅角色显示）与**编辑弹窗**（角色表单参考图片区，常驻）新增「重新生成形象图」按钮：

- 点击后构造提示词（`buildCharacterImageRegenerationPrompt`）：要求读取角色设定与世界 `visual_style`、调用角色形象设计师重新生成 `reference_image` 主形象图、写入角色 JSON；明确不重新生成参考音频。
- 通过 `sendMessage(prompt, true)` 发送；**AI 正在处理时自动压入队列**（同第三节机制）。
- 同时将 `characters||<角色名>` 标记为生成中（见第六节）。
- 历史图查看弹窗（见第五节）复用同一预览弹窗，同样可触发重新生成。

## 五、角色形象图历史（预览弹框内查看 + image_history 字段）

前端（入口在**角色参考图预览弹框**内，不在暂存区列表）：

- 预览弹框操作区「重新生成形象图」旁新增「历史形象图」按钮（垃圾桶图标，仅角色显示）。
- 点击后在同一弹框内切换为历史视图（第一张为"最近归档"，其余缩略图）；按钮变为「返回当前形象图」可切回；关闭弹框自动还原视图与标题；无历史时 toast 提示。
- **恢复历史图**：历史视图下大图正下方有「设为当前形象图」按钮（绿色，仅历史视图显示）。用户点缩略图选中任意一张历史图后点击恢复 → 复用角色保存接口（`POST /api/characters-files/{name}`）写回 `reference_image`，后端归档逻辑自动完成双向整理（旧主图进历史头部、被恢复图从历史移出）；成功后关闭弹框、刷新暂存列表并通知 agent 重新读取。后端零改动。
- i18n：`view_image_history` / `back_to_current_image` / `image_history_title` / `image_history_empty` / `title_image_history` / `restore_history_image` 系列。

后端自动归档（**三条写路径全覆盖**，`script_writer_core`）：

1. `file_manager._safe_write_entity_json` 的 `character_` 分支（`save_character` / 编辑弹窗 / CHARACTER_CARD 代码块回写）；
2. `mcp_tool.create_character_json`（agent 保存角色，走 `save_json_content` 直接覆盖）；
3. `mcp_tool.update_character_json`（**生图任务完成回调 `cron_task_manager` 的真实写入路径**，也是 agent 可直接调用的工具；曾直接 `json.dump` 写回绕过所有归档——「重新生成形象图后历史始终为空」的 s0 根因；现读出旧数据快照后写回前调用同一归档方法）。

归档规则（`_archive_character_image_history`）：

- 旧主图非空，且被替换**或被删除/清空**（新图缺失、为空或不同）→ 旧图归档到 `image_history` 头部（最新在前）；
- 历史基线优先取 new_data 显式携带的（编辑弹窗回存），否则继承 old_data（agent 重建 JSON 时不带该字段）——**图片未变时同样继承，防止历史丢失**；
- 换回旧图时，当前主图从历史移出；去重；截断到 `CHARACTER_IMAGE_HISTORY_MAX_ENTRIES`（默认 20，`config/constant.py`）。
- location/prop 不归档（仅角色）。归档异常不影响主写入。
- 单元测试：`tests/utils/test_file_manager_image_history.py`（12 个用例，含 agent 路径回归）。

## 六、暂存区「图片生成中」标识

- 前端内存级集合 `imageGeneratingKeys`（key：`${fileType}||${name}`），两个标记来源：
  1. 「重新生成形象图」按钮：精确标记该角色；
  2. SSE `tool_call` 事件命中生图工具（`generate_text_to_image` / `generate_4grid_*` / `generate_character_variant_image` / `generate_9grid_location_images` / `edit_image` 等）：将当前 tab 下**无参考图**的资产标记为生成中（典型为角色形象设计师批量补图的弱推断）。
- 展示：**该条目的图片预览按钮图标（山形 SVG）原地替换为 loading 圈**（不带文字，避免挤占文件名宽度），title 提示"图片生成中"。
- 清除：任务终态（done/error/verification_timeout/resetProcessingState）在 `refreshFiles()` 完成后 `clearAllImageGenerating()` 统一清除（内存级瞬态，刷新页面自然重置；弱推断误标无副作用）。
- i18n：`image_generating_badge`（用作 title）。

## 七、故事板拆分弹窗：视频模型分辨率选项

`web/js/storyboard/render.js::renderDefaultVideoModelConfig`（无分镜时的「当前故事板还没有分镜」拆分弹窗）：

- 在「默认视频模型」下方追加 `renderVideoResolutionChips`（与齿轮弹窗同源），绑定**图生视频模型**，随模型切换自动校正档位（复用既有 `set-video-resolution` action 与 `ensureVideoGenerationPrefsSupported` 校正链路，选择持久化走 `persistUiConfig`）。
- 仅在非 busy（未在拆分中）时渲染 chips。

## 涉及文件

| 文件 | 改动 |
| --- | --- |
| `web/script_writer.html` | 折叠按钮与 body 包裹；预览弹窗重新生成 + 历史形象图按钮；编辑弹窗重新生成按钮 |
| `web/js/script_writer.js` | 消息队列、重新生成、生成中标识（图标→loading 圈）、预览弹框内历史视图切换、折叠逻辑、loadFiles 渲染 |
| `web/css/script_writer.css` | 折叠/排队标签/生成中 spinner/样式 |
| `web/js/storyboard/render.js` | 拆分弹窗分辨率 chips |
| `script_writer_core/file_manager.py` | `_archive_character_image_history` 归档（含删除/清空场景）与继承 |
| `script_writer_core/mcp_tool.py` | `create_character_json` 保存前接入归档（agent 路径 s0 修复） |
| `config/constant.py` | `CHARACTER_IMAGE_HISTORY_FIELD` / `CHARACTER_IMAGE_HISTORY_MAX_ENTRIES` |
| `script_writer_core/skills/plot-analyzer/SKILL.md` | 画风识别引导话术 |
| `web/i18n/locales/{zh-CN,en}/index.json` | 新增 i18n 键（顺带去除原有 `status_deleting` 重复键，语义不变） |
| `tests/utils/test_file_manager_image_history.py` | 归档行为单测（新增，含 agent 路径回归） |
