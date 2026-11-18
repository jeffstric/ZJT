# 首帧参考混合收成参考生的一个实现方

状态：已实现（develop_f1186，见 h3_keyframe_ref_as_reference_impl_design.md）。本文是当时的方案决定记录。

> **2026-11-12 演进**：上游混合 webapp 扩到 6 图片槽后，本方案的「有输入条件的
> 实现方 + 提交期探测 + 裁到 3 张」整体退役——混合实现方现在是类型 37 参考生
> 的**无输入条件默认实现方**：点名首尾帧锁帧（KFRef 变体）、没点名全参考图
> （Ref2VA 变体），分派点在 `resolve_h3_prompt_variant`；probe/裁图/编排机制已删。
> 用户固定其他供应商时尊重偏好的决定不变。演进详情见设计文档头部更新块。

## 问题

带首帧的 H3 参考生现在会在提交前把任务从 `minimax_h3_reference_to_video`（类型 37）改成隐藏任务 `minimax_h3_keyframe_ref_to_video`（类型 50，短键 `minimax_h3_kfr`）。类型 50 只有一个实现方 `minimax_h3_keyframe_ref_runninghub_v1`。

用户的供应商偏好按任务键保存。固定在参考生上的 AutoDL 不会带到类型 50，所以「既有首帧又是参考生」总会走 RunningHub 混合模型，排不开、也切不走。

AutoDL 参考生（`zm_u24`）没有首帧槽，文字锚点锁不住第 0 秒。RunningHub 混合 webapp `2108549232725680129` 有 3 个图槽，能锁首尾帧。两种都应该留在参考生任务上，由已有的实现方排序、启用和用户固定来决定用哪一个。

## 决定

新提交不再创建类型 50。任务始终是类型 37，`image_mode` 仍是 `multi_reference`。`minimax_h3_keyframe_ref_runninghub_v1` 挂进类型 37 的 `implementations`，和 RunningHub 参考生、AutoDL 参考生并列。

它是有输入条件的实现方：提示词点了「图N是首帧」或「图N是尾帧」才兼容。没点名时跳过它，按排序用下一个参考生实现方。点了名时，用户固定的实现方优先；没固定才按 `sort_order`。

## 不做什么

- 不把首尾帧图生（类型 34）的实现方并进来。`minimax_h3_first_last_autodl_v1` 继续保持代码级关闭。
- 不删除类型 50 的枚举、历史 `ai_tools.type=50` 行、已有迁移。在途任务还要能轮询和优化。
- 不改混合 webapp 的槽位协议，仍是 3 图 + 2 音频。
- 不让 AutoDL 参考生假装能锁像素。用户固定 AutoDL 时就走 AutoDL。

## 选择规则

偏好键是 `minimax_h3_reference_to_video`。读取顺序沿用 `VideoDriverFactory._get_implementation_for_user`：先用户偏好，再按 `sort_order`，最后任务默认实现方。被禁用或初始化失败的实现方跳过。

在这三步里都要调用该驱动的 `validate_input_compatibility`。现在初次选择不调用这个钩子，只有失败重试才调用。不补上的话，混合实现方只要排序靠前，就会吃掉所有参考生提交，包括没有首帧的。

兼容判定：

| 实现方 | 点了首帧或尾帧 | 没点名 |
| --- | --- | --- |
| `minimax_h3_keyframe_ref_runninghub_v1` | 兼容 | 不兼容，跳过 |
| `minimax_h3_reference_runninghub_v1` | 兼容 | 兼容 |
| `minimax_h3_reference_autodl_v1` | 兼容 | 兼容 |

点名是指提交文本里的「图N是首帧 / 图N是尾帧」，不是节点上是否挂了首帧图。画布勾选「首帧自动带入提示词」时，现有 `ensureShotFrameMentionTokens` 会把标记写进提交文本，这条判定不用再猜节点状态。

固定偏好碰到不兼容时，沿用现在的固定语义：不静默换供应商，返回固定实现方不可用，并清掉这个固定。没固定的偏好不兼容时，落到排序上的下一个兼容实现方。

建议的代码默认排序（数字小的在前）：

| 实现方 | sort_order | 原因 |
| --- | --- | --- |
| `minimax_h3_keyframe_ref_runninghub_v1` | 5204 | 没设偏好且点了首尾帧时，默认仍走能锁帧的混合模型 |
| `minimax_h3_reference_runninghub_v1` | 5205 | 没点名时的默认参考生 |
| `minimax_h3_reference_autodl_v1` | 5208 | 保持现在的位置 |

管理页已有的 `implementation_power_config` 行是按 `(implementation_name, driver_key)` 存的。混合实现方旧行的 `driver_key` 是 `minimax_h3_keyframe_ref_to_video`，挂到参考生后对不上，不要把旧行的 enabled/sort 抄过来。新键没有记录时用上面的代码默认值。

显示名称不要再都叫 `RunningHub`。混合实现方改成 `RunningHub（首帧参考）`，说明里保留 webapp、3 图槽和 2 路音频。

没有偏好时的结果：

- 点了首尾帧：混合实现方。
- 没点名：RunningHub 参考生。
- 用户固定 AutoDL：两种提交都走 AutoDL。
- 用户固定普通 RunningHub 参考生：两种提交都走 9 图参考生，不锁帧。
- 用户固定混合实现方，但这次没点名：任务失败，不改走 AutoDL。
- 管理员关掉混合实现方：点了首尾帧时落到下一个兼容实现方。

## 提交顺序

先选实现方，再裁图。裁图依赖实现方，实现方依赖提示词里的标记和参考图是否存在，这两件事在建 `ai_tools` 行之前就有。

1. 排图：`@首帧图` / `@尾帧图` 仍把对应图片放到参考图列表两端。这一步所有参考生实现方都做。
2. 用本次的提示词、`image_mode`、参考图列表做兼容探测，选出实现方。探测对象只要带上 `validate_input_compatibility` 要读的字段，不必先插入数据库。
3. 选出的是混合实现方时，参考图裁到 3 张，音频裁到 2 路。两端的首尾帧保留，裁中间。其他实现方用各自的上限（参考生 9 张；AutoDL 音频最多 3 路）。
4. 扣费和创建都用类型 37，`implementation` 传选出的实现方 id。扣费必须按这个实现方查表，避免再按 RunningHub 参考生的价扣 AutoDL（事故 `ai_tools` 13452）。

画布和故事板都不要再改 `task_id`。删掉 `H3_KEYFRAME_REF_ROUTE_ENABLED` 以及前端把 `task_id` 换成 `minimax_h3_kfr` 的分支。前端不再按 3 张预先拦截；张数以服务端按实现方裁切为准。旧页面若仍提交 `minimax_h3_kfr`，服务端把它记成类型 37，实现方定为混合实现方，并打一条警告日志。不要再插入 `type=50`。

## 提示词优化

步骤仍按任务键创建。类型 37 已经在 `_H3_PROMPT_OPTIMIZE_KEYS` 里。变体不要再只看任务键：

- `ai_tool.implementation` 是混合实现方：用 KFRef 模板和槽位原句校验。
- 类型 37 的其他实现方：继续用 Ref2VA。原文点了首尾帧时，仍要求逐字带上 EXACT 锚点原句。AutoDL 锁不住像素，但这句保留。
- 历史 `type=50`：继续走 KFRef，给在途任务收尾。

无对白时删掉 `<audio_N>` 整句、小数点不切句，这两处已经在优化器里，不要回退。

角色音色、说话人过滤、无对白不注入音频，按类型 37 的现有口径执行。混合实现方需要的 `image_prompt_note` 改为「选出的实现方是混合模型」时写入，不再判断 `task_type == 50`。

## 类型 50

`UnifiedTaskConfig` 保留，`hidden=True`，再设 `enabled=False`，拒绝新的类型 50 创建。枚举、`DriverKey`、驱动类、实现方 id 100 都留着。`DRIVER_IMPLEMENTATION_MAPPING` 里类型 50 的映射可以留着，供旧行找驱动。

## 要改的位置

- `config/unified_config.py`：类型 37 的 `implementations` 加上混合实现方；类型 50 设 `enabled=False`；混合实现方的 `sort_order`、`display_name`、说明。
- `config/constant.py`：删除 `H3_KEYFRAME_REF_ROUTE_ENABLED`。映射表按上面决定保留或只加注释。
- `task/visual_drivers/driver_factory.py`：初次选择（偏好、排序、默认实现方）对候选调用 `validate_input_compatibility`。没传探测对象时保持现在的行为，避免别的任务被误伤。
- `task/visual_drivers/minimax_h3_keyframe_ref_runninghub_v1_driver.py`：实现兼容钩子。只接受参考模式且提示词点了首帧或尾帧的提交。
- `server.py` 的 `/api/ai-app-run-image`：用请求体做探测再选实现方；收到 `minimax_h3_kfr` 时改记类型 37。选出混合实现方后裁到 3 图 2 音频。
- `api/storyboard.py`、`services/storyboard_agent_cli_service.py`、`services/storyboard_frame_mention.py`：删除 `use_kfr` 改 `task_type`。排图和裁图拆开，裁图放在选出实现方之后。
- `task/pipeline_drivers/h3_prompt_optimize_util.py`：`resolve_h3_prompt_variant` 先看实现方，再看任务键。
- `web/js/shot_frame_video_generator.js`、`web/js/storyboard/frame_mention.js`：删除换 `task_id` 和前端 3 张上限。首尾帧排到列表两端的逻辑保留。
- 测试：`tests/task/test_h3_prompt_optimize.py`、`tests/task/test_pipeline_processor.py`、`tests/storyboard/test_storyboard_frame_mention.py`、`tests/storyboard/test_storyboard_agent_cli_service.py`、`web/tests/shot_frame_h3_keyframe_ref.test.js`、`web/tests/storyboard_frame_mention.test.js`，以及实现方选择、重试兼容的现有测试。补四条：固定 AutoDL 且点了首帧仍走 AutoDL；没偏好且点了首帧走混合实现方；没点名不走混合实现方；固定混合实现方但没点名则失败。
- 文档：`docs/video/shot_frame_video_mode.md`、`docs/storyboard/storyboard_reference_to_video.md`、`docs/storyboard/storyboard_auto_missing_videos.md`、`docs/drivers/minimax_h3_keyframe_ref_runninghub_v1_driver.md`、`docs/drivers/minimax_h3_reference_runninghub_v1_driver.md`、`docs/backend/pipeline_steps.md`。写完后删掉其中「改交隐藏任务 50」的说法。

## 验收

- 参考生、点了「图1是首帧」、用户固定 AutoDL：`ai_tools.type=37`，实现方是 `minimax_h3_reference_autodl_v1`，参考图不裁成 3 张。
- 同样的提交、没有偏好：`type=37`，实现方是 `minimax_h3_keyframe_ref_runninghub_v1`，参考图最多 3 张，首帧在第一张。
- 参考生、没点名、没有偏好：实现方是 `minimax_h3_reference_runninghub_v1`。
- 分镜齿轮和下拉模型仍保存参考生，不写成 50。
- 扣费按实际实现方的算力表。
- 旧的 `type=50` 行还能查状态，新请求不再产生 `type=50`。
