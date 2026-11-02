# moss 文生图驱动 (runninghub_ai_app_moss_v1)

## 概述

用户可见模型名是 **moss**（`name` / `model_name` / `_LABELS`）。模型标识用 `TaskTypeId.MOSS_IMAGE` 与 `DriverKey.MOSS_IMAGE`，数字任务 id 53。RunningHub 只出现在实现层：本驱动通过 RunningHub OpenAPI v2 AI-App 接口对接图片工作流（webapp id `2112932052181016578`）。

**仅支持文生图**：

- 模型配置主分类即 `TEXT_TO_IMAGE`、`categories` 留空 → 前端只在文生图列表出现，图片编辑列表不可见（`UnifiedConfigRegistry.get_by_category` 按 `category` + `categories` 双向匹配）。
- 不支持宫格生图：`supports_grid_image=False`。
- 驱动对带参考图的提交直接拒绝（`submit_task` 返回 USER 错误「moss 模型仅支持文生图」），不静默忽略，避免用户误以为参考图生效。

- **webapp_id**：`2112932052181016578`（可用动态配置 `runninghub.ai_app_moss_webapp_id` 覆盖）
- **任务类型**：TaskTypeId.MOSS_IMAGE = 53
- **key / short_key**：`moss` / `moss`
- **DriverKey**：`moss_image`（模型驱动名，不带实现方）
- **实现方**：`runninghub_ai_app_moss_v1`（实现 id 107）
- **驱动类**：`RunninghubAiAppMossV1Driver`
- **分类**：`TEXT_TO_IMAGE`（主分类，唯一分类）
- **供应商**：`RUNNINGHUB`
- **算力**：`computing_power=1`（任务级覆盖值；实现方 `default_computing_power=1` 与之一致）

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 提示词 | 必填，完整画面描述，写入节点 1 | "" | - |
| 比例 | 写入节点 8 aspect_ratio | 9:16 | 1:1, 2:3, 3:2, 3:4, 4:3, 9:16, 16:9, 21:9 |
| 分辨率 | 映射为节点 8 megapixels（百万像素） | 2K | 1K(1), 2K(2), 4K(4) |

上游工作流默认出图为 1088x1920（9:16 + 2MP），故 `default_ratio='9:16'`、`default_size='2K'`。未知比例回落 `9:16 (Portrait Widescreen)`，非法分辨率回落 2 百万像素。

## 工作流节点映射

| 参数 | nodeId | fieldName | 取值 |
|------|--------|-----------|------|
| 画面比例 | 8 | aspect_ratio | 带括号完整文本（如 `9:16 (Portrait Widescreen)`） |
| 图片倍率 | 8 | megapixels | `"1"` / `"2"` / `"4"`（百万像素） |
| 提示词 | 1 | text | prompt |
| 步数 | 13 | steps | 固定 `"25"` |
| Lora权重 | 18 | strength_model | 固定 `"1"` |

### 比例映射（节点 8 aspect_ratio）

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

## 接口调用

### 提交任务

**POST** `/openapi/v2/run/ai-app/2112932052181016578`（Bearer 认证，`Authorization: Bearer <api_key>`）

```json
{
  "nodeInfoList": [ "…见上方节点映射…" ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}
```

成功响应含 `taskId`，驱动返回 `{"success": True, "project_id": taskId}`。`errorCode` / `errorMessage` 非空时：上游拥堵（421 api queue limit reached 等，`is_upstream_congested_error` 判定）返回 `retry=True + retry_reason=UPSTREAM_CONGESTED`，调度层延迟重试不消耗用户重试次数；其他业务错误返回 USER 失败。

### 状态查询

**POST** `/openapi/v2/query`（Bearer 认证，body 仅 `{taskId}`，v2 接口不再把 apiKey 放 body）。与 qwenimage2.1（v1 status + outputs 两步查询）不同，v2 query 一步返回状态与产物：

- `status == SUCCESS`：从 `results[].url` 提取产物图片 URL（优先 `outputType == 'png'`，否则取第一个带 url 的），返回 `SUCCESS + result_url`。链接 24 小时有效，调度层负责转存。`SUCCESS` 但无产物 URL 时保持 `SUCCESS + result_url=None` 走「任务成功但未返回结果URL」终态语义。
- `status == FAILED`：`errorMessage` 优先，为空回落序列化后的 `failedReason`，返回 USER 失败。
- `QUEUED / RUNNING / 其他`：返回 `RUNNING`。
- 查询网络异常/超时：返回 `RUNNING`（下一轮重试），不误判终态。
- 响应缺 `status` 字段（格式异常）：返回 SYSTEM 失败并 Sentry 告警。

## 注册点清单（新增同构模型时照抄）

1. `config/unified_config.py`：`DriverImplementation.RUNNINGHUB_AI_APP_MOSS_V1`（字符串）、`DriverImplementationId.RUNNINGHUB_AI_APP_MOSS_V1 = 107`、`IMPLEMENTATION_TO_ID` 映射、`DriverKey.MOSS_IMAGE`、`TaskTypeId.MOSS_IMAGE = 53` + `_LABELS`、`ALL_TASK_CONFIGS` 条目、`ImplementationConfig`（`required_config_keys=['runninghub.api_key']`）
2. `config/constant.py`：`VIDEO_DRIVER_MAPPING`（DriverKey → Implementation）加一行
3. `task/visual_drivers/runninghub_ai_app_moss_v1_driver.py`：驱动实现
4. `task/visual_drivers/driver_factory.py`：`register_driver` 注册
5. `web/js/admin.js`：driver_key 显示名 keyMap 加一行
6. 测试：`tests/drivers/test_runninghub_ai_app_moss_v1_driver.py`

无需数据库迁移（不涉及表结构变更）。无需改 `GENERATION_TOOL_REGISTRY`（复用既有 `generate_text_to_image` 工具，模型选择来自用户偏好/模型列表）。

## 单元测试

```bash
python -m pytest tests/drivers/test_runninghub_ai_app_moss_v1_driver.py -v
```

覆盖：比例/百万像素映射、请求结构（节点映射 + Bearer 头）、带参考图拒绝、提交成功/业务错误/上游拥堵/网络异常、v2 查询各状态分支、results 与 failedReason 解析、工厂注册（type 53）、统一配置注册（仅文生图可见、算力 1、不支持宫格）。
