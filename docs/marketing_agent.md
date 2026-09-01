# 营销智能体（Marketing Agent）

## 功能概述

营销智能体是系统两大创作模式之一（另一为短剧模式），面向营销内容创作场景。它提供对话式交互能力，集成 LLM 对话、图片生成、视频生成三大核心功能，帮助用户创作带货脚本、广告创意、产品文案等营销内容。

### 双模式系统

用户首次进入系统时通过模式选择弹窗选择创作模式，选择结果保存在 `localStorage` 的 `creation_mode` 字段中（`short_drama` 或 `marketing`）。两种模式共享后端基础设施，但前端入口和交互风格不同：

| 模式 | 入口 | 主题 | 适用场景 |
|------|------|------|----------|
| 短剧模式 | `/video-workflow-list` | 深色主题 | AI 短剧创作全流程 |
| 营销模式 | `/marketing-inspiration`（首页"开始创作"落地页）→ `/marketing-agent`（生成对话页） | 浅色主题（白底蓝调） | 营销内容创作 |

模式切换入口位于 `web/index.html` 的模式选择弹窗（约第 630-660 行），`selectCreationMode(mode)` 方法仅保存模式状态，不自动跳转。

## 页面架构

### 技术栈

- **框架**：Vue 3（CDN 引入 `vue.global.prod.js`，使用 Composition API）
- **HTTP 客户端**：axios（`axios.min.js`）
- **Markdown 渲染**：marked.js（`marked.min.js`）
- **代码高亮**：highlight.js（`github.min.css` 主题）
- **任务配置**：`task_config.js`（统一任务类型/模型/算力配置模块）
- **视频压缩**：`video_compressor.js`（Canvas + MediaRecorder 方案，按参考视频最低像素要求转码）
- **国际化**：`i18n-core.js` + `i18n-vue-plugin.js` + `i18n-dom.js`

### 挂载前防闪烁（FOUC）

Vue 挂载前（含 i18n 异步加载期间），模板中的 `v-if` 不会生效，页面里「联系我们 / 算力日志 / 算力充值」等弹窗会以原始 HTML 短暂露出，并显示未编译的 `{{ $t(...) }}` 文本。处理方式：

1. `#app` 增加 `v-cloak`，CSS `[v-cloak] { display: none !important; }` 在挂载前隐藏整个应用根节点
2. `#app` 外放置静态 `#pre-mount-loader` 加载遮罩，避免纯白屏；`app.mount('#app')` 后立即 `remove()`
3. 挂载后由 Vue 内 `isInitializing` 加载遮罩接力，直至鉴权/会话初始化完成

### 三栏布局

页面为 Vue 3 单页应用（SPA），采用三栏布局，整体高度 100vh：

```
+--------+------------------+--------------------------------+
| 左侧   | 左侧边栏          | 主内容区                        |
| 窄导航  |                  |                                |
| (64px) | (260px)          | (flex: 1)                      |
+--------+------------------+--------------------------------+
```

| 区块 | 类名 | 宽度 | 说明 |
|------|------|------|------|
| 左侧窄导航 | `.marketing-nav` | 64px | Logo、灵感、生成（高亮）、资产 |
| 左侧边栏 | `.sidebar` | 260px | 新对话按钮、搜索框、最近对话列表、用户信息 |
| 主内容区 | `.main-content` | flex: 1 | 顶部栏 + 消息流 + 底部输入区 |

**响应式**：768px 以下侧边栏变为固定定位的抽屉，通过 `.sidebar.open` 类控制显示。

### 组件结构

页面内所有 UI 均在单个 Vue 3 `createApp()` 实例中实现，无外部组件拆分。主要 UI 区块：

1. **顶部栏** (`.top-bar`)：当前日期、搜索框、算力余额显示
2. **消息流** (`.chat-messages`)：欢迎卡片、用户/AI 消息气泡、打字指示器、继续按钮
3. **底部输入区** (`.input-area`)：文件上传按钮、文本输入框、媒体缩略图条、类型选择、模型选择、比例/分辨率选择、发送按钮
4. **弹窗层**：联系反馈弹窗、算力日志弹窗（iframe）、算力充值弹窗、图片放大模态框

#### 消息流自动滚动（sticky 贴底）

`.chat-messages` 的自动滚动由 `web/js/marketing_agent.js` 中的 `scrollToBottom` 统一控制，采用 **贴底跟随** 策略，避免图片/视频生成轮询、SSE 流式输出把用户从上方历史消息拽回底部：

| 场景 | 行为 |
|------|------|
| 用户已接近底部（距底 ≤100px） | 新内容出现时继续自动滚底 |
| 用户已上滑离开底部 | **不**自动滚动，保留当前阅读位置 |
| 用户主动发送消息 / 新建对话 / 切换会话 / 图转视频等 | `scrollToBottom({ force: true })` 强制滚底 |

Agent 图/视频状态轮询在进度文案（如「生成中 1/3」）未变化时会跳过写入消息内容，减少无意义 re-render。

#### 输入栏「自定义」设置面板（矮屏适配）

Agent 模式下的「自定义」面板（`.marketing-settings-panel`）内容较多（生成偏好图片/视频、比例、时长、模型列表等）。原先仅用 `position: absolute; bottom: 100%` 向上弹出且无整体高度上限，在视口偏矮时展开模型列表会把顶部的「图片 / 视频」等选项顶出屏幕。

处理策略：

1. `.marketing-panel` 统一限制 `max-height` 并支持内部滚动
2. 自定义面板拆成 sticky 标题栏 + 可滚动 `.marketing-panel-body`
3. 面板内模型列表使用 `.marketing-model-list`（`max-height: min(200px, 32vh)`）
4. 图片/视频模型列表与 LLM 列表互斥展开（`toggleModelSelect` / `toggleLLMModelSelect`）
5. 视口高度 ≤760px 或宽度 ≤720px 时改为视口内 `fixed` 面板；宽度 ≤499px 时全屏抽屉
5. **资产库视图** (`.asset-library`)：通过左侧导航切换 `activeView` 为 `assets` 显示，展示用户历史生成结果（图片/视频），每页 60 条，支持分页。视频预览用 `max-width/max-height: 100%` + `object-fit: contain`，竖屏不再按宽度 100% 撑开后裁掉上下；有 `9:16` 等竖屏比例时卡片按 `9 / 16` 增高，缺比例时用 `loadedmetadata` 的真实宽高兜底。图片资产支持"生成视频"操作（`useAssetForVideo`），会将图片带入生成页输入区并自动切换到视频模式。图片放大弹窗中的"生成视频"按钮（`imageToVideo`）同样会自动切换回生成视图。

## 核心功能详解

### 三种创作类型

底部输入栏的类型选择器提供三种创作模式：

| 类型 | key | 图标 | 说明 |
|------|-----|------|------|
| Agent 模式 | `agent` | ✨ | LLM 对话驱动，可调用图片/视频生成工具，支持多模态输入 |
| 图片生成 | `image` | 🖼️ | 直接调用文生图/图生图 API，轮询获取结果 |
| 视频生成 | `video` | 📹 | 直接调用文生视频/图生视频 API，轮询获取结果 |

Agent 模式为默认推荐模式，走 LLM 对话流程，后端 PM Agent 可自主调用图片/视频生成工具。图片/视频模式为直接生成模式，前端直接调用生成 API 并轮询状态。

#### Agent 视频意图路由（企业版）

Agent 模式中的视频生成能力由 `enterprise/` 模块提供。企业版加载后，`enterprise/sops/sop-video-generation.md` 和 `enterprise/skills/marketing-video/SKILL.md` 会覆盖开源目录中的同名占位 SOP/skill，并注册 `generate_text_to_video`、`image_to_video` 工具。社区版没有视频生成工具，开源目录中的 `sop-video-generation` 只负责提示用户视频生成功能为商业版专属。

企业版 Agent 模式中的视频请求分为普通视频和营销视频：

- **普通视频**：用户只描述主体、动作、场景或镜头，例如"生成一个视频，一个女孩在跳舞"、"赛博城市航拍镜头"。这类请求应直接进入视频生成流程，不应询问商品展示、广告宣传、品牌宣传等营销用途。
- **营销视频**：用户明确提到商品、广告、品牌、带货、产品宣传、社交媒体投放、本地生活推广等商业目的。只有这类请求才需要补充商品、品牌、卖点、投放平台等营销信息；其中餐饮、酒旅、旅游、丽人、休闲娱乐、到店零售、生活服务等按本地生活规则处理，非本地生活则按普通营销视频处理。
- **图生视频**：用户上传图片并要求图片动起来、生成动作或镜头运动时，保留真实图片上下文并进入视频生成流程，不得编造图片 URL。

当用户的普通视频描述已经足够明确时，PM Agent 应直接调用视频专家提交生成任务；只有缺少主体、动作、场景或必要素材时，才使用 `ask_user` 补充关键生成信息。

### 会话管理

#### 创建会话

- 调用 `POST /api/session/create`，传入 `user_id`、`world_id`、`auth_token`、`session_type: 2`（营销模式标识）
- 营销智能体使用固定 `world_id = '1'`，无需多世界概念
- 创建成功后将新会话加入本地 `sessions` 列表头部并持久化到 `localStorage`（`marketing_sessions` 键）
- 从 `/marketing-inspiration` 输入框发送或做同款跳转时会携带 `new_session=1`，生成页在加载历史后先创建新会话，再应用 URL 中的 prompt、模式、模型和媒体参数，避免继续写入最近一次对话。

#### 搜索

侧边栏搜索框通过 `v-model` 绑定 `searchQuery`，`filteredSessions` 计算属性对会话标题进行大小写不敏感的模糊过滤。

#### 重命名

- 悬浮会话项显示 `···` 按钮，点击弹出上下文菜单
- 选择"重命名"后，会话标题变为内联输入框（`.history-rename-input`）
- 支持 Enter 确认、Escape 取消、失焦自动确认
- 调用 `PUT /api/session/{session_id}/title` 保存到后端

#### 删除

- 调用 `DELETE /api/session/{session_id}` 进行软删除
- 至少保留一个会话，删除最后一个时提示 `keep_one_session`
- 删除当前活跃会话后自动切换到列表中的第一个会话

#### 加载会话列表

页面初始化时调用 `GET /api/sessions?user_id=xxx&world_id=1&session_type=2&limit=50` 从后端加载，失败时回退到 `localStorage` 缓存。

### 消息交互

#### 消息类型

| 角色 | 头像 | 气泡样式 | 说明 |
|------|------|----------|------|
| `user` | 👤 | 蓝色背景，右对齐 | 用户输入 |
| `ai` | 🤖 | 白色背景，左对齐 | AI 回复 |
| `system` | - | 居中标签 | 任务状态标签（已完成等） |

#### 多模态消息

- 用户上传的图片在消息气泡中以 `<img>` 标签渲染，最大高度 160px，点击可放大
- 视频以 `<video>` 标签渲染，支持 controls
- 音频以 `<audio>` 标签渲染
- 历史消息中的多模态内容（JSON 数组格式的 `image_url` + `text`）在 `parseHistoryMessage` 中解析为文本+图片分别渲染

#### 灵感页输入

`/marketing-inspiration` 顶部输入框中，Enter 会触发送出并跳转到生成页；Shift+Enter 保留为输入换行。该发送路径会带上 `new_session=1`，因此每次从灵感页发起都会在 `/marketing-agent` 新建一条对话。

#### Markdown 渲染

`renderMarkdown(text)` 函数的处理流程：

1. 保护已有的 Markdown 图片语法 `![alt](url)` 和链接语法 `[text](url)`（占位符替换）
2. 将裸图片 URL（以 `.png/.jpg/.gif/.webp` 等结尾）自动转换为 Markdown 图片格式
3. 处理 URL 后紧跟中文等非空白字符的边界问题
4. 恢复占位符
5. 调用 `marked.parse()` 解析为 HTML
6. 为所有 `<img>` 标签添加点击放大事件和样式

#### Verification 交互（ask_user）

当后端 Agent 通过 `ask_user` 工具向用户提问时，SSE 流会推送 `human_verification_required` 事件：

1. 前端解析 `verification` 对象，提取 `title`、`description`、`options`
2. 渲染为特殊消息气泡，包含预设选项按钮和"其他"自由输入按钮
3. 用户选择后调用 `POST /api/verification/{verification_id}` 提交回答
4. 验证期间（`pendingVerificationId` 不为 null）禁止正常发送消息
5. 如果用户在等待 `ask_user` 回答期间上传了图片、视频或音频，`marketing_agent.html` 会等待上传完成，并在提交验证回答时携带 `image_urls`、`video_urls`、`audio_urls` 和 `thumbnail_urls`。后端会把这些媒体 URL 合并进当前 `agent_tasks`，并写入验证回答历史，确保 PM Agent 和后续专家能看到真实 `[图片N]（URL: ...）` 等标签，而不是只看到纯文本回答。

切换会话或刷新页面后，前端会从 `chat_messages` 历史中查找最后一个未被 `verification_answer` 覆盖、且 `agent_verifications.status` 仍为 `pending` 的 `verification_request`，并恢复 `pendingVerificationId`。只有 `verificationId` 等于当前 `pendingVerificationId` 的问题卡片可点击，历史中的旧问题保持禁用，避免误把旧选项提交到当前等待项。主输入框在等待用户回答时仍可提交自定义答案，但不会发送新的普通对话消息。

如果用户切换会话期间 `ask_user` 已超时，后端会在历史接口中为该 verification 返回 `verification_status='cancelled'`。前端加载到非 `pending` 状态时不会恢复等待状态，因此输入框和发送按钮会恢复为普通对话模式；超时后的历史问题仍可展示，但不再阻塞用户继续输入。

#### 高算力确认（系统硬门）

Agent 模式提交文生图 / 图生图 / 文生视频 / 图生视频 / 数字人等计费工具前，后端会先按与扣费相同的规则预估算力，再决定是否打断用户：

| 情况 | 行为 |
|---|---|
| 本次及本轮累计 ≤ 用户软阈值 | 直接提交，不弹确认 |
| 超过用户软阈值 | 弹出「算力确认」卡片，选项：确认生成 / 取消本次生成 / 本次对话不再询问 |
| 余额不足 | 不弹确认，直接告诉模型算力不足 |
| 用户点「本次对话不再询问」 | 本会话后续低于平台硬阈值的生成不再问；超过硬阈值仍问 |
| 底部「图片 / 视频」直出模式 | 不走此门（用户已主动点生成） |

阈值分层：

1. **用户软阈值**：每人可在自定义面板「自动确认上限」自行设置，存 `user_preferences.pref_type=power_confirm`（`world_id=_global`，换对话/换世界共用）。
2. **平台默认软阈值**：用户未设置时使用 `agent.power_confirm_threshold`，默认 35。
3. **平台硬阈值**：`agent.power_confirm_hard_threshold`，默认 200，只约束「本次对话不再询问」之后的放行。

企业版走 `enterprise/routes/user.py` 注册同一组接口（社区版走 `api/user.py`）。商业版不会加载社区用户路由，因此两端都要挂上。

读写接口（需登录，只能改自己的）：

- `GET /api/user/power-confirm` → `{ threshold, is_custom, default_threshold, hard_threshold }`
- `PUT /api/user/power-confirm` body `{ threshold }`
- `DELETE /api/user/power-confirm` 回退平台默认

确认不可被模型绕过：拦截点在 `ExpertAgent._execute_tool`，确认完成前不会调用 `generate_*`。模型也不应再自己用 `ask_user` 问算力。

> **作用范围**：算力确认门仅对营销智能体（`MarketingPMAgent`，`session_type=2`）及分镜（storyboard）链路开启。剧本创作页（`script_writer.html`，`PMAgent`）已于 2026-09-01 关闭此门（`power_confirm_enabled=False`，见 `docs/backend/incidents/2026-09-01-script-writer-power-confirm-loop.md`）：生成前不弹「算力确认」，也不在系统提示中注入阈值说明。

### SSE 流式响应

#### 连接建立

Agent 模式下发送消息的完整流程：

1. `POST /api/session/{session_id}/task` 创建任务，获取 `task_id`
2. `EventSource` 连接到 `/api/task/{task_id}/stream`
3. 超时设置为 900 秒（15 分钟）

#### 事件类型

| 事件类型 | 处理逻辑 |
|----------|----------|
| `message` | 追加文本到当前 AI 消息气泡 |
| `status` | 忽略 |
| `progress` | 忽略 |
| `human_verification_required` | 触发 Verification 交互流程 |
| `verification_timeout` | 清除验证状态，提示超时 |
| `context_compression` | 忽略 |
| `image_task_submitted` | 前端开始轮询图片生成状态 |
| `video_task_submitted` | 前端开始轮询视频生成状态 |
| `error` | 关闭 SSE，显示错误消息 |
| `done` | 关闭 SSE，显示"继续"按钮，刷新算力余额 |

#### 去重与续传

- `/api/task/{task_id}/stream` 会为数据库中的任务消息输出 SSE `id`，取值为 `agent_task_messages.id`。
- 浏览器原生重连时，后端会读取 `Last-Event-ID`；手动恢复连接时也可通过 `last_id` 查询参数指定已处理的最后一条消息。
- 前端维护已处理的 SSE 消息 id 集合，重复 id 会被跳过，避免重连重放时把同一条完整 `message` 再次拼接到 AI 气泡中。
- 当页面或会话切换后恢复活跃 Agent 任务时，前端还会对比当前历史中已展示的 assistant 内容；如果恢复流重放了同样的完整 `message`，会跳过该消息，避免“历史气泡 + 恢复流气泡”重复显示。
- Agent SSE 文本回复的持久化以任务完成回调中的 `session_storage.save_session()` 为准；前端收到 `done` 后不再调用 `/session/{session_id}/message` 追加同一段 assistant 文本，避免“后端保存 + 前端追加”产生相邻重复历史。
- Agent 模式下用户消息的持久化以后端增强版为准：前端发送时只在当前页面即时展示用户气泡，不再调用 `/session/{session_id}/message` 保存展示版；任务完成后 PM Agent 保存包含媒体 URL 标签和用户偏好的增强版 user 消息。历史加载时前端会把 `[用户图片偏好]`、`[用户视频偏好]` 折叠为“查看发送偏好”，避免同一用户输入以 UI 展示版和 LLM 增强版各保存一次。
- `/session/{session_id}/message` 也会跳过与最后一条历史记录 role 和 content 都相同的消息，作为其他追加路径的兜底保护。
- `call_agent` 成功返回的专家结果会在 `_handle_agent_call()` 阶段作为 SSE `message` 推送给前端，确保“图片内容分析”等专家输出立即可见；结果仍会进入 PM 上下文和会话历史，若 PM 后续 assistant 回复复述同一段内容，前端会通过内容去重跳过重复气泡。
- `handleStream` 在建立连接时捕获发起会话 `streamSessionId`，并在 `onmessage` 顶部校验：若用户已切换到其他会话，残留的 SSE 事件（`message` / `image_task_submitted` / `video_task_submitted` / `verification_timeout` 等）会被丢弃并关闭旧连接，避免把上一会话的 AI 回复、任务结果或验证提示串到当前对话。切回原会话时由会话恢复机制重新建立 SSE。

#### 任务状态轮询

Agent 提交图片/视频生成任务后，前端通过 `setInterval` 轮询 `GET /api/get-status/{project_ids}`：

- 图片轮询间隔：5 秒（启动后立即查询一次，不必等待第一个周期）
- 视频轮询间隔：10 秒（启动后立即查询一次）
- 任务完成后将结果（图片/视频 URL）渲染到消息气泡中
- 使用 `sessionTaskRegistry` 注册表跟踪所有活跃任务，支持会话切换后恢复
- 直接图片/视频生成使用 `directGenerationTasks` 为每次提交创建独立任务实例，实例内绑定 `type`、`project_ids`、`msgUid`、`sessionId` 和 `intervalId`。轮询只读取实例内的 `projectIds`，避免多轮对话中后提交的图片任务覆盖先提交的视频任务。
- 直接生成任务完成后优先调用 `replacePendingTask(sessionId, task_type, project_ids, content)` 精确替换原 `__PENDING_TASK__` 历史行；只有匹配失败时才 fallback 追加 assistant 消息，且追加到任务所属的原 session。
- 生成结果统一通过媒体类型过滤后渲染：图片结果会排除 `.mp4/.webm/.mov/.avi/.mkv`，视频结果会排除图片扩展名，避免视频 URL 被 `<img class="generated-image">` 包裹。
- `GET /api/get-status/{project_ids}` 对 CDN 结果采用 CDN 优先策略；如果生成任务已完成但 CDN 仍处于 pending，会先返回本地 `result_url` 作为 `file_url`，并附带 `cdn_status: "pending"`，避免聊天框一直显示生成中
- 前端轮询统一识别 `SUCCESS`/`COMPLETED`/`DONE` 等完成状态，并从 task 本身和 `results[]` 中提取 `file_url`、`result_url`、`video_url`、`image_url`、`output_url`、`download_url` 等字段
- 如果 `video_task_submitted` SSE 事件缺失，但专家工作总结中包含 `project_ids: [...]` 且文本语义为视频任务，前端会自动补启动视频轮询；加载历史会话时也会执行同样的兜底恢复
- 如果 `image_task_submitted` SSE 事件缺失，但专家回复中包含 `project_ids: [...]` 或 `项目ID: 744` 这类图片任务标识，前端会自动补启动图片轮询；图片轮询会绑定触发时的会话，避免切换会话后把结果写入当前对话
- 文本兜底恢复会优先识别视频摘要，包含“视频参数”“图生视频”“文生视频”“时长”“first_last_frame”“multi_reference”等视频信号的工作总结不会再触发图片轮询，避免“图片模式 first_last_frame”被误判为图片生成任务
- Agent 图片/视频轮询启动后均立即查询一次状态，已完成的任务可直接渲染结果，不必等待第一个轮询周期
- 视频兜底恢复按会话绑定轮询结果，异步返回时如果用户已切换到其他会话，不会把结果写入当前对话；历史加载时会过滤空 AI 气泡和重复的视频结果，避免切换会话后重复显示
- 直接发起模式（`checkDirectGenerationStatus`）的轮询在每次 `await` 获取状态返回后，会再次校验 `currentSessionId` 是否仍等于任务实例的 `task.sessionId`：任务进行中切换会话时，旧轮询回调立即停止并清理，不再向当前（已切换的）`messages` 或全局 `imageResults/videoResults` 写入，杜绝"视频生成失败/图片生成失败"提示串到其他对话
- `handleImageTaskSubmitted` / `handleVideoTaskSubmitted` 支持显式 `explicitSessionId` 入参；由 SSE 流派发任务时传入该流的 `streamSessionId`，使轮询与结果持久化归属发起会话，而非事件被处理时的"当前会话"

#### 任务恢复机制

页面刷新或切换会话时，系统通过以下机制恢复未完成的任务：

1. **`__PENDING_TASK__` 标记**：后端在 `chat_messages` 表中保存 `__PENDING_TASK__:{type}:{project_ids}` 标记（`message_type='pending_task'`）。这是内部恢复用行，前端解析后标为 `_isPendingTask`，模板不渲染；切回会话时不会把 `__PENDING_TASK__` 交给 Markdown（否则两侧 `__` 会被收成加粗的 `PENDING_TASK`）
2. **`recoverPendingTasks()`**：加载历史后先恢复 pending 轮询，再跑工作总结文本兜底，避免同一 `project_ids` 再插一条「生成中」。完成时优先替换 pending 消息（通过 `PUT /session/{id}/message/{message_id}`），替换失败则 fallback 追加新消息
3. **`sessionActiveTaskId` 注册表**：记录每个 session 的活跃 Agent task_id，切换回来时检查任务状态并重连 SSE
4. **`directGenerationTasks` / Agent 轮询注册表**：直接生成任务在内存中按任务实例跟踪 project_ids；Agent 图片/视频轮询按 `sessionId:type:project_ids` 去重，支持会话内恢复和并发任务隔离
5. **并发安全**：`clean-pending-tasks` 支持按 `task_type` + `project_ids` 精确清理，并发任务互不影响。轮询和 `recoverPendingTasks(sessionId)` 的 fallback 追加也必须显式传入原始 sessionId，避免用户切换会话后把上一会话的图片/视频结果写入当前会话。

### 模型选择

#### 图片模型

通过 `TaskConfig.getModelOptionsForCategory('text_to_image')` 动态加载，默认优先选择 Seedream 5.0。用户选择保存到 `localStorage`（`marketing_selected_image_model` 键），并通过 `POST /api/text-to-image-model` 同步到后端 `user_preferences` 表。

#### 视频模型

- **文生视频**：`TaskConfig.getModelOptionsForCategory('text_to_video')`
- **图生视频**：`TaskConfig.getModelOptionsForCategory('image_to_video')`，根据 `videoImageMode` 过滤支持的模型
- 模型偏好从后端 `GET /api/video-model` 获取，回退到 `localStorage`
- 用户在 Agent 模式下切换视频模型时，前端 `syncVideoModelToBackend()` 会调用 `POST /api/video-model` 并携带完整 `video_preferences`（含 `model_name`、`ratio`、`duration`、`resolution`、`image_mode`、`enable_face_mask`），后端合并更新 `_video_preferences_cache`，确保 MCP 视频工具执行时读取到最新偏好
- **性价比 / 效果双轨切换**：视频模型列表（Agent 模式「其他设置」内联列表与非 Agent 模式底部弹窗两处）顶部提供与 LLM 模型一致的 `model-track-toggle` 按钮。Agent 模式下视频模型列表内联展开于模型选择按钮正下方、对话模型（LLM）选择之上。场景推导口径与模型列表过滤一致：无参考图 → `video.text_to_video`，首尾帧模式 → `video.image_to_video`，多参考模式 → `video.reference_to_video`（复用 `ModelCatalog.sceneForVideoImageMode`）。当前选中模型所处轨道由 `currentVideoTrack` 计算（优先读 `task_config` 下发的 `track` 字段，回退 `ModelCatalog.inferTrack`），点击按钮时 `selectVideoTrack()` 通过 `ModelCatalog.findTaskByTrack` 在当前列表中选中该轨道推荐模型（文生/图生视频：性价比 `minimax_h3`、效果 `seedance_2_0`；多参考：性价比 `minimax_h3_r2v`），并复用 `selectModel()` 完成偏好同步与持久化。选中 Grok、Happy Horse 等非推荐模型时两按钮均不高亮（custom）；若某轨道推荐模型不在当前过滤后的列表中，点击无动作。图片模式不显示该切换。

#### 模型选择状态

页面 UI 仍保持一个可见的模型选择器，但内部状态已拆分为图片模型和视频模型两套。`selectedImageModel` / `selectedImageModelKey` 保存生图选择，`selectedVideoModelName` / `selectedVideoModelKey` 保存生视频选择，`selectedModel` / `selectedModelKey` 仅作为当前模式的可写计算属性供模板和发送逻辑读取。用户在 Agent 模式下切换“生图 / 生视频”时，不会再用视频模型覆盖图片模型；`image_preferences.model_name` 始终取图片模型，`video_preferences.model_name` 始终取视频模型。

#### LLM 模型（Agent 模式）

调用 `GET /api/models` 加载所有可用 LLM 模型，支持 VL（视觉理解）和 Thinking（深度思考）标签。同名模型可能来自不同供应商，前端使用 `model_id + vendor_id` 作为唯一选择键，避免同名模型同时高亮。默认选择 `doubao-seed-2-0-lite` 时优先使用 `volcengine`，没有火山引擎配置时再回退到 `zjt_api` 或其他供应商。用户选择保存到 `localStorage`（`marketing_selected_llm_model_id` + `marketing_selected_llm_vendor_id` 键），发送消息时通过 `model`、`model_id`、`vendor_id` 字段传给后端。

### 图像比例选择

比例选项通过 `TaskConfig.getRatioOptions(modelKey)` 动态获取，支持的比例如下（定义在 `aspectRatioMap` 中）：

| 比例 | 可视化尺寸 |
|------|-----------|
| auto（智能） | 20x20 |
| 21:9 | 28x12 |
| 16:9 | 24x14 |
| 3:2 | 22x15 |
| 4:3 | 20x15 |
| 1:1 | 18x18 |
| 3:4 | 15x20 |
| 2:3 | 14x22 |
| 9:16 | 12x24 |

用户选择保存到 `localStorage`（`marketing_selected_ratio` 键），并通过 `POST /api/text-to-image-model` 同步到后端。全新用户没有保存偏好时，前端按当前生图模型的 `default_ratio` 初始化；默认 Seedream 5.0 使用 `9:16` 竖屏比例。

### 分辨率选择

图片模式下显示分辨率选项，通过 `TaskConfig.getSizeOptions(modelKey)` 动态获取。选项前自动添加 `auto`（自动根据模型选择最佳分辨率）。分辨率映射：`1K` -> `1K`，`2K` -> 高清 2K，`4K` -> 超清 4K。

Agent 模式下，如果用户没有在本轮偏好、历史对话或明确指令中说明分辨率，专家不再向用户追问清晰度选项，而是直接选择当前模型支持的最低输出分辨率。例如模型支持 1K/2K/4K 时默认 1K，支持 2K/3K 时默认 2K。只有用户主动表达“高清”“大图”“印刷”“海报大图”等需求时，才按需求选择更高分辨率。

前端选择 `auto` 时会显式把 `resolution: "auto"` 同步到后端，用于覆盖旧的固定分辨率偏好；直接图片生成/编辑请求会在提交前将 `auto` 解析为当前模型支持的最低输出分辨率，避免落入接口层的通用 1K 默认值。

分辨率选项表示生成或编辑结果的目标输出清晰度，不用于校验用户上传原图的像素尺寸。例如 Seedream 5.0 支持 2K/3K 时，用户上传 1K 或普通尺寸照片仍可发起图片编辑；系统应将 2K/3K 作为 `image_size` 输出参数传递，而不是要求用户重新上传 2K/3K 原图。

### 视频时长和生成方式

#### 视频时长

通过 `TaskConfig` 的 `supported_durations` 动态获取，前端会在模型支持时长前追加 `auto`，默认选择 `auto`。直连视频提交时，`auto` 会解析为当前模型支持的最长时长；Agent 偏好中保留 `duration: "auto"`，表示不把创作意图锁死为固定秒数。

自定义面板中的时长控件按**数字档位数**自适应（不含 `auto`）：

| 数字档位数 | 模式 | 交互 |
|------------|------|------|
| ≤3（如 `5/8/10` 非连续） | 紧凑点选 | 「自动」与全部合法秒数一排铺开；无滚动条、无输入框；**不伪造**中间秒数 |
| ≥4（如 Seedance `5–15`） | 横滚 + 输入 | 「自动」固定左侧；中间横滚 chips；右侧数字输入，失焦/Enter 时吸附到最近合法秒数 |

合法值始终来自当前模型的 `supported_durations`，输入不得提交列表外整数。工具栏快捷时长下拉仍为纵向列表，本期未改。

#### 生成方式（videoImageMode）

视频模式下有图片时可选择：

| 模式 | key | 说明 |
|------|-----|------|
| 首尾帧 | `first_last_frame` | 第一张为首帧，第二张为尾帧（可选） |
| 全能参考 | `multi_reference` | 所有图片作为风格参考，最多 5 张 |

### 文件上传

#### Agent 对话模式

支持同时上传多种媒体文件：

| 类型 | 最大数量 | 大小限制 | 时长限制 | 说明 |
|------|----------|----------|----------|------|
| 图片 | 9 张 | 10MB（可配置） | - | 上传到 `/api/upload-agent-image` 获取 HTTP URL |
| 视频 | 3 个 | 100MB（可配置） | 15 秒（可配置） | 前端按 480px 目标短边和 409600 最低总像素转码后上传到 `/api/upload-agent-video` |
| 音频 | 5 个 | 20MB | 15 秒（可配置） | 上传到 `/api/upload-agent-audio` |

#### Agent 视频模式

支持上传参考图（首尾帧/全能参考）、参考视频和参考音频。图片上传到 `/api/upload-agent-image`，通过 `image_urls` 字段传给后端。
切换视频模型时已上传图片的保留规则按模式区分：仅首尾帧模式下切到 `supports_last_frame=false` 的模型才裁剪到 1 张主图；全能参考模式切模型不删除参考图（该模式下模型天然不使用尾帧，`supports_last_frame` 与参考图数量无关，上限由各模型 `max_multi_ref_images` 在上传时限制）。
Agent 视频模式下，主图和后续参考图都会等待上传完成并转换为 HTTP URL；发送给后端时按输入区显示顺序去重收集到 `image_urls`，避免 blob 预览地址或未上传完成的参考图遗漏。
当前页面即时渲染的用户气泡统一通过 `collectCurrentMessageMedia()` 收集媒体，再由 `buildUserMessageContent()` 渲染；图片、视频、音频模式和 Agent 模式不再分别拼接预览 HTML。Agent 发送给后端的 `image_urls`、`video_urls`、`audio_urls` 也复用同一媒体集合，确保即时显示、请求 payload 和后端保存的增强版用户消息尽量一致。
纯视频参考文件上传到 `/api/upload-agent-video`，只进入 `video_urls` 流程，不会设置图片上传状态，也不会触发图片 HTTP URL 等待。

会话历史从 `chat_messages` 恢复时依赖媒体标签重新渲染图片、视频和音频。`/api/session/{session_id}/task` 写入用户消息时必须把上传接口返回的 URL 拼入 `[图片N]（URL: ... thumb: ...）`、`[视频N]（URL: ...）`、`[音频N]（URL: ...）` 标签后再落库；上传接口已经根据 `server.is_local` 决定返回本地 URL 还是 CDN URL，历史持久化层只保存返回值，不重新判断或改写 CDN。

生成状态轮询和 Agent SSE 流使用连续失败保护。图片/视频状态轮询、Agent 图片/视频轮询，以及 SSE 连接错误/超时在同一任务上连续失败 3 次后，会停止对应定时器或断开流，并清理活跃任务归属，避免对话区持续追加“请求超时，请稍后重试”之类的错误气泡。

#### 图片/视频模式

图片直接通过 `FormData` 上传到 `/api/text-to-image` 或 `/api/image-edit`。视频上传到 `/api/ai-app-run-image`（图生视频）或 `/api/ai-app-run`（文生视频）。

#### 视频压缩

使用 `VIDEO_COMPRESSOR` 模块（Canvas + MediaRecorder 方案）：

- 目标短边：480px；若总像素低于 409600，会按原比例补足到下游参考视频最低要求
- 帧率：24fps
- 视频码率：1.5Mbps
- 压缩阈值：文件 > 10MB、短边 > 480px、总像素 < 409600 或超过最大时长
- 支持 WebM (VP9/VP8) 和 MP4 格式
- 超过最大时长的视频自动截断

#### @ 引用系统

输入框支持 `@` 触发媒体引用下拉框，列出已上传的媒体文件。选中后插入引用标签到文本中，支持模糊搜索过滤。`mentionDropdown` 状态管理下拉框的显示、查询和选中索引。

### 算力显示

#### 余额显示

顶部栏右侧显示算力余额，每 30-45 秒随机间隔自动刷新（`startComputingPowerRefresh`）。余额根据数值自动变色：

| 余额范围 | CSS 类 | 颜色 |
|----------|--------|------|
| < 100 | `.low-power` | 红色 |
| 100-999 | `.medium-power` | 黄色 |
| >= 1000 | `.high-power` | 绿色 |

点击余额打开算力日志弹窗（iframe 加载 `/computing_power_logs.html`）。

#### 消耗预估

输入区右侧根据当前选中模型和参数实时计算本次操作的算力消耗，使用 `TaskConfig.getComputingPower()` 方法。

#### 算力充值

算力日志弹窗中点击"算力充值"按钮打开充值弹窗：

1. 调用 `GET /api/recharge/packages` 加载套餐列表
2. 用户选择套餐后调用 `POST /api/recharge/wechat-pay` 创建支付订单
3. 通过第三方 QR 码服务生成微信支付二维码
4. 支持自动检测到账

### i18n 国际化

使用自研 i18n 框架（`i18n-core.js`），支持：

- Vue 模板中的 `$t('key')` 翻译
- JS 代码中的 `window.t('key')` 翻译
- 带参数的翻译：`$t('duration_seconds', { dur: 5 })` -> `5秒`
- DOM 属性的 `data-i18n` 自动翻译
- 语言切换器组件（`i18n-switcher.js`）

翻译文件位于 `web/i18n/locales/zh-CN/marketing_agent.json`，共约 215 个翻译键，覆盖页面标题、导航、侧边栏、输入区、模型选择、错误提示等所有用户可见文本。

## API 接口列表

### 会话管理

| 端点 | 方法 | 说明 | 请求参数 |
|------|------|------|----------|
| `/api/session/create` | POST | 创建新会话 | `{ user_id, world_id, auth_token, session_type: 2 }` |
| `/api/sessions` | GET | 获取会话列表 | `?user_id=&world_id=&session_type=2&limit=50` |
| `/api/session/{session_id}/history` | GET | 获取会话历史 | Headers: `Authorization`, `X-User-Id` |
| `/api/session/{session_id}/message` | POST | 追加消息到会话 | `{ role, content }` |
| `/api/session/{session_id}/title` | PUT | 更新会话标题 | `{ title }` |
| `/api/session/{session_id}` | DELETE | 删除会话（软删除） | - |
| `/api/session/{session_id}/latest-task` | GET | 获取最新活跃任务 | - |
| `/api/session/{session_id}/clean-pending-tasks` | POST | 精确清理 pending task 标记 | `{ task_type?, project_ids? }`（不传则清理全部） |
| `/api/session/{session_id}/message/{message_id}` | PUT | 更新消息内容（pending→结果替换） | `{ content, message_type? }` |

### 智能体任务

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/session/{session_id}/task` | POST | 创建 Agent 任务 |
| `/api/task/{task_id}/stream` | GET (SSE) | 流式获取任务消息 |
| `/api/task/{task_id}/status` | GET | 查询任务状态 |
| `/api/verification/{verification_id}` | POST | 提交人工验证回答 |

#### 任务创建请求体

```json
{
  "message": "用户输入文本",
  "auth_token": "认证令牌",
  "image_urls": ["http://..."],
  "video_urls": ["http://..."],
  "audio_urls": ["http://..."],
  "model": "LLM模型名称",
  "model_id": 1,
  "vendor_id": 1,
  "image_preferences": {
    "ratio": "9:16",
    "model_name": "Seedream 5.0",
    "resolution": "2K"
  },
  "video_preferences": {
    "ratio": "16:9",
    "duration": 5,
    "image_mode": "first_last_frame",
    "model_name": "可灵 2.0",
    "task_id": 1
  }
}
```

Agent 模式下，`image_preferences.ratio`、`image_preferences.resolution` 会在创建任务时同步写入后端图片偏好，后续专家调用 `generate_text_to_image` / `edit_image` 工具时会由工具层强制应用当前偏好。`ratio: "auto"` 也会被保存，表示本次任务不强制覆盖专家或模型默认比例。图片编辑场景中，`image_preferences.resolution` 只代表输出结果的目标分辨率；专家不应因为输入原图分辨率低于该值而中断任务或要求用户重传高清原图。如果没有有效的 `image_preferences.resolution`，也没有历史/本轮文本分辨率要求，专家应直接使用当前模型支持的最低输出分辨率，不触发 `ask_user`。

Agent 对话模式即使当前自定义面板停留在“图片”，前端也会随 `/api/session/{session_id}/task` 携带 `video_preferences`，让 PM Agent 能看到用户历史生视频模型、比例、时长和图片模式偏好。前端按本轮真实上传媒体判断模型类别：有图片 URL、参考视频或参考音频时使用图生视频历史模型（`marketing_selected_i2v_model`），都没有时使用文生视频历史模型（`marketing_selected_t2v_model`）。后端在旧客户端未传 `video_preferences` 时，会从 `get_video_preferences(user_id, world_id)` 读取历史视频偏好并追加 `[用户视频偏好]`。

`video_preferences.enable_face_mask` 由「是否处理人脸」勾选状态（`processFace`）和上述图生视频判定共同决定：只传参考视频/音频（视频克隆场景，无图片）时同样视为图生视频，勾选后会携带 `enable_face_mask: true`，后端据此为 Seedance 2.0 / Fast / Mini / 2.5 创建 `face_mask` pipeline step（RUNNINGHUB_FACE_MASK 视频人脸遮盖预处理）。`syncVideoModelToBackend()` 切换视频模型同步偏好时采用同一判定口径。

视频时长选择支持 `auto`。在前端偏好和 Agent 上下文中，`auto` 表示不把创作意图锁死为 5 秒；直连视频接口和企业版 `video_tools` 在真正提交任务时会把 `auto` 解析为当前模型支持的最长时长，避免底层接口收到非数字时长。本地生活营销视频如果选择 3/5/8 秒，但内容包含门店/产品/卖点/口播/BGM/音效/店招等完整信息，PM Agent 应提醒用户改为 `auto` 或模型最长时长；只有用户明确坚持短时长时，才压缩为单一核心镜头。

### 媒体上传

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/upload-agent-image` | POST | 上传 Agent 图片，返回 HTTP URL |
| `/api/upload-agent-video` | POST | 上传 Agent 视频 |
| `/api/upload-agent-audio` | POST | 上传 Agent 音频 |

### 生成任务

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/text-to-image` | POST | 文生图 |
| `/api/image-edit` | POST | 图生图/图片编辑 |
| `/api/ai-app-run` | POST | 文生视频 |
| `/api/ai-app-run-image` | POST | 图生视频 |
| `/api/get-status/{project_ids}` | GET | 查询生成任务状态 |

### 模型和配置

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/system/task-configs` | GET | 获取任务配置（模型/算力/比例等） |
| `/api/system/server-config` | GET | 获取服务器配置（文件大小限制等） |
| `/api/models` | GET | 获取可用 LLM 模型列表 |
| `/api/video-model` | GET | 获取用户视频模型偏好 |
| `/api/video-model` | POST | 设置视频模型偏好（含 task_id + video_preferences 完整字段） |
| `/api/text-to-image-model` | POST | 同步图片模型偏好到后端 |

### 用户和算力

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/user/computing_power` | GET | 查询算力余额 |
| `/api/user/computing_power_logs` | GET | 查询算力日志 |
| `/api/recharge/packages` | GET | 获取充值套餐列表 |
| `/api/recharge/wechat-pay` | POST | 创建微信支付订单 |

## 认证与登录跳转

### 登录状态检查

页面初始化时检查 `localStorage` 中的 `user_id` 和 `auth_token`，如果缺失则自动跳转到登录页面。

### 401 自动跳转

所有带 `Authorization` 头的 API 请求均通过 `checkAuthResponse()` 函数统一检查 HTTP 状态码。当后端返回 `401`（未授权/token 过期）时，自动跳转到登录页面并携带当前页面路径，登录成功后可跳回原页面。

跳转目标格式：`/index.html?redirect_url={当前页面路径}`

`index.html` 已内置 `redirect_url` 参数支持：
1. 解析 `redirect_url` 参数并保存到 `localStorage` 的 `redirect_after_login`
2. 未登录时自动弹出登录窗口
3. 登录成功后检查 `redirect_after_login`，存在则跳转到指定路径

### 世界观

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/worlds` | GET | 获取世界列表 |
| `/api/worlds` | POST | 创建世界 |

## 前端依赖库

| 文件 | 用途 |
|------|------|
| `web/js/vue.global.prod.js` | Vue 3 生产版 |
| `web/js/axios.min.js` | HTTP 客户端 |
| `web/js/marked.min.js` | Markdown 解析器 |
| `web/js/task_config.js` | 任务配置统一管理模块 |
| `web/js/video_compressor.js` | 前端视频压缩模块 |
| `web/css/github.min.css` | 代码高亮主题 |
| `web/i18n/i18n-core.js` | i18n 核心模块 |
| `web/i18n/i18n-vue-plugin.js` | i18n Vue 插件 |
| `web/i18n/i18n-dom.js` | i18n DOM 翻译 |
| `web/i18n/i18n-switcher.js` | 语言切换器组件 |

## 配置项

### localStorage 键

| 键名 | 用途 | 示例值 |
|------|------|--------|
| `creation_mode` | 当前创作模式 | `marketing` |
| `marketing_sessions` | 本地会话历史缓存 | JSON 数组 |
| `marketing_selected_image_model` | 用户选择的图片模型名称 | `Seedream 5.0` |
| `marketing_selected_image_model_key` | 用户选择的图片模型 key | `seedream_5` |
| `marketing_selected_t2v_model` | 文生视频模型名称 | `可灵 2.0` |
| `marketing_selected_i2v_model` | 图生视频模型名称 | `可灵 2.0` |
| `marketing_selected_ratio` | 用户选择的比例 | `9:16` |
| `marketing_selected_llm_model_id` | LLM 模型 ID | `1` |
| `marketing_selected_llm_vendor_id` | LLM 供应商 ID | `1` |
| `marketing_media_type` | Agent 模式的生成偏好 | `image` / `video` |
| `auth_token` | 认证令牌 | JWT token |
| `user_id` | 用户 ID | 数字字符串 |
| `phone` | 用户手机号 | 手机号 |

### 服务端配置（`/api/system/server-config`）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `max_image_size_mb` | 10 | 图片上传大小限制（MB） |
| `max_video_size_mb` | 100 | 视频上传大小限制（MB） |
| `max_video_duration_seconds` | 15 | 视频/音频最大时长（秒） |
| `is_enterprise` | false | 是否为商业版 |

### 前端常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `AGENT_IMAGE_MAX_COUNT` | 9 | Agent 模式最大图片数 |
| `AGENT_VIDEO_MAX_COUNT` | 3 | Agent 模式最大视频数 |
| `AGENT_AUDIO_MAX_COUNT` | 5 | Agent 模式最大音频数 |
| `VIDEO_COMPRESSOR.TARGET_SHORT_EDGE` | 480 | 视频压缩目标短边（px） |
| `VIDEO_COMPRESSOR.MIN_REFERENCE_VIDEO_PIXELS` | 409600 | 参考视频最低总像素数 |
| `VIDEO_COMPRESSOR.FPS` | 24 | 视频压缩帧率 |
| `VIDEO_COMPRESSOR.VIDEO_BITRATE` | 1500000 | 视频压缩码率（bps） |

## 样式与主题

### 主题色变量（CSS 自定义属性）

定义于 `web/css/marketing_agent.css` 的 `:root` 中：

```css
--bg-primary: #f5f5f5;         /* 主背景 */
--bg-secondary: #ffffff;       /* 卡片/输入框背景 */
--bg-sidebar: #fafafa;         /* 侧边栏背景 */
--accent-color: #00a8e6;       /* 主题色（亮蓝） */
--accent-hover: #0095cc;       /* 主题色悬停 */
--accent-light: #e6f7ff;       /* 主题色浅底 */
--user-bubble: #e6f7ff;        /* 用户气泡背景 */
--ai-bubble: #ffffff;          /* AI 气泡背景 */
--text-primary: #1a1a1a;       /* 主文本 */
--text-secondary: #666666;     /* 次要文本 */
--text-muted: #999999;         /* 弱化文本 */
--border-color: #e8e8e8;       /* 边框 */
--shadow: 0 2px 8px rgba(0,0,0,0.06);
--radius-sm: 8px;
--radius-md: 12px;
--radius-lg: 16px;
--header-height: 56px;
--sidebar-width: 260px;
```

### 下拉菜单和弹窗

所有下拉菜单（类型选择、模型选择、比例选择等）采用统一的向上弹出定位（`position: absolute; bottom: 100%`），带 `fadeInUp` 动画。大面板弹窗使用 `box-shadow: 0 -8px 32px` 阴影。

## 与其他模块的关系

### 世界观系统

营销智能体使用固定 `world_id = '1'`，复用 `script_writer` 的世界观基础设施。会话通过 `session_type: 2` 区分营销模式和短剧模式（`session_type: 1`）。

### 算力系统

- 模型选择时通过 `TaskConfig.getComputingPower()` 实时预估消耗
- 发送消息时后端扣减算力，SSE 流结束后前端刷新余额
- 算力不足时后端返回错误，前端提示充值

### PM Agent 后端

Agent 模式的消息通过 PM Agent（`pm_agent.py`）处理：

- PM Agent 根据用户意图委托专家（如 `marketing-image` 专家生图）
- 专家返回结果后，PM Agent 自动提取图片 URL 并注入对话历史（多模态消息）
- PM Agent 通过 `call_agent` 委托专家时会透传本次任务的 `image_urls`、`audio_urls`、`video_urls`；专家会以 `[图片N]`、`[音频N]`、`[视频N]` 标签注入上下文，避免数字人等任务只知道"用户已提供音频"但拿不到真实 URL
- **图片标签不等于图片内容**：注入专家上下文的 `[图片N]（URL: ...，注意：此为图片地址文本，不包含图片内容）` 只是地址文本，LLM 看不到图片本身。需要看图的专家（`image-understanding`）必须先调用 `fetch_image_as_base64(image_url)`，工具成功后 base64 图片才会作为多模态 user 消息注入对话（`expert_agent.py` 的 deferred 多模态注入机制）。2026-09-01 修复：此前 `image-understanding/SKILL.md` 残留旧设计的"正常情况下你能直接看到图片内容"表述（旧版曾直接注入 base64，2026-05-19 提交 20ef0a68 改为按需工具获取），导致模型不调工具就编造图片描述（实际为大虾面被描述成"红烧牛肉面"）；现 SKILL.md、工具描述与标签文案三处均已明确"分析前必须先获取图片数据"
- Agent 前端发送任务前会等待音频上传完成，并只把真实 HTTP 音频 URL 写入 `audio_urls`；上传完成后会同步更新 `mediaItems.serverUrl` 和 `mediaItems.fileUrl`
- 数字人 RunningHub v1 驱动提交 node 185 的音频前会检查音频地址：`localhost`、内网地址和本地文件路径会先上传到 RunningHub 文件存储，并改用返回的 `openapi/...` fileName；已经是 `openapi/...` 的 RunningHub 文件名会直接复用，公网 URL 保持原值
- 通过 `ask_user` 工具实现向用户提问的交互
- 专家通过 `script_writer_core/config/agents_config.json` 中的 `expert_type` 声明所属模式；剧本 PM 只允许 `script` 类型专家，营销 PM 只允许 `marketing` 类型专家
- `call_agent.AgentName` 的工具枚举会按当前 PM 的 `allowed_expert_types` 动态过滤，`_handle_agent_call()` 也会做后端校验，避免营销模式误调用剧本专家或反向串线
- 营销视频克隆必须走 `sop-video-clone` 并委托 `marketing-video`；数字人口播必须走 `sop-digital-human` 并委托 `digital-human-creator`，且数字人专家必须实际调用 `generate_digital_human` 并返回非空 `project_ids` 才算提交成功
- 营销视频克隆当前支持 Seedance2.0、Seedance2.0 Fast、Seedance2.0 Mini（seedance2.0-mini）、Seedance 2.5（seedance2.5）和 MiniMax H3 参考生视频（MiniMax H3 / minimax_h3-r2v）；白名单单一事实来源为 `config/unified_config.py::VIDEO_CLONE_DRIVER_KEYS`。用户选择普通 MiniMax H3（首尾帧）做克隆时，由 `resolve_video_clone_task_config` 自动改用 MiniMax H3 参考生视频。创建营销任务时，界面选中的视频模型会写入全部兼容 video 槽位（含 `video.reference_to_video`），`image_to_video` 工具优先使用 `model_source=request` 的快照，避免参考槽里初始化留下的 MiniMax H3 覆盖界面上的 Seedance 2.5。专家提示词必须通过 `video_urls` 传入参考视频。人脸遮盖对 Seedance 2.0 / Fast / Mini / 2.5 显示「是否处理人脸」（`SEEDANCE_FACE_MASK_DRIVER_KEYS`，不含 MiniMax H3）；克隆提示词基线**不含**「将人脸位置的黑色方框修改为真人人脸」句，该句由 seedance 系 driver 在执行时按 pipeline steps 的素材实际遮盖状态动态决定：volcengine / oversea / kkidc（消费遮盖结果，画面有黑框）自动追加，huimengi（网关 `human_review` 自动处理人脸，使用原始素材）自动移除，保证供应商轮换（跨实现方重试）下提示词与素材状态始终一致。公共逻辑位于 `task/visual_drivers/face_mask_prompt.py`，常量为 `config/constant.py::FaceMaskPromptConstants`。Seedance 2.5 克隆（带参考视频）时驱动将 `ratio` 改为 `adaptive`、`duration` 改为 `-1`，输出跟随参考视频，避免火山 `TaskTypeConstraint`。
- 本地生活营销视频（餐饮、酒旅、旅游、丽人、休闲娱乐、到店零售、生活服务等）仍走 `sop-video-generation` 并委托 `marketing-video`。此类视频推荐 10~15秒，且推荐使用 Seedance2.0、Seedance2.0 Fast、Seedance2.0 Mini（seedance2.0-mini），因为该系列更适合完整短视频叙事，并能更好表达 BGM、TTS 口播和音效
- Seedance2.0 系列是普通本地生活视频的推荐模型，不是全局硬限制。若用户当前选择其他视频模型，PM Agent 可以提醒效果差异，但不能拒绝、不得拒绝继续调用当前模型；只有视频克隆等明确限制场景才按硬限制处理
- 本地生活视频提示词由 `enterprise/skills/marketing-video/SKILL.md` 组织为画面提示词、口播旁白、BGM 与音效提示、店招/品牌文字要求；涉及中文店名、中文口播和招牌文字时可使用中文结构化提示词，避免翻译破坏品牌信息
- 本地生活视频的追问应优先收集店名、主推菜品、核心卖点和参考图片，而不是默认询问通用画风。餐饮、酒旅、旅游等场景默认真实实拍；只有用户明确要求卡通、插画、二次元等特殊表达时，才继续确认非真实风格。需要提供风格选项时，应使用 `真实探店感`、`暖色食欲感`、`高级精致感`、`烟火气市井感`、`清爽干净感` 等营销语义。
- 图生视频必须以真实上传媒体为准。用户在 `ask_user` 中选择“有参考图片”只代表意图，不代表系统已经拿到图片；只有验证回答或任务上下文中存在真实 `[图片N]（URL: ...）` 标签，或 `image_urls` 非空时，才能按图生视频委托。若 `image_urls` 为 null/空，必须提醒用户上传图片或确认改用文生视频，不得把 `https://example.com/...` 这类占位 URL 当作参考图提交。工具层的 `enterprise/tools/video_tools.py::image_to_video` 会在提交 `/api/ai-app-run-image` 前对图片 URL 做轻量级真实性校验：先拒绝示例域名占位 URL，再用短超时 HEAD 探测图片是否可访问；HEAD 不支持时退化为 Range GET 获取 1 字节，探测失败则不提交任务。
- 数字人口播缺少用户音频时，专家应调用通用 `generate_reference_audio` 生成参考音频；数字人专家不暴露角色耦合的 `generate_character_reference_audio`

### 用户偏好同步

用户在前端选择的图片模型、比例、分辨率等偏好通过 API 同步到后端 `user_preferences` 数据库表，确保跨设备/会话的一致性。

Agent 对话任务还会在 `/api/session/{session_id}/task` 入口同步本次请求携带的 `image_preferences`，避免只把“9:16”等偏好写入提示词、但专家实际调用生图工具时仍读取旧偏好。该同步只影响生成/编辑工具的输出参数，不表示上传图片必须与所选分辨率一致。分辨率缺省时按最低可用输出分辨率执行，避免为了清晰度选项反复向用户确认。LLM 调用日志会输出 `Agent` 与 `Agent scope` 字段，可在 `llm.log` 中按 `Agent scope: expert` 或具体专家 ID 筛选专家智能体；OpenAI 兼容模型返回的 `reasoning_content` 会按日志截断规则记录正文，便于排查专家决策过程。

## 灵感发布页（Inspiration）

灵感页（`/marketing-inspiration`，由 `web/marketing_inspiration.html` + `web/js/marketing_inspiration.js` + `web/css/marketing_inspiration.css` 实现）展示已审核通过的公开作品（`marketing_publications` 表），支持瀑布流浏览、Lightbox 详情、"做同款/用作参考图"（携带参数跳转到生成页），以及上传参考图直接发起 Agent 创作。后台灵感审核（`web/admin.html` 营销审核表）视频缩略图用 `max-width/max-height: 100%` + `object-fit: contain`，竖屏用 `loadedmetadata` 把容器改成真实宽高比，避免固定 96×96 + `cover` 裁掉上下。

> 首页（`web/index.html`）在营销模式下点击"开始创作"横幅（`handleStartCreation`）即跳转到本页（`/marketing-inspiration?user_id=...`），灵感页左侧导航再进入生成对话页 `/marketing-agent`。

### 发布与资产固化

用户在生成页将 `ai_tools` 记录"发布为灵感"时，`POST /api/marketing-publications` 触发 `MarketingPublicationAssetService.promote_assets`：

1. 将生成结果、参考图、参考音视频从临时缓存（`/upload/cache/...`、`/upload/temp/...`）复制到长期目录 `/upload/marketing_publications/{publication_id}/`，避免缓存过期导致链接失效。
2. 为每个固化文件创建一条 `media_file_mapping` 记录（`entity_type=6`、`policy_code=never_expire`、`label` 区分 result/reference/audio/video）。
3. 发布时写入数据库的仍是**本地路径**（`result_url`/`cover_url` 指向 `/upload/marketing_publications/...`）。

### CDN 透明加速

灵感页图片/视频统一通过 `server.py` 的 `cdn_redirect_middleware`（约第 391 行）提供 CDN 访问，前端无需感知 URL 变化：

- 浏览器请求任意 `/upload/*.{媒体扩展名}` 时，中间件按 `local_path_hash` 查 `media_file_mapping`；若记录已有 `cloud_path`，则 302 重定向到新鲜的七牛签名 URL（28 小时有效），否则直接返回本地文件。
- `promote_assets` 在创建映射后，通过守护线程 fire-and-forget 调用 `CDNUtil.trigger_cdn_upload` 触发异步上传。因发布接口为 async 端点，此处用独立守护线程而非直接调用，避免 `trigger_cdn_upload` 内部 `ThreadPoolExecutor` 阻塞事件循环（遵守 CLAUDE.md 规则 1：Web 接口不得阻塞）。
- 上传是否触发受 `server.auto_upload_to_cdn` 配置门控：未启用时只建映射不上传，中间件也直接走本地文件，行为与无 CDN 一致。

> 设计说明：**无需在 API 层（`list_public`/`to_dict`）替换 CDN URL**。这与 `ai_tools` 的处理方式一致（保持本地路径，依赖中间件透明重定向）。在 API 层每次生成签名 URL 既冗余又会绕过中间件统一的刷新逻辑。

### 做同款/参考图跳转

Lightbox 中"做同款"调用 `GET /api/marketing-inspirations/{id}/template` 获取参数快照与输入媒体（注意：模板返回的是参考图/参考视频，**不包含**生成的结果本身），再跳转到生成页；"用作参考图"将作品 URL 作为参考图带入 Agent 模式。跳转前对 `src` 做绝对 URL 判断（`/^https?:\/\//`），避免已是完整 URL 时重复拼接 `window.location.origin`。

## 文件清单

| 文件路径 | 类型 | 说明 |
|----------|------|------|
| `web/marketing_agent.html` | 页面 | 营销智能体对话页面（Vue 3 SPA） |
| `web/js/marketing_agent.js` | 脚本 | 对话页逻辑：轮询、媒体渲染、`proxyImageUrl`/`proxyDownloadUrl` 图床刷新 |
| `web/css/marketing_agent.css` | 样式 | 对话页面样式（浅色主题，约 1460 行） |
| `web/js/task_config.js` | 脚本 | 任务配置统一管理模块 |
| `web/js/video_compressor.js` | 脚本 | 前端视频压缩模块（Canvas + MediaRecorder） |
| `web/i18n/locales/zh-CN/marketing_agent.json` | 翻译 | 中文翻译文件（约 215 个键） |
| `web/i18n/locales/en/marketing_agent.json` | 翻译 | 英文翻译文件 |
| `server.py` | 路由 | `/marketing-agent` 静态页面路由（约第 8281 行）；`cdn_redirect_middleware`（约第 391 行）为 `/upload/` 媒体提供透明 CDN 重定向 |
| `api/script_writer.py` | API | 会话管理、任务创建、流式响应、文件上传等 API |
| `api/marketing_publications.py` | API | 灵感发布/审核/列表/模板等接口（`/api/marketing-publications`、`/api/marketing-inspirations`） |
| `model/marketing_publications.py` | 模型 | `marketing_publications` 表模型与查询 |
| `services/marketing_publication_asset_service.py` | 服务 | 发布时资产固化（复制到长期目录）+ 异步触发 CDN 上传 |
| `web/marketing_inspiration.html` | 页面 | 灵感瀑布流页面 |
| `web/js/marketing_inspiration.js` | 脚本 | 灵感页交互（瀑布流、Lightbox、工具栏、做同款/参考图跳转） |
| `web/css/marketing_inspiration.css` | 样式 | 灵感页专用样式 |
| `web/i18n/locales/{zh-CN,en}/marketing_inspiration.json` | 翻译 | 灵感页国际化文案 |
| `web/index.html` | 页面 | 模式选择弹窗入口 |

### 图床图片签名刷新

当 `server.auto_upload_to_cdn=true` 且 `server.is_local=false` 时，营销智能体页不会把图床图片的过期签名 URL 直接写死给 `<img>` 使用。`web/js/marketing_agent.js` 中的 `proxyImageUrl()` 会将外部 HTTP/HTTPS 图片包装为 `/api/proxy-image?url=...`；后端 `proxy_image` 接口识别 CDN 域名后重新生成签名并 302 到新鲜 URL，非 CDN 外链则使用异步 `httpx.AsyncClient` 代理读取，避免在 Web 接口中阻塞事件循环。视频结果走 `proxyDownloadUrl()` → `/api/download`，同样由后端重签名后 302。

生成结果卡片、历史 Markdown 图片/视频、以及历史中已保存的 `generated-image` HTML 都会在渲染时经过代理。这样旧会话重新打开、图床签名超时或点击放大时，媒体仍会自动走代理刷新并显示。轮询完成时若已拿到结果 URL，`hasGeneratedImageResult` / `hasGeneratedVideoResult` 只按 URL 去重，避免把日期路径里的 `/2026` 误判成已展示的任务 ID，从而把新结果从界面删掉。

## 视频分辨率选择

`web/marketing_agent.html` 在直接“视频生成”模式和 Agent 模式的视频设置区都会根据当前视频模型展示分辨率选项；状态、默认值降级和提交逻辑位于 `web/js/marketing_agent.js`。

- 选项来源优先使用 `TaskConfig.getVideoResolutionOptions(selectedModelKey)`，保证 `seedance_2_0_image_to_video`、`seedance_2_0_fast_image_to_video`、`seedance_2_0_mini_image_to_video` 等完整模型 key 能直接读取后端统一配置下发的 `supported_video_resolutions`。
- 默认值优先使用 `TaskConfig.getDefaultVideoResolution(selectedModelKey)`，无默认值时回退到模型配置缓存里的 `default_video_resolution` 或第一项。
- 普通“生成视频”底部比例设置面板在视频模式下显示视频分辨率按钮组；图片模式仍显示图片分辨率。提交视频任务时使用 `selectedVideoResolution` 作为 `resolution` 参数。
- Agent 视频对话任务会把同一分辨率写入 `video_preferences.resolution`，后端视频工具据此透传到实际 `/api/ai-app-run` 或 `/api/ai-app-run-image` 请求。
- Seedance 2.0 Fast / Mini 展示 `480P`、`720P`；Seedance 2.0 标准版展示 `480P`、`720P`、`1080P`、`4K`，具体支持范围以 `config/unified_config.py` 的实现方配置为准。

## 媒体模型偏好隔离

营销页使用 `marketing_ui` 下五个独立槽位：文生图、图片编辑、文生视频、图生视频、参考视频。当前模型下拉框会按真实输入切换槽位；选择结果通过 `GET/PUT /api/marketing/media-preferences` 持久化，不再让文生/编辑或普通/参考视频共享一个运行时模型值。

每次创建 Agent 任务时，五个槽位全部写入 `agent_tasks.execution_context_json.generation_snapshots`。工具按真实输入选槽位并强制覆盖 `task_type`，最终快照同时写入 `ai_tools.extra_config.generation_snapshot`。任务提交后再修改界面偏好不会影响运行中任务。
