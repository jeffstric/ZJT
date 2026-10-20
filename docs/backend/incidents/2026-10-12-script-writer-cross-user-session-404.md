# 2026-10-12 课堂「发送消息失败」：URL 带他人 user_id 导致跨用户会话 404

## 现象

班级约 40 人同时使用系统，其中约 8 名学生在 `script_writer.html`（剧本智能创作系统）
发消息**始终**报「发送消息失败」，刷新、重试均无法恢复；其余用户正常。

## 根因链

1. `script_writer.html` 的用户身份完全取自 URL 参数（`USER_ID = urlParams.get('user_id')`），
   讲师投屏/分享的链接形如 `/script-writer?user_id=2&world_id=1`（user 2 为上课老师）。
   部分学生直接打开了该链接，页面以「user_id=2」的身份视角初始化。
2. 页面初始化调用 `GET /api/sessions?user_id=2&world_id=1&limit=1` 复用最新会话。
   **该接口当时无鉴权且信任参数 user_id**，把老师的最新会话（如 `aa50d104-…`）返回给了
   登录身份是学生自己的浏览器，前端随即把 `sessionId` 绑定为老师的会话。
3. 之后每次发消息 `POST /api/session/{sessionId}/task`，后端属主断言
   `ensure_owner`（session.user_id=2 ≠ 学生登录身份）按防枚举设计**故意返回 404
   「资源不存在」**；前端 i18n 文案未插值错误详情，用户只看到「发送消息失败」。
4. 前端对 history/task 404 无自愈逻辑，`sessionId` 永不重置 → 重试永远失败；
   兜底路径 `POST /api/session/create` 也因 body 回传 `user_id=2` 被
   `check_claimed_user_id` 以 403 user_mismatch 拒绝，同样无法自救。

日志证据（access.log，2026-10-10 ~ 10-12）：`POST /api/session/*/task` 共 53 次 404，
其中 46 次全部打在老师会话 `aa50d104-…` 上；该会话 `GET /history` 200 仅来自老师本人的
2 个 IP，404 来自 30+ 教室网段 IP；全程 0 条 `Session … not found in database`，
排除会话丢失/过期。

## 修复

| 层 | 改动 |
| --- | --- |
| 后端 | `GET /api/sessions` 挂 `@require_permission("script_session:view")`；带 `user_id` 时加 `check_claimed_user_id`（与登录身份不一致 403，不再泄露他人会话列表）；无 `user_id` 的调试路径（列出进程内全部缓存会话）仅限管理员。`SessionCreateRequest.user_id` 改为可省略（省略时以登录身份为准，与 `check_claimed_user_id` 既有语义对齐） |
| 前端 | `script_writer.js`：① 创建任务返回 404 时自愈一次——提示「会话不可用，正在新建会话...」，丢弃旧 `sessionId`、`createSession()` 重建并原样重发消息（重试带 `skipSessionRecovery` 防递归；重建失败把消息放回输入框）；② `createSession` 不再回传 URL `user_id`，会话归属一律以登录身份为准，链接带他人 user_id 时也能正常建会话 |
| i18n | zh-CN / en 新增 `status_session_recreating`、`error_session_recreate_failed` |
| 测试 | 新增 `tests/api/test_sessions_endpoint_auth.py`（401 / 403 / 200 / 调试路径管理员 / 模型可省略）；e2e `test_session.py::test_session_list` 改为带本人 `user_id` 调用 |

## 行为变化与兼容

- 打开他人 `user_id` 链接的学生：页面加载时 `/api/sessions` 返回 403 → 自动走
  `createSession`（以登录身份建会话）→ 页面可用，且不再看到他人会话；发消息不再失败。
- 正常用户（URL user_id = 本人）：无任何变化。
- 前后端需一起发布：后端先上时，带他人 user_id 的旧前端页面会从「复用他人会话（隐性错误）」
  变为「列表 403 → 走旧 createSession（body 仍带 user_id → 403）→ 页面提示创建会话失败」，
  与旧行为相比无功能回退，但不自愈；前端一起上后彻底修复。

## 后续（2026-10-20）

课堂修复只停了「建会话回传 URL user_id」。页面其余请求仍用地址栏里的 `user_id`，
别人的链接打开后身份对不上，世界和素材接口持续 403，用户停在当前页无法操作。

入口现改为：`DOMContentLoaded` 先用 `/api/user/role`（失败则用 `localStorage.user_id`）
取登录身份。与地址栏不一致时，把 `user_id` 改成登录用户并 `location.replace`；
同时去掉配套的 `world_id`（那是对方的世界）。本人链接不刷新。`/api/user/role`
的 `data.id` 即当前用户 id。

## 预防

- 前端页面身份参数（user_id）凡可与登录身份比对的，一律在入口处校验或直接不信任 URL。
- 同族待办：`PUT /session/{id}/title`、`DELETE /api/session/{id}`、`export-world` 等
  遗留弱鉴权端点见 `docs/backend/auth_unification.md` 遗留清单。
