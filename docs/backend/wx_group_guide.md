# 官方微信群引导

注册成功后，引导用户加入智剧通官方微信群。设计目标：**低侵入、不挡主路径**。

## 配置

`config.example.yml` / `config_prod.base.yaml`：

```yaml
wx_group_guide:
  enabled: true  # 是否启用官方微信群引导（关闭后不弹出、不展示官方群入口）
  # qr_url: "https://..."  # 可选，覆盖默认二维码地址
```

| 项 | 说明 | 默认 |
|----|------|------|
| `enabled` | 总开关：注册后 soft 浮层、admin 手册附带 QR、页脚/社交区常驻入口 | `true`（`config_prod.base.yaml` 默认开启） |
| `qr_url` | 可选覆盖二维码 URL | 常量 `ExternalLinks.WX_GROUP_QR_URL` |

默认二维码：

```text
http://ailive.perseids.cn/upload/assert/wx_group.jpg
```

> **协议说明**：该官方图床目前**仅 HTTP 可访问**，使用 `https://` 会出现 `ERR_CONNECTION_REFUSED`。

### HTTPS 站点与混合内容

若部署站点本身是 **HTTPS**，浏览器会拦截页面里的 **HTTP 图片**（Mixed Content）。此时前端自动改用后端同源代理：

| 页面协议 | 配置中的二维码 URL | `<img src>` 实际使用 |
|----------|-------------------|----------------------|
| `http://` | `http://...` 外链 | 直接用外链 |
| `https://` | `http://...` 外链 | **`/api/system/wx-group-qr`**（后端 httpx 异步拉取后回传） |
| 任意 | `/files/...` 同源路径 | 直接用相对路径 |

```http
GET /api/system/wx-group-qr
```

- 非阻塞：`httpx.AsyncClient`，带连接/读取超时与体积上限  
- 内存缓存约 1 小时，减少重复外网请求  
- 引导开关关闭时返回 404  

定义位置：`config/constant.py` → `ExternalLinks.WX_GROUP_QR_URL` / `WX_GROUP_QR_PROXY_*`。

前端通过公开接口读取：

```http
GET /api/system/server-config
```

相关字段：

- `wx_group_guide_enabled`
- `wx_group_qr_url`
- `wx_group_qr_proxy_path`

## 交互流程

### 普通用户（官网 / 本地非首管）

1. 注册成功 → 自动登录  
2. 写入 `sessionStorage.pending_wx_group_guide = home_soft`  
3. 约 0.6s 后右下角 **无遮罩 soft 浮层**（可关、可「不再提示」）  
4. 「不再提示」→ `localStorage.wx_group_guide_dismissed = 1`，之后不再主动弹  

### 首个管理员（本地常见）

1. 注册成功 → `redirect_after_login=/admin?quick_config=1`  
2. 写入 `pending_wx_group_guide = admin_after_config`  
3. **中间不出现微信群遮挡**，直接进后台快速配置  
4. 快速配置保存成功后，在已有「使用手册引导」弹窗内嵌 **可选** 小尺寸 QR（不改主 CTA）  

### 待审核用户

- 审核提示文案中附带一句可加入官方群的说明  
- **不自动弹窗**  

### 常驻入口

- 页脚「官方微信群」文字链（本地 / 官网均可见）  
- 本地页脚社交图标区额外微信图标  

均打开同一二维码 modal。开关关闭时入口一并隐藏。

## 存储键

| Key | 位置 | 含义 |
|-----|------|------|
| `pending_wx_group_guide` | sessionStorage | 本次注册后待展示触点：`home_soft` / `admin_after_config` |
| `wx_group_guide_dismissed` | localStorage | 用户选择不再主动提示 |

## 与「意见反馈个人微信」的区别

| 能力 | 配置 | 说明 |
|------|------|------|
| **官方微信群**（本文） | `wx_group_guide.*` | 注册引导、页脚「官方微信群」、社交区微信群图标 |
| **意见反馈个人号** | `frontend.show_feedback_qr` / `feedback_qr_url` | 右下角「意见反馈」FAB，默认图 `/files/二维码.jpg` |

两套独立开关，互不影响。意见反馈配置详见 [frontend_ui_visibility.md](./frontend_ui_visibility.md)。

## 相关文件

| 路径 | 说明 |
|------|------|
| `config.example.yml` / `config_prod.base.yaml` | 开关 |
| `config/constant.py` | 默认 QR URL |
| `api/system.py` | `server-config` 暴露字段 |
| `web/js/index_app.js` / `web/index.html` / `web/css/index.css` | 首页 soft 浮层 + 常驻入口 |
| `web/js/admin.js` / `web/admin.html` | 配置完成弹窗附带 QR |
| `web/i18n/locales/*/index.json` / `admin.json` | 文案 |
