# 前端静态资源版本号（`?v=`）

> 统一说明 HTML 中静态资源（js / css）引用如何携带版本号，以及 `__VERSION__` 占位符的替换机制。

## 背景

前端各类 `js` / `css` 引用希望带上版本号，以便发版后强制浏览器刷新缓存。HTML 模板中常见的写法：

```html
<script src="/i18n/i18n-core.js?v=__VERSION__"></script>
<link rel="stylesheet" href="/i18n/i18n-switcher.css?v=__VERSION__" />
```

其中的 `__VERSION__` 是**占位符**，必须由后端在返回 HTML 时替换为真实版本号，而不是原样输出字符串。

## 版本号来源

- 版本号统一定义在项目根目录的 [`pyproject.toml`](../pyproject.toml) 中：
  ```toml
  [project]
  version = "1.9.2"
  ```
- 读取入口：[`config/version.py::get_app_version()`](../config/version.py)，带缓存，返回形如 `1.9.2` 的真实版本字符串。
- `server.py` 启动时通过 `STATIC_VERSION = get_app_version()` 获取该值，供 HTML 处理逻辑使用。

> 历史问题：早期 `server.py` 自行读取 `pyproject.toml` 并生成 MD5 hash 作为版本号，导致 URL 中出现的是 hash 而非真实版本号，且开发模式下 `__VERSION__` 不会被替换、原样泄露。已修正为直接使用真实版本号。

## 替换机制

HTML 由 [`server.py::_get_processed_html()`](../server.py) 统一处理后返回。所有 HTML 路由（`/video-workflow`、`/video-workflow-list`、`/marketing-agent`、`/index` 等，以及 SPA 兜底路由）都会经过该函数。处理步骤：

1. **无条件替换 `__VERSION__` 占位符**
   无论是否开启 `cache_bust`，都会执行：
   ```python
   if "__VERSION__" in content:
       content = content.replace("__VERSION__", STATIC_VERSION)
   ```
   保证开发模式（`cache_bust.enabled: false`）下也不会泄露 `?v=__VERSION__` 这种占位字符串。

2. **cache_bust 开启时的自动版本化**（生产模式 `cache_bust.enabled: true`）
   - 对所有本地 `/js/`、`/css/`、`/i18n/` 开头的 `js`/`css` 引用自动追加 `?v={STATIC_VERSION}`（已有 `?v=` 参数会先移除再统一添加，避免重复）。
   - 注入 `window.__STATIC_VERSION`，供 JS 动态 `fetch`（如 i18n `locales/*.json`）做缓存失效。

两种模式最终都把 i18n 等显式写出的 `?v=__VERSION__` 解析为真实版本号，例如：

```
/i18n/i18n-core.js?v=__VERSION__   →   /i18n/i18n-core.js?v=1.9.2
```

## cache_bust 配置

| 环境 | 配置 | 行为 |
|------|------|------|
| 开发 `config_dev.yml` | `frontend.cache_bust.enabled: false` | 不自动版本化其余资源，对静态资源返回 `no-cache` 头；仅替换 `__VERSION__` 占位符 |
| 生产 `config_prod.base.yaml` | `frontend.cache_bust.enabled: true` | 自动给本地 js/css 加版本号并缓存处理后结果 |

## 发版缓存失效

更新 `pyproject.toml` 中的 `version` 后，重启服务即可让所有带版本号的 URL 变化，浏览器缓存随之失效。

## 注意事项

- `__VERSION__` 仅作为版本占位符使用，不要用于其它含义。
- 新增前端静态资源引用时，本地资源（`/js/`、`/css/`、`/i18n/`）无需手写版本号；如需显式指定，使用 `?v=__VERSION__` 占位符，由后端统一替换。
- 真实版本号统一通过 `config/version.py::get_app_version()` 获取，避免在多处重复解析 `pyproject.toml`。
