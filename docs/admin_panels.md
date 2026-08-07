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

仪表盘下方展示模型成功率分析图表和表格。模型列表由后端根据 `config/unified_config.py` 中启用的视频类任务配置动态生成，新增模型后无需前端改动；前端会隐藏调用量为 0 的模型，仅展示有实际数据的模型：

- **数据来源**：`implementation_attempts`（每次实现方尝试的成功/失败），JOIN `ai_tools.type` 聚合；**不**直接按 `ai_tools` 终态计数。这样供应商重试时失败可正确归因到实际失败的实现方。
- **attempt 写入**：任务首次提交时由 `visual_task` 写入 `attempt_number=1`。判断依据是「该任务是否已有 attempt 记录」，**不是** `ai_tools.implementation` 是否为空。画布创建任务时会预写 `implementation`（用于分辨率/算力），不影响首次 attempt 记录。供应商重试由 `ImplementationRetryPipelineDriver` 写 `attempt_number>=2`。
- **日期范围筛选**：支持今天、3 天、7 天快捷筛选，也支持开始日期和结束日期自定义筛选。
- **模型选择**：支持按模型类型选择展示范围，可全选或清空。
- **汇总卡片**：展示总调用次数、成功次数、失败次数、平均成功率。
- **每日趋势图**：使用 ECharts 折线图在同一个图中展示每日模型成功率和调用数量，左侧 Y 轴为成功率，右侧 Y 轴为数量，不同模型使用不同颜色。
- **每日堆积柱状图**：按日期展示不同模型的调用量堆积，便于比较每日调用结构。
- **玫瑰图**：按所选日期范围汇总不同模型调用量，展示模型使用占比对比。
- **分组表格**：按模型类型分组，点击模型行可展开查看各实现方/供应商的成功率和平均耗时。暂未产生调用的模型会显示为 0 次。

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
- **进度指示**：显示已选择和已配置的服务商数量及进度条。共享同一凭证的服务商（如多米生图+生视频、火山多分类）按 `baseName` 合并计数，填一份 Token/Key 即计为「已配置 1」
- **一键选择（快速选择）**：自动选中当前推荐方案——**DeepSeek 大模型** + **多米**（生图/生视频共享 Token）。智剧通 API 正在逐步下线，不再带「推荐」标签，也不再作为快速选择默认项
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

### 6. 模型管理（大模型分段计费）

管理 LLM 模型的启用状态，以及「供应商 × 模型 × token 区间」的算力计费档位。

#### 6.1 模型列表

| 列 | 说明 |
|------|------|
| 展开 | 展开查看该模型的供应商分段计费配置 |
| 启用状态 | 关闭后前端模型选择器不再展示该模型 |
| 计费档位 | 摘要：`N档 · M供应商`；未配置显示「未配置」 |

#### 6.2 分段计费说明

数据表：`vendor_model`（同一供应商-模型可有多行档位）。

| 字段 | 含义 |
|------|------|
| `raw_token_threshold` | 分段上界：当本次 `raw_input_token ≤` 此值时使用本档；`NULL` 表示无上限兜底档 |
| `input/out/cache_token_threshold` | 每 N 个 token 消耗 1 点算力（由单价自动换算） |
| `commission_rate` | 抽成 0~1；计费 `算力 = 阈值算力 × (1+抽成)` |

- **1 点算力 = 0.04 元**
- **录入方式**：界面主填 **元/百万 token（供应商成本）**，`threshold = 0.04 × 10⁶ / 单价`
- **用户收费** = 成本价 × (1+抽成)；前后对比以「钱」展示
- 删除全部档位后该模型调用无法扣费（算力记为 0），请至少保留一档

#### 6.3 操作

- **页面顶部「负责模型」**：全局选择用于 AI 自动配置价格的大模型，展示为 **供应商 / 模型名**（如 `deepseek / deepseek-v4-pro`）；同一模型挂多家供应商时分列多条。默认 `deepseek / deepseek-v4-pro`
- **展开行**：按供应商展示档位；内联改成本单价与抽成
- **添加/编辑档位**：供应商、分段上界、输入/输出/缓存成本（元/百万）、抽成%
- **列表中的元/百万价格**：由系统按阈值公式反算展示，**不是**大模型实时计算
- **AI 生成方案**：自然语言 → 提案 → **金额前后对比确认** → 应用
- **删除档位**：二次确认后立即生效

#### 6.4 AI 改档

```
POST /api/admin/models/{id}/billing/ai-propose       # 生成提案（不写库）
POST /api/admin/models/{id}/billing/ai-apply         # 确认后批量应用
POST /api/admin/models/{id}/billing/reset-defaults   # 还原代码默认档位（?vendor_id=）
```

**行为约定**：

- 单价换算由大模型完成；系统内部统一为 **元/百万 token**
- 提示词要求：`元/千 tokens × 1000 = 元/百万`（例：0.0010→1.0，0.0020→2.0，命中 0.00020→0.2）
- 大模型若无法可靠换算/无法确定档位，必须返回 `{"ok":false,"error":"..."}`，接口以 **400** 展示原因，**不生成可确认的错误提案**
- 成功方案仍需管理员在对比弹窗中点「确认应用」后才写库

#### 6.5 还原默认档位

代码默认目录：`config/default_vendor_model_billing.py`（按 `vendor_name` + `model_name` 登记）。

```
POST /api/admin/models/{id}/billing/reset-defaults?vendor_id=可选
```

- **作用**：删除目标供应商-模型下现有档位，再按代码默认重建（含抽成、分段）
- **范围**：`vendor_id` 为空时还原该模型在目录中登记的**全部**默认供应商；传入则只还原该供应商
- **限制**：未在目录中登记的模型/供应商会返回 400，无法还原
- **UI**：模型计费展开区「还原默认档位」；各供应商旁「还原该供应商默认」
- 新增模型或改官方价后，请同步维护默认目录

### 7. 通知中心

展示系统通知和版本更新信息。

#### 7.1 版本升级提示

当检测到新版本时，显示升级横幅：
- 最新版本号
- 更新日志内容
- 完整更新日志链接

#### 7.2 二进制依赖提醒

- **版本升级所需依赖**：新版本可能需要的二进制工具，提供下载链接
- **本地缺失依赖**：检测当前环境缺失的二进制工具，显示工具名称、描述、下载地址和放置路径

#### 7.3 通知列表

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

`models` 会返回所有启用的图生视频、文生视频、数字人类任务类型（数据为 0 的模型也包含在内），新增模型后无需前端维护映射；页面渲染时会过滤掉调用量为 0 的模型，仅展示有数据的模型。统计仅计入 `implementation_attempts.status IN (2, -1)` 的终态尝试；任务创建时预写的 `ai_tools.implementation` 不会阻止 attempt 记录。

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

### 模型管理 / 大模型分段计费

```
GET    /api/admin/models                       # 模型列表（含 billing_summary）
PUT    /api/admin/models/{model_id}/enabled    # 启用/禁用模型
GET    /api/admin/models/{model_id}/billing    # 档位明细（含 money 用户价/成本价）
GET    /api/admin/vendors                      # 供应商列表
POST   /api/admin/vendor-models                # 新增计费档位
PUT    /api/admin/vendor-models/{tier_id}      # 更新计费档位
DELETE /api/admin/vendor-models/{tier_id}      # 删除计费档位
POST   /api/admin/models/{id}/billing/ai-propose
POST   /api/admin/models/{id}/billing/ai-apply
POST   /api/admin/models/{id}/billing/reset-defaults   # ?vendor_id= 可选
```

新增档位（推荐元/百万）：

```json
{
  "vendor_id": 5,
  "model_id": 12,
  "raw_token_threshold": 128000,
  "input_yuan_per_m": 1.0,
  "out_yuan_per_m": 2.0,
  "cache_yuan_per_m": 0.1,
  "commission_rate": 0.2
}
```

`commission_rate` 为 0~1；`raw_token_threshold` 为 `null` 表示无上限。

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
