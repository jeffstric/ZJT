# GPT Image 2 集成说明

## 概述

GPT Image 2 是 OpenAI 推出的文生图模型，通过多米（Duomi）API 平台或zjt api提供服务。本系统已实现 GPT Image 2 的集成，支持文生图和图片编辑（图生图）功能。

系统支持两个实现方：
- **多米（Duomi）**: 异步接口，支持任务状态轮询
- **zjt api**: 同步接口，OpenAI 标准格式

## 任务类型

系统提供两个任务类型：

| 任务类型 | ID | Key | 功能说明 |
|----------|-----|-----|----------|
| GPT Image 2 文生图 | 25 | `gpt-image-2` | 纯文本生成图片 |
| GPT Image 2 图片编辑 | 26 | `gpt-image-2-edit` | 基于参考图编辑图片 |

## 配置信息

### 任务类型配置

- **任务类型ID**: 25
- **任务Key**: `gpt-image-2`
- **显示名称**: GPT Image 2
- **分类**: 文生图 (text_to_image)
- **供应商**: 多米 (duomi)
- **默认算力**: 5

### 支持的参数

| 参数 | 支持值 | 说明 |
|------|--------|------|
| supported_sizes | `['1k', '2k', '4k']` | 支持 1K、2K、4K 分辨率 |
| supported_ratios | `['1:1', '2:3', '3:2', '16:9', '9:16']` | 支持的比例 |
| supports_grid_merge | `False` | 不支持宫格合并 |
| supports_grid_image | `False` | 不支持宫格生图 |

### 分辨率和比例映射

系统支持 1K、2K、4K 三种分辨率，每种分辨率下支持多种比例：

#### 1K 分辨率
- `1:1` -> `1024x1024` (正方形)
- `3:2` -> `1536x1024` (横版)
- `2:3` -> `1024x1536` (竖版)
- `16:9` -> `1536x1024` (横版)
- `9:16` -> `1024x1536` (竖版)

#### 2K 分辨率
- `1:1` -> `2048x2048` (正方形)
- `3:2` -> `2048x1152` (横版)
- `2:3` -> `1152x2048` (竖版)
- `16:9` -> `2048x1152` (横版)
- `9:16` -> `1152x2048` (竖版)

#### 4K 分辨率
- `1:1` -> `2048x2048` (正方形)
- `3:2` -> `3840x2160` (横版)
- `2:3` -> `2160x3840` (竖版)
- `16:9` -> `3840x2160` (横版)
- `9:16` -> `2160x3840` (竖版)

## 驱动实现

### 驱动类

- **类名**: `GptImageDuomiV1Driver`
- **文件位置**: `task/visual_drivers/gpt_image_duomi_v1_driver.py`
- **实现方名称**: `duomi_gpt_image_v1`

### API 接口

#### 1. 提交任务

- **URL**: `POST https://duomiapi.com/v1/images/generations`
- **认证**: Header `Authorization: {token}`
- **请求体**:
```json
{
    "model": "gpt-image-2",
    "prompt": "图片描述文本",
    "size": "1:1"
}
```

- **参考图支持**（可选）:
```json
{
    "model": "gpt-image-2",
    "prompt": "图片描述文本",
    "size": "1:1",
    "image": ["https://example.com/ref.png"]
}
```

#### 2. 查询任务状态

- **URL**: `GET https://duomiapi.com/v1/tasks/{id}`
- **认证**: Header `Authorization: {token}`
- **响应**:
```json
{
    "id": "task-id",
    "state": "succeeded",
    "data": {
        "images": [
            {"url": "https://...", "file_name": "output.png"}
        ]
    },
    "progress": 100
}
```

### 状态映射

| API 状态 | 系统状态 | 说明 |
|----------|----------|------|
| `pending` | RUNNING | 队列中 |
| `running` | RUNNING | 生成中 |
| `succeeded` | SUCCESS | 成功 |
| `error` | FAILED | 失败 |

### ZJT API 聚合站点

系统支持6个ZJT API聚合站点：

| 站点 | 实现方名称 | 驱动类名 | 配置依赖 |
|------|-----------|----------|----------|
| Site 0 (固定) | `gpt_image_common_site0_v1` | `GptImageCommonSite0V1Driver` | api_aggregator.site_0 |
| Site 1 | `gpt_image_common_site1_v1` | `GptImageCommonSite1V1Driver` | api_aggregator.site_1 |
| Site 2 | `gpt_image_common_site2_v1` | `GptImageCommonSite2V1Driver` | api_aggregator.site_2 |
| Site 3 | `gpt_image_common_site3_v1` | `GptImageCommonSite3V1Driver` | api_aggregator.site_3 |
| Site 4 | `gpt_image_common_site4_v1` | `GptImageCommonSite4V1Driver` | api_aggregator.site_4 |
| Site 5 | `gpt_image_common_site5_v1` | `GptImageCommonSite5V1Driver` | api_aggregator.site_5 |

- **基类**: `GptImageCommonV1Driver`
- **文件位置**: `task/visual_drivers/gpt_image_common_v1_driver.py`
- **接口类型**: 同步接口

#### API 接口

##### 1. 文生图

- **URL**: `POST {base_url}/v1/images/generations`
- **认证**: Header `Authorization: Bearer {api_key}`
- **Content-Type**: `application/json`
- **请求体**:
```json
{
    "model": "gpt-image-2",
    "prompt": "图片描述文本",
    "n": 1,
    "size": "1024x1024"
}
```

##### 2. 图片编辑

- **URL**: `POST {base_url}/v1/images/edits`
- **认证**: Header `Authorization: Bearer {api_key}`
- **Content-Type**: `multipart/form-data`
- **表单字段**:
  - `image`: 图片文件（必需，支持多张）
  - `prompt`: 文本描述（必需）
  - `model`: 模型名称
  - `n`: 生成数量
  - `size`: 图片尺寸

```
POST /v1/images/edits
Content-Type: multipart/form-data

image: [文件上传]
prompt: "将他们合并在一个图片里面"
model: "gpt-image-2"
n: 1
size: "1024x1536"
```

#### 比例映射

| 前端比例 | OpenAI size |
|----------|-------------|
| `1:1` | `1024x1024` |
| `3:2` / `16:9` | `1536x1024` (横版) |
| `2:3` / `9:16` | `1024x1536` (竖版) |

## 配置要求

### 必需配置

在系统配置中需要设置多米 API Token：

```yaml
duomi:
  token: "your_duomi_api_token"
```

### ZJT API 聚合站点配置

使用ZJT API站点时，需要在系统配置中设置：

```yaml
api_aggregator:
  site_0:
    base_url: "https://yw.perseids.cn"
    api_key: "your_api_key"
    name: "智剧通官方API"
  site_1:
    base_url: "https://yw.perseids.cn"
    api_key: "your_api_key"
    name: "ywapi"
  site_2:
    base_url: "https://ai.comfly.chat"
    api_key: "your_api_key"
    name: "comfly"
  # site_3, site_4, site_5 根据需要配置
```

### 配置验证

启动时会验证以下配置：
- `Duomi API Token` 必须存在且不为空（使用多米实现方时）
- `api_aggregator.site_X.api_key` 和 `api_aggregator.site_X.base_url` 必须存在且不为空（使用ZJT API实现方时）

## 使用方式

### 1. 文生图（type=25）

通过标准 AI 工具接口提交任务，指定 `type=25`：

```json
{
    "type": 25,
    "prompt": "a beautiful sunset over the ocean",
    "ratio": "1:1"
}
```

### 2. 图片编辑/图生图（type=26）

通过标准 AI 工具接口提交任务，指定 `type=26`，并传入参考图：

```json
{
    "type": 26,
    "prompt": "an island near sea, with seagulls, moon shining over the sea",
    "ratio": "2:3",
    "image_path": "https://example.com/ref.png"
}
```

**注意**：`image_path` 参数支持：
- 单张图片 URL
- 多张图片 URL 用逗号分隔（如需要）
- 本地图片路径（自动上传到 CDN）

### 支持的比例值

- `1:1` - 正方形
- `2:3` - 竖版
- `3:2` - 横版
- `16:9` - 映射为 3:2 (横版)
- `9:16` - 映射为 2:3 (竖版)

## 错误处理

驱动实现了完整的错误处理和报警机制：

1. **网络异常**: 返回可重试错误，用户可稍后重试
2. **API 格式错误**: 发送报警通知，返回系统错误
3. **未知异常**: 记录完整堆栈，发送报警

## 相关文件

- 配置文件: `config/unified_config.py`
- 驱动文件: `task/visual_drivers/gpt_image_duomi_v1_driver.py`
- 工厂注册: `task/visual_drivers/driver_factory.py`
- 常量定义: `config/constant.py`
