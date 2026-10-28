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
| 112 | `value` | `1920` | 最大分辨率（不建议超过 1920） |

- 提交：`POST /openapi/v2/run/ai-app/2064116518987845634`，`instanceType=plus`（48G 显存；default=24G 实测 SeedVR2 超分必 OOM，2026-10-28 任务 2115435158520954881 验证）
- 状态查询：v1 `/task/openapi/status` + `/task/openapi/outputs`（与去水印一致，v2 提交的任务用 v1 端点轮询已验证同池）

## 算力：按视频秒数阶梯计费（= MiniMax H3 的 2 倍）

- 表：`config/unified_config.py` 的 `VIDEO_ENHANCE_COMPUTING_POWER`（由 `MINIMAX_H3_DIGITAL_HUMAN_COMPUTING_POWER` 逐档 ×2 生成），挂在任务 `TaskTypeId.VIDEO_ENHANCE` 上：

| 秒 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 算力 | 10 | 12 | 16 | 18 | 20 | 22 | 26 | 28 | 32 | 34 | 36 | 40 |

- 梯度同 MiniMax H3（4-15 档，含 11-15 秒外推档），**每档为 H3 对应档的 2 倍**。
- 时长来源：端点 ffprobe 探测（本站 /upload/ URL 转本地路径直探、远程 URL 拉流，超时 `VIDEO_ENHANCE_PROBE_TIMEOUT_SECONDS=15s`），**向上取整**吸附档位（7.3s→8 档）；探测失败回退表单 `duration_seconds`，两者皆缺则 400；超过 15 秒 400 拒绝。
- 扣费时机：提交前预扣（对齐去水印）；失败由后台 `_handle_task_failure` 幂等退费（退费金额按落库 `duration` 档位还原）。

## 兼容说明

- 旧参数 `enhance_type`（5-直接上传/6-营销页历史）已废弃：落库 type 统一 `TaskTypeId.VIDEO_ENHANCE`（5），来源标记进 `extra_config.source`（direct/history）。
- 前端两入口改轮询 `/api/get-status/{ai_tool_id}`（响应 `tasks[0]`）；灵感页历史列表查询 type 由 4（图片放大的错值）修正为 5。
- `GET /api/runninghub-status/{id}` 回归纯 v1 轮询（图片高清放大等存量任务使用），失败退费逻辑抽为 `_refund_failed_runninghub_task()` 共用。

## 相关文件

- `config/constant.py`：时长边界/探测超时常量（端点与驱动共用）+ `DRIVER_IMPLEMENTATION_MAPPING` 登记
- `config/unified_config.py`：算力表、任务配置、实现方注册（ImplementationId 102）
- `task/visual_drivers/video_enhance_runninghub_v1_driver.py`：驱动（App id/节点参数/instanceType 常量 + 提交/轮询/告警/重试分类）
- `server.py`：`_probe_video_duration_seconds()` / `_snap_duration_to_enhance_tier()` / `/api/video-enhance`
- 前端：`web/js/pages/video_enhance.js`、`web/js/pages/ai_script_gen.js`
- 测试：`tests/api/test_video_enhance_v2.py`
