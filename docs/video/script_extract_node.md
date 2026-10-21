# 剧本提取节点（视频 → 文字剧本）

## 概述

剧本提取节点用于把一段输入视频转成文字剧本：后端把**视频关键帧**（图像理解）与
**语音转写稿**（ASR）打包交给多模态 VL 智能体，由智能体一次性生成结构化的中文
Markdown 剧本。结果在节点内展示、可编辑，可一键写入画布的"剧本节点"接入下游
拆分链路（拆幕 / 分镜）。

## 功能特点

1. **双输入方式**：连接视频节点，或节点内上传本地视频（上传走 `/api/video-workflow/upload`
   拿永久 URL，刷新/重试后仍可用）；已引用的视频可点"移除"清空，重新上传或连线
2. **横向两栏布局**：节点加宽为左右两栏——左栏（源视频 + 提取模型/帧分辨率/最大帧数），
   右栏（提取操作 + 剧本结果），压缩纵向占用
2. **多模态智能体**：关键帧截图（按时间序、带时间标签）+ 带时间戳的语音转写稿
   同时送入 VL 模型，画面与声音互相印证
3. **异步任务 + 轮询**：链路分钟级耗时，创建任务立即返回 task_id，前端 3s 轮询
   阶段进度（关键帧 → 音轨 → 转写 → 撰写剧本）
4. **结果可编辑 + 一键写入剧本节点**：textarea 直接编辑并随工作流保存；
   "写入剧本节点"按钮新建画布 `script` 节点并填入内容
5. **工作流重载复原**：源视频、剧本文本、任务进度随工作流保存；刷新后未完成的
   任务自动接续轮询

## 使用方法

1. 左侧菜单点击"剧本提取"创建节点
2. 输入视频（连接视频节点 或 上传本地视频，上限 15 分钟）
3. 按需调整**提取参数**（节点内可调，随工作流保存）：
   - **提取模型**：默认"自动（后端推荐）"，可切换任意已配置密钥的 VL 视觉模型
     （与提示词反推节点同一模型列表）；选中的模型下架/改配时自动回落自动模式
   - **帧分辨率**：720P（默认，清晰，可读画面字幕）/ 480P（均衡）/ 360P（省量，
     token 与体积按面积下降，可支持更多帧）
   - **最大帧数**：4~200（默认 24），按镜头切换自动取帧，超出均匀抽稀（保留首尾）
4. 点击"提取剧本"，状态行依次显示：正在提取关键帧… → 正在提取音轨… →
   正在转写语音 (n/m)... → 智能体正在撰写剧本...
5. 完成后剧本显示在结果区，可编辑、复制，或点"写入剧本节点"

## 后端链路（services/video_script_extract_service.py）

```
POST /api/video-workflow/extract-script        创建任务（video_url / max_frames / frame_height / model / model_id / vendor_id）
GET  /api/video-workflow/extract-script/status/{task_id}   轮询状态/结果
```

Pipeline 各阶段（全部异步，不阻塞事件循环）：

| 阶段 | 实现 |
| --- | --- |
| frames | `probe_stream_duration` 时长校验（≤15 分钟）→ 全片场景检测（超过单次解码上限 600s 时**分段检测合并**，长视频不再退化）→ `build_extract_sample_points` 采样计划（场景切换点为主、不足 max_frames 时按时间均匀补点、min_gap 去重、超量抽稀保首尾）→ 逐点 `extract_frame_at` / 尾点走尾帧链 |
| audio | `voice_replace/ffmpeg_util.extract_audio` 提取 PCM wav；无音轨时跳过 ASR（画面推断继续） |
| asr | `build_slice_ranges` 按 60s 切段 → `slice_audio` 切片 → `SenseVoiceAsrDriver.transcribe_segments` 并发转写（≤3 并发）→ `merge_asr_slice_results` 段偏移还原全片时间戳 → `[MM:SS] 文本` 转写稿；单段失败跳过 |
| llm | 模型挑选 `vl_gateway.pick_vl_model`（用户在节点指定的模型优先；未指定时按偏好 volcengine/doubao-seed-2-0-lite）→ 帧图 `compress_local_image_to_base64`（按用户选档位的像素/MB 预算压缩）→ 多模态消息（system 剧本提取智能体提示词 + user 文本（任务说明+转写稿）+ 逐帧 [text 标签 + image_url]）→ `get_llm_client().call_api`（`asyncio.to_thread` + `wait_for` 超时保护）→ `clean_script_text` 清洗截断 |

任务状态落 **`script_extract_task` 表**（跨 gunicorn worker 共享，迁移脚本
`no_154_20261021_add_script_extract_task`）：POST 创建记录后由创建请求的 worker
在进程内起 asyncio 后台任务执行 pipeline，各阶段更新写库，任意 worker 的状态
查询接口读库。每用户同时只允许 1 个活跃 running 任务（重复提交返回 409）；
running 记录 `updated_at` 超 `TASK_TTL_SECONDS`（30 分钟）未更新即判**执行进程
失联**（worker 重启/崩溃），创建新任务时自动标记失败并释放占用，状态查询按
过期处理（404，前端提示重新提取）。历史记录惰性清理（创建任务时顺带删除超
TTL 行）。单飞槽和状态查询按登录用户。`X-User-Id` 可省略；
若携带则必须与登录身份一致，否则 403。LLM 计费 token 取 `Authorization`，
为空时用 `?auth_token=`。

### 多模态消息形态

与 `services/vl_gateway.call_vl`（单图）同源，但一次携带多帧：

```json
{"role": "user", "content": [
  {"type": "text", "text": "任务说明 + 视频时长 + [MM:SS] 转写稿"},
  {"type": "text", "text": "关键帧1（时间点 00:00）"},
  {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
  {"type": "text", "text": "关键帧2（时间点 00:35）"},
  {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
]}
```

LLM 调用带 `auth_token` + `model_id` + `vendor_id`，token 用量经 `BaseLLMClient._log_token_usage`
自动上报计费，欠费熔断自动生效。

### 输出剧本格式（system prompt 约定）

```
# 剧本标题
## 场景1（时间 00:00-00:35｜地点/环境）
【画面】…【对白】角色：台词…【旁白】…【音效/配乐】…
## 角色表
```

## 配置常量（config/constant.py :: VideoScriptExtractConstants）

| 常量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAX_VIDEO_DURATION_SECONDS` | 900 | 视频时长上限（秒），超出拒绝创建任务 |
| `DEFAULT_MAX_FRAMES` / `MIN_FRAMES_LIMIT` / `MAX_FRAMES_LIMIT` | 24 / 4 / 200 | 帧数节点参数的默认值与防呆边界（官方单请求 ≤600 图，payload 与提帧耗时随帧数线性涨） |
| `DEFAULT_FRAME_HEIGHT` / `FRAME_HEIGHT_ALLOWED` | 720 / (720, 480, 360) | 帧分辨率档位（短边高度），节点参数 |
| `FRAME_BUDGET_BY_HEIGHT` | 720→(92万, 0.5) 480→(41万, 0.25) 360→(23万, 0.15) | 各档位帧图压缩预算（像素/MB）。对齐模型视觉规格：token 与 payload 随面积线性下降（720p≈1000 / 480p≈520 / 360p≈290 token/图） |
| `ASR_SLICE_SECONDS` | 60 | 音频分段转写每段时长（SenseVoice 单次读超时 60s） |
| `ASR_CONCURRENCY` | 3 | 分段转写并发上限 |
| `FRAME_COMPRESS_TIMEOUT` | 20 | 单帧压缩外层超时（秒） |
| `LLM_TIMEOUT` / `LLM_MAX_TOKENS` / `LLM_TEMPERATURE` | 180 / 8000 / 0.4 | 剧本生成调用参数 |
| `MAX_SCRIPT_CHARS` | 30000 | 剧本文本截断上限（与前端 textarea maxlength 一致） |
| `TASK_TTL_SECONDS` | 1800 | 任务记录保留时长；running 记录超期未更新判执行进程失联（过期 404 / 释放并发占用），历史记录惰性清理 |
| `PREFERRED_VENDOR` / `PREFERRED_MODEL` | volcengine / doubao-seed-2-0-lite | VL 模型偏好（须已在模型表配置密钥且 supports_vl） |

## 设计取舍：为什么不走 PM/ExpertAgent 重栈

"视频→剧本"是一次性多模态生成：无 ask_user 交互、无工具循环、无多轮改稿，走
`script_writer_core` 的 PM/Expert 体系（SSE、任务表、ToolExecutor）收益为零。因此
采用与 `llm/script_parser.py`、`services/image_describe.py` 相同的**纯 LLM 提取模块**
模式：pipeline 编排在 service 层，"智能体"由 system prompt（剧本提取专家角色）+
多模态消息构成。若未来需要多轮改稿/确认画风，再升级为 StoryboardImageAgentRunner
式的 ExpertAgent Runner（`api/storyboard.py:2113` 模式）。

## 边界与限制

1. 视频时长 ≤15 分钟；帧数上限（默认 24，最高 200）由用户按视频内容自行调整，
   长视频画面覆盖依赖转写稿补充叙事。上下文不是瓶颈：2026-09-27 官方 API 实测
   deepseek-flash 每图约 1000 token（文档上限 1024/图，随分辨率按面积线性下降），
   24 帧 720p ≈ 2.4 万 token；帧多时建议搭配 480P/360P 档位控制 payload 与 token。
2. SenseVoice ASR 不区分说话人，对白中的"角色名"由智能体从画面与语境推断
3. 任务执行绑定创建时所在 worker 的进程内 asyncio 任务：该进程重启后进行中任务
   失联（updated_at 超 TTL 判过期，需重新提取）；已成功/失败的结果已落库，不受重启影响
4. 外部视频 URL 不支持（与 extract-frame 一致），必须先上传到本站
5. 帧图与 wav 为临时文件（`upload/temp/`），任务结束即清理；源视频不动

## 测试

- 单元测试：`tests/services/test_video_script_extract_service.py`（切片计划、ASR 分段
  合并、转写稿格式化、帧抽稀、多模态消息构造、剧本清洗、DB 任务状态表并发限制/
  TTL 失联判定；DB 层用同接口内存假模型替代，不依赖真实数据库）
- 集成验证：浏览器实测（上传视频 → 提取 → 写入剧本节点 → 刷新复原）
