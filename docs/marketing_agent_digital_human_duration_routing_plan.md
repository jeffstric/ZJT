# 营销数字人时长路由方案：>10 秒自动切换 LTX2.3

> 分支：`develop_1019`（基于 origin/develop @ 0d06a3e8）
> 状态：**v2 已实施**（2026-10-16：H3 单段放开至 15s + 15-30s 分段拼接，LTX2.3 撤下营销路由；本文 §3-§4 的 LTX 路由方案已被 v2 取代，见文末附录 C）
> 日期：2026-10-15（v1）/ 2026-10-16（v2）

## 1. 背景与调查结论

### 1.1 marketing_agent.html 的数字人功能在哪里

`web/marketing_agent.html` 及 `web/js/marketing_agent.js` **不含任何数字人提交代码**——前端只是对话 UI，数字人完全由营销智能体（LLM agent）在后端工具链中完成。现有两条工具链：

| 链路 | 工具 | 模型（task_type） | 端点 | 音频语义 | 时长能力 |
|---|---|---|---|---|---|
| 两段式确认制（**2026-10-12 起默认**） | `prepare_digital_human_draft` + `confirm_digital_human`（`script_writer_core/digital_human_tts_tools.py`） | MiniMax H3（35） | `/api/digital-human-minimax-h3` | **驱动音频**（音频即口播） | 档位 4–10 秒，**超长被 clamp 截断** |
| 参考音色模式（用户明确要求时） | `generate_digital_human`（`script_writer_core/mcp_tool.py:4897`） | wan2.2（13） | `/api/digital-human` | **参考音色**（webapp 内部 TTS 说 text） | 文本 ≤1000 字，无档位 |

**现存痛点**：两段式链路中 `clamp_h3_duration`（`digital_human_tts_tools.py:81`）把 >10 秒的口播一律截到 10 秒档，长文案口播被静默截断；wan2.2 参考音色模式虽无硬时长上限，但口型/音色在长文本下不稳（产品侧结论），且该模式仅剩少数场景。

### 1.2 LTX2.3 数字人基础设施已完整存在，可直接复用

- **模型注册**：`TaskTypeId.DIGITAL_HUMAN_LTX2_3_VOICE`（32），`config/unified_config.py:3144`，数字人品类 `TaskCategory.DIGITAL_HUMAN`。
- **端点**：`POST /api/digital-human-v2`（`server.py:4927`），multipart：`image + audio + text`（text 为动作提示词），音频写 `ai_tools.audio_path`。
- **驱动**：`Ltx23WithVoiceRunninghubV1Driver`（`task/visual_drivers/digital_human_ltx2_3_voice_runninghub_v1_driver.py`），RunningHub webapp `2064227959384395777`，节点：image（444）/ audio（1755）/ value（1624）。
- **时长语义**：音频驱动，**视频时长 = 音频时长**，官方建议 5–30 秒（`docs/video/digital_human_node.md`）。
- **画布先例**：`web/js/digital_human_node.js` 画布数字人节点已默认 LTX2.3（`DH_MODEL_KEY_PRIMARY = 'digital_human_ltx2_3_voice'`）。
- **历史先例**：分镜数字人曾实现 Wan2.2/LTX2.3 双模型时长路由（`docs/storyboard/storyboard_digital_human_dual_model_routing_design.md`，阈值 1 秒，后统一 H3 而废弃）——统一常量、`routing_reason`、`extra_config` 元数据的模式可直接借鉴。

### 1.3 能力对照与差异（路由必须处理的点）

| 维度 | wan2.2（13） | MiniMax H3（35） | LTX2.3（32） |
|---|---|---|---|
| 音频语义 | 参考音色 | 驱动音频 | 驱动音频 |
| 口播驱动 | text（webapp 内 TTS） | audio | audio |
| 时长 | 随文本 | 档位 4–10s | =音频时长，建议 ≤30s |
| 画幅 ratio | 支持 7 种比例 | 不消费 | **不消费（画幅跟随首帧图）** |
| max_edge | 无 | 720/1280/1920 | **无** |
| 算力 | 固定（12） | 按档位 | v2 端点当前**固定 6**，未按时长 |

关键差异：LTX2.3 与 H3 音频语义一致（驱动音频），**两段式链路的 TTS 产物天然可直接喂给 LTX2.3，无需任何音频转换**；wan2.2 的参考音色则不能直接给 LTX2.3（它是"提取音色"用的，不是口播内容）。

## 2. 目标与非目标

**目标**：营销智能体数字人口播，按口播时长自动路由模型：

| 口播时长 D | 模型 | 说明 |
|---|---|---|
| D ≤ 10s | MiniMax H3（35） | 现状不变，档位 clamp |
| 10s < D ≤ 30s | **LTX2.3（32）** | 时长=音频实际时长，ceil 计费 |
| D > 30s | 拒绝并提示 | 超出 LTX2.3 建议上限，提示拆分文案分段生成 |

**非目标**：
- 不改画布（`digital_human_node.js` 已默认 LTX2.3）与分镜链路（已统一 H3）。
- 不改 `/api/digital-human`（wan2.2）端点本身。
- 不做 wan2.2 参考音色模式的自动克隆桥接（见 §4.4，列为可选二期）。

## 3. 路由规则与常量

### 3.1 新增常量（`config/constant.py`）

```python
# ===== 营销数字人时长自动路由（>10s 走 LTX2.3）=====
# H3 数字人档位上限，与 unified_config DIGITAL_HUMAN_MINIMAX_H3.supported_durations 上限一致
DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS = 10
# LTX2.3 With Voice 音频时长上限（官方建议 5-30s，见 docs/video/digital_human_node.md）
DIGITAL_HUMAN_LTX_MAX_DURATION_SECONDS = 30
# 口播时长估算速率（字/秒），与 prepare 现有估算口径一致
DIGITAL_HUMAN_SPEECH_CHARS_PER_SECOND = 4
```

路由阈值单一来源，禁止在工具函数里散落魔法数字（沿用分镜双模型路由设计的教训）。

### 3.2 时长来源（按优先级）

1. TTS 实测时长（`tts.duration`，火山/IndexTTS 产物已由 `probe_audio_duration` 探测）；
2. 用户直供驱动音频：**prepare 阶段补一次 `probe_audio_duration`**（现状用户音频 `duration=None`，必须补齐才有路由依据）；
3. 探测失败时按文案长度估算（`len(script_text) / 4`，现成逻辑）；
4. 仍无法确定 → 走 H3 default 10（保守回退，与现状一致）。

### 3.3 可观测性（借鉴分镜路由设计）

草案与提交结果新增 `model_task_type` / `routing_reason`（`duration_lte_10s_h3` / `duration_gt_10s_ltx2_3` / `duration_fallback_h3`），写入返回 message；`ai_tools.extra_config` 由端点侧自然落库 task_type，无需额外字段。

## 4. 改动点设计

### 4.1 `prepare_digital_human_draft`（主改动，`script_writer_core/digital_human_tts_tools.py`）

现第 4 步「时长与 H3 算力预估」改为路由决策：

```
est_seconds = TTS 实测 or 用户音频 probe or 文案估算
if est_seconds <= 10:   routing = H3(35)；duration = clamp_h3_duration(est)；power = H3 配置按档位
elif est_seconds <= 30: routing = LTX2.3(32)；billable = ceil(est)；power = LTX2.3 配置按 duration
else:                   return 失败：「口播时长约 Xs，超出数字人支持上限 30s，请拆分文案分段生成」
```

草案 dict 新增字段：`model_task_type`、`routing_reason`、`billable_duration`（H3 时等于 `h3_duration`，LTX2.3 时为 ceil 后音频秒数）。`h3_computing_power` 字段语义扩为「视频算力」，或新增 `video_computing_power`（保留旧字段兼容）。

### 4.2 `confirm_digital_human`（提交分派）

- 读 `draft.get('model_task_type', TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)` —— **缺省 H3，兼容升级窗口内的存量草案**。
- 35 → 现有 `/api/digital-human-minimax-h3` 提交路径原样保留。
- 32 → 改投 `/api/digital-human-v2`：files 同样为 `image + audio`，`data.text = motion_prompt`（LTX2.3 的 text 语义与 H3 相同，均为动作提示词，复用同一 VL 生成的 motion_prompt），新增 `duration = billable_duration`（见 4.3）。
- 返回 `model_used` 按实际模型（`'MiniMax H3 数字人'` / `'LTX2.3 数字人'`）。

素材下载、`_fetch_asset_bytes`、一次性消费、30 分钟 TTL 等逻辑完全复用，不重复实现。

### 4.3 `/api/digital-human-v2` 端点扩展（`server.py:4927`）

当前该端点扣费为固定 `get_computing_power()`（=6），与音频时长无关。新增**可选**表单参数：

```python
duration: int = Form(None, description="Billable duration in seconds (audio-driven); omit to keep flat-rate legacy behavior")
```

- 传入时：`computing_power = task_config.get_computing_power(duration=duration)`，写入 `ai_tools.extra_config`（便于退款核对）；
- 缺省时：行为完全不变（向后兼容现有调用方）。
- 同步核对 `implementation_power` 表 / `ImplementationConfig.default_computing_power` 是否有 `ltx2_3_with_voice_runninghub_v1` 的按时长档位配置，缺失则在管理后台补配置（历史提交 145dc62f 已调整过该实现方费用，说明配置通道存在）。

### 4.4 wan2.2 参考音色模式（`generate_digital_human`，一期只引导不改行为）

该模式音频是"参考音色"，LTX2.3 无法直接接手（需要驱动音频）。一期方案：

- 工具内部按 `len(text) / 4` 估算口播时长，**>10s 时不再直接提交 wan2.2**，返回结构化引导：
  `"口播约 X 秒，超过 10 秒建议使用 prepare_digital_human_draft + confirm_digital_human（将自动路由 LTX2.3 数字人，时长与音色更稳）；如必须使用参考音色模式，请缩短文案至约 40 字以内。"`
- LLM 会依据引导自动改走两段式链路（SOP 中该模式本就是少数场景）。
- **可选二期**：用 IndexTTS 以用户参考音频克隆合成驱动音频（复用 `_synthesize_via_indextts`，把 ref 换成用户音频）后自动转投 LTX2.3。不建议一期做：`generate_digital_human` 是同步工具函数（httpx.post 直调），内嵌 TTS（180s 超时）会把链路拉长到分钟级，且涉及 R6 红线（同步包装异步须模块级长寿 executor）。

### 4.5 工具 schema 与 SOP 同步

- `mcp_tool.py` 工具定义：`confirm_digital_human` 的 description 由「提交 MiniMax H3」改为「提交 MiniMax H3 或 LTX2.3 数字人（按口播时长自动路由：≤10s 走 H3，>10s 走 LTX2.3）」；`prepare_digital_human_draft` description 补充路由说明。LLM 无需做路由决策，仅展示草案时告知用户所选模型。
- `agents/skills/marketing-pm/sops/sop-digital-human.md`：新增「时长路由」小节（本方案 §3 表格）+ 确认消息要求展示「将使用的模型」。
- `docs/marketing_agent.md`：数字人链路章节同步。

### 4.6 前端

`web/marketing_agent.html` / `marketing_agent.js` **零改动**：路由完全在后端工具链内完成，消息中模型名随 `model_used` 自然展示。

## 5. 兼容性与风险

| 风险 | 处理 |
|---|---|
| 存量草案无 `model_task_type` | `confirm` 缺省按 H3(35) 处理，行为与现状一致 |
| LTX2.3 不消费 ratio / max_edge | 草案 message 注明「LTX2.3 模式下画幅跟随首帧图」；9:16 需求建议上传竖版首帧。不阻塞提交 |
| 口播 >30s | prepare 直接拒绝并提示拆分（2000 字上限文案理论上可达 ~500s，必须显式拦截而非截断） |
| v2 端点计费口径 | 通过可选 duration 参数修复；缺省保持固定 6 不影响旧调用方 |
| IndexTTS 免费音色路径 | TTS 产物一样有实测时长，路由逻辑与火山路径共用，无差异 |
| 事件循环阻塞 | confirm 内 httpx 调用沿用 `asyncio.to_thread` 包装（现状已合规）；probe 用现有 async 工具 |
| LTX2.3 上游拥堵 | driver 已有 `is_upstream_congested_error` 自动重试，无需新增 |

## 6. 实施步骤与测试

### 实施顺序

1. `config/constant.py` 新增路由常量；
2. `server.py` v2 端点扩展可选 `duration` 参数；
3. `digital_human_tts_tools.py`：prepare 路由决策 + confirm 分派 + 用户音频 probe 补齐；
4. `mcp_tool.py` 工具 description 更新；
5. SOP 与 docs 同步；
6. 核对/补齐 LTX2.3 数字人按时长算力配置（管理后台）。

### 测试设计（`tests/agents/test_digital_human_tts_tools.py` 扩展）

- 路由边界：9.9s→H3；10.0s→H3；10.1s→LTX2.3；30.0s→LTX2.3；30.1s→拒绝并提示拆分。
- 时长来源优先级：实测 > 用户音频 probe > 文案估算 > 回退 H3 default。
- confirm 分派：H3 草案打 `/api/digital-human-minimax-h3`（断言 form 字段不变）；LTX2.3 草案打 `/api/digital-human-v2`（断言 `text=motion_prompt`、`duration=billable_duration`）；旧草案（无 model_task_type）→ H3。
- 草案一次性消费、TTL 行为回归不变。
- v2 端点：传 duration 按档位扣费；不传维持固定值。

## 7. 结论

**可行，且改动面小**：LTX2.3 数字人的端点、驱动、模型注册、画布先例全部现成；营销两段式链路的 TTS 产物（驱动音频）与 LTX2.3 输入语义天然一致，路由只需在 prepare/confirm 两处做时长分支 + v2 端点补一个可选计费参数。wan2.2 参考音色模式因音频语义不同，一期以「超长引导转两段式」处理，二期可选做克隆桥接。

## 附录：实施与自测记录（2026-10-15）

**单测**：`tests/agents/test_digital_human_tts_tools.py` 26 项全过（新增路由边界 6 项、prepare LTX 路由/超限拒绝/用户音频 probe 3 项、confirm LTX 分派 1 项；`tests/agents/` 全目录 137 项回归通过，`lint_blocking_calls.py` 无新增违例）。

**端到端**（本地起全栈服务，登录 admin 账号实测）：

| 验证点 | 结果 |
|---|---|
| `/api/digital-human-v2` 带 `duration=12` 提交（12s 测试音频） | ✅ 提交 RunningHub 成功（taskId 2110762032566599682，RUNNING），`ai_tools.type=32`、`duration=12` 落库，轮询正常 |
| 同端点**不带** duration（向后兼容） | ✅ 正常提交，`duration` 落库 NULL，行为与升级前一致 |
| prepare 真实跑（用户直供 12.04s 音频，跳过 TTS） | ✅ probe 实测→路由 LTX2.3（`duration_gt_10s_ltx2_3`），billable=13，VL 正常生成动作提示词 |
| prepare 真实跑（5s 音频） | ✅ 路由 H3（`duration_lte_10s_h3`），billable=6 |
| prepare 真实跑（35s 音频） | ✅ 拒绝并提示拆分文案 |

**运维注意**：本地环境提交走的是 enterprise **RunningHub 密钥池**（`runninghub.key.1.api_key`，label=用户钱包），池内 key 优先于全局 `runninghub.api_key`——更换 key 时两处都要更新（自测时已把池槽位 1 与全局 key 均更新为用户提供的新 key，并清零该槽位 fail_count）。`get_computing_power(duration=...)` 计费通道已打通，数据库 `implementation_power` 暂无 LTX2.3 数字人按时长档位，当前兜底 6 算力，可在管理后台按档位补配。

## 附录 B：浏览器 UI 端到端实测（2026-10-16）

通过 `marketing_agent.html` 对话完整走通长口播链路：

1. 用户在 UI 发长文案（~120 字）→ PM 委托 digital-human-creator；角色图经 Seedream 文生图（project 318）提供。
2. 火山 TTS 未配置时专家提供降级选项，选 RunningHub 生成驱动音频成功。
3. **音频实测 31.5s → prepare 按 >30s 上限拒绝**，专家如实转达并给出拆分方案（上限保护生效）。
4. 接受拆分后第一段（实测 21s）草案显示「模型：LTX2.3（按时长自动路由）」，确认提交 → `ai_tools` type=32、duration=21，RunningHub 受理（taskId 2110913936210751490）。
5. **成片验证**：`/upload/cache/2026-10-16/319_*.mp4`，ffprobe 实测 24.04s、960×1280、h264+aac（带音轨）；前端自动轮询并展示视频卡片（0:24）。

**实测发现并修复的 bug**：`confirm_digital_human` 此前把图片/音频字节硬编码为 `.png`/`.mp3` 上传，角色图为 jpeg（Seedream 产物）时被 `/api/digital-human-v2` 落盘侧的扩展名+魔数一致性校验（`utils/media_upload.py`）拒绝。已修复为按字节魔数嗅探真实格式（`_detect_image_upload_meta` / `_detect_audio_upload_meta`，支持 png/jpg/webp/gif 与 mp3/wav/ogg/m4a）。该 bug 同样影响 H3 链路的非 png 角色图。

## 附录 C：v2 实施（2026-10-16）——H3 分段拼接取代 LTX2.3 路由

LTX2.3 数字人实测效果不达标（画面失真、牙齿不清晰、尾部约 1 秒唇动无声——其 webapp 输出时长略长于驱动音频且无时长控制参数），自营销路由撤下；模型与 `/api/digital-human-v2` 端点保留供画布使用。

**新路由规则**（常量 `config/constant.py`）：≤15s → H3 单段（官方规格 4-15s，RunningHub webapp 默认实例 15s/720P 实测出片，历史 10s 为自锁限制）；15-30s → **H3 分段拼接**；>30s → 拒绝并提示拆分。

**改动点**：
- `digital_human_tts_tools.py`：`resolve_digital_human_model` v2（segment_mode）；`split_audio_into_segments` 静音切分+整数秒对齐（`_detect_silence_midpoints`）；confirm 分段提交（multipart 带 `segment_audio` 多文件）；`SEGMENTED_MOTION_PROMPT` 固定镜头统一提示词（分段模式强制使用，VL 选音色的提示词要求同步收紧为固定机位）。
- `server.py` `/api/digital-human-minimax-h3`：`duration` 放开 4-15；新增 `segment_audio: List[UploadFile]` + `segment_durations` JSON（各段 4-15 整数、之和=总时长），分段计费=各段档位之和，段音频路径写入 `extra_config.dh_segments/dh_segment_durations`。
- `digital_human_minimax_h3_runninghub_v1_driver.py`：`SUPPORTED_DURATIONS` 4-15；`_submit_segmented_sync` 分段全流水线（逐段提交[失败自动重提]→并行轮询→下载→ffmpeg concat→`/upload/cache` 落盘），以 `sync_mode` 返回本地成片，visual_task 直接落库。
- `unified_config.py`：H3 数字人 `supported_durations` 4-15。
- `mcp_tool.py` / SOP / 本文档同步。

**测试**：`tests/agents/test_digital_human_tts_tools.py` 27 项（新路由边界、分段 confirm 分派、真实 ffmpeg 切片）+ `tests/agents/` 138 项回归通过。

### 附录 C.1 补充实测与修正（2026-10-16 下午）

1. **15s 段长处于显存边界**：project 324 的段 1（15s/720P）在 RunningHub 默认实例上连续两次 `torch.OutOfMemoryError`（SamplerCustomAdvanced），此前 322/323 成功属实例运气。**段长回退生产稳定档 10 秒**（`DIGITAL_HUMAN_SEGMENT_LENGTH_SECONDS=10`），30s = 3×10s；切片函数重写为 N 段（均分点 ±2.5s 窗口内取静音中点）。
2. **修复浏览器链路 confirm 崩溃**（用户实测 `too many values to unpack (expected 2)`）：`upload_files = list(files)` 把 dict 转成了 keys 列表，httpx multipart 编码时对字符串解包报错。改为 (name, (filename, bytes, content_type)) 列表。**单测补真实 httpx.Request 编码断言**防回归。
3. **修复分段计费口径**：草案 ceil(28.5)=29 与切分后 15+15=30 不一致，被端点 sum==duration 校验拦截。confirm 改为按 sum(segment_durations) 下发；prepare 预估同口径（ceil(est/段长)×段长）。
4. **端到端复验**：project 325（28.5s 音频 → 3×10s），三段全部成功、拼接成片 30.38s 落库正常；三段景别接近（固定镜头提示词正确下发时 H3 服从度良好）。
5. **测试坑记录**：Windows curl.exe 对 `-F "text=中文"` 按 GBK 代码页编码，导致自测任务的提示词乱码下发（非系统 bug，浏览器/agent 链路 UTF-8 正常）；测试中文接口用 python requests。

### 附录 C.2 段长恢复 15s + OOM 自动降档（2026-10-16 傍晚）

应用户要求减少切割次数，段长恢复 15s（`DIGITAL_HUMAN_SEGMENT_LENGTH_SECONDS=15`）；同时实测确认 15s 段在 webapp 默认实例显存边界上**随机 OOM**（project 324/326 首选段连续失败，322/323 同参数成功）。落地**自动降档**：driver 流水线改为 `_run_segment_pipeline`（失败抛 `_SegmentedPipelineError`），任一段最终失败且段长 >10s 时，**用完整音频按 10s 稳定档自动重切重跑一次**（project 326 实测：15s 段 OOM → 自动降档 3×10s → 成片 28.25s 落库正常）。

切片能力迁移至 `utils/audio_segment_util.py`（tts_tools 与 driver 共用，task 层不反向依赖 script_writer_core）；静音检测增强（-32dB/0.18s 捕捉标点停顿），切点优先句间静音、窗口放宽 ±3.5s 并有放宽兜底——避免词中硬切（如"高|效"）。

### 附录 C.3 定稿：全部回退 10s 稳定档（2026-10-16 晚）

15s 段 OOM 再现于 project 329（首选段 torch.OutOfMemoryError，RunningHub outputs failedReason 实锤），且用户给出 webapp 底层工作流 JSON **实锤帧对齐公式**（节点 131）：`帧数 = max(5, round(秒×24)) + (5 - max(5, round(秒×24)) % 17) % 17`，即输出帧数 ≡5 (mod 17)——15s→362 帧、10s→243 帧，与 11 条实测样本完全吻合，输出时长确定性问题排除。**用户拍板：不赌运气，全部回 10s 稳定档**——

- 路由：≤10s H3 单段；10-30s 分段拼接（每段 10s，30s=3×10s）；>30s 拒绝。11-15s 不做单段（OOM 风险），并入分段。
- **撤回 11-15s 算力外推档**（50988e89）：`MINIMAX_H3_DIGITAL_HUMAN_COMPUTING_POWER` 删除，数字人实现方回 `MINIMAX_H3_720P_COMPUTING_POWER`（4-10）；supported_durations 回 4-10；driver SUPPORTED_DURATIONS 回 4-10。
- driver 内置的"段长>10s 失败自动降档 10s"逻辑保留（当前不触发，为段长将来上调预留）。
- **切点窗口约束修复**（词中硬切"高|效"的根因之一）：切点窗口下限补 `total - max_seg×remaining`，保证任意切点下所有段 ≤ 段长上限——此前末段切片 10.966s 超过 duration=10，被 webapp 内部 AudioCrop（end=start+duration，工作流节点 224）裁掉尾部 0.97s 语音，即"片尾突然上升、听不清"的截断残句。修正后验证（28.5s 音频）：cuts=[9.854, 19.854]，三段 9.85/10.0/8.65s 全部 ≤ duration。
- 测试 27 项 + agents 138 项回归通过。

### 附录 C.4 固定镜头强化提示词 A/B 实测（2026-10-16 晚）

**换镜头根因（用户提供 webapp 底层工作流 JSON 确认）**：最终 prompt = 节点214 动作提示词 **拼接** 节点246 Qwen3-VL 的看图描述（JoinStrings 241），而 QwenVL 的指令模板（节点248）要求"详细描述图片人物和背景"且 **seed=randomize**——每段运行 VL 都会生成不同措辞的构图描述（半身/特写等），我们注入的固定镜头提示词只占一半。

**A/B 实测**（同素材同 3×10s 切分，仅换提示词）：模糊表述"固定镜头，景别保持一致"（330）段2/3 仍有推近；强化版**"固定机位中景：人物胸部以上居中构图…镜头完全静止，全程不推近、不拉远、不摇移、不切换景别。"**（333）三段景别高度一致。已更新 `SEGMENTED_MOTION_PROMPT` 为强化版。

**连带发现并修复**：webapp 每次运行输出分辨率随机（同参数 960×1280 与 512×704），拼接 filter 需先统一缩放；且 format 滤镜误标双 label 的语法错误（332 拼接失败）已修。工作流底层还确认了输出帧数公式：`帧数 = max(5, round(秒×24)) + (5 - 帧数%17) % 17`（节点131），输出时长确定性。

### 附录 C.5 对接锁镜头版 webapp + 英文 integrated_multimodal 提示词（2026-10-17）

用户多次反馈 H3 旧 webapp(2087200340012785665)镜头持续运动——根因是该工作流**没有相机控制**（H3 Ref2V 参考图只锁身份，运镜是模型自由度），且内部 QwenVL(randomize) 看图描述会拼进 prompt 引入随机构图措辞。用户另找作者制作了**锁镜头版 webapp**（2111473047642398722），要求 214 提示词为英文 `integrated_multimodal_description` 格式（模板由用户提供，含"camera strictly locked on a tripod / zero camera movement / body position fixed"等强指令）。

**对接改动**：
- driver `webapp_id` 更换为 2111473047642398722（节点结构与旧一致：209 图/212 时长/213 最长边/214 提示词/215 音频/229 开始秒）；
- prepare 新增 `_generate_locked_camera_prompt`：VL(Qwen3-VL) 看角色图，按用户提供的英文模板生成提示词（VL 失败降级为无人物细节的英文兜底模板），存草案 `h3_locked_prompt`；
- confirm 的 214 下发 `h3_locked_prompt`（旧草案无字段时用英文兜底模板），替代原中文动作提示词；
- 分段拼接/计费/降档机制不变（每段下发同一英文提示词，各段独立生成后拼接）。

**实测（project 335，3×10s）**：成片 29.67s 落库正常；四帧抽检（覆盖三段+末尾）景别一致、人物居中、无黑边；末尾频谱干净（语音自然结束+静音收尾，无截断残句/突增）。镜头固定效果待用户最终确认。

### 附录 C.6 修复 10-16s 路由死角（2026-10-19）

用户实测 10.2s 口播 confirm 失败：端点分段校验写死 `16 <= duration <= 30`，而路由把 10-16s 也分到分段（切分后 sum 8-16s 落在 16 以下）——**10-16s 成为路由死角**。同区块还残留 15s 口径（单段 4-15 放行，11-15s 无分段文件会走单段赌 OOM）。统一修正到 10s 口径：单段 4-10；分段带 segment_audio 且总时长 8-30（≥2 段各 4s，各段 4-10）。实测 project 337（10.2s 音频 → 2 段 6+6s）：成片 13.17s 落库正常。


### 附录 C.7 取消 30s 上限——段数随时长自然增长（2026-10-19）

用户指出：分段架构无 30s 技术上限。已放宽——`DIGITAL_HUMAN_SEGMENT_MAX_TOTAL_SECONDS` 30→600（仅作异常超长音频的兜底拒绝线），实际时长由 prepare 的口播文案上限（2000 字 ≈ 6-7 分钟 ≈ 40 段）自然约束。prepare 草案 message 会预告**段数与预计耗时**（每段 4~10 分钟，总耗时为段数×4~段数×10）；SOP/mcp_tool 同步更新（超长内容提示耗时随段数线性增长）。切分/拼接/降档逻辑天然支持任意段数。
### 附录 C.8 拼接方案改型：末帧接力串行链式（2026-10-19）

用户拍板：分段生成改**末帧接力串行链式**——段 1 用角色图，段 i+1 首帧 = 段 i 末帧（提取上传），逐段串行生成，全部完成后统一缩放拼接。拼接点画面完全连续，消除景别跳变。

- `_run_segment_pipeline`（sync 长跑，sync executor 进程池内）：串行循环——上传段音频→提交（输入图=角色图[段1] 或前段末帧[段2+]）→轮询→下载；段提交/生成失败自动重试一次；全部成功后 concat 落盘，sync_mode 返回 result_url。
- 顺带清理：重复的旧 `_submit_segments_async`（并行快速提交版，被多次 checkout 往返产生的残留）删除，保留串行末帧接力单一实现。
- 代价：分段任务改为串行，总耗时 = 段数 × 单段时长（每段约 4~10 分钟）；换取消除拼接点景别跳变。


### 附录 C.9 修复 ffmpeg/ffprobe 硬编码相对路径——Linux 部署分段必现失败（2026-10-20）

**事故（zjt_trial 环境，会话 0a38dcac，project 1256，43s/3 段）**：末帧接力链式下 seg_1 在 RunningHub 生成成功并下载后，`_extract_last_frame` 以相对路径 `bin/ffmpeg/ffmpeg` 调用 ffmpeg → `FileNotFoundError`（服务器无 `bin/` 目录，系统 ffmpeg 在 `/usr/bin/ffmpeg`）→ 整条 submit_task 失败、算力退款，前端只见"服务异常"。

**根因**：`86a652f9`（dev2 ffmpeg 定位兼容 Linux）只改了 `_concat_and_store` 的 ffmpeg 调用（`_get_ffmpeg_path()`）；其后 `37f4018f` 接力链新代码 `_extract_last_frame` 又写回硬编码，且 `_concat_and_store` 内探测首段尺寸的 ffprobe 仍硬编码 `bin/ffmpeg/ffprobe`——驱动内共 3 处残留（含一份被后定义覆盖的重复 `_extract_last_frame`）。Windows 开发机存在 `bin/ffmpeg/ffmpeg.exe`，自测不可复现；**所有无 `bin/ffmpeg/` 的 Linux 部署上分段数字人（>10s）必现失败**（单段不走末帧提取，不受影响）。

**修复**：3 处调用统一改 `_get_ffmpeg_path()` / `_get_ffprobe_path()`（读主配置 `bin.ffmpeg` / `bin.ffprobe`，缺省回退 PATH）；删除被覆盖的重复 `_extract_last_frame` 定义；`_extract_last_frame` 补 `OSError` 捕获——ffmpeg 启动失败时按契约返回 None（下一段回退角色图首帧），不再炸整条流水线。

**测试**：`tests/drivers/test_digital_human_minimax_h3_runninghub_v1_driver.py` 新增 3 项（配置路径生效 / ffmpeg 不可启动优雅降级 / ffprobe 配置路径）+ 驱动相关 184 项回归通过。


### 附录 C.10 上游 421 拥堵回队重试 + 分段断点续跑（2026-10-20）

**事故（zjt-dev 环境，会话 f140f999）**：19.87s 口播 → 2 段分段拼接，第 1 段 11s 档上游两次无原因 FAILED、自动降档 10s 重切后 seg_2 提交时 RunningHub 返回 `errorCode=421`（api queue limit reached，账号级并发打满）。分段链路抛出 `_SegmentedCongestedError` 本意为"可重试拥堵信号"，但 `submit_task` 无对应 except 分支，落入通用 `Exception` 被当成不可重试硬失败——4 分钟内 7 次密集重试全部撞在拥堵高峰后终态失败退款，用户什么都拿不到，还误报 Sentry `UNEXPECTED_EXCEPTION`。

**修复**：

- `submit_task` 新增 `except _SegmentedCongestedError` 分支，返回 `_build_upstream_congested_result()`（`retry=True / UPSTREAM_CONGESTED`），与单段路径一致交回调度层：释放本地槽位 → 30s 延迟回队（`runninghub.upstream_congest_retry_delay`）→ 不消耗 try_count、不退款、不切换实现方，上游恢复即生成；`_check_task_expiration`（`task_expire_days`，默认 7 天）兜底过期退款。
- **断点续跑**：段成片按 `ai_tools.id` 确定性落盘 `temp/h3seg_{id}_seg_{idx}.mp4`，重试时 `_is_valid_segment`（ffprobe 探测视频流 + 时长与档位偏差 ≤3s，防复用下载中途被杀的截断残文件）校验通过的已完成段直接复用，从第一个缺失的段继续生成；下一段首帧取自已复用段的末帧（接力衔接，失败回退角色图）。杜绝"第 2 段撞 421 → 第 1 段被完整重复生成"的上游费用浪费。
- 顺带修复接力链 latent bug：末帧上传失败的回退分支引用不存在的 `result_url_role`（NameError 会炸整条 submit_task），改为回退到角色图 URL。

**测试**：驱动测试新增 4 项（421→UPSTREAM_CONGESTED 转换 / 续跑命中跳段 / 缓存损坏回退全量重生成 / 全缓存零提交直接拼接），累计 775 项驱动测试通过。


### 附录 C.11 段生成失败「带刹车」：返回值吞掉导致流水线空转（2026-10-20）

**背景**：zjt-dev 任务 12787（31.5 分钟慢单）排查中发现：现行串行接力代码丢弃 `_wait_and_download_segment` 的 `(ok, err)` 返回值——段上游 FAILED / 轮询超时 / 下载失败时，流水线**带着不存在的段文件继续跑**：下一段首帧静默回退角色图、后续段白跑（每段 2-5 分钟 + 上游计费），最终 `_concat_and_store` 才以误导性的「分段视频拼接失败」报错，真实根因（第几段、为什么失败）完全丢失。docstring 承诺的「段生成失败自动重试一次」实际只覆盖了提交阶段。

**修复**：等待出片的返回值接回——失败按旧版语义换新 RunningHub 任务**自动重提一次**（C.7 前行为），重提的提交若命中 421 仍走 UPSTREAM_CONGESTED 回队；双败立即抛 `_SegmentedPipelineError("第 {idx} 段重试后仍失败: {根因}")`，流水线当场带刹车，不再空转后续段。降档兜底（11-15s OOM 重切 10s）经评估暂不恢复——该档 OOM 概率很低，双败如实报错退款即可。

**测试**：新增 2 项（生成失败重提一次后成功 / 双败抛错带刹车且不误报拼接失败），`tests/drivers` 累计 780 项通过。


### 附录 C.12 修复多段接力「越来越黑」：无损末帧 + 黑段检测 + 每 2 段回锚（2026-10-20 实施，2026-10-21 回锚间隔 3→2）

**事故（zjt-dev 任务 12792，会话 4fc2e175，5 段接力，成片 67.6s）**：用户反馈数字人口播视频越来越黑。成片逐秒亮度（YAVG）实测：段 1 ≈174.7 → 段 2 ≈163.5 → 段 3 ≈155.3 → **段 4 ≈29.9（整段近黑屏 13 秒）** → 段 5 ≈141.6。接力帧肉眼对比同样逐轮变暗、噪点/色斑累积。排查结论：ffmpeg 抽帧本身亮度误差 <1（已排除），RunningHub 上传为原样二进制（已排除）；劣化发生在「接力帧经 H3 VAE 重编码→扩散再生成」环节，每轮漂移 -6~-12 YAVG 且偏暗居多，多段接力累积成灾；另有 H3 段内偶发骤黑（12792_seg_4 首末帧正常、中段 13 秒 YAVG≈30），当时无任何画面内容校验，黑段直接进拼接交付。

**修复**（驱动 `task/visual_drivers/digital_human_minimax_h3_runninghub_v1_driver.py`，常量 `config/constant.py`）：

- **抽帧改无损**：`_extract_last_frame` 由 `-sseof -0.3 -frames:v 1 -q:v 2` JPEG 改为两级无损 PNG——快路径 `-sseof -<窗口> + -update 1` 覆盖写留下**真正最后一帧**（旧写法带 `-frames:v 1` 会在窗口第一帧后停止，取到的并非末帧，与 `services/video_frame_extract_service.py` C.10 前修复的语义坑相同）；兜底全片解码 `-update 1`。消除 JPEG `-q:v 2` + 4:2:0 色度子采样在接力循环中的逐轮有损累积。
- **黑段检测**：段下载后 `_check_segment_brightness` 用 ffmpeg signalstats 测全帧平均 YAVG（注意不能加 `fps=1` 抽稀——fps 滤镜对单帧图片因缺乏下一帧 pts 输出空帧，会导致首帧参考图测量恒失败），双判据命中即视同生成失败走既有「换新任务重提一次」：绝对下限 `DIGITAL_HUMAN_BLACK_SEG_YAVG_FLOOR=50`（12792 黑段实测 35~38，正常段 ≥140）；相对首帧参考图（接力帧/角色原图）偏暗超 `DIGITAL_HUMAN_BLACK_SEG_DARK_RATIO=25%`（自然漂移 ~10% 以内放行，避免误重提浪费上游费用）。重提后仍黑抛 `_SegmentedPipelineError` 带刹车，不拼接黑片交付。测量失败（ffmpeg 异常）降级放行，不阻塞流水线。
- **每 2 段回锚角色原图**：`DIGITAL_HUMAN_REANCHOR_SEGMENT_INTERVAL=2`（2026-10-21 由 3 收紧至 2：实测漂移每段可达 -12 YAVG，3 段累积 ~36 仍明显偏暗；2 段约束在 ~24 以内），段 3/5/7…（`_is_reanchor_segment`）首帧直接用角色原图而非接力末帧，把累积漂移约束在每 2 段归零一次；断点续跑路径同样遵守回锚规则。接力帧提取/上传失败的回退分支补齐重置为角色图（旧代码 extraction 失败时 image_url 残留上一段首帧的 latent bug 一并修复）。

**验证**：19 项驱动测试全过（新增 6 项：两级无损末帧参数 / 回锚点序列 / 4 段链路回锚断言 / 黑段重提一次 / 双黑带刹车 / 测量失败降级放行），`tests/drivers` 累计 786 项通过。用 12792 生产残留段文件实测：角色原图 YAVG=191.7、接力帧 173.3 测量正常；seg_1(174.6)/seg_2(163.6) 放行，seg_4(37.6) 命中黑段；回锚序列 [3,5,7,9] 正确（2026-10-21 调整 N=2 后复验）。


### 附录 C.13 黑段双杀不再判失败：回退角色原图首帧放行（2026-10-21）

**背景**：C.12 的黑段检测上线当天误杀任务 12811——医生角色在深色木墙背景前口播（`temp/h3seg_12811_seg_1.mp4` 抽帧核实画面完全正常），角色原图为浅色亮底（YAVG=173.9），H3 再生成后场景固有暗（两次稳定输出 YAVG=101.8/73.8），命中相对判据（>25% 偏暗）→ 重提仍黑 → 双杀抛错退款。绝对下限 50 并未命中，是相对判据对「亮底角色图 → 暗场景视频」的必然误报。

**改动**（`_submit_segments_async` / `_download_validated_segment` / `_check_segment_brightness`）：

- 黑段不再作为失败理由：某段两次判黑后，自动**回退数字人输入的角色原图作为该段首帧重新生成一次并直接放行**（该次不再因亮度判黑，仅校验结构完整性）；仅当这回生成/下载本身失败才抛 `_SegmentedPipelineError`。
- 回退后整条链固定角色原图首帧（跳过末帧接力，避免暗帧继续传递），亮度校验降级为仅告警——场景固有暗的链路上不再每次三跑（初提+重提+回退），各段一次生成即可。
- `_download_validated_segment` 返回 `(ok, err, was_black)`，黑段败因显式上抛；`_check_segment_brightness` 新增 `reject_black=False` 告警模式。

**测试**：`test_submit_segments_brakes_when_black_segment_twice` 改写为 `test_submit_segments_falls_back_to_role_image_on_persistent_black`（双黑→回退角色图→放行，断言回退后首帧均角色图 URL 且不再抽接力帧），新增 `test_submit_segments_brakes_when_fallback_generation_fails`（回退后生成失败才抛错）。20 项驱动测试全过。


### 附录 C.14 恢复 15s 档后端点校验漏改——11-15s 路由死角回归（2026-10-21）

**背景**：c3d48902（2026-10-19，用户确认显存充裕）恢复路由层 11-15s 单段（`DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS` 10→15、分段段长 10→15、计费档位 4-15、driver OOM 降档兜底），但其对 `server.py` 的改动只覆盖分段档位校验（各段 4-15），**漏改单段模式两处校验**（仍是 4-10 口径）：无分段时 `duration > 10` 即 400「超过 10 秒的视频须提供 segment_audio」、单段白名单 `range(4, 11)`。路由把 11-15s 分到单段（不带 segment_audio）→ 端点必 400，11-15s 口播完全不可用（400 在扣费校验之前，无资损）。与 C.6 同类：端点校验与路由层口径漂移。

**修复**：端点校验不再写死数字，统一引用常量——单段上限 `duration > DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS`、白名单 `range(4, DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS + 1)`，错误信息随常量口径；server.py import 补 `DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS`。confirm docstring、SOP（`sop-digital-human.md` 路由表与 11-15s 引用块）、`mcp_tool.py` 工具 description 与 wan2.2 引导文案、`docs/marketing_agent.md` 中残留的 10s 口径一并同步。

**防回归**：`tests/api/test_digital_human_h3_duration_validation.py` 新增 11 项端点校验用例（11-15s 单段放行 / 16s 无分段 400 / <4s 400 / 显式分段不受单段口径牵连 / 分段和校验保留）。红线：端点校验与路由层必须共用 `DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS`，禁止再写死 10/15。


### 附录 C.15 修复 VL 锁镜头提示词生成失败导致段间换装/换背景：重试 + 本地映射兜底 + 兜底模板加约束（2026-10-21）

**背景**：任务 12815（会话 98bb4735，52s 分 4 段）成片 0~14s 是灰衬衫深色演播室、14s 起变白大褂明亮诊所，用户在拼接点看到背景/衣服突变。调查证实与末帧接力/回锚无关（该任务黑段双杀后全链固定角色原图首帧，根本没走接力）：

1. **根因**：12:02:44 `_generate_locked_camera_prompt` 取角色图走远程下载，内网环境自访问 frp 公网地址（zjt-dev.perseids.cn）瞬时不通（httpx `ConnectError: All connection attempts failed`）→ 单次失败即降级为无约束兜底模板（`a static medium shot of a person facing the camera directly`，全文无服装/背景描述）。H3 webapp 是主体参考模式（人脸保留、服装/背景由提示词+采样自由生成），约束缺失 → 段 1 三次生成全部漂移成灰衬衫演播室（前两次 YAVG 106.3/69.7 被黑段相对判据连杀，第三次被 C.13 双杀回退强制放行），段 2-4 正常白大褂。
2. **对照**：同图任务 12814、异图任务 12812 的 VL 提示词均成功（含 `white medical lab coat` / `beige knitted cardigan...field of daisies` 细节），逐段抽首帧核验全部保真——证明机制本身无恙，纯提示词约束缺失所致。
3. 同 URL 的选音色路径（`_pick_voice_by_image`）12:02:21 也遇同样瞬断，但其有本地映射兜底所以成功了；锁镜头提示词路径无此兜底。12:02 后同一域名 curl 实测 93ms 正常，确认为瞬时故障。

**改动**（`script_writer_core/digital_human_tts_tools.py` + `config/constant.py`）：

- `_generate_locked_camera_prompt` 整体重试 `DIGITAL_HUMAN_VL_PROMPT_MAX_ATTEMPTS`（3）次、相邻间隔 `DIGITAL_HUMAN_VL_PROMPT_RETRY_DELAY_SECONDS`（2s），重试耗尽才降级兜底模板；每次尝试内远程下载失败后改用本地映射文件直读兜底一次（复用 `_pick_voice_by_image` 的 `try_map_url_to_local_file` 策略，直接命中 frp 自访问瞬断的主因）。
- `LOCKED_CAMERA_PROMPT_FALLBACK` 的 scene 槽位加入约束：`keeping the exact same outfit, hairstyle and background as the reference image`——兜底提示词细节少但不再放任 H3 换装/换背景。
- prepare 阶段注释与 `locked_note` 同步（兜底模板语义变化）。

**测试**：`tests/agents/test_digital_human_tts_tools.py` 新增 `TestLockedCameraPrompt` 4 项——瞬时失败重试至成功（断言尝试次数=MAX_ATTEMPTS）、远程失败走本地映射直读成功、重试耗尽返回 success=False、兜底模板含服装/发型/背景约束。34 项全过；CI 红线（blocking_calls/migration_names/tool_executor_signature/frontend_xss）全过。

### 附录 C.16 手部微动：锁镜头模板加"手部例外"条件从句 + 分镜链 DEFAULT_PROMPT 同步（2026-10-21）

**背景**：用户反馈生成的数字人手完全不动（口型由音频驱动，其余部位一动不动）。需求：输入图片中有手时，让手小幅动起来。**约束：不新增 LLM 调用**——营销链的 VL 本来就看图生成锁镜头提示词，顺带输出手部动作描述即可；分镜链本来就没有 VL 步骤，用条件从句把"有没有手"的判断交给视频模型自己对照首帧做。

**改动**（`script_writer_core/digital_human_tts_tools.py` + `config/constant.py`）：

- `LOCKED_CAMERA_PROMPT_TEMPLATE`：全身冻结措辞改为"身体姿态/服装/背景与参考图完全一致且保持静止（motionless）+ 条件从句 `If hands are visible in the frame, the hands make subtle natural movements—gentle finger gestures and small wrist motions only; otherwise the entire body remains fixed in the center of the frame`"。**不动 C.4/C.15 的防漂移强度**——镜头三件套（locked tripod / frozen frame / zero camera movement）原样保留，手部是唯一 carve-out，幅度锁死手指/手腕级别。
- `VL_LOCKED_CAMERA_INSTRUCTION`：在"提取性别/发型/服装/背景"之外要求 VL 检查有无清晰可见的手部——有则在场景描述中译入一句手部细微动作（禁止大幅度摆臂/改变手部结构），无则不提手；指令内嵌模板同步更新（VL 逐字照抄内嵌模板，不同步会被旧模板覆盖）。**同一次 VL 调用完成，零新增调用**；单段与分段模式都走 `h3_locked_prompt`（`effective_motion_prompt`/`SEGMENTED_MOTION_PROMPT` 仅 draft 展示，不进驱动），改一处全覆盖。
- 分镜链 `StoryboardDigitalHumanConstants.DEFAULT_PROMPT`：`图片1中的角色在说话。` → 追加"如画面中可见手部，手部配合说话有细微自然的动作（手指轻动、手腕微转），身体其余部分保持不动。"——条件从句无手不生效，避免无手图凭空"长出手"。

**测试**：`tests/agents/test_digital_human_tts_tools.py` 新增 2 项——模板/兜底/指令均含手部从句且防漂移约束（motionless / zero camera movement）不削弱；分镜 DEFAULT_PROMPT 含条件从句 + 身体锁定。

**待 A/B 验证**（沿用 C.4 流程）：含手图 10~20 张测"动起来比例 + 手部畸变率"，无手图若干张测 hallucinate 长手风险，并回归段间换装/换背景（不得重现 12815）；不达标则收紧措辞或整体回退（改动集中在 3 个常量，回退成本极低）。

### 附录 C.17 修复传 motion_prompt 跳过 VL 选音色导致 voice_id=None 崩溃（750aba96，2026-10-21）

**背景**：会话 750aba96（更年期数字人口播）专家首次 prepare 抛"准备数字人草案异常: int() argument must be ... not 'NoneType'"，被误判为"语音服务不可用"反馈用户；专家去掉 motion_prompt 重试才巧合自救。根因：`need_vl_analysis` 旧条件含 `(not motion_prompt)` 因子，专家按 SOP 传 motion_prompt 时整体跳过 VL 看图选音色，`voice_id` 保持 None 流到下游 `synthesize_speech_for_user(voice_id=int(voice_id))` 崩溃——motion_prompt 与选音色是两个独立参数，互不隶属。

**改动**（`script_writer_core/digital_human_tts_tools.py`）：

- `need_vl_analysis` 改为 `bool(image_url) and ((need_voice and not voice_id) or not motion_prompt)`：缺音色（需声音且未指定）**或**缺动作提示词才看图分析。比调查报告建议的 `(need_voice or not voice_id)` 多保留一条性质：音色与动作提示词**都已显式给出**时走快速路径不触发 VL 分析（省一次调用、参数不被覆盖）。
- 合成前加防御：需要音色却仍未确定时返回明确错误"未能确定音色：请显式指定 voice_id，或提供驱动音频（audio_url）后重试"，杜绝此类场景再被包装成 int(None) TypeError 误导排障。

**注意**（遗留观察，未改）：VL 分支内 `voice_id = picked["voice_id"]` 仍会**覆盖**显式指定的 voice_id（只传 voice_id 不传 motion_prompt 时命中）——与 docstring"voice_id 显式指定 > VL 看图挑选"的优先级表述不一致，但属存量行为且 SOP 常规传 motion_prompt 不会命中，留待需要时单独处理。

**测试**：`tests/agents/test_digital_human_tts_tools.py` 新增 2 项——`test_motion_prompt_does_not_skip_vl_voice_picking`（回归：传 motion_prompt 仍走 VL 选音色、voice_id 正确、显式 motion_prompt 优先；已验证在旧代码上复现 int(None) TypeError 失败）、`test_explicit_voice_and_motion_skip_vl_analysis`（快速路径：双显式不触发 VL 分析）。

**加固（同日追加，用户反馈同型报错再次出现 2 次）**：对 prepare 全链路做 int(None) 风险盘点——当前代码上 :573/:590/:606/:667 的 `int(voice_id)` 均被 2.5 防御与门条件覆盖、`_pick_voice_by_image` 的 JSON 解析异常被自身 try 降级、`_resolve_draft_resolution`/`synthesize_speech_for_user` 入参均有保护，**已无 reachable 的 int(None) 路径**（再现已推未部署时段的旧版本）。仍追加两层防御防回归：

- 入口规范化 `voice_id`：非数字（LLM 传 `'abc'` 等脏值）立即返回"voice_id 必须是数字音色 ID，收到: ..."，0/负数归一为未指定——下游所有 int(voice_id) 拿到的只会是 int 或 None。
- 外层兜底错误文案带异常类型名：`准备数字人草案异常(TypeError): ...`，专家上报可直接引用类型、命中对应降级规则（服务端堆栈本就有 `logger.error(exc_info=True)` 记录）。

新增 `test_invalid_voice_id_rejected_with_clear_error`：脏 voice_id 返回参数级明确错误，不再冒"准备数字人草案异常"笼统文案。
