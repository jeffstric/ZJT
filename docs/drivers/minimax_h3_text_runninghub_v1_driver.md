# MiniMax H3 文生视频驱动 (minimax_h3_text_runninghub_v1)

## 概述

纯提示词生成视频。通过 RunningHub AI-App 接口**复用「MiniMax H3 多参生视频」工作流**（与参考生视频驱动同一 webapp），所有素材槽位（9 张参考图 + 2 个参考音频 + 2 个参考视频）固定留空、音/视频旁路开关固定 `select=2`。

> **可行性验证**（2026-09，dev 环境）：空素材提交 webapp 实测任务 SUCCESS 出片（taskId `2097196166260416514`，5s/16:9/480P 耗时 128s、26 coins）。参考图 LoadImage 节点空槽不影响工作流执行；音/视频加载器经 ImpactSwitch 懒加载旁路。

- **webapp_id**：`2086470155902734337`（复用参考生视频工作流）
- **任务类型**：TaskTypeId.MINIMAX_H3_TEXT_TO_VIDEO = 45
- **DriverKey**：`minimax_h3_text_to_video`
- **实现方**：`minimax_h3_text_runninghub_v1`（id=84）
- **驱动类**：`MinimaxH3TextRunninghubV1Driver`
- **分类**：`TEXT_TO_VIDEO`（主分类，仅出现在文生视频入口）
- **提示词优化**：当前原样透传 `ai_tool.prompt`；驱动已预留 `extra_config.h3_prompt_optimize.optimized_prompt` 回读逻辑，未来新增 T2VA 变体时无需改驱动

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 提示词 | 必填，文本 | "" | - |
| 时长 | 秒 | 5 | 4, 5, 6, 7, 8, 9, 10 |
| 比例 | 视频比例 | 9:16 | 9:16, 16:9, 1:1, 4:3, 3:4, 2:3, 3:2, 21:9 |
| 分辨率 | 清晰度（影响算力，480P=720P×0.42） | 720P | 480P, 720P |

> **素材输入**：无任何图片/音频/视频输入。即使 `ai_tools` 记录残留素材路径（如模式误选），驱动也不上传、不填槽位。

### 算力对照表（复用 H3 族算力表）

| 时长(秒) | 720P(基准) | 480P(×0.42) |
|----------|------------|-------------|
| 4 | 5 | 3 |
| 5 | 6 | 3 |
| 6 | 8 | 4 |
| 7 | 9 | 4 |
| 8 | 10 | 5 |
| 9 | 11 | 5 |
| 10 | 13 | 6 |

## 工作流节点映射

与参考生视频版完全一致，区别仅在所有素材槽位固定留空、旁路开关固定 `2`：

| 参数 | nodeId | fieldName | 文生视频取值 |
|------|--------|-----------|--------------|
| 参考图1~9 | 137/139/142/147/149/150/151/152/153 | image | 固定 `""` |
| 参考音频1/2 | 155/163 | audio | 固定 `""` |
| 参考视频1/2 | 158/164 | video | 固定 `""` |
| 音频开关 | 167/168 | select | 固定 `"2"`（旁路） |
| 视频开关 | 165/166 | select | 固定 `"2"`（旁路） |
| 提示词 | 138 | value | prompt（优先优化结果） |
| 时长 | 132 | value | 秒数（INTConstant） |
| 比例 | 115 | aspect_ratio | 带括号完整文本（带 fieldData） |
| 分辨率 | 115 | megapixels | 0.4（480P）/ 0.9（720P） |

比例/分辨率映射、状态查询接口（`/task/openapi/status` + `/task/openapi/outputs`）与参考生视频版一致，见 [minimax_h3_reference_runninghub_v1_driver.md](minimax_h3_reference_runninghub_v1_driver.md)。

## 接口调用

### 提交任务

**POST** `/openapi/v2/run/ai-app/2086470155902734337`

请求体（素材槽位全空示例）：
```json
{
  "nodeInfoList": [
    {"nodeId": "137", "fieldName": "image", "fieldValue": "", "description": "图1"},
    {"nodeId": "139", "fieldName": "image", "fieldValue": "", "description": "图2"},
    {"nodeId": "142", "fieldName": "image", "fieldValue": "", "description": "图3"},
    {"nodeId": "147", "fieldName": "image", "fieldValue": "", "description": "图4"},
    {"nodeId": "149", "fieldName": "image", "fieldValue": "", "description": "图5"},
    {"nodeId": "150", "fieldName": "image", "fieldValue": "", "description": "图6"},
    {"nodeId": "151", "fieldName": "image", "fieldValue": "", "description": "图7"},
    {"nodeId": "152", "fieldName": "image", "fieldValue": "", "description": "图8"},
    {"nodeId": "153", "fieldName": "image", "fieldValue": "", "description": "图9"},
    {"nodeId": "155", "fieldName": "audio", "fieldValue": "", "description": "参考音频1"},
    {"nodeId": "167", "fieldName": "select", "fieldValue": "2", "description": "参考音频1开关"},
    {"nodeId": "163", "fieldName": "audio", "fieldValue": "", "description": "参考音频2"},
    {"nodeId": "168", "fieldName": "select", "fieldValue": "2", "description": "参考音频2开关"},
    {"nodeId": "158", "fieldName": "video", "fieldValue": "", "description": "参考视频1"},
    {"nodeId": "165", "fieldName": "select", "fieldValue": "2", "description": "参考视频1开关"},
    {"nodeId": "164", "fieldName": "video", "fieldValue": "", "description": "参考视频2"},
    {"nodeId": "166", "fieldName": "select", "fieldValue": "2", "description": "参考视频2开关"},
    {"nodeId": "138", "fieldName": "value", "fieldValue": "提示词", "description": "提示词"},
    {"nodeId": "132", "fieldName": "value", "fieldValue": "5", "description": "视频秒数"},
    {"nodeId": "115", "fieldName": "aspect_ratio", "fieldData": "...", "fieldValue": "16:9 (Widescreen)", "description": "长宽比"},
    {"nodeId": "115", "fieldName": "megapixels", "fieldValue": "0.9", "description": "视频分辨率"}
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}
```

## 建单链路

- 前端文生视频模式 → `POST /api/ai-app-run`（payload 仅 prompt/ratio/duration/resolution/task_id，无素材字段）
- 任务类型 45 不在 `_H3_PROMPT_OPTIMIZE_KEYS` 中，不走 param_prepare，建单即 `PENDING` 直接提交
- 无数据库迁移：`ai_tools.type` 直接落 45

## 关联事故说明

ai_tools 12307（2026-09-08）：`minimax_h3_image_to_video`（type=34）曾被错误挂载 `categories=[TEXT_TO_VIDEO]`，用户纯文字提交后在驱动层报"MiniMax H3 任务需要至少1张首帧图片"，用户侧只看到"服务异常"。本驱动接入的同时已摘除该错误挂载——文生视频入口现在展示真正的 `minimax_h3_text_to_video`。
