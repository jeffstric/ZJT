# 统一配置系统

本文档介绍统一配置系统的使用方法，该系统整合了任务类型、驱动、算力、模型参数等配置。

## 概述

统一配置系统位于 `config/unified_config.py`，提供以下功能：

- **一处定义，处处使用**：所有任务配置集中在 `ALL_TASK_CONFIGS` 列表中
- **声明式配置**：每个任务类型用 `UnifiedTaskConfig` 定义全部属性
- **自动注册**：模块加载时自动注册，无需手动调用
- **前端 API**：提供 `/api/system/task-configs` 接口供前端获取配置
- **向后兼容**：保留 `constant.py` 中的旧 API

## 快速开始

### 新增任务类型

在 `config/unified_config.py` 的 `ALL_TASK_CONFIGS` 列表中添加配置：

```python
UnifiedTaskConfig(
    id=20,                              # 任务类型ID（唯一）
    key='new_model_image_to_video',     # 唯一标识符
    name='新模型图生视频',                # 历史任务标签（兼容旧接口）
    model_name='新模型',                  # 用户可见的纯模型名
    variant_label='首尾帧',                 # 同名条目需要消歧时才显示
    category=TaskCategory.IMAGE_TO_VIDEO,
    provider=TaskProvider.NEW_PROVIDER,
    driver_name='new_model_image_to_video',  # 业务驱动名称
    implementation='new_model_v1',           # 实现驱动类名
    computing_power={5: 10, 10: 18},         # 按时长计费
    supported_ratios=['9:16', '16:9', '1:1'],
    supported_durations=[5, 10],
    default_ratio='9:16',
    default_duration=5,
    sort_order=36,
),
```

### 查询配置

```python
from config.unified_config import UnifiedConfigRegistry, TaskCategory

# 按 ID 获取
config = UnifiedConfigRegistry.get_by_id(3)
print(config.name)  # "图片生成视频 (Sora2)"

# 按 key 获取
config = UnifiedConfigRegistry.get_by_key('sora2_image_to_video')

# 获取某分类的所有任务
video_tasks = UnifiedConfigRegistry.get_by_category(TaskCategory.IMAGE_TO_VIDEO)

# 获取算力
power = config.get_computing_power(duration=10)
```

### 前端 API

**获取所有任务配置**
```javascript
// GET /api/system/task-configs
const response = await fetch('/api/system/task-configs');
const data = await response.json();

// data.data.tasks - 所有任务配置列表
// data.data.categories - 分类信息
// data.data.providers - 供应商信息
```

**获取单个模型配置**
```javascript
// 通过任务类型ID查询
// GET /api/system/model-config?task_type_id=3
const response = await fetch('/api/system/model-config?task_type_id=3');

// 或通过模型key查询
// GET /api/system/model-config?model_key=sora2_image_to_video
const response = await fetch('/api/system/model-config?model_key=sora2_image_to_video');

const data = await response.json();
// data.data.ratios - 支持的比例列表
// data.data.sizes - 支持的尺寸列表
// data.data.durations - 支持的时长列表
// data.data.default_ratio - 默认比例
// data.data.default_size - 默认尺寸
// data.data.default_duration - 默认时长
// data.data.computing_power - 算力消耗
```

## 配置属性说明

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | int | ✅ | 任务类型ID，数据库中的 type 字段 |
| `key` | str | ✅ | 唯一标识符，用于代码引用 |
| `name` | str | ✅ | 历史任务标签，保留给旧接口/旧快照 |
| `model_name` | str | ✅（内置任务） | 用户可见的纯模型名，不包含 ID、供应商或能力后缀 |
| `variant_label` | str | ❌ | 同一能力下的同名模型消歧，如“首帧”“多参考” |
| `legacy_names` | list | ❌ | 历史名称别名，用于旧请求/快照反查 |
| `category` | str | ✅ | 分类，使用 TaskCategory 常量 |
| `provider` | str | ✅ | 供应商，使用 TaskProvider 常量 |
| `driver_name` | str | ❌ | 业务驱动名称 |
| `implementation` | str | ❌ | 实现驱动类名 |
| `computing_power` | int/dict | ❌ | 算力消耗，整数或按时长字典 |
| `supported_ratios` | list | ❌ | 支持的比例列表 |
| `supported_sizes` | list | ❌ | 支持的尺寸列表（图片类） |
| `supported_durations` | list | ❌ | 支持的时长列表（视频类） |
| `default_ratio` | str | ❌ | 默认比例 |
| `default_size` | str | ❌ | 默认尺寸 |
| `default_duration` | int | ❌ | 默认时长 |
| `enabled` | bool | ❌ | 是否启用，默认 True |
| `sort_order` | int | ❌ | 排序顺序 |

## 图片编辑任务（节选）

| ID | key | 名称 | 说明 |
|----|-----|------|------|
| 38 | `qwen-image-edit` | Qwen Image Edit | 空壳任务，无实现方；无比例/分辨率选项（跟随原图缩到约 1MP） |

完整列表见 `config/unified_config.py` 的 `ALL_TASK_CONFIGS`。

### 模型名与任务标识

`id` / `key` 是调度与持久化标识，不应拼入面向用户的模型名。
新界面读取 `model_name`，必要时附加 `variant_label`；`name` 在存量前端
完成迁移前继续下发。`matches_identifier()` 同时识别 key、纯模型名、
历史 `name` 和 `legacy_names`，以保证已保存偏好和任务快照可继续恢复。

## 分类常量 (TaskCategory)

```python
TaskCategory.IMAGE_EDIT      # 图片编辑
TaskCategory.TEXT_TO_VIDEO   # 文生视频
TaskCategory.IMAGE_TO_VIDEO  # 图生视频
TaskCategory.TEXT_TO_IMAGE   # 文生图
TaskCategory.VISUAL_ENHANCE  # 视觉增强
TaskCategory.AUDIO           # 音频
TaskCategory.DIGITAL_HUMAN   # 数字人
TaskCategory.OTHER           # 其他
```

## 供应商常量 (TaskProvider)

```python
TaskProvider.DUOMI        # 多米供应商
TaskProvider.RUNNINGHUB   # RunningHub 供应商
TaskProvider.VIDU         # Vidu 官方
TaskProvider.VOLCENGINE   # 火山引擎
TaskProvider.LOCAL        # 本地处理
```

## 向后兼容

`config/constant.py` 保留了旧的 API，内部委托给新系统：

```python
# 以下导入仍可正常使用
from config.constant import (
    TaskTypeId,
    TaskCategory,
    TaskProvider,
    TaskTypeRegistry,
    VIDEO_DRIVER_MAPPING,
    TASK_COMPUTING_POWER,
)
```

## 配置验证

```python
from config.unified_config import validate_configs

errors = validate_configs()
if errors:
    for error in errors:
        print(f"配置错误: {error}")
```

## 文件结构

```
config/
├── unified_config.py    # 统一配置系统（新）
├── constant.py          # 常量定义（向后兼容）
├── config_util.py       # 配置工具函数
└── default_configs.py   # 动态配置默认值
```
