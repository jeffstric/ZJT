# 管理后台使用说明

本文档介绍管理后台的功能和使用方法。

## 访问入口

1. **顶部导航栏**：管理员登录后，在顶部导航栏会显示「管理后台」按钮
2. **直接访问**：访问 `/admin` 路径

## 权限要求

- 需要登录且用户角色为 `admin`
- 普通用户访问管理后台会被拒绝并跳转

## 如何成为管理员

### 方式一：首个注册用户（推荐）

**系统会自动将第一个注册的用户设置为管理员**。

首次安装系统后，第一个注册的用户将自动：
1. 获得 `admin` 角色
2. 跳转到管理后台进行快速配置
3. 配置完成后引导查看使用手册

### 方式二：数据库手动设置

如果需要手动添加管理员，可在数据库中执行以下 SQL：

```sql
UPDATE users SET role = 'admin' WHERE phone = '你的手机号';
```

### 方式三：现有管理员设置

已有管理员可以在「用户管理」页面将普通用户提升为管理员。

## 功能模块

### 1. 仪表盘

显示系统概览数据：

| 指标 | 说明 |
|------|------|
| 用户总数 | 系统注册用户总数 |
| 3天活跃工作流 | 最近3天有更新的工作流数量 |

### 2. 用户管理

#### 2.1 用户列表

- **搜索**：按手机号搜索用户
- **筛选**：按状态（正常/禁用）、角色（用户/管理员）筛选
- **分页**：支持分页浏览

#### 2.2 用户操作

| 操作 | 说明 |
|------|------|
| 查看详情 | 查看用户完整信息 |
| 调整算力 | 增加或扣减用户算力（需填写原因） |
| 禁用/启用 | 切换用户状态 |
| 设为管理员 | 将普通用户提升为管理员 |

#### 2.3 算力调整

- 正数表示增加算力
- 负数表示扣减算力
- 必须填写调整原因
- 算力不能为负数（自动限制为0）

## API 接口

所有管理接口需要在请求头中携带 `Authorization: Bearer <token>`，且用户角色必须为 `admin`。

### 仪表盘

```
GET /api/admin/dashboard
```

响应示例：
```json
{
    "code": 0,
    "data": {
        "total_users": 1234,
        "active_workflows_3d": 56
    }
}
```

### 用户列表

```
GET /api/admin/users?page=1&page_size=20&keyword=138&status=1&role=user
```

参数：
- `page`: 页码（默认1）
- `page_size`: 每页数量（默认20，最大100）
- `keyword`: 搜索关键词（手机号）
- `status`: 状态筛选（0=禁用, 1=正常）
- `role`: 角色筛选（user/admin）

### 用户详情

```
GET /api/admin/users/{user_id}
```

### 更新用户状态

```
PUT /api/admin/users/{user_id}/status
Content-Type: application/json

{
    "status": 0  // 0=禁用, 1=正常
}
```

### 更新用户角色

```
PUT /api/admin/users/{user_id}/role
Content-Type: application/json

{
    "role": "admin"  // user 或 admin
}
```

### 调整用户算力

```
POST /api/admin/users/{user_id}/power
Content-Type: application/json

{
    "amount": 100,      // 正数增加，负数扣减
    "reason": "系统补偿"  // 必填
}
```

响应示例：
```json
{
    "code": 0,
    "message": "算力调整成功",
    "data": {
        "old_power": 500,
        "new_power": 600
    }
}
```

## 安全说明

1. **权限校验**：所有 `/api/admin/*` 接口都会校验管理员权限
2. **自我保护**：管理员不能禁用自己、不能降级自己的权限
3. **操作记录**：算力调整会记录操作原因和管理员信息

## 文件结构

```
api/
├── __init__.py      # API 模块
└── admin.py         # 管理员 API 路由（独立文件）

web/
├── admin.html       # 管理后台主页面
├── css/
│   └── admin.css    # 管理后台样式
└── js/
    └── admin.js     # 管理后台逻辑

server.py            # 主服务（通过 include_router 注册 admin 路由）

model/
├── users.py         # UsersModel 管理员方法
├── computing_power.py  # ComputingPowerModel.admin_adjust
└── video_workflow.py   # VideoWorkflowModel.count_active_recent_days
```

## 后续扩展

以下功能暂未实现，可根据需要后续添加：

- 任务监控
- 订单管理
- 音色库管理
- 操作日志（商业版功能）
