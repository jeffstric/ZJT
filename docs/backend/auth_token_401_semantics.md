# 登录 Token 与 401 语义约定

## 背景

- 登录 token 存于 MySQL `user_tokens` 表（`model/user_tokens.py`），校验只读（`expire_time > NOW()`），失败不删记录。
- **单会话策略**：每次密码登录先删该用户全部旧 token 再写新 token（`perseids_server/services/auth_service.py:118`）。同账号在别处登录后，旧客户端持有的 token 随即失效（"顶号"），其下一次请求收到 401 属**正确行为**。
- token 固定 30 天有效期，无续期机制。
- `perseids_server/client.py` 的 `make_perseids_request` / `async_make_perseids_request` 是**进程内本地路由**（无 HTTP 层），历史上只能靠 message 文案匹配（`'token' in message`、裸 `'认证' in message`）判定 token 失效，算力不足/限额/服务异常等错误因此被误报为"登录过期"，进而触发前端清除共享 localStorage，导致全站登出。

## 内部 error_code 打标机制（源头打标，下游只查 code）

常量定义于 `config/constant.py`：

| 常量 | 值 | 含义 |
|---|---|---|
| `PERSEIDS_ERR_INVALID_AUTH_TOKEN` | `INVALID_AUTH_TOKEN` | `AuthService.verify_token` 未通过，token 确证无效 |
| `PERSEIDS_ERR_NO_VALID_TOKEN` | `NO_VALID_TOKEN` | 按 user_id 查不到有效 token（被顶号/登出/重置密码），确证无效 |
| `ERROR_CODE_TOKEN_EXPIRED` | `TOKEN_EXPIRED` | 对前端响应：token 确证失效 |
| `ERROR_CODE_AUTH_SERVICE_UNAVAILABLE` | `AUTH_SERVICE_UNAVAILABLE` | 对前端响应：认证服务自身故障（非 token 问题） |

产出点：
- `perseids_server/client.py`：所有 `verify_token` 失败的返回，第三元素携带 `{'error_code': INVALID_AUTH_TOKEN}`。
- `perseids_server/services/auth_service.py` `get_auth_token_by_user_id`：`'未找到有效的token'` 时产出 `NO_VALID_TOKEN`，由 `client.py` 透传；`'查询token失败'`（DB 异常）不打标，归服务故障。

**下游判定只查 `error_code`，禁止再做 message 文案匹配**（`api/script_writer.py` 的 `verify_auth_token` / `check_computing_power`、`server.py` `/api/user/computing_power` 均已改为该模式）。

## 对外 401/502 语义分级

| 场景 | HTTP | error_code | 前端预期行为 |
|---|---|---|---|
| 未携带 token | 401 | `missing_auth_token` | 本地有 token 则不清不跳（误报保护）；无 token 才跳登录 |
| token 确证失效 | 401 | `invalid_auth_token` / `TOKEN_EXPIRED`（+`token_expired: true`） | 清 localStorage + 跳登录 |
| 认证服务故障 | 502 | `AUTH_SERVICE_UNAVAILABLE` | 普通服务异常提示，**不清 token 不跳登录** |
| 算力/限额/其他业务错误 | 400 | 无 | 普通错误提示 |

## 前端处理约定

- `web/js/storyboard/api.js`：
  - `authHeaders` 每次请求**现读** `localStorage.getItem('auth_token')`（`state.authToken` 仅兜底），避免模块级捕获的旧 token 在多标签页重登录后仍被轮询使用；
  - `handleAuthError` 按上表分级：确证失效才清存储并跳 `/?login=1`；缺 token/未知 401 且本地有 token 时按普通错误处理。
- `web/js/index_app.js`：`login=1` 不再无条件清 localStorage；本地有 token 时调用 `verifyAuthTokenOnLoginEntry()` 主动校验（`GET /api/user/computing_power`，只带 Authorization 不带 X-User-Id），确证失效才清 5 个 key（auth_token/phone/email/user_id/invite_code，各清除点 key 集合统一）并弹登录框。
- `web/js/admin.js`：仅 401 清 token；403（已登录但非管理员）只跳转，保留登录态。
- `web/js/script_writer.js` `checkTokenExpired`：其接口的 401 现在只在确证失效时返回，原有处理无需变更。

## 已知行为缺口

- `/api/user/computing_power` 在 token 确证失效时，若请求带 `X-User-Id` 头会走本地兜底返回 200 + 本地算力（`server.py:2480-2500`），**会掩盖 401 信号**——单会话策略下"被顶号"无法靠算力轮询检测。属有意保留的产品行为；前端做主动 token 校验时不得携带 `X-User-Id`。

## 相关测试

- 后端：`tests/api/test_script_writer_auth.py`（401 分类、文案误报回归、源头打标透传）。
- 前端：`web/tests/storyboard_api_auth.test.js`（handleAuthError 分级）、`web/tests/index_login_token_verify.test.js`（login=1 主动校验约定）。
