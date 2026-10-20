# 统一鉴权与属主校验方案（P0 安全审计修复）

## 背景

安全审计发现一组 P0 级零鉴权端点：`@require_permission` 装饰器为空实现（打印日志后直接放行），叠加端点内部不做属主校验，导致匿名用户可凭 task_id/session_id/record_id 读写任意用户数据（SSE 任务流、会话端点群、sync-files/submit-to-database、ai-tools history/detail/timeline）。

本方案三层修复：**认证层**（我是谁）→ **授权层**（我能碰谁的资源）→ **客户端适配**。无数据库改动。

## 一、认证层：require_permission 真实现

`perseids_server/utils/permission.py`：

- `require_permission`：解析 `Authorization: Bearer <token>`（缺失/无效 → 401），通过后把 user_id 注入 `request.state.user_id`。权限点字符串保留但暂映射为"登录即可"（`UsersModel` 仅 user/admin 两角色，权限表体系后续迭代）。
- **query 兜底**：header 缺失时回退 `?auth_token=` 查询参数，兼容存量前端调用（校验强度与 header 一致；新代码一律用 header）。
- `admin_required`：登录校验 + `role == 'admin'` 判定。
- `has_permission` / `get_user_permissions`：保留 TODO，待权限表落地。

## 二、身份解析与属主断言辅助

实现提升到底层包 `perseids_server/utils/auth_identity.py`（`api/auth_identity.py` re-export，既有调用点零改动）：

| 辅助 | 用途 |
|---|---|
| `resolve_authorization_user_id(value)` | Bearer（兼容裸 token）→ `(user_id, 401响应)`，走 `UserTokensModel.get_user_id_by_token`（带过期检查） |
| `get_auth_user_id(request)` | 读装饰器注入的 `request.state.user_id` |
| `ensure_owner(entity_user_id, auth_user_id)` | 属主断言，str/int 归一化比较，不符返回 **404**（防枚举） |
| `check_claimed_user_id(claimed, auth_user_id)` | body/query 携带的 user_id 与登录身份比对，不符返回 **403**；空值放行（以登录身份为准） |

## 三、授权层：端点逐一修复

### script_writer.py

| 端点 | 修复 |
|---|---|
| `GET /task/{task_id}/stream` | 属主断言（`agent_tasks.user_id`，不符 404）；同步 `task_exists` 改 `asyncio.to_thread` |
| `GET /task/{task_id}/status` | 同上 |
| `GET /session/{id}/history`、`POST clear/compress`、`PUT history`、`POST message` | 会话属主断言（`chat_sessions.user_id`，不符 404） |
| `POST /session/{id}/task` | 会话属主断言 |
| `POST /session/create` | body.user_id 与登录身份比对（不符 403）；token header 优先、body 兜底 |
| `POST /sync-files` | 补挂装饰器；user_id 一律以 token 为准；隔离空间下校验 world 属主 |
| `POST /submit-to-database` | 同上 |
| `POST /session/clear-directory` | 删除（TODO 空实现，无调用方） |

### storyboard.py

- `GET /agent-task/{task_id}/stream`：属主断言（原实现连任务存在性检查都没有）。

### server.py（ai-tools）

- `GET /api/ai-tools/history`：删除 `user_id: Query(...)` 客户端自报，改用登录身份。
- `GET /api/ai-tools/detail/{record_id}`：删除可缺省 `X-User-Id` 头逻辑（原实现缺省时跳过检查），强制属主断言，不符 404。
- `GET /api/ai-tools/{ai_tool_id}/timeline`：删除 query 弱信任回退（`user_id`/`auth_token` 参数），一律 header token；admin 放行保留。

### verify_auth_token 重写（api/script_writer.py）

旧实现两大弱点：空 token 直接放行；只按 user_id 查"该用户是否存在有效 token"，不校验调用者出示的 token 属主（任何人持自己的 token 可冒任意 user_id）。

新实现（纯本地，不再走 `get_auth_token_by_user_id` 远端查询）：

- 空/缺失 token → 401 `TOKEN_EXPIRED`（不再放行）；
- `UserTokensModel.get_user_id_by_token(token)` 查不到（无效/过期/被顶号）→ 401 `TOKEN_EXPIRED`；
- **token 属主 ≠ 声明 user_id** → 401 `TOKEN_EXPIRED`；
- 本地 DB 异常 → 502 `AUTH_SERVICE_UNAVAILABLE`（不误报 token 失效）。

单会话顶号语义不变：顶号后旧 token 被删，本地查询即失败。

## 四、客户端适配

### SSE 改造（EventSource 无法带 header）

新增 `web/js/sse_client.js`：fetch + ReadableStream 实现（参考 `web/js/storyboard/api.js` 的 `streamStoryboardAgentTask`），接口 `SSEClient.createEventStream(url, {onMessage, onError, onClose}, {lastId})`。

替换 4 处裸 EventSource：`script_writer.js`（主流程、`reconnectSSE`、ask_user 测试弹窗）、`marketing_agent.js`（`handleStream`）。事件语义（connected/message/progress/tool_call/done/error/heartbeat）不变；服务端 401 时 fetch 返回非 2xx → onError → 走既有的 `checkTaskStatus` 重连/降级路径。

### Authorization header 补齐

- `script_writer.js`：create、task、status、sync-files、submit-to-database。
- `marketing_agent.js`：create、task、status；全文件 20 处裸 token（无 Bearer 前缀）统一加 `Bearer `（服务端 `normalize_authorization_token` 两者兼容）。
- ai-tools 7 个工具页（text_to_image/image_edit/video_enhance/ai_video_gen/digital_human/ai_script_gen/image_to_video）history 查询 + `index.html` timeline 弹窗：query `auth_token` → header。
- storyboard 前端 SSE 已带 Bearer，无需改动。
- `script_writer.js`（2026-09-15 补丁）：文件系列端点（`world-files` / `characters-files` / `scripts-files` / `locations-files` / `props-files`）约 13 处 `fetch` 原本不带 `Authorization` 头（POST 保存仅把 `auth_token` 放 body，装饰器不读 body），后端真鉴权上线后返回 401 → 前端 `checkTokenExpired` 把**任何** 401 都当 token 过期 → 整页跳登录页（e2e `test_script_writer.py` 批量失败）。已全部补 `Authorization: Bearer ${AUTH_TOKEN}` 头。
- `DELETE /api/staging-file`（2026-10-16）：右侧暂存栏的角色卡、场景、道具、剧本删除是同一个按钮函数 `deleteStagingFile()`，都打到这个接口，只带 `Authorization` 头，不把 token 放进 URL。该接口曾把 `auth_token` 设为必填 query，四类删除在进函数前都被 FastAPI 打成 422 `Field required`（`loc: ["query", "auth_token"]`），函数体内也从未读取这个参数。已去掉 query 必填，登录身份仍由 `require_permission` 从 Authorization 头解析，query `user_id` 必须与登录用户一致。
- 同族漏头补丁（2026-09-15，e2e 复现定位）：
  - `marketing_agent.js`：`GET /api/session/{id}/latest-task`（页面刷新恢复活跃任务流）裸 `fetch` 无头，401 → 整页跳登录（e2e `test_marketing_agent.py` 29 例批量失败）。已补 `Authorization: Bearer`。
  - `workflow.js`：`GET /api/computing-power-config`（驱动状态，TaskConfig 主路径与回退路径共 2 处）裸 `fetch` 无头，401 导致驱动状态/模型选项加载失败（e2e `test_node_operations.py` 模型/时长选项为空）。已补 `Authorization: Bearer`（`getAuthToken()`）。
  - `events.js`：`GET /api/config/upload`（上传大小配置）裸 `fetch` 无头。已补 `Authorization: Bearer`（`getAuthToken()`）。

### 视频工作流生图/生视频提交端补齐（2026-10-11，宫格生图 401 事故）

用户宫格生图一直提示"提交任务失败"的根因：`nodes.js` / `script_node.js` 等的提交请求是裸 `fetch`（`appendAuthToForm` 只把 `auth_token` 放 FormData，装饰器不读 body），完全依赖 cookie 翻译；cookie 会话失效（localStorage token 仍有效、页面看似登录态）即 401，而 401 响应体无 `detail`/`message` 字段，前端兜底文案退化为"提交任务失败"。

- `api.js` 新增统一封装并导出：
  - `authPostForm(url, form)`：带 `Authorization: Bearer <localStorage token>` 头 POST FormData（token 不拼 URL，遵守 XSS/凭据红线）；
  - `extractApiErrorMessage(data, res)`：优先 `detail`/`message`，401 时返回"登录已过期，请保存当前内容后重新登录"。
- 9 个文件 18 处"提交任务"裸 `fetch` 全部改走 `authPostForm`（宫格生图、分镜图、全景图、运镜控制、图片节点、镜头组视频、分镜视频、数字人）：
  - `/api/image-edit`、`/api/text-to-image`：`nodes.js`（宫格 + 镜头组视频）、`script_node.js`（3 处宫格流程）、`shot_frame_generator.js`（2 处）、`camera_control_node.js`、`panorama_node.js`、`workflow.js`（图片节点）；
  - `/api/ai-app-run-image`、`/api/ai-app-run`：`api.js`（2 处）、`shot_frame_video_generator.js`（3 处）、`nodes.js`（3 处镜头组视频）、`digital_human_node.js`。
- 后端 `perseids_server/utils/auth_identity.py`：401（missing/invalid token）与 403（user_mismatch）响应体补 `detail` 字段（"登录已过期/失效，请保存当前内容后重新登录"），前端按 `data.detail` 展示，旧前端新后端组合下也不再显示含糊的"提交任务失败"。
- 用户侧恢复方式：重新登录一次重置 cookie 即可。

### 服务端内部回环调用适配（script_writer Agent 工具）

`script_writer_core/mcp_tool.py` 的 Agent 工具用 httpx 回环调用本服务受保护端点，原实现只把 `auth_token` 放 form 字段，而 `require_permission` 只认 header/query，导致鉴权真实现上线后稳定 401（典型表现：角色形象设计反复报 "401 Unauthorized" 并向用户提问）。已在 4 处 `httpx.post` 补 `Authorization: Bearer <token>` 头（token 为空则不加头，保持原行为；红线禁止 token 拼 URL，不走 query 兜底）：

- `generate_text_to_image` → `POST /api/text-to-image`
- `edit_image` → `POST /api/image-edit`
- `generate_digital_human` → `POST /api/digital-human`
- `submit_grid_image_task`（宫格 i2i）→ `POST /api/image-edit`

视频工具同根因（marketing_agent / storyboard 视频生成 401）：`enterprise/tools/video_tools.py` 的 `generate_text_to_video` → `POST /api/ai-app-run`、`image_to_video` → `POST /api/ai-app-run-image`，同样只把 `auth_token` 放 form 字段，已补 Bearer 头。

场景多角度同根因（2026-10-08）：`task/location_multi_angle_task.py` 调度器回环 `POST /api/image-edit` 只把任务快照 `auth_token` 放 form 字段，`require_permission` 返回 `Authorization is required`。每个角度重试 3 次后被跳过，终态变成「所有角度生成失败，共完成 0/N 个」。已补 `Authorization: Bearer` 头（快照为空不加头，不走 query）。

故事板导出下载（2026-10-08）：`<a href="/api/download">` 带不上 `Authorization`，中间件用 HttpOnly cookie 填头。管理端切换用户只改 `localStorage`，cookie 里的旧 token 失效后下载返回 `invalid_auth_token`，其余接口仍 200。故事板改为 `fetch /api/download?format=json`（Bearer 头，URL 不带登录 token），CDN 重签名地址放在 JSON 的 `redirect_url`，再由浏览器跳到该 CDN 地址下载。未带 `format=json` 的 302 / 本地文件 / 外部代理保持原样。工作流视频/语音/图片下载、营销页放大图，以及首页独立工具页（文生图、图片编辑、图生视频、视频生成、剧本生视频、数字人、语音、视频增强）的下载按钮，都走同一约定（`web/js/download_attachment.js`）。`<video>` / `<audio>` 播放仍用 `proxyDownloadUrl` 的 302，媒体标签带不上自定义头。

画布音频生成同根因（2026-10-14）：`dialogue_group_node.js`（对话组节点"生成对话音频"）与 `text_to_speech_node.js`（TTS 节点）的 `POST /api/audio-generate` 只把 `auth_token` 放 FormData（服务端 `require_permission` 不读 form 字段，签名里的 `auth_token: Form(None)` 是从未被使用的死参数），裸 `fetch` 无 Authorization 头时中间件回退用 cookie 填头；cookie 残留失效 token（多实例/多标签页共享 localhost cookie 但各持不同 token 时尤其常见）即报 `invalid_auth_token`，而画布其余带头的请求全部正常——用户困惑点正是"能进画布为什么这个按钮 401"。已改为 `Authorization: Bearer`（与 `panorama_node.js` 等节点一致），form 里的 `auth_token` 字段删除。
`format=json` 的外链降级（2026-10-09）：`format=json` 只对 CDN URL 返回 `redirect_url`；非 CDN 外链（小红书图床、任务缓存失败回退的厂商原始 URL 等）无法签名时不再 400，直接落到代理流式下载（200 + 文件流），前端 `downloadWithAuth` 对非 JSON 响应按 blob 保存——外链下载不因统一改造从"能下"变"必败"（回归见 `tests/api/test_download_format_json.py::test_format_json_non_cdn_falls_back_to_proxy_stream`）。

> 注（2026-09-16 落地确认）：上文对 video_tools 的修补实际从未提交进 enterprise 仓库（当时仅改了 `script_writer_core/mcp_tool.py` 4 处），storyboard 智能体批量/单场视频生成因此持续 401（`require_permission` 只认 Authorization 头 / query，form 字段不过鉴权）。本次已真正补上两处 `httpx.post` 的 `Authorization: Bearer` 头（token 为空不加头），并同步加 `trust_env=False` 防代理环境变量劫持内部回环；回归见 `tests/agents/test_video_tools_resolution.py::test_*_sends_bearer_header`。

## 五、发布与兼容注意

1. **前后端需一起发布**：后端先上会以 401 打断旧前端（EventSource 裸连、无 header 请求）。
2. 外部 storyboard-agent CLI/skill 不受影响：其 `/api/agent-auth/exchange` 换取的 auth_token 同存于 `user_tokens` 表，可被装饰器解析；其调用的端点不在本次改动范围。
3. **遗留清单**（审计同族但未点名，装饰器未覆盖，仍为零鉴权或弱鉴权，后续迭代处理）：
   - 注：`GET /api/sessions` 已挂 `require_permission("script_session:view")` 并加 `check_claimed_user_id`（2026-10-12，含无 user_id 调试路径仅限管理员；`SessionCreateRequest.user_id` 同步改为可省略，省略时以登录身份为准，见 `docs/backend/incidents/2026-10-12-script-writer-cross-user-session-404.md`）；
   - `PUT /session/{id}/title`、`DELETE /api/session/{id}` 等 session 同族端点未挂装饰器（`latest-task`、`POST /session/{id}/model` 已挂 `require_permission`）；
   - `export-world`、`world-upload-token`、`import-world-from-cloud`、`recharge/*` 等端点未挂装饰器（部分靠 body/query 自报 user_id）；
   - 注：`upload-agent-image` / `upload-agent-audio` / `upload-agent-video` 已挂 `require_permission`（2026-09-15 确认）；前端 6 处裸 `fetch`（`marketing_agent.js` 5 处 + `marketing_inspiration.js` 1 处，原先仅把 `auth_token` 放 FormData）已补 `Authorization: Bearer` 头，否则上传 401 → `checkAuthResponse` 整页跳登录（e2e `test_marketing_agent_image_upload` 失败根因）；
   - 注：`world-files` / `characters-files` / `scripts-files` / `locations-files` / `props-files` 文件系列已在 58e459fb 挂 `require_permission`（含 GET/POST/PATCH），前端缺头问题已按上文补齐；
   - `api/marketing_publications.py` 的 `X-User-Id` 裸信任。

## 五、X-User-Id 防冒充收口（"伪主人"漏洞修复，2026-10-20）

### 漏洞

一批接口（`/api/worlds*` 全族、storyboard、script_split 等，6 个文件 110+ 处）只读
`X-User-Id` 自报头认定身份，从不校验 `Authorization` token 属主：任何人不带 token
（或持自己的 token）把 `X-User-Id` 改成他人即可删改他人资源。前端的 `user_id` 来自
URL 参数，切号后旧标签页仍带旧 `user_id`，天然"串号"。

### 修复（三层）

1. **统一身份解析助手** `utils/resource_access.py::resolve_authenticated_user_id(auth_token, claimed_user_id)`：
   user_id 唯一可信来源是 token 解析结果；token 缺失/无效 → 401；自报头与 token
   属主不一致 → 401。
2. **`/api/worlds*` 全部 7 个接口**（list/get/create/update/hide/restore/delete）改用
   该助手，权限校验全部基于 token 属主。
3. **全站一致性中间件** `x_user_id_consistency_middleware`（核心逻辑
   `utils/resource_access.py::enforce_x_user_id_consistency`，独立可单测）：凡携带
   `X-User-Id` 的 `/api/` 请求，必须持有有效 token 且属主一致——
   缺失 `401 missing_auth_token`、失效 `401 invalid_auth_token`、不一致
   `401 user_mismatch`。cookie 会话由 `auth_cookie_translation_middleware` 翻译注入，
   本中间件同时直接兜底读 `AUTH_COOKIE_NAME`，与执行顺序无关。未携带 `X-User-Id`
   的请求不受影响（公公开端点、require_permission 端点行为不变）。
   `api/script_split.py::_resolve_request_identity` 同步去掉"token 失效回退
   X-User-Id"旧路径，与中间件同语义。

### 前端适配

`web/js/script_writer.js`：`401 + error_code=user_mismatch` 走独立分支
`handleUserMismatch()`——token 本身有效，不能清 token 跳登录页（redirect_url 会原样
带回旧 user_id 形成 401 回环），改为提示后回首页按当前登录账号重新进入。

### 兼容注意

- 正常前后端（Authorization 与 X-User-Id 同源）不受影响；e2e conftest 默认头一致，兼容。
- 例外行为确认无冲突：`/api/user/computing_power` 的 X-User-Id 本地算力兜底仅发生在
  本地 token 有效、上游 perseids 失效的路径（见 auth_token_401_semantics.md），中间件放行。
- 遗留清单中 `api/marketing_publications.py` 的 X-User-Id 裸信任由中间件全局覆盖。

## 相关测试（本次新增/更新）

- `tests/api/test_x_user_id_consistency.py`（新增，14 例）：助手与中间件全矩阵
  （无 token/失效/不一致/一致/cookie 兜底，非 /api 与无头放行）。
- `tests/storyboard/test_script_split_api.py`：X-User-Id-only 用例全部改带一致 token；
  "token 覆盖冲突 header""失效 token 回退"两例反转为 401 防线用例。
- `tests/api/test_script_split_resume.py`：autouse fixture mock token 解析 + save_field。
- `auto_test/e2e/test_script_split.py::test_owner_isolation_query_task`：伪造
  X-User-Id + 失效 token 预期从 403/404 改为 401（中间件拦截）。

## 相关测试

- `tests/api/test_require_permission_auth.py`：装饰器真实现（401/注入/query 兜底/裸 token 兼容）+ 属主断言辅助 + 401 响应体 `detail` 字段断言（2026-10-11）。
- `web/tests/api.test.js`：`authPostForm`（Bearer 头/空 token 无头）与 `extractApiErrorMessage`（detail 优先/401 重新登录引导）单测（2026-10-11）。
- `tests/api/test_script_writer_auth.py`：verify_auth_token 新语义（空 token 拒绝、属主不符拒绝、DB 故障 502）。
- `tests/api/test_sessions_endpoint_auth.py`：`GET /api/sessions` 鉴权收紧（未登录 401、user_id 不一致 403、本人 200、调试路径仅管理员、SessionCreateRequest.user_id 可省略）。
- e2e（`auto_test/e2e/conftest.py`）自带标准 `Authorization: Bearer`，兼容。
- e2e `test_auth.py::test_logout_success`（2026-09-15 修正）：单会话策略下 `test_login_success` 的次账号登录会顶掉 session 级 `secondary_auth_token`，故登出用例改为用例内新登录拿 fresh token 再登出。
