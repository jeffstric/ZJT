# 本站公告（用户通知）功能

## 概述

管理员在 `/admin` 后台「公告管理」页配置本站公告（如"智剧通9月征稿"、"智剧通新增订阅功能"），用户在首页（index.html）通过头部铃铛查看。

与既有 `notifications` 表（`services/notification_service.py` 从远程官方服务器定时拉取的全局公告，`is_read` 为全局共享、无 user 维度、无图片）**相互独立**：

| | 本站公告（本功能） | 系统通知（远程拉取） |
|---|---|---|
| 表 | `announcements` + `announcement_reads` | `notifications` |
| 来源 | 本站管理员后台创建 | 远程服务器 `REMOTE_API_BASE/notifications/check` |
| 已读语义 | 每用户独立（announcement_reads 表） | 全局共享（is_read 字段） |
| 内容 | 文字 + 链接 + 图片（多张） | 文字 + 链接（extra_data） |
| 用户端入口 | 首页铃铛「公告」分区 | 首页铃铛「系统通知」分区 + /admin 通知中心 |

## 数据库

迁移：`alembic/versions/no_129_20260906_add_announcement_tables.py`（挂在 head `20260905_ai_audio_speed`）。

### announcements

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int AI PK | |
| title | varchar(200) NOT NULL | 标题 |
| content | text | 正文（纯文本，前端按 `white-space: pre-wrap` 渲染，防 XSS） |
| link_url | varchar(500) NULL | 跳转链接（必须 http/https 或由上传产生的相对路径） |
| link_text | varchar(100) NULL | 链接展示文字 |
| images | text | 图片 URL JSON 数组（`/upload/announcement/...` 相对路径） |
| level | varchar(16) | info / success / warning / error |
| status | varchar(16) | draft / published / offline |
| publish_at | datetime NULL | 定时发布，NULL=立即；到点自动生效（查询条件 `publish_at <= NOW()`） |
| expire_at | datetime NULL | 失效时间，NULL=长期；过期自动不展示（查询条件 `expire_at > NOW()`） |
| created_by | int NOT NULL | 创建人 users.id |
| created_at / updated_at | datetime | |

### announcement_reads

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int AI PK | |
| announcement_id | int NOT NULL | 公告 ID |
| user_id | int NOT NULL | 用户 ID |
| read_at | datetime | |

约束：`UNIQUE KEY uk_announcement_user (announcement_id, user_id)`（幂等去重），`KEY idx_user_id`。

## 接口

响应统一 `{code: 0, data}`；所有 async 端点内同步 DB 调用均经 `asyncio.to_thread` 包裹。

### 用户侧（需登录，Authorization: Bearer <auth_token>）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/announcements?limit=50` | 有效公告列表（published + 发布窗口内），每条带 `is_read`（LEFT JOIN） |
| GET | `/api/announcements/unread-count` | 未读数（铃铛徽标，前端 60s 轮询） |
| POST | `/api/announcements/read-all` | 全部已读（INSERT IGNORE SELECT 有效公告） |
| POST | `/api/announcements/{id}/read` | 单条已读（INSERT IGNORE 幂等） |

### 管理侧（require_admin：token → users.role == 'admin'）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/admin/announcements` | 创建（status: draft / published，支持定时发布） |
| GET | `/api/admin/announcements/list?page=&page_size=` | 全量分页（含草稿/已下线） |
| PUT | `/api/admin/announcements/{id}` | 编辑内容（状态走 publish/offline） |
| POST | `/api/admin/announcements/{id}/publish` | 发布（draft/offline → published） |
| POST | `/api/admin/announcements/{id}/offline` | 下线（published → offline） |
| DELETE | `/api/admin/announcements/{id}` | 删除（级联清理已读记录） |
| POST | `/api/admin/announcements/upload-image` | 公告图片上传（multipart `file` 字段） |

图片上传规则：仅 `image/*` 且扩展名 ∈ jpg/jpeg/png/gif/webp，单张 ≤10MB（`config/constant.py: AnnouncementConstants`）；保存至 `upload/announcement/<yyyyMM>/`，返回相对 URL（同源可用，自动享受 `/upload/` CDN 中间件）。

## 代码位置

- 模型：`model/announcements.py`、`model/announcement_reads.py`（末尾含 CREATE_TABLE_SQL）
- 服务：`services/announcement_service.py`（字段校验 / 状态机 / 级联删除）
- 路由：`api/announcements.py`（`router` + `admin_router` 两个 APIRouter，`server.py` include）
- 管理端前端：`web/admin.html`「公告管理」tab + `web/js/admin.js`（loadAnnouncements 等方法）+ `web/css/admin.css`（.ann-* 样式）
- 用户端前端：`web/index.html`（铃铛 + 面板 + 详情弹窗 DOM，`app.mixin(window.AnnouncementCenterMixin)` 注册）+ `web/js/announcement_center.js`（mixin：轮询/面板/已读）+ `web/css/announcement_center.css`
- i18n：`web/i18n/locales/{zh-CN,en}/admin.json`（ann_* 管理端键）、`.../index.json`（ann_* 用户端键）
- 测试：`tests/crud/test_announcements_crud.py`、`tests/services/test_announcement_service.py`、`tests/api/test_announcements_api.py`

## 数据流

1. 管理员在 `/admin` →「公告管理」→ 新建公告（可存草稿或直接发布，可设定时发布/失效时间/级别/链接/图片）。
2. 用户首页登录后，`announcement_center.js` 每 60s 轮询 `/api/announcements/unread-count`，铃铛显示红色徽标。
3. 点铃铛展开面板：上方「公告」（本站，per-user 已读），下方「系统通知」（复用 `/api/notifications/poll`，全局已读）。
4. 点击条目 → 详情弹窗（正文 pre-wrap 文本、图片九宫格可点击放大、链接按钮）；打开即自动标记已读，徽标减一。
5. 「全部已读」按钮调 `/api/announcements/read-all`。

## 设计要点

- **防 XSS**：正文/标题一律 Vue 文本插值渲染（不使用 v-html）；图片 URL 仅接受 `/`、`http(s)://` 开头（服务端校验）；详情弹窗外链 `target="_blank"` 一律带 `rel="noopener noreferrer"`（后端已滤 `javascript:`，前端隔离 window.opener 为纵深防御第二层）。
- **幂等已读**：`INSERT IGNORE` + 唯一键，重复标记不报错。
- **定时发布/过期**：不依赖定时任务，查询条件实时过滤（`publish_at <= NOW()` / `expire_at > NOW()`）。时间为 **naive datetime**：与 MySQL `NOW()` 同以部署时区为准，要求应用容器与数据库时区保持一致（跨时区部署需显式对齐，如同时设为 `Asia/Shanghai`）。
- **时间格式校验**：`publish_at`/`expire_at` 在服务层校验格式（`YYYY-MM-DD HH:MM(:SS)`，常量 `AnnouncementConstants.DATETIME_FORMATS`），不合法值返回友好错误；API 异常分支只回统一话术，SQL 报错原文仅进日志不透出客户端。
- **更新成功语义**：不以 `affected > 0` 判定成功——pymysql 默认 affected rows 只计「值变化」的行，同值保存（含对已发布公告再次点发布）会 affected=0 被误报失败；入口已确认公告存在，UPDATE 未抛异常即成功。
- **删除事务性**：删除公告与级联清理已读记录在同一 `transaction()` 内（`AnnouncementsModel.delete_with_reads`），任一步失败整体回滚，不留孤儿 reads。
- **常量集中**：公告状态/级别/时间格式的值统一定义在 `config/constant.py:AnnouncementConstants`；`model/announcements.py` 的 `AnnouncementStatus`/`VALID_LEVELS` 仅作引用别名，避免双处定义漂移。
- **防误伤既有体系**：表名/接口/前端类名均与现有 notifications 体系隔离；远程公告的展示与已读逻辑未改动。
