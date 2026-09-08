# 成片对白音色替换

成片（Seedance / Kling / MiniMax H3 / Veo 等）里的说话音色是随机的，和角色库无关。本功能在成片之后做 **音色转换（VC）**，保住口型，不用 TTS 盖掉原声。

VC 后端当前主力为 **Vevo2**（Amphion style-preserved VC，FM-only 推理，音质/相似度优于 Seed-VC）；Seed-VC 保留作回退。

送进 VC 之前必须先 **UVR 人声/环境声分离**，只对人声做音色替换，再把原环境声叠回去。整段带 BGM/风声/底噪一起转，效果会明显变差。

相关入口：`storyboard.html`、`video_workflow.html` 分镜节点。

## 谁 / 何时

| 问题 | 权威 | 不靠什么 |
|------|------|----------|
| 谁在说 | `storyboard_dialogue.character_id` / `shotJson.dialogue` | 成片音色、性别、音高 |
| 哪一段时间 | SenseVoice ASR 带时间戳的转写 | 平均切时长（仅兜底） |

参考音用角色 `default_voice`。跨男女替换效果会明显变差，测试时尽量给角色挂同性别参考音。

对齐 **不是**「把 ASR 句子分类成某个角色」，也 **不是** 台词字符串相等：

> 已知有序对白 `D1…Dn`（每句已有角色），把 ASR 时间轴切成 n 段，使第 i 段尽量对应 Di 的文本；再拿 Di 的 `character.default_voice` 做 VC。

实现：`services/voice_replace/aligner.py`。

## 打分

规范化（NFKC、去标点空白、全半角）后：

- `recall` = LCS / 对白长度
- `precision` = LCS / ASR 窗口长度（防止短台词吞掉后面整段）
- `pinyin_recall` = 拼音音节 LCS（无 `pypinyin` 时退化为字级）
- `score = 0.4 * recall + 0.4 * precision + 0.2 * pinyin_recall`

完全相等才给满分。成片多了「那堆」这类字，分数仍会很高，但长窗口因为 precision 低，不会抢走下一句。

## 切分

- **唯一角色**（含同一人多句）：整段语音都归他，不算文本门槛。
- **多人**：从左到右在 ASR 字时间轴上找每句的最佳窗口（有序、不交叉）。
- **成片乱编、分数低于 `VOICE_REPLACE_SCORE_LLM`**：按对白字数比例切整段，`method=order`，默认等用户确认。
- 对不上的 ASR（广告/胡话）进 `leftover_asr`，**保留原声**，不猜测角色。
- 成片漏了某句：该句 `method=skipped`，不补 TTS。

阈值见 `config.constant.VoiceReplaceConstants`。

## 场景

| 场景 | 行为 |
|------|------|
| 单人 | 短路整段 VC |
| 双人台词接近 | 窗口切在 ASR 段界，各转各的 |
| 一人声演两人 | 仍按对白切两段，用两个参考音；不按 speaker_id |
| 音色完全不像提示词 | 忽略源音色，只看文本/顺序 |
| 数字人 | 跳过（驱动音已是角色 TTS） |
| 无对白 / 无语音 | skip |

## 基础设施

推理服务（SenseVoice ASR / UVR 人声分离 / Vevo2 VC，Seed-VC 保留作回退）部署在独立的 GPU 推理服务器上，具体地址与部署方式不入库：worker 通过 yaml `voice_replace.*_base_url` 或环境变量（`SENSEVOICE_ASR_URL` / `UVR_URL` / `VEVO2_URL` / `SEEDVC_URL`）获取地址，未配置时回落 `VoiceReplaceConstants` 占位地址。前端禁止直连这些服务。

一期不做说话人分离（cam++）。内容切分优先。

### SenseVoice ASR

- `POST /api/v1/asr_segments`：fsmn-vad 切段 + 每段 ASR，返回 `{start,end,text,raw_text}`（秒）
- `POST /api/v1/asr`：兼容接口（无时间戳）
- 推理在线程池 + `asyncio.wait_for`，超时 60s

注意：SenseVoice 的 CTC timestamp 是 `[token, t0, t1]`，FunASR `inference_with_vad` 会把 `t[0]` 当毫秒做加法而崩溃。分段接口因此用 **VAD 时间 + 逐段 ASR**，不用 `output_timestamp=True`。

## 任务与产物

- 独立表 `video_voice_replace_job` / `video_voice_replace_segment`，不进 `ai_tools`。
- **分镜页手动触发（当前）**：对话页签「音频来源」下的「替换音色」→ `POST /api/storyboard/scene/{id}/voice-replace`。只处理**当前选中成片**，不自动入队、不做批量。
- 跳过：对口型、无视频、无对白、角色全无 `default_voice`。同一成片已 `completed` 再点会带 `force` 重跑；进行中再次点击复用原任务。
- `GET /api/storyboard/scene/{id}/voice-replace` 给按钮轮询状态。
- scheduler `process_voice_replace_jobs` 拾取 `queued` → UVR 分离人声/环境声 → 对人声 ASR → 对齐 →（低置信则 `wait_confirm`）→ 只对人声 Vevo2 → 叠回环境声 → mux。
- UVR 失败时回退成片混音（旧行为），并打 warning，不把任务直接打挂。
- `Kim_Vocal_2` 等 karaoke 模型有时把对白分到 Instrumental。worker 会对两条 stem 都做 ASR，选有字的那条当人声。
- 产物写 `upload/voice_replace/{job_id}/result.mp4`，并挂成新的分镜视频 candidate；成功后 `audio_embedded=1`。
- 低置信默认 `wait_confirm`。工作流节点一期 skip（`workflow_not_supported`）。数字人 skip。
- worker 默认打公网入口地址（经 yaml `voice_replace.*_base_url` 配置下发），未配置时回落 `VoiceReplaceConstants` 占位常量。

## 相关代码

- `services/voice_replace/aligner.py`
- `services/voice_replace/asr_driver.py`：`SenseVoiceAsrDriver`（httpx 异步 `POST /api/v1/asr_segments`）
- `services/voice_replace/uvr_driver.py`：`UvrDriver`（httpx 异步 `POST /api/v1/uvr`，zip 内 `vocals.wav` / `instrumental.wav`）
- `services/voice_replace/vevo2_driver.py`：**主力 VC 驱动**。`Vevo2Driver.convert(source, reference, dest)` → `POST /api/v1/convert`（multipart，zip 内 `converted.wav`）。flow-matching 步数 `VEVO2_FM_STEPS=32`，超时 `VEVO2_TIMEOUT=300`。**只转 UVR 人声**；对白窗口前后各留 1.5s 上下文。切太短（~1.5s）会把字转糊；带环境声整段转会把底噪变成胡话。
- `services/voice_replace/seedvc_driver.py`：Seed-VC Gradio `/gradio_api/call/predict`（取非流式 wav），回退保留，worker 不再引用。
- `services/voice_replace/ffmpeg_util.py`：抽音 / 切片 / atempo / concat / 人声+环境声 `amix` / mux（`asyncio.create_subprocess_exec` + 超时）。Seed-VC 输出常为 22050Hz，所有片段先 `aresample=44100` 再拼接；混流按**视频时长** `apad`，禁止 `-shortest` 把成片截短。
- `services/voice_replace/enqueue.py`：分镜入队（`enqueue_scene_job`）
- `services/voice_replace/worker.py`：单任务编排
- `api/storyboard.py`：`POST/GET /scene/{id}/voice-replace`
- `web/js/storyboard/render.js`：对话页「替换音色」按钮
- `task/voice_replace_task.py`：scheduler 每 8s 拾取 `queued` 任务（`max_instances=1`）
- `config/constant.py`：`VoiceReplaceConstants`、`VoiceReplaceJobStatus`
- YAML：`voice_replace.asr_base_url` / `uvr_base_url` / `vevo2_base_url` / `seedvc_base_url`（可用 `SENSEVOICE_ASR_URL`、`UVR_URL`、`VEVO2_URL`、`SEEDVC_URL` 覆盖）
- `tests/services/test_voice_replace_aligner.py`
- `tests/services/test_voice_replace_asr_driver.py`
- `tests/services/test_voice_replace_uvr_driver.py`
- `tests/services/test_voice_replace_vevo2_driver.py`
- `tests/services/test_voice_replace_enqueue.py`

`SenseVoiceAsrDriver.transcribe_segments(audio)` 接受本地路径、bytes 或 http(s) URL，返回 `List[AsrSegment]`，可直接交给 `align_dialogues`。超时 `ASR_TIMEOUT` / `HTTP_CONNECT_TIMEOUT`。禁止在 API 协程里用 `requests`。
