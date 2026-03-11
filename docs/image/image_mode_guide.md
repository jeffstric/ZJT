# 图片模式使用指南

本文档介绍 `ai_app_run_image` 接口支持的三种图片输入模式。

## 概述

图生视频任务支持三种图片输入模式：

| 模式 | 标识 | 说明 |
|------|------|------|
| 首尾帧模式 | `first_last_frame` | 第一张图片为首帧，第二张（可选）为尾帧 |
| 多参考图模式 | `multi_reference` | 所有图片作为参考图 |
| 首尾帧+参考图模式 | `first_last_with_ref` | 第一张为首帧，最后一张为尾帧，中间为参考图 |

## API 参数

### 新增参数

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `image_mode` | string | `first_last_frame` | 图片模式 |
| `reference_image_urls` | string | null | 参考图URL列表（逗号分隔） |

### 示例请求

#### 首尾帧模式（默认）

```bash
curl -X POST "/api/ai-app-run-image" \
  -F "prompt=一只猫在奔跑" \
  -F "task_id=14" \
  -F "image_urls=https://example.com/first.jpg,https://example.com/last.jpg" \
  -F "image_mode=first_last_frame"
```

#### 多参考图模式

```bash
curl -X POST "/api/ai-app-run-image" \
  -F "prompt=一只猫在奔跑" \
  -F "task_id=14" \
  -F "image_urls=https://example.com/ref1.jpg,https://example.com/ref2.jpg" \
  -F "image_mode=multi_reference"
```

#### 首尾帧+参考图模式

```bash
curl -X POST "/api/ai-app-run-image" \
  -F "prompt=一只猫在奔跑" \
  -F "task_id=14" \
  -F "image_urls=https://example.com/first.jpg,https://example.com/middle.jpg,https://example.com/last.jpg" \
  -F "image_mode=first_last_with_ref"
```

## 数据存储结构

### 数据库字段

| 字段 | 用途 | 格式 |
|------|------|------|
| `image_path` | 首尾帧图片URL | 逗号分隔，如 `"first.jpg,last.jpg"` |
| `reference_images` | 参考图URL列表 | JSON数组，如 `'["ref1.jpg", "ref2.jpg"]'` |
| `extra_config` | 模式配置 | JSON对象，如 `'{"image_mode": "first_last_frame"}'` |

### 各模式存储方式

| 模式 | `image_path` | `reference_images` |
|------|--------------|-------------------|
| 首尾帧 | 1-2张首尾帧 | `null` |
| 多参考图 | `null` | 参考图列表 |
| 首尾帧+参考图 | 2张首尾帧 | 中间参考图列表 |

## 配置层

### 在 unified_config.py 中配置模型支持的图片模式

每个图生视频任务可以配置 `supported_image_modes` 字段来指定支持的图片模式：

```python
from config.unified_config import ImageMode

UnifiedTaskConfig(
    id=TaskTypeId.VIDU_IMAGE_TO_VIDEO,
    key='vidu_image_to_video',
    name='图片生成视频 (Vidu-q2-pro-fast)',
    category=TaskCategory.IMAGE_TO_VIDEO,
    # ... 其他配置
    supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
    default_image_mode='first_last_frame',  # 默认模式
)
```

### ImageMode 常量

```python
class ImageMode:
    FIRST_LAST_FRAME = 'first_last_frame'     # 首尾帧模式
    MULTI_REFERENCE = 'multi_reference'       # 多参考图模式
    FIRST_LAST_WITH_REF = 'first_last_with_ref'  # 首尾帧+参考图模式
```

## 驱动支持情况

### 当前各驱动对模式的支持

| 驱动 | 首尾帧 | 多参考图 | 首尾帧+参考图 | 配置模式 |
|------|--------|----------|--------------|---------|
| Vidu | ✅ 完整支持 | ⚠️ 使用第一张 | ⚠️ 仅使用首尾帧 | `first_last_frame`, `multi_reference` |
| VEO3 | ✅ 完整支持 | ⚠️ 使用第一张 | ⚠️ 仅使用首尾帧 | `first_last_frame`, `multi_reference` |
| Kling | ✅ 完整支持 | ⚠️ 使用第一张 | ⚠️ 仅使用首尾帧 | `first_last_frame` |
| Sora2 | ⚠️ 仅使用首帧 | ⚠️ 使用第一张 | ⚠️ 仅使用首帧 | `first_last_frame` |
| LTX2 | ⚠️ 仅使用首帧 | ⚠️ 使用第一张 | ⚠️ 仅使用首帧 | `first_last_frame` |
| Wan22 | ⚠️ 仅使用首帧 | ⚠️ 使用第一张 | ⚠️ 仅使用首帧 | `first_last_frame` |

**说明**：
- ✅ 完整支持：驱动原生支持该模式
- ⚠️ 部分支持：驱动会自动降级处理，日志中会记录警告
- **配置模式**：当前在 `unified_config.py` 中配置的 `supported_image_modes`

### 驱动层方法

驱动基类 `BaseVideoDriver` 提供以下方法解析图片模式：

```python
# 解析图片模式
mode = self.parse_image_mode(ai_tool)  # 返回 'first_last_frame' 等

# 获取首尾帧
first_frame, last_frame = self.get_first_last_frames(ai_tool)

# 获取参考图列表
reference_images = self.get_reference_images(ai_tool)

# 一次性获取所有图片信息
image_info = self.get_all_images_by_mode(ai_tool)
# 返回: {'mode': '...', 'first_frame': '...', 'last_frame': '...', 'reference_images': [...]}
```

## 向后兼容

- `image_mode` 默认值为 `first_last_frame`，与现有行为一致
- 不传 `reference_images` 时，该字段为 `null`
- 现有接口调用无需修改即可正常工作

## 数据库迁移

需要运行 Alembic 迁移来添加 `reference_images` 字段：

```bash
alembic upgrade head
```

迁移脚本：`alembic/versions/20260303_add_reference_images_field.py`
