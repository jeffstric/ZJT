# GPT Image 2.6 集成说明

## 概述

GPT Image 2.6 为**新建**模型（独立于 2.5，非改名），拆分为 **Sunburst** 与 **Flare** 两个独立模型
（前端模型列表中各一个条目），通过多米（Duomi）API 平台或 zjt api（通用聚合站点）提供服务。
接口与 GPT Image 2 / 2.5 完全一致，**仅上游模型名称不同**，均支持文生图和图片编辑（图生图）。
定价与 2.5 相同（固定 2 点算力）。

| 模型 | 上游模型名 | 任务类型 ID | 实现方 |
|------|-----------|------------|--------|
| GPT Image 2.6 Sunburst | `gpt-image-2.6-sunburst` | 55 | 多米（默认）+ ZJT官方站点 |
| GPT Image 2.6 Flare | `gpt-image-2.6-flare` | 56 | 多米（默认）+ ZJT官方站点 |

## 任务类型

每个模型一个任务类型，同时挂在「图片编辑」与「文生图」两个类目下（与 GPT Image 2 / 2.5 模式一致）：

| 任务类型 | ID | Key | short_key |
|----------|-----|-----|-----------|
| GPT Image 2.6 Sunburst 图片编辑 | 55 | `gpt-image-2.6-sunburst-edit` | `gpt-image-2.6-sunburst` |
| GPT Image 2.6 Flare 图片编辑 | 56 | `gpt-image-2.6-flare-edit` | `gpt-image-2.6-flare` |

- 业务驱动名称（DriverKey）: `gpt_image_2_6_sunburst` / `gpt_image_2_6_flare`
- 算力: 2 点（与 2.5 相同，可在管理后台按实现方覆盖）
- 支持比例: `1:1`、`2:3`、`3:2`、`16:9`、`9:16`
- 支持分辨率: `1k`、`2k`、`4k`
- 支持宫格生图: 是

## 实现方

每个模型 7 个实现方（多米优先；聚合站点 site_0~site_5 与 GPT Image 2 / 2.5 对齐，未配置密钥的站点自动隐藏）：

| 实现方名称 | 实现方 ID | 所属模型 | 显示名 | 驱动类 | 接口类型 |
|-----------|---------|---------|--------|--------|---------|
| `duomi_gpt_image_2_6_sunburst_v1`（默认） | 112 | Sunburst | 多米 | `GptImage26DuomiSunburstV1Driver` | 异步轮询 |
| `gpt_image_2_6_common_sunburst_site0_v1` | 114 | Sunburst | ZJTapi | `GptImage26CommonSunburstSite0V1Driver` | 同步 |
| `gpt_image_2_6_common_sunburst_site1_v1` ~ `site5_v1` | 115~119 | Sunburst | gpt_site1~5 | `GptImage26CommonSunburstSite1V1Driver` ~ `Site5V1Driver` | 同步 |
| `duomi_gpt_image_2_6_flare_v1`（默认） | 113 | Flare | 多米 | `GptImage26DuomiFlareV1Driver` | 异步轮询 |
| `gpt_image_2_6_common_flare_site0_v1` | 120 | Flare | ZJTapi | `GptImage26CommonFlareSite0V1Driver` | 同步 |
| `gpt_image_2_6_common_flare_site1_v1` ~ `site5_v1` | 121~125 | Flare | gpt_site1~5 | `GptImage26CommonFlareSite1V1Driver` ~ `Site5V1Driver` | 同步 |

- 多米驱动文件: `task/visual_drivers/gpt_image_2_6_duomi_v1_driver.py`
  （复用 `GptImageDuomiV1Driver` 的提交/查询/尺寸映射逻辑，仅覆盖 `DEFAULT_MODEL` 与 `driver_name`）
- 站点驱动: `task/visual_drivers/gpt_image_common_v1_driver.py`
  （基类 `GptImage26CommonSunburstV1Driver` / `GptImage26CommonFlareV1Driver`，站点类 site_0 ~ site_5；
  2.6 基类扩展 `xhigh`/`max` 质量档与 `gif`/`svg` 输出格式）

### 多米 API 接口

1. 提交任务: `POST https://duomiapi.com/v1/images/generations?async=true`
   - Header: `Authorization: {duomi.token}`
   - 请求体:
     ```json
     {
         "model": "gpt-image-2.6-sunburst",
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

- 文生图: `POST {base_url}/v1/images/generations`（JSON，`model` 为对应 2.6 模型名）
- 图片编辑: `POST {base_url}/v1/images/edits`（multipart/form-data，`model`/`n`/`size`/`quality` 等与 GPT Image 2 相同）
- 同步接口直接返回结果：`response_format` 缺省为 `b64_json`（`url` 返回 7 天有效链接，需及时转存）
- 接口格式细节（尺寸映射、extra_config 透传、响应兼容）与 [GPT Image 2 集成说明](./gpt_image_2_integration.md)、[GPT Image 2.5 集成说明](./gpt_image_2_5_integration.md) 一致，另有 2.6 扩展：

#### 2.6 扩展参数（gif / svg）

| 参数 | 生效范围 | 说明 |
|------|---------|------|
| `output_format` | 文生图 + 图片编辑 | 输出格式：`png`/`jpeg`/`webp`/`gif`/`svg`（GPT Image 2 / 2.5 仅支持前三种）。值大小写不敏感，`jpg` 自动归一为 `jpeg`，非法值忽略并记 warning |
| `quality` | 文生图 + 图片编辑 | 质量档：2.5 的 `low`/`medium`/`high`/`auto` 之外，2.6 新增 `xhigh`/`max` |

- 两个参数均通过 `ai_tool.extra_config` 传入（如 `{"output_format": "gif", "quality": "xhigh"}`），驱动仅透传合法值
- `b64_json` 响应不携带格式信息，驱动按字节魔数识别真实格式（png/jpeg/gif/webp/svg）生成 data URL；
  svg 落盘缓存扩展名为 `.svg`（`utils/media_cache.py` 的 `save_data_url_to_cache` ext_map），gif 此前已支持
- 接口文档依据：openlux gpt-image-2.6（`POST {base_url}/v1/images/generations`，参数与 gpt-image-2.5 一致）

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

通过标准 AI 工具接口提交任务，指定 `type=55`（Sunburst）或 `type=56`（Flare）：

```json
{
    "type": 55,
    "prompt": "a beautiful sunset over the ocean",
    "ratio": "1:1",
    "image_size": "1k"
}
```

图生图（图片编辑）额外传入 `image_path`（单张 URL、逗号分隔多张或本地路径）。

需要 gif/svg 输出或 `xhigh`/`max` 质量档时，通过 `extra_config` 传入（通用站点实现方）：

```json
{
    "type": 56,
    "prompt": "a rotating loading spinner",
    "ratio": "1:1",
    "image_size": "1k",
    "extra_config": "{\"output_format\": \"gif\", \"quality\": \"xhigh\"}"
}
```

Web 接口侧两个入口均支持 `extra_config` 表单字段（JSON 字符串）：

- 文生图: `POST /api/text-to-image`（`prompt`/`task_id`/`aspect_ratio`/`image_size` + `extra_config`）
  ```bash
  curl -X POST "$HOST/api/text-to-image" \
    -H "Authorization: Bearer <token>" \
    -F "task_id=56" -F "prompt=a rotating loading spinner, seamless loop" \
    -F "aspect_ratio=1:1" -F "image_size=1K" \
    -F 'extra_config={"output_format":"gif","quality":"xhigh"}'
  ```
- 图生图: `POST /api/image-edit`（`prompt`/`task_id` + `ref_image_urls` 或 `image` 文件 + `extra_config`）

注意：上游规定 **gif/svg 仅文生图（generations）端点支持**（`n=1`），图片编辑（edits）即使传
`output_format=gif` 也返回静图。
`output_format`/`quality` 只在**通用站点实现方**（site_0~5）生效，多米实现方不读取 extra_config。

GIF 帧参数：`frame_count`（2~16 帧）/`frame_duration_ms`（20~2000ms）已支持 extra_config 透传，
**仅在 `output_format=gif` 时下发**（转 int，超范围忽略）。
⚠️ 帧表尺寸限制与自动收敛（openlux 实测，任务 158/159/160）：GIF 由多帧拼成"帧表"（帧格=请求尺寸），
帧表需同时满足「最长边 ≤ 3840」与像素预算（约 829 万像素）。1K（1024x1024）下：9 帧→3072x3072
超像素预算；4/6 帧→4096x2048 超长边，均 400。**驱动已在 gif 时自动把帧格等比缩放到边长 ≤928**
（保持比例、16 的倍数；9 帧帧表 2784x2784=7.75MP、4x2 帧表 3712x1856 均留余量，日志有 warning），
因此界面选任意分辨率 + 任意帧数（2/4/6/9）都可直接提交；代价是 GIF 单帧分辨率上限 928px。
`frame_count` 默认 2 帧。
另外 `image_generation_user_error` 类型同时覆盖参数错误与内容审核，错误分类按消息特征判定，
帧表尺寸类错误会给出明确的帧数/分辨率调整建议，不再误报为"内容审核未通过"。

**文生图页界面**：`web/js/pages/text_to_image.js` 选中 2.6 模型时，按任务配置的
`params_schema`（`GPT_IMAGE_2_6_PARAMS_SCHEMA`）自动渲染「输出格式」「画质」下拉
（配置驱动，机制同视频增强页），选中值随 `extra_config` 表单字段提交；切换模型自动重置，
未配置 schema 的模型不显示参数区、也不传 extra_config。

**视频工作流图片节点**：`web/js/image_node.js` 的图片节点同样按任务配置的
`params_schema` 渲染「输出格式」下拉（仅配置了 `output_format` 的模型如 GPT Image 2.6
显示；首项「默认（PNG）」为空串，选中时不传 `extra_config`）。选中值持久化在
`node.data.outputFormat`（序列化整体落库，无字段白名单），工作流保存/重载后由
`createImageNodeWithData` 的 `_updateOutputFormatOptions` 钩子复原；切换模型时新模型
无该参数则重置为空串。提交仅无底图的文生图分支（`generateImageFromText` 第 7 参
`{ output_format }` → `/api/text-to-image`）透传，图生图（`/api/image-edit`）不带。

## 计费（算力定价）

定价按实现方分流（业务决定，2026-11-20）：任务级 `computing_power=0`，基准下沉到实现方——

- **多米（异步）**：固定 **2 算力**（渠道基准价；低于 openlux 实测成本， knowingly，渠道策略）
- **通用站点 site_0~5（同步，走 openlux 网关）**：基准 **7 算力**（1K PNG 默认品质真实成本，
  依据 2026-11-20 openlux 网关消费导出：$0.031 ≈ 5.6 算力成本，毛利 ~25%）× 修饰符表
  `GPT_IMAGE_2_6_POWER_MODIFIERS`（sunburst / flare 共用）：

| 维度 | 取值（倍率） | 说明 |
| --- | --- | --- |
| resolution | 1k=1.0 / 2k=2.0 / 4k=4.0（大小写双键） | 两个实现方都适用；2K/4K 暂无实测按像素量估算 |
| quality | low=0.5 / medium=1.0 / auto=1.5 / high=2.0 / xhigh=3.5 / max=6.0 | 按实测 token 量排序；仅通用站点生效（多米不透传 quality，按 medium 计） |
| output_format | gif=1.5 | 其余格式 1.0 |
| frame_count | 2=2.0 / 4=4.5 / 6=7.0 / 9=10.0 | 仅 GIF；按实测最差样本定价（2 帧成本最高 17.9、6 帧最高 71.4 算力） |

折算价目（1K，通用站点）：PNG low 4 / medium 7 / auto 11 / high 14 / xhigh 25 / max 42 算力；
GIF 2 帧 21 / 4 帧 48 / 6 帧 74 / 9 帧 105 算力（GIF 帧格被驱动收敛 ≤928，
上游成本与分辨率档位无关，故 GIF 不计 resolution/quality 维度，缺省帧数按 2 帧计）。
多米（1K）：任何画质 2 算力，2K=4、4K=8。

站点侧任意维度递增无倒挂，每个实测样本定价 ≥ 真实成本（回归见
`tests/config/test_gpt_image_2_6_power.py`）。扣费与退费重算共用
`utils/computing_power.build_image_task_billing_context()` 构建上下文；
前端价格展示在任务级算力为 0 时回落默认实现方（多米）基准（`to_frontend_dict`）。

实现方基准由 `implementation_power_config`（DB 种子 + no_167/no_168 迁移）与
代码默认 `default_computing_power` 共同提供，运营可在后台「实现方管理」热调整。

⚠️ 已知边界：用户选择 gif/高画质但路由到多米实现方时，多米不透传这些参数
（实际出静图/默认品质），计费按实际实现方口径计（多米 2 不随画质上浮），
不会多收；但「选了 GIF 却路由到多米拿不到动图」属于路由问题，与计费无关。

## 相关文件

- 配置文件: `config/unified_config.py`（`TaskTypeId.GPT_IMAGE_2_6_SUNBURST/FLARE`、`DriverKey.GPT_IMAGE_2_6_SUNBURST/FLARE`、`ALL_TASK_CONFIGS`、`ALL_IMPLEMENTATIONS`、`DriverImplementationId` 112~125、`IMPLEMENTATION_TO_ID`、`GPT_IMAGE_2_6_PARAMS_SCHEMA`、`GPT_IMAGE_2_6_POWER_MODIFIERS`）
- 常量映射: `config/constant.py`（`DRIVER_IMPLEMENTATION_MAPPING`、`IMAGE_QUALITY_EXTRA_CONFIG_KEY`、`IMAGE_OUTPUT_FORMAT_EXTRA_CONFIG_KEY`、`IMAGE_FRAME_COUNT_EXTRA_CONFIG_KEY`）
- 多米驱动: `task/visual_drivers/gpt_image_2_6_duomi_v1_driver.py`
- 通用站点驱动: `task/visual_drivers/gpt_image_common_v1_driver.py`（文件末尾 2.6 站点类）
- 工厂注册: `task/visual_drivers/driver_factory.py`
- 算力上下文: `utils/computing_power.py`（`build_image_task_billing_context`）
- 算力种子迁移: `alembic/versions/no_169_20261119_add_gpt_image_2_6_power.py`
- 算力基准同步迁移（2→7，仅站点）: `alembic/versions/no_170_20261120_update_gpt_image_2_6_power_base.py`
- 单元测试: `tests/drivers/test_gpt_image_2_6_drivers.py`、`tests/config/test_gpt_image_2_6_power.py`
