# RunningHub AI App 图片驱动 (runninghub_ai_app_image_v1)

## 概述

通过 RunningHub AI-App 接口对接图片工作流（webapp id `2113539132868874242`），**同一工作流同时支持图片编辑与文生图**两种模式，由任务是否有参考图自动区分：

- **图片编辑**：`ai_tool.image_path` 携带 1-6 张参考图，上传 RunningHub 图床后填入图片节点；自动开启「原图无偏移」（nodeId 25）与「使用图片尺寸」（nodeId 29，输出跟随图 1 尺寸，忽略节点 28）。
- **文生图**：`image_path` 为空，图片槽位全部填 `"None"`（工作流节点 16 `easy makeImageList` 的 `skip_empty=true` 自动忽略 None）；**必须关闭**节点 25/29（RunningHub 文档要求文生图关闭，否则画面偏移或报错），通过节点 28 显式指定比例与像素。

- **webapp_id**：`2113539132868874242`（可用动态配置 `runninghub.ai_app_image_webapp_id` 覆盖）
- **任务类型**：TaskTypeId.RUNNINGHUB_AI_APP_IMAGE = 52
- **DriverKey**：`runninghub_ai_app_image`
- **实现方**：`runninghub_ai_app_image_v1`
- **驱动类**：`RunninghubAiAppImageV1Driver`
- **分类**：`IMAGE_EDIT`（主分类）+ `categories=[TEXT_TO_IMAGE]`（图片编辑与文生图入口同时可见）
- **供应商**：`RUNNINGHUB`（自动纳入 RunningHub 槽位与多密钥轮换体系）
- **多参考图上限**：6 张（图片节点 17-22）

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 提示词 | 必填；编辑模式为修改指令，文生图为完整画面描述 | "" | - |
| 参考图 | 编辑模式 1-6 张（逗号分隔 URL），文生图为空 | 空 | - |
| 比例 | 仅文生图生效（编辑模式跟随图 1） | 1:1 | 1:1, 2:3, 3:2, 3:4, 4:3, 9:16, 16:9, 21:9 |
| 分辨率 | 仅文生图生效，映射为 megapixels 百万像素 | 2K | 1K(1), 2K(2), 4K(4) |

## 工作流节点映射

| 参数 | nodeId | fieldName | 图片编辑取值 | 文生图取值 |
|------|--------|-----------|--------------|------------|
| 图1~图6 | 17/18/19/20/21/22 | image | RunningHub 图床路径（不足补 `"None"`） | 固定 `"None"` |
| 提示词 | 23 | value | prompt | prompt |
| 使用反推 | 24 | value | 固定 `"false"` | 固定 `"false"` |
| 原图无偏移 | 25 | value | `"true"` | `"false"`（必须关闭） |
| 使用图片尺寸 | 29 | value | `"true"`（跟随图 1 尺寸） | `"false"`（必须关闭） |
| 图片比例 | 28 | aspect_ratio | 不传 | 带括号完整文本（如 `9:16 (Portrait Widescreen)`） |
| 自定义尺寸 | 28 | megapixels | 不传 | `"1"` / `"2"` / `"4"`（百万像素） |

### 比例映射（节点 28 aspect_ratio）

| 平台比例 | 工作流枚举值 |
|----------|--------------|
| 1:1 | `1:1 (Square)` |
| 2:3 | `2:3 (Portrait Photo)` |
| 3:2 | `3:2 (Photo)` |
| 3:4 | `3:4 (Portrait Standard)` |
| 4:3 | `4:3 (Standard)` |
| 9:16 | `9:16 (Portrait Widescreen)` |
| 16:9 | `16:9 (Widescreen)` |
| 21:9 | `21:9 (Ultrawide)` |

未知比例回落 `1:1 (Square)`。

## 接口调用

### 提交任务

**POST** `/openapi/v2/run/ai-app/2113539132868874242`（同 `qwen_multi_angle_runninghub_v1` 的 ai-app v2 接口）

```json
{
  "nodeInfoList": [ "…见上方节点映射…" ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}
```

### 状态查询

- **POST** `/task/openapi/status`：`{apiKey, taskId}`，`data` 为 `SUCCESS / FAILED / RUNNING`
- **POST** `/task/openapi/outputs`：成功后提取 `data[].fileUrl` 作为 `result_url`

### 参考图上传

参考图经 `RunningHubFileStorage.upload_file` 上传 RunningHub 图床，`fieldValue` 使用返回的 `key`（`pasted/…`）。上传失败直接抛错判 SYSTEM（避免过期签名 URL 透传导致下游 401 假象），第三方图床签名过期归为 USER 错误提示重新上传。

## 错误处理

与 RunningHub 族驱动一致：

- `errorCode=421`（api queue limit reached）：上游拥堵，返回 `retry=True, retry_reason=UPSTREAM_CONGESTED`，调度层自动延迟重试（不退算力、不消耗重试次数）
- 网络异常（ConnectionError/TimeoutError）：`retry=True`
- 业务错误（errorCode/errorMessage 非空）：USER 错误直接展示
- 响应格式异常 / 未预期异常：Sentry 报警 + SYSTEM 错误

## 注册点清单

| 位置 | 内容 |
|------|------|
| `config/unified_config.py` | `TaskTypeId.RUNNINGHUB_AI_APP_IMAGE = 52`、`DriverKey.RUNNINGHUB_AI_APP_IMAGE`、`DriverImplementation.RUNNINGHUB_AI_APP_IMAGE_V1`、`UnifiedTaskConfig` 条目（id=52）、`_LABELS` 显示名 |
| `config/constant.py` | `DRIVER_IMPLEMENTATION_MAPPING[runninghub_ai_app_image] = runninghub_ai_app_image_v1` |
| `task/visual_drivers/driver_factory.py` | `register_all_drivers()` 注册 |
| `config/model_catalog.py` | `MODEL_FAMILIES["runninghub-ai-app"] = "RunningHub"`（模型分组） |

算力预估（`power_confirm._estimate_image`）与模型列表（`/text-to-image-models` 等）均按统一配置自动生效，无需额外注册。

## 单元测试

`tests/drivers/test_runninghub_ai_app_image_v1_driver.py`：覆盖编辑/文生图两模式节点参数构建、比例与百万像素映射、多图截断、上传失败、提交成功/业务错误/上游拥堵/网络重试/图片过期、状态查询。
