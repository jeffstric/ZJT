# 火山引擎（豆包语音）TTS 快速合成 + 音色库

> 2026-10 接入，2026-10-12 实测对齐**语音合成 2.0**（`seed-tts-2.0`）接口并
> 端到端验证通过（真实合成 / 试听缓存 / 扣费流水 / 历史记录）。
> IndexTTS 克隆链路（`/api/audio-generate`）保持不变、免费。

## 一、功能总览

| 能力 | 入口 | 说明 |
|---|---|---|
| 音色库 | `GET /api/tts/voices` | `voice` 表系统预置音色（7 个 2.0 音色），附计价档位 |
| 快速合成 | `POST /api/tts/synthesize` | 同步秒级返回 `audio_url`；预扣算力，失败退款 |
| 试听 | `GET /api/tts/preview/{voice_id}` | 服务端固定示例句 + 按音色落盘缓存，**免费** |
| 声音页 UI | `web/js/pages/audio_generate.js` | 顶部模式切换：音色库合成 / 参考音频克隆 |
| 工作流节点 | `web/js/text_to_speech_node.js` | TTS 节点"合成引擎"下拉，重载后自动复原 |
| 管理配置 | admin 快速配置 → 多媒体 | 「火山引擎语音合成」卡片，单 API Key |

## 二、开通与配置（部署前置）

1. 火山控制台 → **语音技术**（豆包语音，新版控制台
   <https://console.volcengine.com/speech/new>）→ 开通「**语音合成 2.0**」
   （新用户有 2 万字免费试用额度）。
2. **API Key 管理** 创建 API Key：⚠️ 密钥本体是 UUID 形式的字符串
   （`api-key-xxx` 是 key 名称，别复制错）。
3. 配置（YAML 或管理后台「快速配置-多媒体」均可，DB 优先热生效）：

```yaml
volcengine_tts:
  api_key: ""       # 豆包语音控制台 API Key（UUID 密钥本体）
  # resource_id: "seed-tts-2.0"   # 语音合成 2.0（默认）；seed-icl-2.0 为声音复刻
  # power_tiers: [[50, 1], [200, 4], [500, 10], [1000, 20], [2000, 40]]
```

4. 未配置时合成接口返回友好错误；音色需在控制台「音色库」可用。

## 三、接口实测记录（2026-10-12，重要）

新版 2.0 接口与旧版大模型 TTS（`volc.service_type.10029`）**不兼容**，踩坑记录：

| 项 | 2.0 正确姿势 | 旧版/错误姿势（实测报错） |
|---|---|---|
| 鉴权 | `X-Api-Key: {uuid}` 单头 | `X-Api-App-Key`+`X-Api-Access-Key` 双头 → 401 grant not found |
| 资源 ID | `seed-tts-2.0` | `volc.service_type.10029` → 403 resource not granted |
| 请求体 | `{"req_params": {...}}` 包裹 | 平铺 `user/reqid/voice_type/...` → 200 speaker mismatch |
| 音色参数 | `speaker` | `voice_type` |
| 音色 ID | `zh_female_vv_uranus_bigtts`（2.0 音色库） | `BV700_streaming` → speaker mismatch |
| 请求头 | 另需 `X-Api-Request-Id: {uuid}` | — |
| 语速 | `speech_rate`：-50~100（100=2.0x） | `speed_ratio` 0.2~3.0 |
| 响应 | **JSON 块流**：`{"code":0,"data":"<b64>"}` 串联，结束块 `{"code":20000000}` | v3 二进制帧（4字节头+payload） |

代码侧已全部按 2.0 实测姿势实现（`utils/volcengine_tts_util.py`）。

## 四、计费

- **模式**：字符档位预付费（与图像/视频"提交预扣 + 失败退款"惯例同构）。
- **档位默认值**（`config/volcengine_tts_constants.py` `POWER_TIERS`）：

  | 文本长度 | 算力 | 参考成本（5元/万字符） |
  |---|---|---|
  | ≤50 字 | 1 | 0.025 元 |
  | ≤200 字 | 4 | 0.10 元 |
  | ≤500 字 | 10 | 0.25 元 |
  | ≤1000 字 | 20 | 0.50 元 |
  | ≤2000 字（上限） | 40 | 1.00 元 |

- **热更新**：动态配置 `volcengine_tts.power_tiers`（DB 优先 YAML 兜底）。
- **退款**：火山调用失败 / 落盘失败 → 立即退款，流水号 `refund-{原流水号}` 幂等。
- **流水绑定**：`ai_audio.transaction_id` 保存预扣流水；`engine`/`voice_id`
  记录引擎与所用音色。
- **计费凭证**：与登录同一来源。`Authorization` 为空时使用 `?auth_token=`。
  两者都空时合成服务才跳过扣费（仅内部无登录调用）；HTTP 入口没有凭证会先 401。
- **免费路径**：算力 0 时跳过扣费；试听永远免费
  （固定示例句 + 按音色缓存 `preview_{voice_type}.mp3`）。
- **预置音色 voice_type**：`reference_audio` 行必须是 SQL NULL，不能是字符串 `NULL`。
  `no_152` 种子插入 `None`；已升级库由 `no_153` 把误写成 `'NULL'` 的行改回。

## 五、代码结构

| 文件 | 职责 |
|---|---|
| `config/volcengine_tts_constants.py` | 常量独立文件：端点/资源ID/超时/档位/2.0 音色种子/换算函数 |
| `model/voice.py` | 音色库表 `voice`（provider 维度：volcengine / reference_audio 预留） |
| `alembic/versions/no_145_*` | 建 voice 表 + ai_audio 加 `engine`/`voice_id` |
| `alembic/versions/no_146_*` | 音色种子切换到 2.0（旧 BV 音色下线） |
| `utils/volcengine_tts_util.py` | 2.0 客户端（httpx 全 async）+ `TtsJsonBlockDecoder` 块流解析 |
| `api/tts.py` | 三个接口 + 计价/预检/预扣/退款链路 |
| `web/js/voice_library_api.js` | 前端共享 API（声音页 Vue 与工作流画布共用，fetch，不依赖 axios） |
| `web/js/components/voice_picker.js` | Vue 音色选择器（卡片/筛选/试听） |
| `web/js/pages/audio_generate.js` | 声音页双模式表单 |
| `web/js/text_to_speech_node.js` | 工作流 TTS 节点引擎切换 |
| `web/js/admin.js` + `config/default_configs.py` | 管理后台快速配置（volcengine_tts.api_key） |

工作流画布注意：

- `video_workflow.html` 不加载 axios。音色列表、试听、快速合成都走 `voice_library_api.js` 的 `fetch`，并带 `Authorization` 头。
- 节点文案键在 `web/i18n/locales/{zh-CN,en}/video_workflow.json`。`window.t` 缺键时返回键名本身（标题会显示 `tts_title`，按钮会显示 `tts_generate_btn`），节点里的中文兜底不会生效，新增文案必须同时写入中英语言包。
- 快速合成下拉只请求 `provider=volcengine`。`reference_audio` 是克隆参考，不能走 `/api/tts/synthesize`。

## 六、音色维护

- 一期种子：7 个 2.0 音色（Vivi/小何/温暖阿虎/解说小明/温柔妈妈/魅力苏菲/
  魅力女友），2026-10-12 逐一合成验证通过（`VOLCENGINE_TTS_VOICES`）。
- 控制台标准音色共 99 个，其余按需增补：常量加行 → 新迁移插入；或直接
  `voice` 表 INSERT（完整音色 ID 在控制台音色库详情页复制）。
- 下线音色：`UPDATE voice SET is_active=0 WHERE voice_type='...'`。
- 声音复刻 2.0（`seed-icl-2.0`）克隆音色接入为二期（已开通，2 万字额度）。

## 七、测试

```bash
python -m pytest tests/api/test_tts_api.py tests/utils/test_volcengine_tts_util.py -q
# 24 passed：JSON块流解析（多块/半块/utf8切断）、计价档位、语速换算、
# 余额不足400、失败退款幂等、成功链路落盘+ai_audio、试听缓存命中
```

端到端实测（2026-10-12，本地 prod 环境）：`POST /api/tts/synthesize`
29 字 → 5.47s mp3、扣 1 算力、`ai_audio` 写入 engine=volcengine/voice_id/speed=1.2。

## 八、二期规划（未实施）

- 声音复刻 2.0：角色参考音频克隆为专属音色（`seed-icl-2.0`）；
- 用户私有音色（`voice.user_id>0` CRUD）与收藏；
- 分镜自动配音切换引擎（`character.default_voice` 扩展音色库语义）；
- 情感参数与语音指令（2.0 支持 context_texts 情绪上下文）；
- IndexTTS 克隆链路是否同档位收费（当前免费）。
