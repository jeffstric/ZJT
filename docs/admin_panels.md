# 管理后台使用说明

本文档介绍管理后台的功能和使用方法。

## 访问入口

1. **顶部导航栏**：管理员登录成功后，首页会立即刷新当前用户角色，并在顶部导航栏显示「管理后台」按钮
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
| 月活用户 | 当月活跃用户数量（需手动点击查询） |

#### 1.1 模型成功率分析

仪表盘下方展示模型成功率分析图表和表格：

- **日期范围筛选**：支持今天、3 天、7 天快捷筛选，也支持开始日期和结束日期自定义筛选。
- **模型选择**：支持按模型类型选择展示范围，可全选或清空。
- **汇总卡片**：展示总调用次数、成功次数、失败次数、平均成功率。
- **每日趋势图**：使用 ECharts 折线图在同一个图中展示每日模型成功率和调用数量，左侧 Y 轴为成功率，右侧 Y 轴为数量，不同模型使用不同颜色。
- **每日堆积柱状图**：按日期展示不同模型的调用量堆积，便于比较每日调用结构。
- **獇瑰图**：按所选日期范围汇总不同模型调用量，展示模型使用占比对比。
- **分组表格**：按模型类型分组，点击模型行可展开查看各实现方/供应商的成功率和平均耗时。

### 2. 用户管理

#### 2.1 用户列表

- **搜索**：按手机号搜索用户
- **筛选**：按状态（正常/待审核/禁用）、角色（用户/管理员）筛选
- **分页**：支持分页浏览
- **账号列**：手机号和邮箱合并为一列显示，由于用户只会绑定其中一种账号，列表中优先显示手机号，其次显示邮箱
- **注册时间**：列表默认只显示注册日期，鼠标移动到日期上可查看完整时间
- **操作按钮**：智剧通Token按钮在列表中以窄按钮 `Token` 显示，鼠标移动到按钮上可查看完整开启/关闭状态
- **角色配置**：管理员/普通用户的角色切换入口已移入用户详情弹窗，列表中仅展示当前角色

#### 2.2 用户操作

| 操作 | 说明 |
|------|------|
| 查看详情 | 查看用户完整信息（ID、手机号、角色、状态、算力、邀请码、注册时间） |
| 调整算力 | 增加或扣减用户算力（需填写原因） |
| 审批登录 | 对状态为"待审核"的用户进行审批通过 |
| 启用/智剧通Token | 开启或关闭用户的智剧通Token功能（非社区版） |
| 调整有效期 | 调整用户智剧通Token的过期时间（非社区版，需Token已启用） |
| 禁用/启用 | 切换用户状态 |
| 角色切换 | 在用户详情弹窗中将普通用户提升为管理员，或将管理员调整为普通用户 |

#### 2.3 算力调整

- 正数表示增加算力
- 负数表示扣减算力
- 必须填写调整原因
- 算力不能为负数（自动限制为0）

### 3. 系统配置

管理系统全局配置项。

#### 3.1 配置列表

- **搜索**：按配置键名搜索
- **分页**：支持分页浏览
- **列信息**：配置键、配置值、类型、描述、是否敏感、更新时间

#### 3.2 配置操作

| 操作 | 说明 |
|------|------|
| 快速配置 | 引导式配置向导，支持按分类（大模型/生图/生视频/其他）选择服务商并填写API密钥 |
| 初始化配置 | 初始化系统默认配置 |
| 刷新缓存 | 刷新配置缓存使修改生效 |
| 编辑 | 修改配置值（支持字符串、数字、布尔、JSON类型） |
| 查看历史 | 查看配置项的修改历史记录 |

#### 3.3 快速配置弹窗

快速配置采用两栏模式：
- **左侧面板**：按分类标签（大模型、生图模型、生视频模型、其他服务）展示服务商卡片
- **右侧面板**：选中服务商的配置表单，支持保存、测试连接、移除操作
- **进度指示**：显示已选择和已配置的服务商数量及进度条
- **一键选择**：快速选择推荐配置方案
- **社区版限制**：社区版用户无法选择标记为"商业版专属"的服务商

#### 3.4 敏感配置

- 敏感配置值默认显示为星号遮罩
- 点击"查看"按钮可弹窗显示完整值
- 弹窗中提供复制功能
- 配置历史中敏感值显示为"已脱敏"

### 4. 签到管理

管理用户每日签到功能的配置。

| 配置项 | 说明 |
|--------|------|
| 启用签到 | 开关签到功能 |
| 基础奖励 | 每次签到获得的算力值 |
| 连续签到奖励 | 开关连续签到额外奖励 |
| 奖励阶梯 | 配置连续签到天数与对应额外奖励 |

### 5. 实现方管理

管理AI服务实现方（服务商）的配置。

#### 5.1 使用说明

- **优先级**：同一类型有多个实现方时，按排序值从小到大依次尝试
- **算力消耗**：不同实现方消耗的算力不同，修改前请确认

#### 5.2 分组展示

实现方按 `driver_key` 分组展示（如图生视频、文生视频等），每组包含：

| 列 | 说明 |
|------|------|
| 排序值 | 数字越小优先级越高，可直接编辑 |
| 名称 | 实现方标识名 |
| 显示名称 | 实现方展示名称，标记"使用中"为当前默认 |
| 算力配置 | 支持按时长配置不同算力值，可恢复默认值 |
| 描述 | 实现方功能描述 |

#### 5.3 算力配置

- 支持按视频时长分别配置算力消耗（如5s、10s等）
- 无时长选项的实现方使用固定算力值
- 可一键恢复为默认算力值

### 6. 通知中心

展示系统通知和版本更新信息。

#### 6.1 版本升级提示

当检测到新版本时，显示升级横幅：
- 最新版本号
- 更新日志内容
- 完整更新日志链接

#### 6.2 二进制依赖提醒

- **版本升级所需依赖**：新版本可能需要的二进制工具，提供下载链接
- **本地缺失依赖**：检测当前环境缺失的二进制工具，显示工具名称、描述、下载地址和放置路径

#### 6.3 通知列表

- **通知类型**：公告、维护、新功能、安全
- **通知级别**：info、warning、error、success
- **操作**：标记单条已读、全部标记已读
- **未读角标**：侧边栏菜单显示未读数量（超过99显示"99+"）
- **自动轮询**：每30秒自动轮询新通知

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

### 月活用户查询

```
GET /api/admin/dashboard/monthly-active-users
```

响应示例：
```json
{
    "code": 0,
    "data": {
        "count": 89,
        "year": 2026,
        "month": 5
    }
}
```

### 模型成功率分析

```
GET /api/admin/dashboard/model-analysis?days=7&start_date=2026-06-03&end_date=2026-06-09
```

参数：
- `days`：快捷时间范围，支持 1 到 30 天。未传日期范围时按该参数查询。
- `start_date`：可选，开始日期，格式 `YYYY-MM-DD`。
- `end_date`：可选，结束日期，格式 `YYYY-MM-DD`，按整天包含结束日期。

返回数据包含模型汇总 `models` 和每日聚合 `daily`。前端使用 `daily[].models` 渲染每日趋势折线图、每日堆积柱状图，并使用 `models` 渲染调用量玫瑰图和明细表格。

### 用户列表

```
GET /api/admin/users?page=1&page_size=20&keyword=138&status=1&role=user
```

参数：
- `page`: 页码（默认1）
- `page_size`: 每页数量（默认20，最大100）
- `keyword`: 搜索关键词（手机号）
- `status`: 状态筛选（0=禁用, 1=正常, 2=待审核）
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

### 审批用户登录

通过更新用户状态实现（将待审核用户 status=2 改为正常 status=1）：

```
PUT /api/admin/users/{user_id}/status
Content-Type: application/json

{
    "status": 1  // 1=正常
}
```

### 切换智剧通Token

```
PUT /api/admin/users/{user_id}/zjt-token
Content-Type: application/json

{
    "zjt_token_enabled": true
}
```

### 获取智剧通Token状态

```
GET /api/admin/users/{user_id}/zjt-token
```

### 调整Token有效期

```
PUT /api/admin/users/{user_id}/zjt-token-expire
Content-Type: application/json

{
    "expire_at": "2027-01-01T00:00:00"
}
```

### 系统配置列表

```
GET /api/admin/config?page=1&page_size=20&keyword=search
```

### 更新配置

```
PUT /api/admin/config/{config_key}
Content-Type: application/json

{
    "config_value": "new_value"
}
```

### 配置历史

```
GET /api/admin/config-history?key={config_key}
```

### 初始化配置

```
POST /api/admin/config/init
```

### 刷新配置缓存

```
POST /api/admin/config/reload
```

### 签到配置

签到配置通过通用的系统配置接口管理，配置键以 `checkin.` 为前缀：

```
GET /api/admin/config?keyword=checkin    # 查看签到相关配置
PUT /api/admin/config/{config_key}       # 修改单个配置项
PUT /api/admin/config/batch              # 批量修改配置
```

相关配置键：
- `checkin.enabled` - 是否启用签到功能
- `checkin.base_reward` - 每次签到基础奖励算力
- `checkin.streak_bonus_enabled` - 是否启用连续签到奖励
- `checkin.streak_bonus_config` - 连续签到阶梯奖励配置（JSON）

### 实现方管理

```
GET /api/admin/implementation-configs          # 获取实现方配置列表
GET /api/admin/implementation-powers           # 获取实现方算力配置
PUT /api/admin/implementation-config           # 更新实现方配置（排序、启用等）
POST /api/admin/implementation-power           # 设置实现方算力
DELETE /api/admin/implementation-power         # 删除实现方算力配置
POST /api/admin/implementation-configs/sort-order  # 批量更新排序
```

### 通知管理

```
GET /api/notifications/admin/list?page=1&page_size=20
DELETE /api/notifications/admin/{id}
```

## 安全说明

1. **权限校验**：所有 `/api/admin/*` 接口都会校验管理员权限
2. **自我保护**：管理员不能禁用自己、不能降级自己的权限
3. **操作记录**：算力调整会记录操作原因和管理员信息
4. **敏感配置保护**：敏感配置值默认脱敏显示，需手动点击查看完整值
5. **社区版限制**：部分功能（如智剧通Token管理、商业版服务商）在社区版中不可用

## 国际化支持

管理后台支持多语言切换：
- 支持中文和英文
- 通过侧边栏顶部的语言切换器切换
- 所有文本使用 i18n 翻译键，支持 `data-i18n` 属性和 Vue `$t()` 函数

## 文件结构

```
api/
├── __init__.py          # API 模块
├── admin.py             # 管理员 API 路由
└── notifications.py     # 通知 API 路由

web/
├── admin.html           # 管理后台主页面（Vue 3 单页应用）
├── css/
│   └── admin.css        # 管理后台样式
└── js/
    └── admin.js         # 管理后台逻辑（Vue 3 应用、服务商配置定义）

i18n/
├── i18n-core.js         # 国际化核心库
├── i18n-dom.js          # DOM 扫描翻译
└── i18n-switcher.js     # 语言切换器

server.py                # 主服务（通过 include_router 注册 admin 路由）

model/
├── users.py             # UsersModel 管理员方法
├── computing_power.py   # ComputingPowerModel.admin_adjust
├── video_workflow.py    # VideoWorkflowModel.count_active_recent_days
└── notifications.py     # 通知数据模型

services/
└── notification_service.py  # 通知拉取服务

config/
├── constant.py          # NotificationConstants 等常量定义
└── required_binaries.yml # 二进制依赖配置

alembic/versions/        # 数据库迁移脚本
```

## 后续扩展

以下功能暂未实现，可根据需要后续添加：

- 任务监控
- 订单管理
- 音色库管理
- 操作日志（商业版功能）
