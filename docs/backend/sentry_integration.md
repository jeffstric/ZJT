# Sentry 错误监控集成

## 初始化链路

`server.py` 启动时调用 `SentryUtil.init_from_env()`（`utils/sentry_util.py`），读取配置并初始化 `sentry_sdk`。SDK 为可选依赖，未安装时仅告警、不影响启动。

## 事件携带的关键信息

每次 `capture_exception` / `capture_message` / `send_alert` 上报的事件自动携带以下三组标识，用于 Sentry 后台定位问题来源：

| 字段 | Sentry 语义 | 取值来源 | 示例 |
|------|------------|---------|------|
| `environment` | Sentry 环境标识 | 动态配置 `sentry.environment` | `production` / `test` |
| `release` | 版本发布标识（后台按版本聚合 issue、区分新引入/已修复） | `pyproject.toml` `[project].version`（经 `config/version.py::get_app_version()` 读取） | `2.3.8` |
| `mode`（tag） | 运行模式，可按 tag 过滤/搜索 | `edition.mode`（经 `config/constant.py::Edition.get_mode()` 读取） | `community` / `enterprise` |

注意事项：

- `mode` 的取值不是直接读 yaml：`Edition.get_mode()` 会在 `edition.mode=enterprise` 但 `enterprise/` 目录不存在时降级为 `community`，保证上报的是**实际生效**的模式。
- `release` / `mode` 读取失败时仅记录 warning 并以空值跳过，不阻断 Sentry 初始化。
- 事件发送全程使用后台线程（见 `send_alert` 实现），Sentry 服务端不可达时不会阻塞业务调用线程。

## DSN 配置来源与优先级

动态配置读取顺序为**数据库 > 用户配置文件（如 `config_prod.yml`）> 基类配置文件（`config_prod.base.yaml`）**。

生产基线 DSN 已统一收敛在 `config_prod.base.yaml`：

```yaml
sentry:
  dsn: "https://b78e7bd086738180e4714333d8f8a88a@sentry.perseids.cn/6"
  environment: "production"
```

部署实例无需在各自 `config_prod.yml` 中再配置 DSN；若配置了则覆盖基线值。`config.example.yml` 中保留占位符，真实 DSN 不进入示例模板。

## 后台使用建议

- **按版本排查**：Issue 详情页通过 release 筛选，确认问题首次出现的版本；发布新版本后在 Releases 页对比新旧版本错误率。
- **按模式过滤**：搜索 `mode:enterprise` 或 `mode:community` 区分商业版与社区版问题（两者可用功能不同，报错面不同）。
