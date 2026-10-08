# 视频去水印驱动 (video_watermark_runninghub_v1)

## 概述

把用户视频交给 RunningHub AI-App「去水印去字幕去模糊高清」工作流，去掉短视频平台水印和字幕。调度进程负责上传视频和提交任务；HTTP 接口只保存文件、按秒扣算力并写入待处理任务。

- **webapp_id**：`2108118160242200577`
- **任务类型**：TaskTypeId.VIDEO_WATERMARK_REMOVE = 49
- **DriverKey**：`video_watermark_remove`
- **实现方**：`video_watermark_runninghub_v1`（id=99）
- **驱动类**：`VideoWatermarkRunninghubV1Driver`
- **分类**：`VISUAL_ENHANCE`
- **模型选择器**：`hidden=True`。不出现在图生视频等模型下拉里。画布上的「去水印」节点直接调用本接口。
- **权限点**：`video:watermark_remove`（当前登录即可）

上游文档：<https://www.runninghub.cn/call-api/api-detail/2108118160242200577?apiType=4>

## 算力

与 MiniMax H3 720P 共用 `MINIMAX_H3_720P_COMPUTING_POWER`。任务 `computing_power=0`，按实现方的时长表计费，不乘 480P 折扣。时长不在表内时接口直接拒绝，避免回退到表内第一档少扣算力。

| 时长(秒) | 算力 |
|----------|------|
| 4 | 5 |
| 5 | 6 |
| 6 | 8 |
| 7 | 9 |
| 8 | 10 |
| 9 | 11 |
| 10 | 13 |

## 工作流节点

| 参数 | nodeId | fieldName | 取值 |
|------|--------|-----------|------|
| 视频 | 5099 | video | 上传结果的 fileName，没有 fileName 时用 url |
| 提示词 | 5134 | text | 用户提示词；留空时用默认去水印提示词 |
| 视频时长 | 5145 | value | 秒，字符串，仅 4-10 |
| 每帧秒数 | 5146 | value | 帧率，默认 24，允许 1-120 |

`instanceType` 为 `default`，`usePersonalQueue` 为 `"false"`。多个视频路径只取第一个。

提交：`POST {runninghub.host}/openapi/v2/run/ai-app/2108118160242200577`

查询沿用现有 RunningHub 驱动：`POST /task/openapi/status`，成功后再 `POST /task/openapi/outputs`。结果优先取 mp4 / webm / mov / mkv。`errorCode=421` 按上游拥堵自动重试。

## 本服务接口

**POST** `/api/video-watermark-remove`

权限：`video:watermark_remove`。认证使用 `Authorization: Bearer`。算力扣费使用同一登录 token。

| 字段 | 位置 | 说明 |
|------|------|------|
| video | 文件 | 视频文件。与 `video_url` 同时存在时用文件 |
| video_url | 表单 | 已有视频地址 |
| duration_seconds | 表单 | 默认 5，仅 4-10 |
| fps | 表单 | 默认 24，范围 1-120，写入 `extra_config.fps` |
| prompt | 表单 | 可选，最多 2000 字 |
| user_id | 表单 | 可选；传入时必须等于登录用户 |

成功响应：

```json
{
  "success": true,
  "project_id": 123,
  "status": "submitted",
  "computing_power": 6,
  "duration": 5
}
```

`project_id` 是 `ai_tools.id`。记录状态为待处理，任务类型 49，由视频调度器调用本驱动。接口本身不请求 RunningHub。

## 画布节点

视频工作流「添加节点 → 去水印」（`web/js/video_watermark_node.js`，类型 `video_watermark`）：

1. 把视频节点的输出连到去水印节点的输入（松开在端口上，或拖到 50px 内吸附）。一个去水印节点只收一个视频。
2. 读到时长且四舍五入后在 4–10 秒内时，自动选中该秒数并显示算力，用户仍可改。读不到时长时由用户在 4–10 里选。超出 4–10 秒时按钮禁用，提示仅支持该范围。帧率固定 24，不在界面上改。提示词可空，空则用驱动默认提示词。
3. 提交 `POST /api/video-watermark-remove`（`Authorization: Bearer`，表单里带已有的 `video_url`）。成功后在右侧新建视频节点，写入 `project_id`，连线 `去水印 → 视频`。成片地址由现有 `poll-status` 在 `url` 为空时回填。
4. 重载走节点注册表。保存 `videoUrl`、时长、提示词、状态。提交时重新读当前连线，不只用上次记下的地址。断开连线或删掉源视频节点会清空预览。

本地还在上传（`blob:`）或成片还没回来的视频不能提交。

## 配置

复用已有 `runninghub.api_key` 与 `runninghub.host`，不新增配置键。
