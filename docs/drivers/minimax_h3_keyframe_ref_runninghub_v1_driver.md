# MiniMax H3 首帧参考混合驱动 (minimax_h3_keyframe_ref_runninghub_v1)

## 概述

通过 RunningHub AI-App 调用「全能参考+首帧+音频｜MiniMax H3声音角色双一致」。

画布上的分镜节点仍然停在参考模式。只有当前模型是 MiniMax H3 参考生视频，并且视频提示词里有 `@首帧图` 或 `@尾帧图` 时，这次提交才换成这个任务。`image_mode` 保持 `multi_reference`，不切到首帧模式。任务在模型下拉里隐藏。图生视频历史记录的类型列表包含隐藏任务，所以这条记录能在首页图生视频的历史里看到，类型名来自 `task_type_name_map`。`audio_path` 里逗号分隔的参考音频会在同一条历史里用播放器逐段显示。

有结束关键帧时，KFRef 指令要求大模型把镜头写成从首帧走到尾帧。原文里的「固定运镜」和起始姿势不能写成 fixed camera 或保持到结尾，结尾景别只由尾帧图决定。否则视频模型会停在首帧构图，尾帧对不上。

有起始关键帧时，KFRef 指令要求大模型保持开场时间线与首帧构图自洽：0.00 秒只允许出现首帧图里可见的人物，首帧图里没有的角色不得写成开场在场或「throughout」全程在场，必须写明第几秒入画（如 `walks into frame around the 2-second mark`），入画前反应画外处理，开头不安排切镜。否则视频模型为让对话成立，第 0 帧就改换构图（事故 ai_tools 13131：首帧图单人，成片首帧双人；同批 13129/13130 同图同病）。注意参考模式画布上首帧约束只是提示词软约束，提示词自身必须不与首帧图冲突。

指令还常驻「镜头指令保留」规则：原文里任何镜头运动描述（固定镜头/固定机位、推镜头、拉镜头、摇镜、跟随、手持等）必须原样保留到优化结果并遵守，不得删除、替换或弱化——固定镜头写成 `static locked-off shot`，禁止 push in / pull back / pan / tilt / zoom / dolly，原文构图与景别偏好通过人物走位和动作实现；推、拉、摇、移按原文方向与速度保留。规则常驻指令、由 LLM 按原文判断有无镜头描述，代码不做关键词枚举；唯一例外是存在结束关键帧时，镜头必须从首帧走到尾帧、固定镜头让位（既有 end_override 优先级；事故 ai_tools 13134：原文「固定镜头」被优化结果改写成 `pushes in slowly toward a medium close-up`，视频模型照做）。

- **webapp_id**：`2108549232725680129`
- **任务类型**：TaskTypeId.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO = 50
- **DriverKey**：`minimax_h3_keyframe_ref_to_video`
- **short_key**：`minimax_h3_kfr`
- **实现方**：`minimax_h3_keyframe_ref_runninghub_v1`（id=100）
- **驱动类**：`MinimaxH3KeyframeRefRunninghubV1Driver`
- **图片**：最多 3 张，来自 `reference_images`
- **音频**：最多 2 路，按 `audio_path` 顺序填节点 157（`<Audio 1>`）和 188（`<Audio 2>`）。fieldValue 用上传后的 fileName。没有对应音频时 fieldValue 是字符串 `None`。第 3 路及以后丢弃并记日志。**台词有无优先取优化步骤的 LLM 语义判断**（`extra_config.h3_prompt_optimize.has_dialogue`，能识别无引号台词、排除引号店名/标语），无标记（旧任务/优化禁用/回退原文存 null）时回退正则 `has_quoted_dialogue`（原文引号 CJK 片段）。**判无对白 → 不上传音频**：清空在上传循环之前完成，两路音频槽都填 `None`，用户手动上传的音频同样丢弃——`<Audio N>` 只有绑到要说新台词的角色身上才是音色参考，没有目标台词时连上的语音会被当成成片声音，叠在环境音上发糊；无对白且提示词残留「参考音频说明：…」句时同步剥除（该句带说话语义，会诱导视频模型让角色发声，dev3 案例 ai_tool 1816）。**判有对白 → 按提示词实际声明的 `<Audio N>` 数上传**：驱动解析优化结果里的声明（`_AUDIO_DECL_RE`），声明几路传几路，未声明的槽填 `None`——优化只给开口说话的角色写绑定句，单人说话镜头不再把非说话人音色挂槽（H3 会把无声明的人声错配给画面人物或混入成片，server8 分镜 2 事故）；回退原文/无优化记录时声明为 0，同样不上传（干净降级为模型自动配音）。Ref2VA 的音频行为不变
- **提示词优化**：`h3_prompt_optimize` 的 KFRef 变体，模板是 `task/pipeline_drivers/prompts/minimax_h3_kfref_en.txt`，不走 Ref2VA 六段结构。大模型必须按槽位逐字写出 `<Picture N> is the EXACT starting key frame at 0.00 seconds.`，以及 `<Picture N> is the EXACT ending key frame at {时长} seconds (ref_imageN).`。时长用本条任务的 `duration`（样例中的 10.00 只对 10 秒视频）。同时有首尾帧时，结束句对应 Picture 3，也就是 `ref_image3`。代码不把这两句拼进结果；校验失败会让大模型再写一次，仍失败则回退原文。输出走**首行 JSON 头协议**：`{"has_dialogue": true|false}`（LLM 对原文有无台词的语义判断）+ 空行 + 原样正文，代码强校验格式；判 `false` 时校验拒绝任何 `<audio` 出现。有台词且有可用音频时正文**只给实际开口说话的角色**写绑定句（`<Audio N> is the voice-timbre reference for <画面描述> (S1): ...`，编号取音色说明中该角色对应的音频号；不说话的角色不写，未声明的音频不上传），类型前缀随之追加 `audio reference`；说话人按发声顺序拿稳定 (S1)/(S2)，锚定优先级为参考图 > 外观+位置，角色名禁止作为唯一锚。步骤参数可带 `image_prompt_note`（分镜画面构成，绑定原料）。节点 138 用优化后的提示词。槽位从 `extra_config.h3_prompt_optimize.original_prompt` 解析，避免优化结果丢掉「图N是首帧」
- **参考视频**：不支持，提交时丢弃并记日志
- **查询接口**：`/task/openapi/status` + `/task/openapi/outputs`
- **配置**：复用 `runninghub.api_key` 和 `runninghub.host`，不新增配置键
- **算力**：与 MiniMax H3 参考生视频相同，720P 基表，480P × 0.42

## 槽位

| 点名 | Picture 1（node 137） | Picture 2（node 156） | Picture 3（node 187） |
|------|----------------------|----------------------|----------------------|
| 只有 `@首帧图` | 首帧 | 第 1 张参考，或空 | 第 2 张参考，或空 |
| 只有 `@尾帧图` | 第 1 张参考，或空 | 第 2 张参考，或空 | 尾帧 |
| 两个都有 | 首帧 | 至多 1 张参考，或空 | 尾帧 |

Picture 2 不是尾帧。空图片槽的 `fieldValue` 是空字符串。空音频槽的 `fieldValue` 是字符串 `None`。多出来的中间参考、第 3 路及以后的音频会被丢掉；无对白镜头（原文无引号台词）两路音频都不上传。

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
