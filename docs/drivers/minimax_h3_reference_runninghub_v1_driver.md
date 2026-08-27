# MiniMax H3 参考生视频驱动 (minimax_h3_reference_runninghub_v1)

## 概述

通过 RunningHub AI-App 接口调用「MiniMax H3 多参生视频」工作流，支持最多 9 张参考图 + 2 个参考视频 + 2 个参考音频生成视频。

- **webapp_id**：`2086470155902734337`（自有账号复制版应用，复制自公共应用 `2084224746308325377`，并在其基础上新增了 4 个参考音视频 API 节点）
- **任务类型**：TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO = 37
- **DriverKey**：`minimax_h3_reference_to_video`
- **实现方**：`minimax_h3_reference_runninghub_v1`（id=67）
- **驱动类**：`MinimaxH3ReferenceRunninghubV1Driver`
- **图片模式**：多参考图模式（`multi_reference`），最多 9 张
- **参考音频/视频**：各最多 2 个（`ai_tool.audio_path` / `ai_tool.video_path`，逗号分隔 URL；`supports_ref_audio_video=True`）
- **提示词优化**：提交前经 `h3_prompt_optimize` 步骤按 Ref2VA 规范改写（见下文「提示词优化（Ref2VA）」）
- **查询接口**：`/task/openapi/status` + `/task/openapi/outputs`（与首尾帧版一致）

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 参考图 | 必填，1~9 张 | - | - |
| 参考音频 | 可选，1~2 个，独立参考音频（非参考视频音轨） | - | wav/mp3 等 |
| 参考视频 | 可选，1~2 个 | - | mp4 等 |
| 时长 | 秒 | 5 | 4, 5, 6, 7, 8, 9, 10 |
| 比例 | 视频比例 | 9:16 | 9:16, 16:9, 1:1, 4:3, 3:4, 2:3, 3:2, 21:9 |
| 分辨率 | 清晰度（影响算力，480P=720P×0.42） | 720P | 480P, 720P |
| 提示词 | 文本 | "" | - |

> **算力**：基准为 720P（1 算力 ≈ 13 R币），480P 为 720P 的 42%（通过分辨率倍率 `MINIMAX_H3_480P_PRICE_MULTIPLIER=0.42`）。
> 与首尾帧版共用算力表。

### 算力对照表

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

| 参数 | nodeId | fieldName | 说明 |
|------|--------|-----------|------|
| 参考图1 | 137 | image | LoadImage |
| 参考图2 | 139 | image | LoadImage |
| 参考图3 | 142 | image | LoadImage |
| 参考图4 | 147 | image | LoadImage |
| 参考图5 | 149 | image | LoadImage |
| 参考图6 | 150 | image | LoadImage |
| 参考图7 | 151 | image | LoadImage |
| 参考图8 | 152 | image | LoadImage |
| 参考图9 | 153 | image | LoadImage |
| 参考音频1 | 155 | audio | LoadAudio（fieldValue 取上传后的 fileName） |
| 参考音频2 | 163 | audio | LoadAudio（fieldValue 取上传后的 fileName） |
| 参考视频1 | 158 | video | VHS_LoadVideo（fieldValue 取上传后的 fileName） |
| 参考视频2 | 164 | video | VHS_LoadVideo（fieldValue 取上传后的 fileName） |
| 视频1开关 | 165 | select | ImpactSwitch（1=启用 158，2=旁路） |
| 视频2开关 | 166 | select | ImpactSwitch（1=启用 164，2=旁路） |
| 音频1开关 | 167 | select | ImpactSwitch（1=启用 155，2=旁路） |
| 音频2开关 | 168 | select | ImpactSwitch（1=启用 163，2=旁路） |
| 提示词 | 138 | value | 文本 |
| 时长 | 132 | value | INTConstant（秒） |
| 比例 | 115 | aspect_ratio | ResolutionSelector（带括号文本，带 fieldData） |
| 分辨率 | 115 | megapixels | ResolutionSelector（0.4/0.9） |

> **参考图填充规则**：用户传 N 张图时，按顺序填入前 N 个节点（上传后的图标识），剩余 9-N 个节点 `fieldValue` 留空（避免 RunningHub 用节点默认值）。
> 参考图固定 nodeId 列表（顺序敏感）：`["137","139","142","147","149","150","151","152","153"]`。
> **参考音频/视频同理**：按顺序填入 155/163（音频）、158/164（视频），未传时 `fieldValue` 留空；音/视频为独立映射，`audio_path[i]`→第 i 个音频节点、`video_path[i]`→第 i 个视频节点，互不关联。
> **旁路开关**：音/视频加载器经 ImpactSwitch（懒加载）接入 H3 节点——有文件时对应开关 `select=1`，无文件时 `select=2`；旁路时加载器不执行（空槽位不会报 `Please upload...` 错），H3 对应输入收到 None（等效未接线）。驱动对 4 个开关总是显式下发。

## 分辨率映射

复用首尾帧版 `MINIMAX_H3_DRIVER_VALUES`：

| 标准分辨率 | megapixels |
|------------|-----------|
| 480P | 0.4 |
| 720P（默认） | 0.9 |

> 注：工作流接口默认 megapixels=0.6（608×1056），本驱动按 480P/720P 标准档下发 0.4/0.9。

## 比例映射

| 比例 | aspect_ratio fieldValue |
|------|-------------------------|
| 1:1 | 1:1 (Square) |
| 16:9 | 16:9 (Widescreen) |
| 9:16 | 9:16 (Portrait Widescreen) |
| 4:3 | 4:3 (Standard) |
| 3:4 | 3:4 (Portrait Standard) |
| 2:3 | 2:3 (Portrait Photo) |
| 3:2 | 3:2 (Photo) |
| 21:9 | 21:9 (Ultrawide) |

## 提示词优化（Ref2VA）

参考生视频任务创建时，经 param_prepare 的 `h3_prompt_optimize` 步骤把用户原文改写成 MiniMax 官方 Ref2VA（full-reference）六段结构（规范来源：[MiniMax-H3 h3-prompt-writing ref-en.txt](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt)，剪枝版模板：`task/pipeline_drivers/prompts/minimax_h3_ref2va_ref_en.txt`）：

```text
subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape / non_diegetic_music
```

- **参考标签**：`<picture_N>` 对应第 N 张输入参考图，`<video_N>` 第 N 个参考视频，`<audio_N>` 第 N 个参考音频，`<subject_N>` 为从资产抽象的可复用内容；标签顺序与输入资产一一对应（步骤参数 `ref_counts` 携带图/视频/音频计数）。
- **对话保真**：六段结构描述文字输出英文，但 `<d>` 内台词/歌词及画面可见文字必须逐字保留原语言（标签按实际语言写，如 `[Chinese]`），严禁翻译；模板含中文对话正反例，原文含"引号包裹的 CJK 片段"时 user message 追加条件式点名指令，语义判断交给 LLM。
- **触发条件**：`pipeline.h3_prompt_optimize_enabled=true`（默认开）+ 至少一项参考资产；改写失败回退原文，不阻断出片。
- **驱动消费**：提交时优先使用 `extra_config.h3_prompt_optimize.optimized_prompt`，否则用 `ai_tool.prompt`（原文备份在 `extra_config.original_prompt`）。
- 机制详情（原子创建、模型回退链、超时）见 `docs/backend/pipeline_steps.md` 的 `h3_prompt_optimize` 章节。

## 接口调用

### 提交任务

**POST** `/openapi/v2/run/ai-app/2086470155902734337`

请求体（示例：3 张参考图 + 1 参考音频 + 1 参考视频）：
```json
{
  "nodeInfoList": [
    {"nodeId": "137", "fieldName": "image", "fieldValue": "参考图1标识", "description": "图1"},
    {"nodeId": "139", "fieldName": "image", "fieldValue": "参考图2标识", "description": "图2"},
    {"nodeId": "142", "fieldName": "image", "fieldValue": "参考图3标识", "description": "图3"},
    {"nodeId": "147", "fieldName": "image", "fieldValue": "", "description": "图4"},
    {"nodeId": "149", "fieldName": "image", "fieldValue": "", "description": "图5"},
    {"nodeId": "150", "fieldName": "image", "fieldValue": "", "description": "图6"},
    {"nodeId": "151", "fieldName": "image", "fieldValue": "", "description": "图7"},
    {"nodeId": "152", "fieldName": "image", "fieldValue": "", "description": "图8"},
    {"nodeId": "153", "fieldName": "image", "fieldValue": "", "description": "图9"},
    {"nodeId": "155", "fieldName": "audio", "fieldValue": "参考音频1 fileName", "description": "参考音频1"},
    {"nodeId": "163", "fieldName": "audio", "fieldValue": "", "description": "参考音频2"},
    {"nodeId": "158", "fieldName": "video", "fieldValue": "参考视频1 fileName", "description": "参考视频1"},
    {"nodeId": "164", "fieldName": "video", "fieldValue": "", "description": "参考视频2"},
    {"nodeId": "165", "fieldName": "select", "fieldValue": "1", "description": "参考视频1开关"},
    {"nodeId": "166", "fieldName": "select", "fieldValue": "2", "description": "参考视频2开关"},
    {"nodeId": "167", "fieldName": "select", "fieldValue": "1", "description": "参考音频1开关"},
    {"nodeId": "168", "fieldName": "select", "fieldValue": "2", "description": "参考音频2开关"},
    {"nodeId": "138", "fieldName": "value", "fieldValue": "提示词", "description": "提示词"},
    {"nodeId": "132", "fieldName": "value", "fieldValue": "5", "description": "视频秒数"},
    {"nodeId": "115", "fieldName": "aspect_ratio", "fieldData": "...", "fieldValue": "9:16 (Portrait Widescreen)", "description": "长宽比"},
    {"nodeId": "115", "fieldName": "megapixels", "fieldValue": "0.9", "description": "视频分辨率"}
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}
```

### 查询状态（与首尾帧版一致）

1. **POST** `/task/openapi/status`，body：`{apiKey, taskId}` → 返回 `data` 状态字符串
2. SUCCESS 后 **POST** `/task/openapi/outputs`，body：`{apiKey, taskId}` → 取首个 `fileUrl`

## 与首尾帧版 (minimax_h3_runninghub_v1) 差异

| 维度 | 首尾帧版 | 参考生视频版 |
|------|---------|-------------|
| webapp_id | 2086436470516174849 | 2086470155902734337 |
| 图片模式 | first_last_frame（首帧+尾帧） | multi_reference（1~9 张参考图） |
| 图片节点 | 114 首帧 / 145 尾帧 | 137/139/142/147/149/150/151/152/153 |
| 参考音频/视频节点 | 无 | 155/163（audio）、158/164（video），各最多 2 个 |
| 提示词节点 | 143 text | 138 value |
| 提示词优化变体 | I2VA / FL2VA | Ref2VA（六段结构 + 参考标签） |
| 时长节点 | 136 value | 132 value |
| 比例档位 | 5 档 | 8 档（多 2:3/3:2/21:9） |
| 算力/分辨率/查询接口/上传逻辑 | — | 完全复用 |
