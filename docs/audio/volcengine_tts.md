# 火山引擎（豆包语音）TTS 快速合成 + 音色库

> 2026-10 接入。火山大模型语音合成（V3 单向流式 HTTP），支持**秒级快速合成**与
> **预置音色库切换**；按字符档位**预扣算力**，失败自动退款。IndexTTS 克隆链路
> （`/api/audio-generate`）保持不变、免费。

## 一、功能总览

| 能力 | 入口 | 说明 |
|---|---|---|
| 音色库 | `GET /api/tts/voices` | `voice` 表系统预置音色（种子 13 个免费音色），附计价档位 |
| 快速合成 | `POST /api/tts/synthesize` | 同步秒级返回 `audio_url`；预扣算力，失败退款 |
| 试听 | `GET /api/tts/preview/{voice_id}` | 服务端固定示例句 + 按音色落盘缓存，**免费** |
| 声音页 UI | `web/js/pages/audio_generate.js` | 顶部模式切换：音色库合成 / 参考音频克隆 |
| 工作流节点 | `web/js/text_to_speech_node.js` | TTS 节点"合成引擎"下拉，重载后自动复原 |

## 二、开通与配置（部署前置）

1. 火山控制台 → **语音技术** → 开通「语音合成大模型」→ 应用管理创建应用。
   ⚠️ 这是**豆包语音控制台**的凭证，与方舟 `volcengine.api_key` **不是同一套**。
2. 在 `config_dev.yml` / `config_prod.yml` 填写：

```yaml
volcengine_tts:
  app_key: ""       # 豆包语音控制台 App ID
  access_key: ""    # 豆包语音控制台 Access Token
  # resource_id: "volc.service_type.10029"   # 默认即可
  # power_tiers: [[50, 1], [200, 4], [500, 10], [1000, 20], [2000, 40]]  # 可选热更新
```

3. 未配置时 `/api/tts/synthesize` 返回友好错误（提示填配置），不影响其他功能。
4. 音色需在控制台「音色列表」中可用且**免费**（通用音色如 `BV700_streaming`
   免费可直接用；精品音色需购买授权，见下文"音色维护"）。

## 三、计费

- **模式**：字符档位预付费（与图像/视频"提交预扣 + 失败退款"惯例同构）。
- **档位默认值**（`config/volcengine_tts_constants.py` `POWER_TIERS`）：

  | 文本长度 | 算力 | 参考成本（5元/万字符） |
  |---|---|---|
  | ≤50 字 | 1 | 0.025 元 |
  | ≤200 字 | 4 | 0.10 元 |
  | ≤500 字 | 10 | 0.25 元 |
  | ≤1000 字 | 20 | 0.50 元 |
  | ≤2000 字（上限） | 40 | 1.00 元 |

- **热更新**：动态配置 `volcengine_tts.power_tiers`（DB 优先 YAML 兜底），
  格式 `[[上限字符, 算力], ...]` 升序。
- **退款**：火山调用失败 / 落盘失败 → 立即 `increase` 退款，流水号
  `refund-{原扣费流水号}` 幂等（`computing_power_log` 自动配对展示）。
- **流水绑定**：`ai_audio.transaction_id` 保存预扣流水；`engine`/`voice_id`
  记录引擎与所用音色（历史列表可直接混排两种引擎的记录）。
- **免费路径**：无 Authorization 头或算力 0 时跳过扣费（开源部署惯例）；
  试听永远免费（固定示例句 + 按音色缓存 `preview_{voice_type}.mp3`，防
  "自定义试听文本"套利）。

## 四、代码结构

| 文件 | 职责 |
|---|---|
| `config/volcengine_tts_constants.py` | 常量独立文件：端点/超时/档位/音色种子清单/计价与语速纯函数 |
| `model/voice.py` | 音色库表 `voice`（provider 维度：volcengine / reference_audio 预留） |
| `alembic/versions/no_145_20261011_create_voice_library_volcengine_tts.py` | 建表 + 种子音色 + `ai_audio` 加 `engine`/`voice_id` |
| `utils/volcengine_tts_util.py` | V3 客户端（httpx 全 async）+ `V3ChunkDecoder` 帧解析器 |
| `api/tts.py` | 三个接口 + 计价/预检/预扣/退款链路 |
| `web/js/voice_library_api.js` | 前端共享 API（声音页 Vue 与工作流画布共用） |
| `web/js/components/voice_picker.js` | Vue 音色选择器（卡片/筛选/试听） |
| `web/js/pages/audio_generate.js` | 声音页双模式表单 |
| `web/js/text_to_speech_node.js` | 工作流 TTS 节点引擎切换 |

## 五、关键实现说明

### 1. V3 单向流式协议

- 端点：`POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`
- Header：`X-Api-App-Key` / `X-Api-Access-Key` / `X-Api-Resource-Id: volc.service_type.10029`
- 响应为 chunked 二进制帧：4 字节协议头（版本/类型/序列化/压缩）+ JSON
  payload（音频 base64 在 `data`，`is_last` 标记结束），拼接全部 `data` 即完整 mp3。
- `V3ChunkDecoder` 带缓冲、支持半帧重组，同时兼容"尾部 4 字节 payload_size"
  变体布局；官方协议按消息边界 flush（每 chunk 一帧）。⚠️ 若线上实测帧格式
  与官方文档有出入，只需调整该类（单测：`tests/utils/test_volcengine_tts_util.py`）。
- 请求体字段以官方文档为准；当前实现按社区通用结构（`user/operation/reqid/
  text/voice_type/audio_params`），首次真实联调时逐字段核对。

### 2. 落盘与 CDN

- 结果落盘 `upload/tts/volcengine/tts_{时间}_{uuid8}.mp3`（临时名 + `os.replace`
  原子替换），对外 URL `{server_host}/upload/tts/volcengine/...`。
- 注册七牛 CDN mapping（`MediaFileEntity.TTS`，NEVER_EXPIRE），注册失败自动
  本地直出兜底；时长用 ffprobe（`probe_audio_duration`）。

### 3. 音色维护

- 种子清单唯一事实来源：`config/volcengine_tts_constants.py` 的 `VOLCENGINE_TTS_VOICES`
  （上线前对照官方[音色列表](https://www.volcengine.com/DoubaoVoice/Tonelist-1)
  核对 voice_type 与"免费"标记）。
- 增补音色：常量加行 → 新迁移插入；或直接 `voice` 表 INSERT。
- 下线音色：`UPDATE voice SET is_active=0 WHERE voice_type='...'`（接口按
  is_active 过滤，历史记录不受影响）。
- 免费额度与单价随官方活动变动，以控制台
  [计费说明](https://www.volcengine.com/docs/6561/1099320) 为准。

## 六、测试

```bash
python -m pytest tests/api/test_tts_api.py tests/utils/test_volcengine_tts_util.py -q
# 26 passed：帧解析(官方/seq/gzip/变体/半帧/error/超限)、计价档位边界、
# 余额不足400、上游失败退款幂等、成功链路落盘+ai_audio、试听缓存命中
```

## 七、二期规划（未实施）

- 用户私有音色（`voice.user_id>0` CRUD）与收藏；
- 声音复刻 2.0：角色参考音频克隆为火山 voice_type，与预置音色混用；
- 分镜自动配音切换引擎（`character.default_voice` 扩展音色库语义）；
- 情感参数（火山 `emotion`/`emotion_scale`，仅情感音色生效）；
- IndexTTS 克隆链路是否同档位收费（当前免费）。
