# GPT Image 2.5 集成说明

## 概述

GPT Image 2.5 拆分为 **Sunburst** 与 **Flare** 两个独立模型（前端模型列表中各一个条目），
通过多米（Duomi）API 平台或 zjt api（通用聚合站点）提供服务。
接口与 GPT Image 2 完全一致，**仅上游模型名称不同**，均支持文生图和图片编辑（图生图）。

| 模型 | 上游模型名 | 任务类型 ID | 实现方 |
|------|-----------|------------|--------|
| GPT Image 2.5 Sunburst | `gpt-image-2.5-sunburst` | 46 | 多米（默认）+ ZJT官方站点 |
| GPT Image 2.5 Flare | `gpt-image-2.5-flare` | 47 | 多米（默认）+ ZJT官方站点 |

## 任务类型

每个模型一个任务类型，同时挂在「图片编辑」与「文生图」两个类目下（与 GPT Image 2 模式一致）：

| 任务类型 | ID | Key | short_key |
|----------|-----|-----|-----------|
| GPT Image 2.5 Sunburst 图片编辑 | 46 | `gpt-image-2.5-sunburst-edit` | `gpt-image-2.5-sunburst` |
| GPT Image 2.5 Flare 图片编辑 | 47 | `gpt-image-2.5-flare-edit` | `gpt-image-2.5-flare` |

- 业务驱动名称（DriverKey）: `gpt_image_2_5_sunburst` / `gpt_image_2_5_flare`
- 算力: 2 点（可在管理后台按实现方覆盖）
- 支持比例: `1:1`、`2:3`、`3:2`、`16:9`、`9:16`
- 支持分辨率: `1k`、`2k`、`4k`
- 支持宫格生图: 是

## 实现方

每个模型 7 个实现方（多米优先；聚合站点 site_0~site_5 与 GPT Image 2 对齐，未配置密钥的站点自动隐藏）：

| 实现方名称 | 所属模型 | 显示名 | 驱动类 | 接口类型 |
|-----------|---------|--------|--------|---------|
| `duomi_gpt_image_2_5_sunburst_v1`（默认） | Sunburst | 多米 | `GptImage25DuomiSunburstV1Driver` | 异步轮询 |
| `gpt_image_2_5_common_sunburst_site0_v1` | Sunburst | ZJTapi | `GptImage25CommonSunburstSite0V1Driver` | 同步 |
| `gpt_image_2_5_common_sunburst_site1_v1` ~ `site5_v1` | Sunburst | gpt_site1~5 | `GptImage25CommonSunburstSite1V1Driver` ~ `Site5V1Driver` | 同步 |
| `duomi_gpt_image_2_5_flare_v1`（默认） | Flare | 多米 | `GptImage25DuomiFlareV1Driver` | 异步轮询 |
| `gpt_image_2_5_common_flare_site0_v1` | Flare | ZJTapi | `GptImage25CommonFlareSite0V1Driver` | 同步 |
| `gpt_image_2_5_common_flare_site1_v1` ~ `site5_v1` | Flare | gpt_site1~5 | `GptImage25CommonFlareSite1V1Driver` ~ `Site5V1Driver` | 同步 |

- 多米驱动文件: `task/visual_drivers/gpt_image_2_5_duomi_v1_driver.py`
  （复用 `GptImageDuomiV1Driver` 的提交/查询/尺寸映射逻辑，仅覆盖 `DEFAULT_MODEL` 与 `driver_name`）
- 站点驱动: `task/visual_drivers/gpt_image_common_v1_driver.py`
  （基类 `GptImage25CommonSunburstV1Driver` / `GptImage25CommonFlareV1Driver`，站点类 site_0 ~ site_5）

### 多米 API 接口

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

### zjt api 站点接口

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

配置可走 YAML 或后台系统配置（数据库 `system_config`，热更新，键名如 `api_aggregator.site_1.api_key`），数据库优先。

实现方是否对用户可见由运行时校验决定：
- 多米实现方：`duomi.token` 有值即显示
- site_0：`api_aggregator.site_0.api_key` 有值即显示（base_url 固定）
- site_1 ~ site_5：`api_aggregator.site_X.api_key` 与 `api_aggregator.site_X.base_url` **都**有值才显示；实现方管理后台同样按此规则过滤，未配置的站点不会出现

## 使用方式

通过标准 AI 工具接口提交任务，指定 `type=46`（Sunburst）或 `type=47`（Flare）：

```json
{
    "type": 46,
    "prompt": "a beautiful sunset over the ocean",
    "ratio": "1:1",
    "image_size": "1k"
}
```

图生图（图片编辑）额外传入 `image_path`（单张 URL、逗号分隔多张或本地路径）。

## 相关文件

- 配置文件: `config/unified_config.py`（`TaskTypeId.GPT_IMAGE_2_5_SUNBURST/FLARE`、`DriverKey.GPT_IMAGE_2_5_SUNBURST/FLARE`、`ALL_TASK_CONFIGS`、`ALL_IMPLEMENTATIONS`）
- 常量映射: `config/constant.py`（`DRIVER_IMPLEMENTATION_MAPPING`）
- 多米驱动: `task/visual_drivers/gpt_image_2_5_duomi_v1_driver.py`
- 通用站点驱动: `task/visual_drivers/gpt_image_common_v1_driver.py`（文件末尾 2.5 站点类）
- 工厂注册: `task/visual_drivers/driver_factory.py`
- 算力种子迁移: `alembic/versions/no_133_20260910_add_gpt_image_2_5_power.py`
- 单元测试: `tests/drivers/test_gpt_image_2_5_drivers.py`
