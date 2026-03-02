# 动态配置管理

## 概述

动态配置管理功能允许管理员通过后台页面修改系统配置，无需重启服务即可生效。配置存储在数据库中，支持环境隔离（dev/prod/test）和修改历史记录。

## 核心特性

- **热更新**: 配置修改后立即生效，无需重启服务
- **环境隔离**: 支持 dev/prod/test 多环境独立配置
- **修改历史**: 自动记录配置修改历史，便于审计和回溯
- **敏感配置脱敏**: token/密钥等敏感配置在历史记录中自动脱敏
- **降级策略**: 数据库读取失败时自动降级到 YAML 配置文件

## 数据库表

### system_config（主配置表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| env | VARCHAR(32) | 环境标识：dev/prod/test |
| config_key | VARCHAR(128) | 配置键，点号分隔 |
| config_value | TEXT | 配置值 |
| value_type | ENUM | 值类型：string/int/float/bool/json |
| description | VARCHAR(512) | 配置描述 |
| editable | TINYINT(1) | 是否允许通过页面修改 |
| is_sensitive | TINYINT(1) | 是否为敏感配置 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |
| updated_by | INT | 修改人 user_id |

### system_config_history（修改历史表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| config_id | INT | 关联 system_config.id |
| env | VARCHAR(32) | 环境标识 |
| config_key | VARCHAR(128) | 配置键 |
| old_value | TEXT | 旧值（敏感配置脱敏） |
| new_value | TEXT | 新值（敏感配置脱敏） |
| value_type | VARCHAR(32) | 值类型 |
| is_sensitive | TINYINT(1) | 是否敏感配置 |
| updated_by | INT | 修改人 user_id |
| updated_at | DATETIME | 修改时间 |

## API 接口

### 获取配置列表

```
GET /api/admin/config
```

**参数**:
- `keyword` (可选): 搜索关键字
- `page` (可选): 页码，默认 1
- `page_size` (可选): 每页数量，默认 50

### 获取单个配置详情

```
GET /api/admin/config/{config_key}
```

**返回**: 配置详情及最近 10 条修改历史

### 更新配置值

```
PUT /api/admin/config/{config_key}
```

**参数**:
- `value`: 新的配置值

### 刷新配置缓存

```
POST /api/admin/config/reload
```

### 初始化默认配置

```
POST /api/admin/config/init
```

从 YAML 配置文件导入默认配置到数据库（仅新增，不覆盖已存在的配置）

## 代码使用

### 读取动态配置

```python
from config.config_util import get_dynamic_config_value

# 优先从数据库读取，数据库无记录则回退到 YAML
max_retry = get_dynamic_config_value('task_queue', 'max_retry_count', default=30)
api_key = get_dynamic_config_value('runninghub', 'api_key', default='')
```

### 设置动态配置

```python
from config.config_util import set_dynamic_config_value

set_dynamic_config_value(
    'task_queue', 'max_retry_count',
    value=50,
    value_type='int',
    description='任务最大重试次数',
    updated_by=user_id
)
```

### 清除配置缓存

```python
from config.config_util import invalidate_dynamic_cache

# 清除指定配置缓存
invalidate_dynamic_cache('task_queue.max_retry_count')

# 清除所有缓存
invalidate_dynamic_cache()
```

## 支持热更新的配置

| 分类 | 配置键示例 | 敏感 |
|------|-----------|------|
| 任务队列 | `task_queue.max_retry_count` | 否 |
| 上传限制 | `upload.max_image_size_mb` | 否 |
| 前端调试 | `frontend.debug_password` | 是 |
| 工作流 | `workflow.poll_status_interval`（秒） | 否 |
| 测试模式 | `test_mode.enabled` | 否 |
| 超时设置 | `timeout.request_timeout` | 否 |
| 图片下载 | `image.enable_download` | 否 |
| RunningHub | `runninghub.api_key` | 是 |
| Duomi | `duomi.token` | 是 |
| Vidu | `vidu.token` | 是 |
| 微信支付 | `pay.wxpay.api_key` | 是 |
| Google | `google.api_key` | 是 |
| 七牛云 | `file_storage.qiniu.access_key` | 是 |
| Sentry | `sentry.dsn` | 是 |

## 敏感配置脱敏规则

敏感配置（`is_sensitive=1`）在修改历史中自动脱敏：

- 保留前 4 位 + `****` + 后 4 位
- 例如: `sk-f3694dd0xxxx` → `sk-f****xxxx`
- 长度 ≤ 8 时显示 `********`

## 缓存机制

- 内存字典缓存 + 30 秒 TTL
- 配置修改时主动清除对应缓存
- 可通过 API 手动刷新缓存

## 管理页面

访问 `/admin` 页面，点击左侧「系统配置」菜单：

1. **初始化配置**: 首次使用需点击「初始化配置」按钮，从 YAML 导入配置到数据库
2. **编辑配置**: 点击配置行的「编辑」按钮修改配置值
3. **查看历史**: 点击「历史」按钮查看修改记录
4. **刷新缓存**: 点击「刷新缓存」按钮清除配置缓存
