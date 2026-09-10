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

## 五、发布与兼容注意

1. **前后端需一起发布**：后端先上会以 401 打断旧前端（EventSource 裸连、无 header 请求）。
2. 外部 storyboard-agent CLI/skill 不受影响：其 `/api/agent-auth/exchange` 换取的 auth_token 同存于 `user_tokens` 表，可被装饰器解析；其调用的端点不在本次改动范围。
3. **遗留清单**（审计同族但未点名，装饰器未覆盖，仍为零鉴权或弱鉴权，后续迭代处理）：
   - `PUT /session/{id}/title`、`GET /session/{id}/latest-task`、`POST /session/{id}/model`、`GET /api/sessions`、`DELETE /api/session/{id}` 等 session 同族端点未挂装饰器；
   - `characters-files` / `scripts-files` / `locations-files` / `props-files` 文件系列、`upload-agent-*`、`export-world`、`world-upload-token`、`import-world-from-cloud`、`recharge/*` 等端点未挂装饰器（部分靠 body/query 自报 user_id）；
   - `api/marketing_publications.py` 的 `X-User-Id` 裸信任。

## 相关测试

- `tests/api/test_require_permission_auth.py`：装饰器真实现（401/注入/query 兜底/裸 token 兼容）+ 属主断言辅助。
- `tests/api/test_script_writer_auth.py`：verify_auth_token 新语义（空 token 拒绝、属主不符拒绝、DB 故障 502）。
- e2e（`auto_test/e2e/conftest.py`）自带标准 `Authorization: Bearer`，兼容。
