# 前端 auth_token 拼 URL 收敛方案（轮询凭证迁移 + 401 自愈）

> 触发事故（2026-10-20，会话 `203d9493-6cf5-45d0-8083-d168ae355588`）：
> 营销智能体图文转视频轮询期间，localStorage 残留的失效 token 令
> `GET /api/get-status/1259,1260,1261,1262?auth_token=...` 持续 401，页面在生成
> 中途被全局 401 拦截踢到登录页，进度卡片中断，用户误以为生成失败——实际服务端
> 4 个视频全部生成成功（10:57:48~10:59:38 依次完成）。事故暴露两类问题：
>
> 1. **安全（AGENTS.md 前端安全红线 X2/X3）**：token 拼 URL 进 query，会经
>    Referer、浏览器历史、服务端访问日志（access.log 中每行轮询都是明文 token）泄漏；
> 2. **可用性**：轮询凭证是 localStorage 的 token 快照，与 HttpOnly cookie 会话
>    状态脱节（token 已失效而 cookie 有效），且 401 直接跳登录页打断生成中任务。
>
> 本文是收敛方案与分批落地记录。

## 0. 目标形态

- **浏览器页面**：同源请求不携带任何显式凭证（不拼 URL、不发 localStorage
  里的 Bearer），由服务端 `auth_cookie_translation_middleware`（server.py，仅在
  Authorization 头**为空**时注入 HttpOnly cookie 凭证）自动鉴权；
- **非浏览器客户端**（脚本/CLI）：`Authorization: Bearer <token>` 头；
- **401 兜底**：统一走 `web/js/auth_self_heal.js` 自愈，而非直接跳登录页。

⚠️ 关键约束：cookie 翻译中间件**只在 Authorization 为空时生效**。失效 token 以
非空 Bearer 头发出会压住 cookie 翻译，因此浏览器页面不能把 localStorage 的
token 挪进请求头完事——正确做法是干脆不发，让 cookie 生效。

## 1. 401 自愈模块 `web/js/auth_self_heal.js`

与 `script_writer.js` 的 `handleTokenExpired`（首个落地实现）行为对齐，抽成公共模块：

1. 并发去重（多请求同时 401 只触发一次）；
2. 清 localStorage 残留 token（`auth_token` / `token`）——失效 Bearer 会压住
   cookie 翻译，必须先清掉；
3. 裸 fetch（不带 Authorization 头）探测 `/api/user/role` 判断 HttpOnly cookie
   会话是否仍有效；
4. cookie 有效 → reload 无感自愈（重载后页面不再携带失效凭证）；**60 秒内只自愈
   一次**，防 reload 循环；
5. cookie 也失效 → 回调 `onLoginExpired`（页面跳登录页）。

另导出 `probeSession` 供页面初始化门禁复用（见下）。

## 2. 本批落地（P0：营销智能体，分支 develop_f1055）

| 改动 | 说明 |
|---|---|
| `web/js/auth_self_heal.js`（新增） | 公共 401 自愈模块，见上 |
| `web/js/marketing_agent.js` | ① 6 处 get-status 轮询删除 `params: { auth_token }`（含历史页恢复轮询）；② `checkAuthResponse` 401 改走 `handleAuth401`（自愈优先，cookie 失效才 `redirectToLogin`）；③ 注册 axios 全局 401 拦截触发自愈；④ 初始化门禁在 localStorage token 缺失时用 `probeSession` 探测 cookie 会话兜底（否则自愈 reload 后会被门禁弹回登录页） |
| `web/marketing_agent.html` | 引入 `auth_self_heal.js`（先于 marketing_agent.js） |
| `scripts/lint_frontend_xss.py` | X3 新增 params 对象形态匹配（`params: {...auth_token}` / `params = x ? {auth_token...}` / `searchParams.append`），精确锚定变量名 `params`，不误伤 JSON body / FormData 里的合法 `auth_token` 字段；未迁移页面进 `X3_ALLOWED_FILES` 过渡豁免（只减不增） |
| `web/tests/marketing_agent_poll_auth.test.js`（新增） | 回归用例：轮询不带 URL token、401 走自愈、门禁 cookie 兜底、自愈契约 |

后端不改：`/api/get-status` 等端点的 `auth_token` query 参数保留做过渡期兼容
（旧缓存 JS 仍会带 token 访问），后续批次统一下线。

## 3. 待迁移清单（P1/P2，迁移完清空 lint 豁免）

token 仍经 axios params 进 URL 的文件（`X3_ALLOWED_FILES`）：

- `web/js/index_app.js`（/api/subscription/*、recharge/packages 等 4 处）
- `web/js/pages/ai_script_gen.js`、`ai_video_gen.js`、`audio_generate.js`、
  `digital_human.js`、`image_edit.js`、`image_to_video.js`、`skill_config.js`、
  `text_to_image.js`、`video_enhance.js`（get-status / runninghub-status /
  audio-status 轮询）

P2（单端改不动，需上游配合）：`web/external_recharge.html` 从**进入 URL** 读
auth_token（外部跳转带入），需上游改一次性 code 或 postMessage，另立方案。

已知无需迁移：`web/js/api.js`（FormData body 字段，不进 URL）、
`web/js/sse_client.js`（fetch + Bearer 头实现 SSE，无 URL 传参）、
`script_writer` / storyboard 系列（此前已迁移，401 自愈的原始实现来源）。

## 4. 排查佐证（事故时间线摘要）

- 10:47:52 任务提交成功，pending 气泡写入；轮询开始 401（token 已失效）
- 10:49 前端被 401 拦截踢到登录页；10:49:49 重新登录换新 token，轮询恢复 200
- 10:57:48~10:59:38 4 个视频全部完成；10:59:41 结果卡片替换 pending 气泡
- 期间 access.log 每行轮询 URL 均含明文 token（泄漏面实证）
