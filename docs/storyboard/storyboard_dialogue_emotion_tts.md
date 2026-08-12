# 故事板对白情感向量 TTS（企业版）

## 概述

剧本拆分后自动配音默认与角色参考音相同（`emo_control_method=0`）。  
**企业版**在拆分阶段由 LLM 为每句对白产出 8 维情感向量 `emo_vec`，入库后自动/手动配音以 `emo_control_method=2` 提交 IndexTTS。

## 版本门禁

| 档位 | 行为 |
|------|------|
| 开源/社区版 | 门面 Community，不注入 parser 指令，配音不带向量 |
| 个人版 Studio（许可证 `edition=studio`） | Provider 可注入，但 `is_enabled()=False` |
| 企业版（许可证 `edition=enterprise`） | 全链路启用 |

门面：`services/dialogue_emotion.py`  
实现：`enterprise/services/dialogue_emotion/`  
探查：`GET /api/system/...` 返回 `data.features.dialogue_emotion_tts`

## 情感向量约定

与 `web/js/pages/audio_generate.js` 一致：

- 维度顺序：喜、怒、哀、惧、厌恶、低落、惊喜、平静
- 每维 `[0, 1.5]`，总和 `≤ 1.5`
- 存储：`storyboard_dialogue.emo_vec` 逗号分隔字符串

### 超和后备

服务端 `normalize`（enterprise）：

1. 单维钳制
2. `sum > 1.5` → **比例缩放**到 1.5
3. 非法/全 0 → 不启用向量（method=0）

## 数据流

```text
script_parser（企业版注入 emo_vec 指令）
  → build_storyboard_scenes_from_parsed_script（normalize 后写入 payload）
  → storyboard_dialogue.emo_vec
  → StoryboardVoiceoverBootstrapService.ensure_dialogue_voiceover
       → resolve_tts_emotion_kwargs（门面）
  → ai_audio(emo_control_method=2, emo_vec=...)
  → audio_task / IndexTTS
```

## 安全

- 主仓禁止业务层直读 `emo_vec` 写 TTS，必须经门面。
- 社区/个人版即使 API body 带 `emo_vec` 也不会生效。
- script_split worker / scheduler 须走 enterprise bootstrap 注入 Provider。

## 相关常量

`config.constant.EmotionVectorConstants`

## 关键日志（排障）

统一前缀 **`[dialogue-emotion]`**，便于 `grep`：

| 位置 | 标记 |
|------|------|
| script_parser 注入指令 | `[dialogue-emotion][script-parser] emotion instructions enabled` |
| 落库前 normalize | `[dialogue-emotion] normalize ok/scaled ... emo_vec=...` |
| build scenes | `[dialogue-emotion][build-scenes] ... normalized_emo_vec=...` |
| 自动配音提交 | `[dialogue-emotion][voiceover-bootstrap] ... emo_control_method=... emo_vec=...` |
| TTS 执行 | `[dialogue-emotion][audio-task] task_id=... emo_control_method=... emo_vec=...` |
| 档位门禁 | `[dialogue-emotion] gate edition=... allowed=...` |

本地冒烟（不跑完整 LLM 拆分）：

```bash
# 项目根，使用已装依赖的 Python
set comfyui_env=prod
.venv\Scripts\python.exe scripts\test_dialogue_emotion_pipeline.py
```

完整线上验证：企业版许可证 + 拆分 worker bootstrap 后，对故事板点「从剧本生成」，在 worker/Web 日志中检索上述前缀。
