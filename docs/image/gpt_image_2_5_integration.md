# GPT Image 2.5 集成说明

## 概述

GPT Image 2.5 通过多米（Duomi）API 平台或 zjt api（通用聚合站点）提供服务。
接口与 GPT Image 2 完全一致，**仅上游模型名称不同**，支持文生图和图片编辑（图生图）。

上游提供两个模型变体（仅模型名不同，接口相同）：

| 变体 | 上游模型名 | 默认实现方 |
|------|-----------|-----------|
| Sunburst | `gpt-image-2.5-sunburst` | 是（多米） |
| Flare | `gpt-image-2.5-flare` | 否 |

## 任务类型

系统提供一个任务类型，同时挂在「图片编辑」与「文生图」两个类目下（与 GPT Image 2 模式一致）：

| 任务类型 | ID | Key | 功能说明 |
|----------|-----|-----|----------|
| GPT Image 2.5 图片编辑 | 46 | `gpt-image-2.5-edit`（short_key: `gpt-image-2.5`） | 文生图 + 基于参考图编辑图片 |

- 业务驱动名称（DriverKey）: `gpt_image_2_5`
- 算力: 2 点（可在管理后台按实现方覆盖）
- 支持比例: `1:1`、`2:3`、`3:2`、`16:9`、`9:16`
- 支持分辨率: `1k`、`2k`、`4k`
- 支持宫格生图: 是

## 实现方

### 多米（Duomi）— 异步接口

- `duomi_gpt_image_2_5_sunburst_v1`（默认，多米·Sunburst）：`GptImage25DuomiSunburstV1Driver`
- `duomi_gpt_image_2_5_flare_v1`（多米·Flare）：`GptImage25DuomiFlareV1Driver`
- 驱动文件: `task/visual_drivers/gpt_image_2_5_duomi_v1_driver.py`
- 复用 `GptImageDuomiV1Driver` 的提交/查询/尺寸映射逻辑，仅覆盖 `DEFAULT_MODEL`

#### API 接口

1. 提交任务: `POST https://duomiapi.com/v1/images/generations?async=true`
   - Header: `Authorization: {duomi.token}`
   - 请求体:
     ```json
     {
         "model": "gpt-image-2.5-sunburst",
         "prompt": "图片描述文本",
         "size": "2048x1152",
         "image": ["https://example.com/ref.png"]
     }
     ```
   - `image` 为可选参考图数组（图生图时传入）
2. 查询任务: `GET https://duomiapi.com/v1/tasks/{id}`
   - 状态映射: `pending`/`running` → RUNNING，`succeeded` → SUCCESS，`error` → FAILED
   - 成功结果: `data.images[0].url`

### zjt api 通用聚合站点 — 同步接口

sunburst / flare 各覆盖 site_0 ~ site_5 共 12 个实现方：

| 实现方名称 | 驱动类 |
|-----------|--------|
| `gpt_image_2_5_common_sunburst_site{0..5}_v1` | `GptImage25CommonSunburstSite{0..5}V1Driver` |
| `gpt_image_2_5_common_flare_site{0..5}_v1` | `GptImage25CommonFlareSite{0..5}V1Driver` |

- 基类: `GptImage25CommonSunburstV1Driver` / `GptImage25CommonFlareV1Driver`（位于 `task/visual_drivers/gpt_image_common_v1_driver.py`）
- 文生图: `POST {base_url}/v1/images/generations`（JSON，`model` 为对应 2.5 模型名）
- 图片编辑: `POST {base_url}/v1/images/edits`（multipart/form-data，`model`/`n`/`size`/`quality` 等与 GPT Image 2 相同）
- 接口格式细节（尺寸映射、extra_config 透传、响应兼容）与 [GPT Image 2 集成说明](./gpt_image_2_integration.md) 完全一致

## 配置要求

```yaml
# 多米实现方
duomi:
  token: "your_duomi_api_token"

# zjt api 聚合站点实现方
api_aggregator:
  site_0:
    base_url: "https://yw.perseids.cn"
    api_key: "your_api_key"
    name: "智剧通官方API"
  # site_1 ~ site_5 按需配置
```

实现方是否对用户可见由 `required_config_keys` 运行时校验：`duomi.token` 有值时显示多米实现方，`api_aggregator.site_X.api_key` 有值时显示对应站点。

## 使用方式

通过标准 AI 工具接口提交任务，指定 `type=46`：

```json
{
    "type": 46,
    "prompt": "a beautiful sunset over the ocean",
    "ratio": "1:1",
    "image_size": "1k"
}
```

图生图（图片编辑）额外传入 `image_path`（单张 URL、逗号分隔多张或本地路径）。

模型变体（Sunburst / Flare）通过实现方偏好切换（与供应商站点切换同一机制）。

## 相关文件

- 配置文件: `config/unified_config.py`（`TaskTypeId.GPT_IMAGE_2_5`、`DriverKey.GPT_IMAGE_2_5`、`ALL_TASK_CONFIGS`、`ALL_IMPLEMENTATIONS`）
- 常量映射: `config/constant.py`（`DRIVER_IMPLEMENTATION_MAPPING[DriverKey.GPT_IMAGE_2_5]`）
- 多米驱动: `task/visual_drivers/gpt_image_2_5_duomi_v1_driver.py`
- 通用站点驱动: `task/visual_drivers/gpt_image_common_v1_driver.py`（文件末尾 2.5 站点类）
- 工厂注册: `task/visual_drivers/driver_factory.py`
- 单元测试: `tests/drivers/test_gpt_image_2_5_drivers.py`
