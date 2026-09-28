# 用户备注与用户昵称

> 管理员可给用户添加**备注**（仅后台可见）；用户可在前台**自定义昵称**，不填时系统自动分配**随机趣味默认昵称**（如"机智的熊猫521"）。

## 一、功能概述

1. **管理员备注**：管理后台用户列表新增"备注"列与"备注"操作按钮，点击弹出编辑弹窗保存。备注仅管理员可见，用户侧接口一律不返回该字段。
2. **用户昵称**：前台「设置 → 个人资料」tab 中修改，长度 1~30 字符；**留空保存 = 清除当前昵称并由系统重新随机分配一个默认昵称**。
3. **默认昵称规则**：随机趣味名 = 形容词 + 动物（如"机智的熊猫"，**末尾不带数字**，允许重复），词库见 `config/constant.py` 的 `NICKNAME_ADJECTIVES` / `NICKNAME_ANIMALS`（组合空间 400）。生成时查库尽量去重（昵称不强制唯一，重试后仍撞名则接受）。

## 二、数据模型

迁移脚本：`alembic/versions/no_143_20260926_add_users_remark_nickname.py`（挂在 no_142 之后）。

### `users` 表新增字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `nickname` | `VARCHAR(50)` DEFAULT NULL | 用户昵称；NULL=使用系统默认昵称（迁移已为存量用户回填随机昵称） |
| `remark` | `VARCHAR(500)` DEFAULT NULL | 管理员备注，仅后台可见 |

模型层（`model/users.py`）：

- `User.to_dict()` 输出 `nickname` 与 `display_name`（= `nickname or "用户{id}"` 兜底），**不输出 `remark`**——`to_dict` 会被用户侧路径复用，备注只在 admin 的 `list_all` / `admin_get_user` 中单独附加，从源头防泄漏。
- `UsersModel.create()` 未传昵称时自动分配随机默认昵称。
- `UsersModel.update_nickname(user_id, nickname)`：trim 后非空则校验 ≤ `NICKNAME_MAX_LEN`(30)，空则重新生成默认昵称，返回实际落库昵称。
- `UsersModel.update_remark(user_id, remark)`：校验 ≤ `REMARK_MAX_LEN`(500)，空串落 NULL（清除备注）。
- `UsersModel.list_all()` 关键字搜索扩展为 手机号 / 邮箱 / 昵称 LIKE。

## 三、接口

### 1. 管理员设置备注（api/admin.py）

```
PUT /api/admin/users/{user_id}/remark
Authorization: Bearer <token>        # 需管理员
{"remark": "重要客户"}                # 空串 = 清除备注
```

响应：`{"code": 0, "data": {"target_user_id": 2, "remark": "重要客户"}}`
错误：401 未登录 / 403 非管理员 / 404 用户不存在 / 400 超 500 字符。

### 2. 用户修改昵称（api/user.py + server.py 双挂载）

```
PUT /api/user/nickname
Authorization: Bearer <token>        # 登录用户本人
{"nickname": "小明"}                  # 空串 = 重置为随机默认昵称
```

响应：`{"code": 0, "data": {"nickname": "小明", "display_name": "小明"}}`
错误：401 未登录 / 400 超 30 字符。

> **挂载说明**：该路由在 `api/user.py`（社区版 router 挂载）与 `server.py`（`@app.put` 直接注册）各有一份，业务逻辑统一复用 `api.user.apply_nickname_change`。原因：enterprise 模块 discover 成功但 load 失败时（如组件注册异常），`server.py` 的回退 `include_router(api.user)` 不会执行，api/user.py 的路由整体缺失（E2E 实测踩坑），故 server.py 直接注册兜底，保证商业版环境可用。

### 3. 昵称展示来源（server.py）

`GET /api/user/role` 响应 `data` 新增 `nickname` 与 `display_name`（存量同步 DB 调用已顺手包 `asyncio.to_thread`）。管理后台 `GET /api/admin/users`（列表）与 `GET /api/admin/users/{id}`（详情）响应含 `nickname` / `display_name` / `remark`。

## 四、前端

### 管理后台（web/admin.html + web/js/admin.js + web/css/admin.css）

- 用户列表新增"备注"列（超长 CSS 截断 + title 悬浮全文，Vue 插值天然转义）；账号列下方灰色小字显示昵称（`display_name`）；空表行 colspan 7→8。
- 操作列"备注"按钮 → `remarkModal` 编辑弹窗（textarea，maxlength=500，字数提示），保存调备注接口后刷新列表。
- 用户详情弹窗新增"昵称"与"备注"展示行。
- i18n 键（zh-CN/en 两份 `admin.json` 同步）：`col_remark`、`col_nickname`、`btn_edit_remark`、`modal_remark`、`modal_remark_content`、`modal_remark_placeholder`、`toast_remark_saved`。

### 前台（web/index.html + web/js/index_app.js）

- 「用户设置」弹窗新增"个人资料"tab：昵称输入框（maxlength=30，placeholder 提示留空=随机分配）+ 保存；成功后同步顶栏显示。
- 顶栏原打码手机号位置改为 `displayName` computed（昵称优先，未取到回退打码账号），title 悬浮显示打码账号；点击行为（邀请中心）不变。
- `fetchUserRole()` 从 `/api/user/role` 带出昵称；登出/清态同步清空 `nickname`。

## 五、测试

- `tests/api/test_admin_user_remark.py`：备注保存/trim/清除/超长 400/404/403/401（7 例）。
- `tests/api/test_user_nickname.py`：设置/清空重置/超长/边界/未登录（5 例）。
- `tests/model/test_users_nickname_remark.py`：display_name 兜底、remark 不进 to_dict、默认昵称生成器格式与去重（5 例）。
- `web/tests/admin_user_remark.test.js`：前端源码断言（API 路径、列/弹窗、i18n 键、后端端点）（7 例）。
