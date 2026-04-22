# Gemini Image Preview 通用供应商驱动 (gemini_image_preview_common_v1)

## 概述

`gemini_image_preview_common_v1_driver.py` 实现了兼容 Gemini 原生 API 格式的通用供应商驱动，用于调用多个 Gemini 图片生成模型。

## 支持的模型

| Task ID | 模型名称 | 说明 |
|---------|---------|------|
| 1 | gemini-2.5-flash-image | Gemini 2.5 Flash 图片生成 |
| 7 | gemini-3-pro-image-preview | Gemini 3 Pro 图片生成 |
| 17 | gemini-3.1-flash-image-preview | Gemini 3.1 Flash 图片生成 |

## 特性

- **同步接口**：直接返回结果，无需轮询状态
- **Base64 图片输入**：支持将图片编码为 base64 格式上传
- **宽高比控制**：支持 `9:16`、`16:9`、`1:1`、`3:4`、`4:3`、`21:9`、`1:4`、`4:1`、`1:8`、`8:1`
- **清晰度控制**：支持 `1K`、`2K`、`4K`
- **多图输入**：支持逗号分隔的多个图片 URL
- **多模型支持**：根据 task_id 自动选择对应的模型
- **格式兼容**：同时支持驼峰格式（inlineData）和下划线格式（inline_data）
- **多站点支持**：支持 site_0（YWAPI 官方固定站点）到 site_5 共 6 个聚合站点

## 配置

### Site 0（YWAPI 官方固定站点）

在 `config.yml` 中添加以下配置：

```yaml
api_aggregator:
  site_0:
    base_url: "https://yw.perseids.cn"  # 固定YWAPI官方站点，base_url不可修改
    api_key: "your_api_key"              # API Key
    name: "ywapi"
```

### Site 1-5（自定义聚合站点）

```yaml
api_aggregator:
  site_1:
    base_url: "https://xxx.ai"  # API 基础 URL（根据实际中转站配置）
    api_key: "your_api_key"      # API Key
    name: "自定义名称"
```

## API 格式

### 请求格式

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {"text": "生成一张美丽的风景图"},
        {"inlineData": {"mimeType": "image/jpeg", "data": "base64_data"}}
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["TEXT", "IMAGE"],
    "imageConfig": {
      "aspectRatio": "9:16",
      "imageSize": "1K"
    }
  }
}
```

### 响应格式

```json
{
  "candidates": [{
    "content": {
      "parts": [{
        "inlineData": {
          "mimeType": "image/png",
          "data": "base64_result_image"
        }
      }]
    }
  }]
}
```

## 使用示例

```python
from task.visual_drivers.gemini_image_preview_common_v1_driver import GeminiImagePreviewSite0V1Driver

# 创建驱动实例（Site 0 - YWAPI 官方固定站点）
driver = GeminiImagePreviewSite0V1Driver()

# 提交任务（同步返回结果）
result = driver.submit_task(ai_tool)

if result['success']:
    # 同步接口直接返回结果
    image_url = result['result_url']  # data:image/png;base64,xxx 或缓存URL
```

## 站点实现类

| 类名 | 站点 | 说明 |
|------|------|------|
| `GeminiImagePreviewSite0V1Driver` | site_0 | YWAPI 官方固定站点，base_url 固定为 `https://yw.perseids.cn` |
| `GeminiImagePreviewSite1V1Driver` | site_1 | 自定义聚合站点 1 |
| `GeminiImagePreviewSite2V1Driver` | site_2 | 自定义聚合站点 2 |
| `GeminiImagePreviewSite3V1Driver` | site_3 | 自定义聚合站点 3 |
| `GeminiImagePreviewSite4V1Driver` | site_4 | 自定义聚合站点 4 |
| `GeminiImagePreviewSite5V1Driver` | site_5 | 自定义聚合站点 5 |

## 文件列表

| 文件 | 说明 |
|------|------|
| `task/visual_drivers/gemini_image_preview_common_v1_driver.py` | 驱动实现 |
| `tests/driver_integration/test_gemini_image_preview_common_driver.py` | 单元测试 |
| `config/unified_config.py` | 驱动常量定义 (`DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE0_V1` 等) |
| `task/visual_drivers/driver_factory.py` | 驱动注册 |

## 运行测试

```bash
python -m unittest tests.driver_integration.test_gemini_image_preview_common_driver -v
```

## 参考文档

- [Gemini API 图片生成官方文档](https://ai.google.dev/gemini-api/docs/image-generation)
- API 端点格式: `/v1beta/models/{model_name}:generateContent`
