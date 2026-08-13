# AI Tools 流水线步骤机制

## 概述

Pipeline Steps（流水线步骤）是 `ai_tools` 处理流程的扩展机制，支持在任务提交前和执行结束后插入可异步处理的子步骤。

两个核心阶段：
- **param_prepare**（参数预处理）：在任务提交到外部 API 之前，对输入数据进行预处理（如 Seedance 2.0 / 2.0 Fast / 2.0 Mini 视频/图片人脸遮盖）
- **before_finish**（结束前处理）：任务失败后，自动切换不同供应商重试

> **适配模型清单（单一事实来源）**：param_prepare 人脸遮盖适用的 Seedance 模型统一维护在 `config/unified_config.py::SEEDANCE_FACE_MASK_DRIVER_KEYS`，`server.py` 闸门与 `PipelineDriverFactory` 均查询该集合，新增模型只需在此追加一项。

> **用户开关与版本门（opt-in）**：人脸遮盖改为**用户显式勾选才生效（默认不勾选）**。`/api/ai-app-run-image` 新增表单参数 `enable_face_mask: bool = Form(False)`；`server.py` 的 `need_pipeline_steps` 闸门最终为 `is_seedance_face_mask AND enable_face_mask AND (NOT Edition.is_community()) AND runninghub_api_key AND has_any_param_prepare_input`。
> - **未勾选 / 社区版**：闸门为假 → 走 `AIToolsModel.create`（普通生成，**不创建任何步骤**，避免卡在 `WAITING_PARAM_PREPARE`）。
> - **勾选 + 商业版**：走 `AIToolsModel.create_with_pipeline_steps`（建 `face_mask` / `image_face_mask` 步骤）。
> - 版本判断 `NOT Edition.is_community()` **必须**在闸门内，不能仅依赖 `create_with_pipeline_steps` 内部判断，否则社区版会把 ai_tool 以 `WAITING_PARAM_PREPARE` 落库却不建步骤，导致任务永久卡死。
> - 前端通过 `/api/system/task-configs` 下发的每模型标志 `needs_face_mask`（= `key in SEEDANCE_FACE_MASK_DRIVER_KEYS`）显隐「是否处理人脸」选项；社区版下选项仍显示但置灰提示「商业版功能」。智能体（marketing-video）路径经 `video_preferences.enable_face_mask` 透传同一开关。

## 状态机

```
                  [API 创建 ai_tool]
                         |
                         v
                   PENDING (0)
                    /         \
          [有 param_prepare]  [无步骤]
             步骤?               |
                |                v
                v          _submit_new_task()
      WAITING_PARAM_PREPARE (4)     |
                |                   v
      [所有步骤完成]         PROCESSING (1)
                |             /          \
                v      [成功]          [失败]
          PENDING (0)     |              |
                |         v              v
                |    COMPLETED (2)  [有 before_finish
                |                    步骤?]
                |                   /         \
                |            [有]             [无]
                |               |              |
                |               v              v
                |    WAITING_BEFORE_FINISH(5)  FAILED (-1)
                |               |
                |    [重试步骤选新供应商]
                |               |
                |               v
                +-------- PENDING (0)
                         (用新 implementation 重新提交)
```

### AI Tool 状态

| 状态值 | 名称 | 说明 |
|-------|------|------|
| 0 | PENDING | 待处理 |
| 1 | PROCESSING | 处理中（已提交到外部 API） |
| 2 | COMPLETED | 处理完成 |
| -1 | FAILED | 处理失败 |
| 3 | SYNC_QUEUED | 已提交到同步任务进程池 |
| **4** | **WAITING_PARAM_PREPARE** | 等待参数预处理步骤完成 |
| **5** | **WAITING_BEFORE_FINISH** | 等待结束前处理步骤完成（失败重试中） |

### Pipeline Step 状态

| 状态值 | 名称 | 说明 |
|-------|------|------|
| 0 | PENDING | 待处理 |
| 1 | PROCESSING | 处理中 |
| 2 | COMPLETED | 完成 |
| -1 | FAILED | 失败 |
| -2 | TIMEOUT | 超时 |

## 数据库表

### ai_tool_pipeline_steps

与 `ai_tools` 多对一关系，每个 ai_tool 可拥有多个流水线步骤。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| ai_tool_id | int | 关联 ai_tools.id |
| stage | varchar(32) | 阶段：`param_prepare` / `before_finish` |
| step_type | varchar(64) | 步骤类型：`face_mask` / `image_face_mask` / `implementation_retry` / `storyboard_first_frame_grid_split` / `h3_prompt_optimize` |
| step_order | int | 同阶段内执行顺序（0 起始） |
| status | tinyint | 步骤状态 |
| params | json | 步骤参数 |
| result_data | json | 步骤结果 |
| error_message | text | 失败原因 |
| async_task_id | int | 关联 async_tasks.id |
| retry_count | int | 重试次数 |
| next_retry_at | datetime | 下次重试时间 |
| max_retries | int | 最大重试次数（默认5） |

## 步骤类型

### h3_prompt_optimize（MiniMax H3 提示词优化）

用于 `param_prepare` 阶段，在 `TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO`（34）/ `TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO`（37）正式提交 RunningHub 前，把用户原文改写成官方 I2VA / FL2VA / Ref2VA 结构。

**触发条件**：任务类型为 MiniMax H3 图生视频（34）或参考生视频（37）+ `pipeline.h3_prompt_optimize_enabled=true`（默认开）+ 有可用输入（34 需至少一张首帧；37 需至少一项参考资产：参考图/参考视频/参考音频）。社区版同样执行。数字人 H3 不走此步。

**变体**：仅首帧 → I2VA；另有尾帧 → FL2VA；参考生视频（多参考资产）→ Ref2VA（官方 ref-en.txt 六段结构：`subject_definitions` / `summary` / `retention_analysis` / `detailed_description` / `overall_soundscape` / `non_diegetic_music`，步骤参数带 `ref_counts` 参考资产计数，供指令声明 `<picture_N>`/`<video_N>`/`<audio_N>` 与输入资产的顺序对应关系）。

**原子创建（无竞态）**：H3 入口（`server.py` / `api/storyboard.py`）判定 `needs_h3_atomic_param_prepare` 为真时，走 `AIToolsModel.create_with_pipeline_steps`，`ai_tool` 与 `h3_prompt_optimize` 步骤在同一事务内创建，避免调度器在两者之间抢先提交未优化任务。若事务内最终未产出任何步骤（如无首帧），则就地回退 `PENDING`。普通（非 H3 / 非 Seedance）图生视频直接以 `PENDING` 创建，不进流水线、零额外耗时。

**处理流程**：
1. `AIToolsModel.create_with_pipeline_steps` 在事务内创建 `h3_prompt_optimize` 步骤并置 `WAITING_PARAM_PREPARE`；故事板入口会把用户选的对话模型写入步骤参数（`chat_model`/`chat_vendor_id`）
2. `H3PromptOptimizePipelineDriver` 用剪枝版官方规范 + 中文改写指令 + 原文调用聊天模型（`asyncio.to_thread` + `wait_for` 90s）
3. 结构校验失败重试 1 次，仍失败则回退原文（`fallback=true`），**不把步骤标 FAILED**，避免整单退费
4. 原文写入 `extra_config.original_prompt`（只写一次）和 `extra_config.h3_prompt_optimize`
5. `ai_tool.prompt` 替换为优化结果，H3 驱动提交 RunningHub

**模型回退链**：所用聊天模型按优先级选取，每步校验 api_key 是否已配置，首个可用者胜出：① 故事板步骤参数中的对话模型 → ② `pipeline.h3_prompt_optimize_model`（默认 `deepseek-v4-flash`）→ ③ 剧本拆分默认模型 `gemini-3-flash-preview`。独立图生视频入口无故事板上下文，跳过第 ① 步。全部未配置则直接回退原文，不发起必败调用。

**超时**：`H3_PROMPT_OPTIMIZE_TIMEOUT=90s`，同时作为外层 `wait_for` 与底层 `request_timeout`（对齐 httpx，避免超时后线程残留）；重试 1 次，最坏约 180s 后回退原文。

**配置**：`pipeline.h3_prompt_optimize_enabled` / `pipeline.h3_prompt_optimize_model` / `pipeline.h3_prompt_optimize_vendor_id`

### face_mask（人脸遮盖）

用于 `param_prepare` 阶段，在 Seedance 2.0 等需要处理含人脸视频的场景中，先将视频中的人脸遮盖掉。

**触发条件**：Seedance 2.0 / 2.0 Fast / 2.0 Mini 任务类型 + 用户勾选 `enable_face_mask=true` + 商业版（非社区版）+ `pipeline.seedance_face_mask_enabled=true` + 有 video_path 输入

**遮盖语义**：单帧 ComfyUI 工作流 `人脸识别_单帧.json` 不再在检测前 resize，YOLOv8 的 `BBOX Detector (combined)` 直接在原图上生成整图尺寸的 bbox 矩形 mask，再通过 `8x8` 黑色图像按 mask 拉伸合成回原图。遮盖区域以检测框 `x1/y1/x2/y2` 为基础，并使用 `dilation=128` 增加安全边距，补偿 YOLO face bbox 在侧脸、头发遮挡、扇子遮挡、局部置信度偏高时只框住人脸核心区域的问题；它不是 SEGS 裁剪图或人脸轮廓分割区域，避免出现纯黑背景里残留脸部裁剪图的结果。

**处理流程**：
1. FaceMaskPipelineDriver 调用 RunningHubFaceMaskDriver.submit_with_slot_management()；提交前先将本地视频用 ffmpeg 按帧 PTS 归一化为固定 CFR（`MediaConstants.FACE_MASK_CFR_FPS`，24fps），并按 `FACE_MASK_UPLOAD_MAX_SHORT_SIDE`（512px）等比缩短边后上传——VFR webm 的帧率元数据不可信，RH 端（ComfyUI `VHS_LoadVideo`）对 VFR 源的解码帧数/时间轴与本地不一致且逐次不同，直接上传会导致遮罩时间轴漂移；短边缩放用于防止 1080p 等大视频在 RH 端全量加载时爆显存（OOM_KILLED）
2. 创建 async_task 记录（implementation=RUNNINGHUB_FACE_MASK）
3. 槽位满时自动安排重试（指数退避：30s → 60s → 120s → 300s）
4. 后台任务 process_pending_async_task_submissions() 负责重试提交
5. process_runninghub_async_tasks() 轮询 async_task 状态
6. 完成后将遮盖后的视频 URL 写入 step.result_data
7. PipelineProcessor 将结果应用回 ai_tools.video_path

**本地叠加融合（`utils/face_mask_util.py` 的 `overlay_face_mask`）**：帧率元数据对浏览器录制的 VFR webm 完全不可信（可能把时间基误报为 1000fps，也可能误报看似合理但与时长矛盾的 60fps），因此一律不信任元数据：融合前先用 ffmpeg 按每帧 PTS 时间戳把原视频和 RunningHub 遮罩视频统一重采样为固定 CFR（`MediaConstants.FACE_MASK_CFR_FPS`，24fps，与 RH 输出一致），时长保持不变。

**遮罩逐帧对齐（关键）**：RH 工作流中的 `ImpactSEGSToMaskBatch` 对一帧的**每个检测框**各产出一个 mask（如人脸 + 画面内印刷照片误检），直接累积会让遮罩流比视频帧数多且错位（事故实证：268 帧视频产出 307 帧遮罩，错位集中在前段）。因此 RH 工作流（App `2085225276274987010`，工作流 JSON 在 RunningHub 侧维护、不上库）把每帧的检测批**用全黑 mask 补齐到固定 3 个后取 OR 并集**（ImageFromBatch 下标越界会报错，补齐是为了兼容检测数不足的帧；全部使用 MaskToImage/ImageFromBatch/ImageToMask/InvertMask/MaskComposite/easy batchAnything 等核心或已验证节点），保证每帧恰好输出 1 个 mask、与源视频严格 1:1，且同帧多个人脸（最多 3 个）都能遮盖；不做全帧 IMAGE 合成，显存占用与旧版相当。融合侧 `_split_mask_video` 兼容含全白分隔帧的历史格式；帧数比例映射（`_map_mask_frame_index`）兜底零星出入，越界冻结最后一帧，不回绕到第 0 帧。输出同为 24fps，保证与原视频时长、音频同步。严禁回到"按元数据帧率/裸检测框流直接配对"的做法，否则遮罩会随时间漂移、输出时长与音频错乱。

**调试产物**：配置 `pipeline.face_mask_debug_keep`（默认 `true`）开启后，每次融合在 `upload/cache/face_mask_debug/task_<async_task_id>_<时间戳>/` 下保留各阶段产物：`source_input<ext>`（浏览器上传的原始视频，未经任何处理）、`original_cfr.mp4`（原视频 CFR 中间产物，等同于上传给 RH 的内容）、`mask_source.mp4`（RH 返回的遮罩源）、`mask_cfr.mp4`（遮罩 CFR 中间产物）。同时叠加日志会打印原视频元数据帧率（仅供参考，不参与决策）。

### image_face_mask（图片人脸遮盖）

用于 `param_prepare` 阶段，在 Seedance 2.0 / 2.0 Fast / 2.0 Mini 的图生视频任务提交前，对 `image_path` 和 `reference_images` 中的人脸绘制红色矩形网格。

**触发条件**：Seedance 2.0 / 2.0 Fast / 2.0 Mini 任务类型 + 用户勾选 `enable_face_mask=true` + 商业版（非社区版）+ `pipeline.seedance_face_mask_enabled=true` + 有 `image_path` 或 `reference_images` 输入

**配置开关**：`pipeline.seedance_face_mask_enabled`，默认 `true`，是 Seedance 人脸遮盖前置处理的**总开关**（管理员级），同时控制图片（`image_face_mask`）和视频（`face_mask`）两种遮盖步骤。关闭后图片和视频的遮盖步骤均不创建，任务走普通生成流程。其上还有两层用户/版本级门：用户级 `enable_face_mask`（前端「是否处理人脸」勾选，默认不勾选，**opt-in**）与版本级 `NOT Edition.is_community()`（社区版禁止），三者同时满足才会创建步骤（见上文「用户开关与版本门」）。

**处理语义**：调用 RunningHub AI App `2067560129192620033`，将输入图片上传后映射到节点 `3` 的 `image` 字段。RunningHub 返回的矩形黑块图只作为人脸检测中间结果；系统下载原图和黑块图，通过新增黑色区域提取每张脸的独立矩形框，再在原图副本上绘制红色网格。网格内部保留原始像素，不填充色块。

图片差异提取、矩形吞噬和红色网格绘制属于商业实现，位于 `enterprise/services/face_mask/image_face_grid.py`。主仓库 `utils/image_face_grid_util.py` 只保留稳定调用门面，由 `enterprise.register()` 注册真实 Provider；社区版不包含该算法。

网格行列数按人脸框短边像素分档：`<80px` 使用 3×3、`80–159px` 使用 5×5、`160–319px` 使用 8×8、`>=320px` 使用 10×10。小脸因此不会被过密线条覆盖，多脸图片中的每个矩形框分别绘制。

网格线宽按吞噬后的最终矩形数量（与人脸数相关）统一分档：1–5 个矩形使用 `3px`，6–10 个使用 `4px`，11 个及以上使用 `5px`（`ImageFaceGridConstants.GRID_LINE_WIDTH_TIERS` / `GRID_MAX_LINE_WIDTH`）。同一张图片中的所有网格使用相同线宽，并继续采用 OpenCV `LINE_8` 硬边绘制。更粗线宽会抬高生成视频前缀检测时的组件 fill ratio，需与下方裁剪检测阈值配套。

矩形绘制前会删除被更大矩形 100% 完全包含的小矩形，避免大网格内部重复出现小网格；部分重叠、边缘接触和相邻矩形仍分别保留。线宽数量在该吞噬步骤之后计算，因此已删除的小矩形不会使线条增粗。

**失败回退**：黑块图下载失败时任务后处理失败；原图下载、矩形提取或网格写入失败时回退到已经下载的 RunningHub 黑块图，不会回退到未经处理的原图。缓存便捷函数下载失败可能返回原远程 URL，处理器会显式拒绝该值，避免将无效 `/https://...` 路径写入任务结果。

**处理流程**：
1. ImageFaceMaskPipelineDriver 调用 RunningHubImageFaceMaskDriver.submit_with_slot_management()
2. 创建 async_task 记录（implementation=RUNNINGHUB_IMAGE_FACE_MASK）
3. 槽位满时自动安排重试（指数退避：30s → 60s → 120s → 300s）
4. process_runninghub_async_tasks() 轮询 RunningHub v2 任务状态
5. 完成后下载并缓存 RunningHub 黑块图，同时取得原始图片
6. 从两图差异提取多个人脸矩形框，在原图副本上绘制自适应红色网格
7. 网格转换失败时安全回退黑块图，将最终本地相对路径写入 `step.result_data`
8. PipelineProcessor 根据 step.params 中的 `field` 和 `index` 回写 `ai_tools.image_path` 或 `ai_tools.reference_images`

### 生成结果视频的人脸网格前缀裁剪

`image_face_mask` 是输入图片预处理步骤，但它绘制的红色人脸网格可能短暂出现在生成视频开头。任务生成成功后，系统会在写入 `COMPLETED` 终态前调用 `services/generated_video_face_grid_service.py` 公共门面；实际检测、门控和裁剪位于 `enterprise/services/face_mask/`。

**门控条件**：仅当结果媒体类型为 `video`，且当前 `ai_tool_id` 存在已完成的 `image_face_mask` 步骤时处理。开关 `GeneratedVideoFaceGridTrimConstants.ENABLED` 关闭、图片结果、未命中步骤或远程 URL fallback 都保持原 URL，不运行视频裁剪。

**裁剪语义**：只扫描视频起始 `0.5` 秒；使用 FFprobe 的帧 PTS 找到最后一个网格帧，并从其后的精确下一帧时间戳开始裁剪，不使用固定帧率估算。帧加载采用 **ffprobe + ffmpeg 双路**：ffprobe 以显示序 PTS 取时间戳（`read_intervals` 窗口），ffmpeg 以解码墙钟取 rawvideo 像素（`-t` 窗口）。两路在 H.264 B 帧 / PTS 漂移 / VFR 场景下，可能在窗口末尾差 1~2 帧；此时按**公共前缀对齐**（`min(probe_count, raw_count)`）截断，而非要求帧数严格相等。边界帧落在约 `0.5~1.0s`（look-ahead 窗口），而检测只消费前 `SCAN_SECONDS=0.5s`，丢弃末尾边界帧不影响裁剪点。不一致时默认打 `warning` 日志（`FRAME_COUNT_MISMATCH_LOG_ENABLED`）。

**网格检测 fill 容差**：`detect_face_grid_frame` 用连通域 + 投影线/交点结构识别红网格，并以 `MAX_COMPONENT_FILL_RATIO=0.7` 过滤实心红块。图片侧线宽随人脸数分档为 3–5px，叠加 8×8 密度与 480p/H.264 压缩时，真实网格组件 fill 实测可达约 `0.46–0.60`（旧阈值 `0.4` 会误杀为 `no_grid`）。实心色块 fill≈1.0 仍被阈值拒绝，且投影结构（线数/交点）也会拒绝无网格纹理的色块。未发现网格时原样返回；探测、解码、帧分析、转码、校验或路径映射异常均 fail-open，保留原 URL，不把普通后处理失败升级为生成任务失败。

**完成路径**：

1. `download_queue_task` 在远程结果下载成功后异步处理，并将同一个 `postprocess.result_url` 写入 `ai_tools`、`download_queue` 和完成日志。
2. `visual_task` 的同步返回、本地结果及下载队列入队失败 fallback，在终态更新前 `await` 异步服务；成功入队时不重复处理，由 download worker 独占该步骤。
3. `sync_task_executor` 只在实际任务工作进程内完成本地/缓存结果处理，再构造 `SyncTaskResult`；调度线程的 `_handle_task_result()` 仅持久化结果，不运行 FFmpeg。

异步入口使用非阻塞子进程和有界门控查询线程池。download queue 的租约满足“下载超时 + 视频后处理总预算 + 完成落库余量”的硬约束，避免后处理期间被下一轮 worker 误回收。

### implementation_retry（实现方重试）

用于 `before_finish` 阶段，任务失败后自动切换供应商重试。

**触发条件**：主任务失败 + 存在替代实现方

**处理流程**：
1. 从 UnifiedConfigRegistry 获取同任务类型的可用实现方列表
2. 排除已经实际尝试过、已禁用或无法初始化的实现方，只选择优先级最高的 **1 个**替代实现方
3. 为该实现方创建唯一一个 `implementation_retry` 步骤；不会提前为后续实现方创建候选步骤
4. retry driver 先切换 `ai_tools.implementation` 并记录新的 implementation attempt，最后才把 `tasks.status` 改为 QUEUED
5. 主调度器只抓取 QUEUED 任务，因此抓到时 implementation 和 attempt 已经是新的供应商
6. 如果新供应商再次真实失败，再由失败入口按同样规则创建下一个唯一候选
7. 初始供应商之外最多尝试 3 个不同的备用供应商，即最多形成 `A → B → C → D`；达到上限或没有可用实现方后进入终态失败

步骤参数使用 `retry_mode=single_candidate_v1` 标识新模式，并记录 `retry_index`、`attempt_number`、`target_implementation` 与失败来源。升级前已经存在的多候选步骤仍兼容处理：只执行第一个，其余旧候选标记为 `legacy_multiple_candidates`，不会同时切换多个供应商。

**无锁顺序交接**：失败处理先将当前 attempt 标记失败，再把 `ai_tools/tasks` 设为 `WAITING_BEFORE_FINISH`，最后才创建唯一 PENDING 步骤；retry driver 先写入新 implementation 和 attempt，最后才把 `tasks` 设为 QUEUED。标准启动方式只运行一个 scheduler，两个 Job 各自 `max_instances=1`，因此不增加事务封装、应用锁或分布式锁。

**失败路径统一入口**：所有任务失败路径（driver 创建失败、提交失败、状态检查异常等）均通过 `_handle_task_failure()` 统一处理，由其调用 `handle_failure_with_retry()` 尝试切换供应商。无可用替代供应商时走终态失败 + 退费。

### storyboard_first_frame_grid_split（分镜首帧宫格拆分）

用于 `before_finish` 阶段，将分镜首帧宫格图（grid image）拆分为各场景的独立首帧并落库。

> **关联键说明**：该步骤类型通过 `params.grid_task_id`（= `grid_image_tasks.id` 主键）与宫格任务关联，**不依赖** `ai_tool_id == grid_image_tasks.project_id` 这一等式。原因是宫格图重试时 `_resubmit_image_request` 会新建一条 `ai_tools` 记录，`reset_for_retry` 把 `grid_image_tasks.project_id` 更新为新 `ai_tool_id`，导致 `project_id` 漂移；而 `grid_task_id` 主键在重试中保持稳定。因此 step 的查找（成功路径 dispatch）、失败回写、孤儿清理统一按 `params.grid_task_id` 关联。

**生命周期**：
1. 提交宫格 i2i 任务时（`mcp_tool.submit_grid_image_task`）**预建** PENDING 步骤，`params.grid_task_id` = 新建的 `grid_image_tasks.id`
2. 宫格图成功后（`_dispatch_storyboard_first_frame_grid_split`）按 `grid_task_id` 找到预建步骤，校准 `params`（补充重试后的最新宫格图数据），再 dispatch
3. 步骤被 `_is_grid_task_owned_step` 识别，**不**由全局 `process_pipeline_steps` 调度器执行，而由 `grid_image_task` 调度器主动 dispatch
4. 宫格图失败时（`_fail_pending_grid_split_step_for_task`）按 `grid_task_id` 将仍 PENDING 的步骤标记 FAILED
5. 孤儿兜底清理（`_cleanup_orphan_grid_split_steps`，每轮 grid 调度开头）按 `grid_task_id` JOIN `grid_image_tasks`，对已进入终态（含 COMPLETED 与各失败终态）但仍 PENDING 的孤儿步骤批量 FAILED

## 文件结构

```
model/
  ai_tool_pipeline_steps.py      # 数据库模型
task/
  pipeline_processor.py          # 编排器核心
  pipeline_drivers/
    __init__.py                  # 驱动工厂 + 步骤创建规则
    base_pipeline_driver.py      # 驱动抽象基类
    face_mask_driver.py          # 人脸遮盖驱动
    image_face_mask_driver.py    # 图片人脸遮盖驱动
    implementation_retry_driver.py  # 供应商重试驱动
    storyboard_grid_split_driver.py  # 分镜首帧宫格拆分驱动
  grid_image_task.py             # 宫格任务调度（含 grid split step dispatch/fail/孤儿清理）
scripts/
  cleanup_stale_grid_split_steps.py  # 一次性清理僵尸 grid split step 的运维脚本
```

## 调度

`scheduler.py` 中注册了 `process_pipeline_steps` 定时任务（每 13 秒），负责：
1. 查询所有 PROCESSING 状态的 pipeline steps
2. 检查关联 async_task 的状态
3. 推进步骤和 ai_tool 的状态

## 服务重启恢复

服务重启时，`_reset_orphan_processing_tasks()` 会将所有 WAITING_PARAM_PREPARE 和 WAITING_BEFORE_FINISH 状态的任务重置为 PENDING，让调度器重新检查 pipeline 步骤。

## 监控 SQL

```sql
-- 查看当前流水线步骤状态分布
SELECT stage, step_type, status, COUNT(*) as cnt
FROM ai_tool_pipeline_steps
GROUP BY stage, step_type, status;

-- 查看卡住的步骤（PROCESSING 超过 10 分钟）
SELECT id, ai_tool_id, stage, step_type, async_task_id, updated_at
FROM ai_tool_pipeline_steps
WHERE status = 1 AND updated_at < NOW() - INTERVAL 10 MINUTE;

-- 查看待重试的步骤
SELECT
    id,
    ai_tool_id,
    stage,
    step_type,
    retry_count,
    max_retries,
    next_retry_at
FROM ai_tool_pipeline_steps
WHERE status = 0
  AND next_retry_at IS NOT NULL
  AND next_retry_at <= NOW()
  AND retry_count < max_retries
ORDER BY next_retry_at;

-- 排查僵尸 storyboard grid split step（仍 PENDING 但宫格任务已进入终态）
-- 此类 step 会被全局调度器每 13s 反复 skip 刷日志，可用 scripts/cleanup_stale_grid_split_steps.py 清理
SELECT
    s.id AS step_id, s.ai_tool_id, s.created_at,
    CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params, '$.grid_task_id')) AS UNSIGNED) AS grid_task_id,
    g.status AS grid_status
FROM ai_tool_pipeline_steps s
LEFT JOIN grid_image_tasks g
  ON g.id = CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params, '$.grid_task_id')) AS UNSIGNED)
WHERE s.step_type = 'storyboard_first_frame_grid_split'
  AND s.stage = 'before_finish'
  AND s.status = 0;
```

## 相关文档

- [任务队列管理](./task_queue_management.md)
- [RunningHub 并发控制](./runninghub_concurrency_control.md)
- [统一配置系统](./unified_config_system.md)
