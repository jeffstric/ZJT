# 前端社区触点可配置（社交图标 / 意见反馈二维码）

通过 YAML 控制：

1. 首页页脚**社交平台图标**整块显示/隐藏  
2. 各页右下角**意见反馈**入口显示/隐藏，以及弹窗中的**个人微信二维码**图片地址  

**不依赖**商业版 `enterprise/`；配置与读取均在开源主仓完成。

---

## 配置

在 `config_prod.base.yaml`（生产基线默认）、`config.example.yml` / `config_prod.yml` / `config_dev.yml` 的 `frontend` 段：

```yaml
frontend:
  # 页脚社交平台图标（GitHub/Bilibili/抖音/…）。仅在 server.is_local=true 时有意义；默认 true
  show_social_icons: true
  # 右下角「意见反馈」浮动入口及个人微信二维码弹窗；默认 true
  show_feedback_qr: true
  # 意见反馈弹窗中的个人微信二维码地址（与官方微信群 wx_group_guide 无关）
  # 默认 /files/二维码.jpg；可改为 /files/你的图.jpg 或可公网访问的图片 URL
  feedback_qr_url: "/files/二维码.jpg"
```

| 键 | 类型 | 默认 | 含义 |
|----|------|------|------|
| `frontend.show_social_icons` | bool | `true` | 是否展示 index 页脚 `.local-footer` 社交图标区 |
| `frontend.show_feedback_qr` | bool | `true` | 是否展示意见反馈 FAB 及其个人 QR 弹窗 |
| `frontend.feedback_qr_url` | string | `/files/二维码.jpg` | 反馈弹窗中二维码图片地址 |

修改后需**重启服务**（或走现有配置重载流程）后生效。

### 私有化示例

```yaml
server:
  is_local: true
wx_group_guide:
  enabled: false
frontend:
  show_social_icons: false
  show_feedback_qr: false
  # 若仍展示反馈，可只换自己的图：
  # show_feedback_qr: true
  # feedback_qr_url: "/files/my_wechat_qr.jpg"
```

### 换自己的反馈微信图

1. 将图片放到 `files/`（例如 `files/my_wechat_qr.jpg`），或使用已托管的 HTTPS/HTTP 图片 URL。  
2. 配置：

```yaml
frontend:
  show_feedback_qr: true
  feedback_qr_url: "/files/my_wechat_qr.jpg"
```

3. 重启服务。

也可继续沿用默认：不改配置，直接替换仓库内 `files/二维码.jpg`（兼容旧方式）。

---

## 可见性逻辑

```text
社交图标可见  ⇔  is_local === true  AND  show_social_icons === true
意见反馈可见  ⇔  show_feedback_qr === true   （与 is_local 无关）
官方微信群    ⇔  wx_group_guide.enabled      （独立，见 wx_group_guide.md）
```

| 能力 | 配置 | 资源 |
|------|------|------|
| 页脚社交图标 | `frontend.show_social_icons` + `server.is_local` | HTML 硬编码外链 |
| 意见反馈个人微信 | `frontend.show_feedback_qr` / `feedback_qr_url` | 默认 `/files/二维码.jpg` |
| 官方微信群引导 | `wx_group_guide.*` / branding | 远端群图 / 品牌定制 |

**禁止混用**：关闭 `wx_group_guide` 不会隐藏意见反馈；关闭 `show_feedback_qr` 不影响官方群引导。

---

## 公开 API

```http
GET /api/system/server-config
```

成功时 `data` 新增字段：

| 字段 | 类型 | 缺省（键缺失） |
|------|------|----------------|
| `show_social_icons` | boolean | `true` |
| `show_feedback_qr` | boolean | `true` |
| `feedback_qr_url` | string | `/files/二维码.jpg` |

实现位置：`api/system.py`（`_is_show_social_icons` / `_is_show_feedback_qr` / `_get_feedback_qr_url`）。  
默认图常量：`config/constant.py` → `ExternalLinks.FEEDBACK_QR_URL`。

前端失败或旧后端缺字段时：**回退为开启 + 默认图**，避免社区入口意外消失。

---

## 页面覆盖

| 页面 | 社交图标 | 意见反馈 |
|------|----------|----------|
| `web/index.html` + `js/index_app.js` | ✅ | ✅ |
| `web/marketing_agent.html` + `js/marketing_agent.js` | — | ✅ |
| `web/video_workflow.html` + `js/events.js` | — | ✅ |
| `web/video_workflow_list.html` + `js/video_workflow_list.js` | — | ✅ |
| `web/script_writer.html` + `js/script_writer.js` | — | ✅ |
| `web/storyboard.html` | — | 当前无反馈 FAB（no-op） |

关闭时优先不渲染 / 隐藏入口 DOM，避免仅 CSS 隐藏仍可误触。

---

## 相关文件

| 路径 | 说明 |
|------|------|
| `config.example.yml` / `config_prod.yml` / `config_dev.yml` | YAML 键 |
| `config/constant.py` | `ExternalLinks.FEEDBACK_QR_URL` |
| `api/system.py` | `server-config` 下发 |
| `docs/video_workflow_feedback.md` | 工作流反馈 UI 细节 |
| `docs/backend/wx_group_guide.md` | 官方群（勿与本能力混淆） |
