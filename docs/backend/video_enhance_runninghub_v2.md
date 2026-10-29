# 视频高清修复（RunningHub 驱动模式）

## 架构

`/api/video-enhance` 采用 **visual_task 驱动模式**（与视频去水印同构）：

```
前端（灵感页/营销页）
  └─ POST /api/video-enhance        只落库 + 入队 + 预扣算力
       ├─ ffprobe 探测时长 → 吸附 4-15 档 → 按档算力（MiniMax H3 的 2 倍）
       ├─ ai_tools 落库（type=5, duration=档位, status=PENDING, video_path）
       └─ tasks 入队（TASK_TYPE_GENERATE_VIDEO / QUEUED）
调度器进程（task/visual_task.py）
  ├─ _submit_new_task → video_enhance_runninghub_v1 驱动
  │    ├─ 上传视频到 RunningHub（RunningHubFileStorage）
  │    └─ POST /openapi/v2/run/ai-app/2064116518987845634（Bearer 认证）
  └─ _check_task_status → 驱动轮询 v1 /task/openapi/status + /outputs
       └─ 成功 → _handle_task_success：结果下载缓存 + CDN 映射 + COMPLETED
         （解决 RunningHub 结果 URL 24 小时过期问题）
前端轮询 GET /api/get-status/{ai_tool_id}（tasks[0].status/results[].file_url）
失败 → 后台 _handle_task_failure 幂等退费（按落库 duration 档位还原）
```

## 注册链路

- `DriverKey.VIDEO_ENHANCE = 'video_enhance'`（unified_config）
- `DriverImplementationId.VIDEO_ENHANCE_RUNNINGHUB_V1 = 102`
- 任务配置 `TaskTypeId.VIDEO_ENHANCE`：provider=RUNNINGHUB、driver_name=DriverKey.VIDEO_ENHANCE（进 RUNNINGHUB_TASK_TYPES → 自动享受密钥池轮换与槽位管理）
- `DRIVER_IMPLEMENTATION_MAPPING`（config/constant.py）：`video_enhance → video_enhance_runninghub_v1`
- 驱动注册：`task/visual_drivers/driver_factory.py`
- 驱动实现：`task/visual_drivers/video_enhance_runninghub_v1_driver.py`

## RunningHub AI App 节点参数

App id 与节点参数常量在驱动文件顶部维护（仅驱动使用，惯例同去水印/音频驱动）：
`task/visual_drivers/video_enhance_runninghub_v1_driver.py` 的 `VIDEO_ENHANCE_*`。
时长上下限与 ffprobe 探测超时（端点与驱动共用）在 `config/constant.py`：

| 节点 | 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 46 | `video` | 上传后的 fileName | 上传视频 |
| 108 | `select` | `1` | 模型切换 |
| 112 | `value` | `1920` | 最大分辨率（用户可选，见下节参数 schema） |

## 用户参数 schema（配置驱动）

「视频高清放大」的用户可选参数由 **schema 唯一定义**于 `config/unified_config.py` 的
`VIDEO_ENHANCE_PARAMS_SCHEMA`（遵守常量集中管理约定），三者共用这一份事实来源：

1. **透出**：`UnifiedTaskConfig.params_schema`（非空时）经 `to_frontend_dict()` 挂在
   `GET /api/system/task-configs` 的 `video_enhance` 任务配置项下（key 为 `params_schema`），
   前端走既有 `TaskConfig.load()` 机制获取。
2. **接口校验**：`POST /api/video-enhance` 新增可选 Form 字段 `params`（JSON 字符串，
   如 `{"max_resolution":"1080"}`），经 `validate_video_enhance_params()` 校验
   （key 必须在 schema 中、value 必须在 options 白名单内），非法即 400 拒绝、不静默丢弃；
   合法则并入 `extra_config["params"]` 落库。**不传则不落 params**（库数据保持干净，
   缺省回落由驱动完成）。
3. **驱动映射**：`video_enhance_runninghub_v1` 驱动 `_resolve_schema_params()` 按 schema
   **列表驱动**逐项解析 `extra_config["params"]`（不信任库数据）：缺省回落 schema
   `default`，白名单外的非法值告警后回落 `default`；再按各项的 `node_id`/`field_name`
   映射进 RunningHub 节点值（本期即 node 112 `value`）。

**新增参数只需改 `VIDEO_ENHANCE_PARAMS_SCHEMA` 一处**（加一项
`key/label/type/options/default + node_id/field_name`），透出、校验、驱动映射、
前端表单即全部生效；若新参数映射到新节点，在驱动 `build_create_request()` 的
`node_info_list` 中追加该节点的显式构造即可（46/108/112 之外）。

**本期只开放 `max_resolution`（最大输出分辨率，node 112）**，原因是 node 108（模型）
合法取值未确认、instanceType 写死 `plus`（default=24G 显存实测 SeedVR2 必 OOM，见下），
均不对用户开放。

前端渲染见 `web/js/pages/video_enhance.js`：mounted 时 `TaskConfig.load()` 取
`video_enhance.params_schema` 动态渲染（本期仅 `select` 类型；schema 字段名经
`window.escapeHtml` 转义）；取不到 schema 时保持旧界面（无参数区、不传 params）。
schema 结构示例：

```json
[{"key": "max_resolution", "label": "最大输出分辨率", "type": "select",
  "options": [{"value": "720", "label": "720P"}, {"value": "1080", "label": "1080P"},
              {"value": "1440", "label": "1440P"}, {"value": "1920", "label": "1920P"}],
  "default": "1920", "node_id": "112", "field_name": "value"}]
```

- 提交：`POST /openapi/v2/run/ai-app/2064116518987845634`，`instanceType=plus`（48G 显存；default=24G 实测 SeedVR2 超分必 OOM，2026-10-28 任务 2115435158520954881 验证）
- 状态查询：v1 `/task/openapi/status` + `/task/openapi/outputs`（与去水印一致，v2 提交的任务用 v1 端点轮询已验证同池）
- **outputs 瞬时失败不得终态退费**：上游 status 已 `SUCCESS` 后，outputs 网络抖动/超时、421 拥堵、429 限流、5xx 返回 `RUNNING + preserve_retry_count=True`（对齐 `runninghub_ai_app_image_v1`），调度层自行安排结果获取且不消耗生成阶段 `try_count`；任务过期检查仍作最终兜底。其他非零业务错误码直接 `FAILED`。`code==0` 但没有视频地址仍 `FAILED`（视频任务必须有产物）。

## 算力：按视频秒数阶梯计费（= MiniMax H3 的 2 倍）

- 表：`config/unified_config.py` 的 `VIDEO_ENHANCE_COMPUTING_POWER`（由 `MINIMAX_H3_DIGITAL_HUMAN_COMPUTING_POWER` 逐档 ×2 生成），挂在任务 `TaskTypeId.VIDEO_ENHANCE` 上：

| 秒 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 算力 | 10 | 12 | 16 | 18 | 20 | 22 | 26 | 28 | 32 | 34 | 36 | 40 |

- 梯度同 MiniMax H3（4-15 档，含 11-15 秒外推档），**每档为 H3 对应档的 2 倍**。
- 时长来源：端点 ffprobe 探测（本站 /upload/ URL 转本地路径直探、远程 URL 拉流，超时 `VIDEO_ENHANCE_PROBE_TIMEOUT_SECONDS=15s`），**向上取整**吸附档位（7.3s→8 档）；探测失败回退表单 `duration_seconds`，两者皆缺则 400；超过 15 秒 400 拒绝。
- 扣费时机：提交前预扣（对齐去水印）；失败由后台 `_handle_task_failure` 幂等退费（退费金额按落库 `duration` 档位还原）。
- 前端预估：`web/js/pages/video_enhance.js` 选中视频后浏览器读取元数据时长，按与服务端相同的口径（向上取整、下限 4 秒）吸附档位，用 `TaskConfig.getComputingPower('video_enhance', 档)` 展示"预计消耗算力"；超 15 秒直接提示并禁用提交（与服务端 400 一致）；读取失败则提示以服务端 ffprobe 探测为准。

## 兼容说明

- 旧参数 `enhance_type`（5-直接上传/6-营销页历史）已废弃：落库 type 统一 `TaskTypeId.VIDEO_ENHANCE`（5），来源标记进 `extra_config.source`（direct/history）。
- 前端两入口改轮询 `/api/get-status/{ai_tool_id}`（响应 `tasks[0]`）；灵感页历史列表查询 type 由 4（图片放大的错值）修正为 5。
- `GET /api/runninghub-status/{id}` 回归纯 v1 轮询（图片高清放大等存量任务使用），失败退费逻辑抽为 `_refund_failed_runninghub_task()` 共用。

## 相关文件

- `config/constant.py`：时长边界/探测超时常量（端点与驱动共用）+ `DRIVER_IMPLEMENTATION_MAPPING` 登记
- `config/unified_config.py`：算力表、任务配置、实现方注册（ImplementationId 102）、`VIDEO_ENHANCE_PARAMS_SCHEMA`（用户参数 schema 唯一事实来源）与 `validate_video_enhance_params()`
- `task/visual_drivers/video_enhance_runninghub_v1_driver.py`：驱动（App id/节点参数/instanceType 常量 + 提交/轮询/告警/重试分类 + `_resolve_schema_params()` 参数解析回落）
- `server.py`：`_probe_video_duration_seconds()` / `_snap_duration_to_enhance_tier()` / `/api/video-enhance`（`params` 字段按 schema 校验后并入 `extra_config`）
- 前端：`web/js/pages/video_enhance.js`、`web/js/pages/ai_script_gen.js`
- 测试：`tests/api/test_video_enhance_v2.py`
