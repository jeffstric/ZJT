# 按幕合并导出（已废弃）

原先设想：多条短分镜共享一条成片，导出时按 `clip_start` 合并 segment。

已改为火山剧创式拆分：**参考生视频在剧本拆分时就把单条分镜时长拉满到模型上限**（如 Seedance 2.0 的 15 秒），仍然一镜一条视频、整片按镜 concat。不再需要 `merge_id` / `clip_start`。

见拆分弹窗「视频生成方式」与 `pack_shots_for_reference_video`。
