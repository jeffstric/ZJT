# qwenimage2.1 图片驱动 (runninghub_ai_app_image_v1)

## 概述

用户可见模型名是 **qwenimage2.1**（`name` / `model_name` / `_LABELS`）。模型监督用 `TaskTypeId.QWEN_2_1_IMAGE` 与 `DriverKey.QWEN_2_1_IMAGE`，数字任务 id 仍是 52，不另建任务类型。RunningHub 只出现在实现层：本驱动通过 RunningHub AI-App 接口对接图片工作流（webapp id `2113539132868874242`），**同一工作流同时支持图片编辑与文生图**两种模式，由任务是否有参考图自动区分：

- **图片编辑**：`ai_tool.image_path` 携带 1-6 张参考图。开启「原图无偏移」（nodeId 25）后，采样画布跟随图 1，并四舍五入到 32 的倍数，节点 28 的百万像素不会改变编辑出图尺寸。驱动在上传前把图 1 覆盖裁切到所选比例和分辨率（与 ComfyUI ResolutionSelector 相同：百万像素 × 1024²，对齐 32）。4K + 16:9 为 2720×1536，4K + 1:1 为 2048×2048。图 2-6 保持原尺寸。节点 29「使用图片尺寸」保持关闭。
- **文生图**：`image_path` 为空，图片槽位全部填 `"None"`（工作流节点 16 `easy makeImageList` 的 `skip_empty=true` 自动忽略 None）；**必须关闭**节点 25/29（RunningHub 文档要求文生图关闭，否则画面偏移或报错），通过节点 28 显式指定比例与像素。

- **webapp_id**：`2113539132868874242`（可用动态配置 `runninghub.ai_app_image_webapp_id` 覆盖）
- **用户可见名**：`qwenimage2.1`（历史名 `RunningHub AI App 图片` / `RunningHub AI App` 仅作 `legacy_names` 反查）
- **任务类型**：TaskTypeId.QWEN_2_1_IMAGE = 52
- **key / short_key**：`qwenimage2.1` / `qwenimage2.1`（下拉选项的 value）
- **legacy_keys**：`runninghub-ai-app-image`、`runninghub-ai-app`（旧工作流节点存的 short_key，重载时改写成当前 short_key）
- **DriverKey**：`qwen_2_1_image`（模型驱动名，不带实现方）
- **实现方**：`runninghub_ai_app_image_v1`（类名与实现 id 101 不改）
- **驱动类**：`RunninghubAiAppImageV1Driver`
- **分类**：`IMAGE_EDIT`（主分类）+ `categories=[TEXT_TO_IMAGE]`（图片编辑与文生图入口同时可见）
- **供应商**：`RUNNINGHUB`（自动纳入 RunningHub 槽位与多密钥轮换体系）
- **多参考图上限**：6 张（图片节点 17-22）

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 提示词 | 必填；编辑模式为修改指令，文生图为完整画面描述 | "" | - |
| 参考图 | 编辑模式 1-6 张（逗号分隔 URL），文生图为空 | 空 | - |
| 比例 | 编辑与文生图都写入节点 28 | 1:1 | 1:1, 2:3, 3:2, 3:4, 4:3, 9:16, 16:9, 21:9 |
| 分辨率 | 文生图映射为节点 28 的 megapixels；编辑时另外把图 1 缩到同一画布 | 2K | 1K(1), 2K(2), 4K(4) |

## 工作流节点映射

| 参数 | nodeId | fieldName | 图片编辑取值 | 文生图取值 |
|------|--------|-----------|--------------|------------|
| 图1~图6 | 17/18/19/20/21/22 | image | 图 1 先缩到所选画布再上传；图 2-6 原图上传（不足补 `"None"`） | 固定 `"None"` |
| 提示词 | 23 | value | prompt | prompt |
| 使用反推 | 24 | value | 固定 `"false"` | 固定 `"false"` |
| 原图无偏移 | 25 | value | `"true"` | `"false"`（必须关闭） |
| 使用图片尺寸 | 29 | value | `"false"`（编辑尺寸由图 1 画布决定） | `"false"`（必须关闭） |
| 图片比例 | 28 | aspect_ratio | 带括号完整文本 | 带括号完整文本（如 `9:16 (Portrait Widescreen)`） |
| 自定义尺寸 | 28 | megapixels | `"1"` / `"2"` / `"4"`（百万像素） | `"1"` / `"2"` / `"4"`（百万像素） |

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

参考图经 `RunningHubFileStorage.upload_file` 上传 RunningHub 图床，`fieldValue` 使用返回的 `key`（`pasted/…`）。编辑模式会先把图 1 覆盖裁切到所选画布再上传，图 2-6 原样上传。上传失败直接抛错判 SYSTEM（避免过期签名 URL 透传导致下游 401 假象），第三方图床签名过期归为 USER 错误提示重新上传。

## 错误处理

与 RunningHub 族驱动一致：

- `errorCode=421`（api queue limit reached）：上游拥堵，返回 `retry=True, retry_reason=UPSTREAM_CONGESTED`，调度层自动延迟重试（不退算力、不消耗重试次数）
- 网络异常（ConnectionError/TimeoutError）：`retry=True`
- 业务错误（errorCode/errorMessage 非空）：USER 错误直接展示
- 响应格式异常 / 未预期异常：Sentry 报警 + SYSTEM 错误

## 注册点清单

| 位置 | 内容 |
|------|------|
| `config/unified_config.py` | `TaskTypeId.QWEN_2_1_IMAGE = 52`、`DriverKey.QWEN_2_1_IMAGE`、`DriverImplementation.RUNNINGHUB_AI_APP_IMAGE_V1`、`DriverImplementationId.RUNNINGHUB_AI_APP_IMAGE_V1 = 101`、`IMPLEMENTATION_TO_ID`、`ImplementationConfig`（缺这一项时提交会报没有可用实现方，历史驱动显示 `unknown`）、`UnifiedTaskConfig` 条目（id=52，key/short_key/显示名均为 `qwenimage2.1`，`legacy_keys` 保留旧 key）、`_LABELS` |
| `config/constant.py` | `DRIVER_IMPLEMENTATION_MAPPING[qwen_2_1_image] = runninghub_ai_app_image_v1` |
| `task/visual_drivers/driver_factory.py` | `register_all_drivers()` 注册实现类 `RunninghubAiAppImageV1Driver` |
| `config/model_catalog.py` | `MODEL_FAMILIES["qwenimage2.1"] = Qwen`。系列按当前 short_key 归组，不再用实现方 key |
| `web/js/admin.js` | `formatDriverKey('qwen_2_1_image')` 显示 `qwenimage2.1` |
| `web/js/task_config.js` | `legacy_keys` 参与匹配；`canonicalModelKey` 把旧 short_key 改写成 `qwenimage2.1` |

算力预估（`power_confirm._estimate_image`）与模型列表（`/text-to-image-models` 等）均按统一配置自动生效，无需额外注册。

## 单元测试

`tests/drivers/test_runninghub_ai_app_image_v1_driver.py`：覆盖编辑/文生图两模式节点参数构建、比例与百万像素映射、多图截断、上传失败、提交成功/业务错误/上游拥堵/网络重试/图片过期、状态查询。
