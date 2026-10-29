# 日志敏感信息脱敏

## 目标

应用日志不得记录完整手机号、邮箱、验证码、密码、Bearer Token、JWT、
API Token、API Key、Secret、auth_token（会话 token，含 URL query 形态）
或 Authorization 凭据。

脱敏只影响日志文本，不改变接口参数、数据库字段和业务返回。

## 实时日志保护

`utils/log_sanitizer.py` 提供两层保护：

1. 进程级 `LogRecordFactory` 在日志进入 Handler 前格式化并脱敏消息，
   能覆盖 `%s` 参数、f-string 和第三方 Logger。
2. 项目统一 Handler 使用 `SensitiveDataFilter` 和
   `RedactingFormatter`，异常堆栈写入文件前会再次脱敏。

认证、注册、密码重置、短信和邮件验证码等高风险调用点还会显式调用
`mask_phone()`、`mask_email()` 或 `mask_identifier()`，形成纵深保护。

示例：

```text
13800138000          -> 138****8000
tester@example.com   -> t***r@example.com
验证码：123456       -> 验证码：<redacted>
Bearer abcdef...     -> Bearer <redacted>
auth_token=<64hex>   -> auth_token=<redacted>
```

## auth_token 键（2026-10-23，审计 BUG-R2-S2-A8-H4）

会话 token（user_tokens 64 位 hex）曾以 `?auth_token=` query 形式出现在
请求行并被默认开启的 access log 原样落盘——裸 hex 不匹配 Bearer/JWT 模式，
`_SENSITIVE_KEY_VALUE_PATTERN` 的 key 清单也已补入 `auth[_-]?token`，
请求行/参数化日志中的该键一律脱敏。存量前端（index_app.js 订阅 5 处 GET）
已同步迁移到 Authorization 头（红线14）；`pages/*.js` 轮询器与
`permission.py` 的 query 兜底为遗留兼容路径，由脱敏兜底，后续分批收口。

## 历史日志

本次改动只保护新产生的日志，不扫描、不改写、不删除历史日志。
历史日志继续按照现有运维和审计策略保留。

## 运维建议

- 日志目录仅允许服务账号和管理员读取。
- 线上日志按合规要求设置保留期，过期后安全删除。
- 日志备份必须加密，并应用与线上日志相同的访问控制和到期策略。
- 新增认证、支付、短信、邮件或外部 API 日志时，测试必须断言敏感值
  不出现在日志输出中。
- 禁止为了排障临时记录请求体、Authorization Header、完整 Token、
  密码、验证码或私钥。
