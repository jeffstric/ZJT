# MiniMax H3 首帧参考混合驱动 (minimax_h3_keyframe_ref_runninghub_v1)

## 概述

通过 RunningHub AI-App 调用「全能参考+首帧+音频｜MiniMax H3声音角色双一致」。

画布上的分镜节点仍然停在参考模式。只有当前模型是 MiniMax H3 参考生视频，并且视频提示词里有 `@首帧图` 或 `@尾帧图` 时，这次提交才换成这个任务。`image_mode` 保持 `multi_reference`，不切到首帧模式。任务在模型下拉里隐藏。图生视频历史记录的类型列表包含隐藏任务，所以这条记录能在首页图生视频的历史里看到，类型名来自 `task_type_name_map`。`audio_path` 里逗号分隔的参考音频会在同一条历史里用播放器逐段显示。

有结束关键帧时，KFRef 指令要求大模型把镜头写成从首帧走到尾帧。原文里的「固定运镜」和起始姿势不能写成 fixed camera 或保持到结尾，结尾景别只由尾帧图决定。否则视频模型会停在首帧构图，尾帧对不上。

- **webapp_id**：`2108549232725680129`
- **任务类型**：TaskTypeId.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO = 50
- **DriverKey**：`minimax_h3_keyframe_ref_to_video`
- **short_key**：`minimax_h3_kfr`
- **实现方**：`minimax_h3_keyframe_ref_runninghub_v1`（id=100）
- **驱动类**：`MinimaxH3KeyframeRefRunninghubV1Driver`
- **图片**：最多 3 张，来自 `reference_images`
- **音频**：最多 2 路，按 `audio_path` 顺序填节点 157（`<Audio 1>`）和 188（`<Audio 2>`）。fieldValue 用上传后的 fileName。没有对应音频时 fieldValue 是字符串 `None`。第 3 路及以后丢弃并记日志
- **参考视频**：不支持，提交时丢弃并记日志
- **提示词优化**：`h3_prompt_optimize` 的 KFRef 变体，模板是 `task/pipeline_drivers/prompts/minimax_h3_kfref_en.txt`，不走 Ref2VA 六段结构。大模型必须按槽位逐字写出 `<Picture N> is the EXACT starting key frame at 0.00 seconds.`，以及 `<Picture N> is the EXACT ending key frame at {时长} seconds (ref_imageN).`。时长用本条任务的 `duration`（样例中的 10.00 只对 10 秒视频）。同时有首尾帧时，结束句对应 Picture 3，也就是 `ref_image3`。代码不把这两句拼进结果；校验失败会让大模型再写一次，仍失败则回退原文。节点 138 用优化后的提示词。槽位从 `extra_config.h3_prompt_optimize.original_prompt` 解析，避免优化结果丢掉「图N是首帧」
- **查询接口**：`/task/openapi/status` + `/task/openapi/outputs`
- **配置**：复用 `runninghub.api_key` 和 `runninghub.host`，不新增配置键
- **算力**：与 MiniMax H3 参考生视频相同，720P 基表，480P × 0.42

## 槽位

| 点名 | Picture 1（node 137） | Picture 2（node 156） | Picture 3（node 187） |
|------|----------------------|----------------------|----------------------|
| 只有 `@首帧图` | 首帧 | 第 1 张参考，或空 | 第 2 张参考，或空 |
| 只有 `@尾帧图` | 第 1 张参考，或空 | 第 2 张参考，或空 | 尾帧 |
| 两个都有 | 首帧 | 至多 1 张参考，或空 | 尾帧 |

Picture 2 不是尾帧。空图片槽的 `fieldValue` 是空字符串。空音频槽的 `fieldValue` 是字符串 `None`。多出来的中间参考、第 3 路及以后的音频会被丢掉。

没有这两个标记时，前端不会提交这个任务。

## 工作流节点

| 参数 | nodeId | fieldName | 说明 |
|------|--------|-----------|------|
| Picture 1 | 137 | image | 图片用上传后的 url |
| Picture 2 | 156 | image | 参考图，不是尾帧 |
| Picture 3 | 187 | image | 结束关键帧，或第二张参考 |
| 音频 1 | 157 | audio | fileName；没有音频时为 `None` |
| 音频 2 | 188 | audio | fileName；没有第二路时为 `None` |
| 提示词 | 138 | value | 优化后的提示词 |
| 时长 | 132 | value | 4–10 秒 |
| 比例 | 115 | aspect_ratio | 与 H3 参考生视频相同的 8 个 COMBO 值 |
| 分辨率 | 115 | megapixels | 480P=`0.4`，720P=`0.9` |

这个应用没有 ImpactSwitch，也没有参考视频节点。
