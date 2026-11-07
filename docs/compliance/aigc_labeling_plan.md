# 深度合成内容标识合规方案（AIGC Labeling Plan）

> 状态：**第一阶段（增量隐式标识）已实施**（2026-11-08，develop_f1163）——实施细节与挂点清单见 [docs/backend/aigc_marking.md](../backend/aigc_marking.md)。本文档保留整体方案与后续阶段规划。
> 依据：《互联网信息服务深度合成管理规定》（2023-01-10 施行）、《人工智能生成合成内容标识办法》（国信办通字〔2025〕2号，2025-09-01 已施行）、强制性国标 GB 45438-2025《网络安全技术 人工智能生成合成内容标识方法》及 6 项配套标准实践指南。
> 实施决策（2026-11-07 评审）：ContentProducer 先用占位值 `zjt`（标识服务平台不可访问，申请到正式编码后替换）；**不补存量**，仅增量覆盖；隐式标识先行，显式标识后续阶段。
> 原方案结论：**系统此前完全不具备内容标识能力（无水印、无元数据写入），而《标识办法》已于 2025-09-01 施行，属存量不合规，需按 P0 优先级落地。**

---

## 一、法规义务 → 系统差距对照表

| # | 义务 | 条款依据 | 要求摘要 | 系统现状 | 差距 |
|---|------|---------|---------|---------|------|
| 1 | **隐式标识（元数据）** | 深度合成规定第 16 条；标识办法第 5 条；GB 45438-2025 附录 E | 生成内容的**文件元数据**中写入：内容属性信息（Label）、服务提供者名称/编码（ContentProducer）、内容编号（ProduceID） | **无任何元数据写入**（仅 `runninghub_ai_app_image_v1_driver.py:164` 读 EXIF 方向） | ❌ 缺失 |
| 2 | **显式标识** | 深度合成规定第 17 条；标识办法第 4 条 | 智能对话、合成人声、人脸生成等易混淆内容须添加显著提示（文本提示 / 音频语音提示 / 图片适当位置 / 视频起始画面）；其他服务须提供显著标识功能 | **无**。唯一画面写入能力是 ASS 字幕硬烧（`services/storyboard_subtitle.py:708`）；上游水印参数只控制供应商水印（如 `seedream_volcengine_v1_driver.py:295 watermark:False`），非本平台标识 | ❌ 缺失 |
| 3 | **下载/复制/导出保标识** | 标识办法第 4 条 | 提供下载、复制、导出功能时，确保文件中含有显式标识（隐式标识随文件元数据自然携带） | 出口较多：`GET /api/download`（server.py:1104）、故事板整片导出（api/storyboard.py:6555）、素材包（6677）、剪映草稿导出（server.py:12030+）、时间轴素材包（12482）、世界包导出（api/script_writer.py:6787）、资产库（api/asset_library.py:161）、Agent CLI `/generate-image` | ❌ 缺失 |
| 4 | **用户协议披露** | 标识办法第 8 条 | 用户服务协议中说明标识的方法、样式规范 | 用户协议未见 AIGC 标识条款 | ❌ 缺失 |
| 5 | **无显式标识申请的留痕** | 标识办法第 9 条 | 用户申请不添加显式标识的，须先通过用户协议明确其义务责任，并**依法留存提供对象信息日志 ≥6 个月** | 无相关记录机制 | ❌ 缺失 |
| 6 | **禁止删标/不得提供删标工具** | 标识办法第 10 条 | 任何组织和个人不得恶意删除、篡改、伪造、隐匿标识，不得为他人实施提供工具或服务 | 系统内置**视频去水印**功能（task 49，`video_watermark_runninghub_v1_driver.py`），且多处驱动显式关闭上游水印（watermark=False） | ⚠️ 需评估 |
| 7 | **站内传播核验与提示** | 标识办法第 6 条 | 传播服务提供者核验元数据隐式标识，确认为 AI 内容的加显著提示；用户提供声明功能的 | 灵感广场（api/marketing_publications.py）为站内传播场景，无核验、无提示 | ❌ 缺失 |
| 8 | **日志与溯源留存** | 深度合成规定第 14、15 条 | 生成内容日志留存；向主管部门提供溯源支持 | ✅ **已具备**：`ai_tools`（user_id/type/prompt/implementation/result_url/extra_config）、`ai_tools_log`（全量事件）、`media_file_mapping`、资产库 `source_url` | ✅ 数据基础完整 |
| 9 | **实名认证** | 深度合成规定第 14 条 | 不得向未实名用户提供服务 | ✅ 手机号+验证码注册（users 表） | ✅ 已满足 |
| 10 | **服务提供者编码** | 标识办法第 5 条 | ContentProducer 需服务提供者名称或**编码**（标识服务平台 aigc.cac.gov.cn） | 未申请 | ⚠️ 行政流程，需立即启动 |

---

## 二、系统现状（调查结论）

### 2.1 内容生成类型（全部在标识义务范围内）
- **图片**（12+ 驱动）：moss 文生图（task 53）、gpt_image_duomi 系列（25/26/46/47）、Seedream（16/18/33）、Gemini 图片编辑（1/7/17/51）、Qwen（24/38/52）、高清放大（4）、宫格/分镜批量图等
- **视频**（30+ 驱动）：Seedance 全系（21/22/23/31/36）、LTX2（10/20）、可灵（12）、VEO3.1（15）、Sora2（2）、万相（11/39）、Vidu（19/42/43/44）、数字人（13/32/35，含分段拼接 `task/compose_task.py:564`）、高清修复（5）、**去水印（49）**、营销视频 article-to-video（enterprise/tools/marketing_video_tools.py）
- **音频**：TTS（api/tts.py → volcengine_tts_service.py）、音色克隆（task 9）、变声/配音替换（services/voice_replace/）
- **文本**：剧本写作、剧本拆解、分镜 Agent、营销智能体、LLM 对话

统一调度链：`server.py` → `ai_tools` 落库 → `task/visual_task.py:1387 process_generate_video` → 驱动提交/轮询 → `_handle_task_success`（visual_task.py:1096）→ `download_queue` → worker 下载 → `utils/media_cache.py:186 download_and_cache` 落盘 → 回写 `ai_tools.result_url`。

### 2.2 存储与分发
- 本地 `upload/cache/<日期>/` 等目录 + 七牛 CDN 长期桶（`utils/file_storage/qiniu_storage.py`，CDN 302 重定向 server.py:1040）
- **关键发现：`download_and_cache` 是所有生成产物落盘的汇聚点** —— 在此挂标识写入，一处覆盖全部生成链路
- 分发出口：`/api/download`（三模式：本地/CDN 重签名 302/外链代理）、静态 `/upload/`、各类导出端点、资产库、Agent CLI

### 2.3 现有可复用能力
- ffmpeg 已有（`bin/ffmpeg/`，路径经配置 `bin.ffmpeg`），支持无损 remux 写元数据
- Pillow 已有（图片元数据处理零新依赖）
- 溯源数据完整，ProduceID 可直接用 `ai_tools.id`

---

## 三、方案设计

### 3.1 总体架构：两个卡点 + 一个编号体系 + 一个分级策略

```
生成驱动(45+) ──┐
                              ├→ [卡点A] 落盘时写隐式标识(元数据)  ←  media_cache.download_and_cache
TTS/变声/数字人 ─┘                    （一处挂点覆盖全部生成链路）
                                     │  可选: 强制显式标识类在此同步烧录
                                     ▼
                            upload/cache/* + 七牛CDN
                                     │
用户/资产库/导出/CLI ◄──── [卡点B] 分发出口校验兜底（缺标则补写后返回）
                              /api/download、故事板导出、剪映导出、资产库…
```

**ProduceID 编号体系**：`<ai_tools.id>`（单文件产物）或 `<ai_tools.id>#<序号>`（多 clip/分段拼接产物）。ContentProducer 取平台统一编码（配置项，待申请）。这两个值在 `_handle_task_success` 处已知，可随 download_queue 传递到落盘环节。

**新模块**：`services/aigc_marking/`
- `aigc_service.py` —— 统一入口：构建标识 JSON、分发到对应 writer、写后校验、失败重试
- `metadata_writer.py` —— 图片/视频/音频元数据写入（见 3.2）
- `explicit_marker.py` —— 显式标识烧录（见 3.3）

### 3.2 隐式标识实现（零新依赖，全部无损操作）

XMP 包内容（按 GB 45438-2025 附录 E）：

```json
{"AIGC": {"Label": "1", "ContentProducer": "<平台编码>", "ProduceID": "<ai_tools.id>", "ReservedCodeContentProp": "<生成时间戳>", "ContentProp": "<任务类型>"}}
```

> 注：`Label`/字段枚举取值以正式发布的国标附录 E 与实践指南为准，编码申请下来后统一核对；`ProduceID` 用 `ai_tools.id` 保证可回溯。

| 格式 | 写入方式 | 无损性 | 实现要点 |
|------|---------|--------|---------|
| PNG | Pillow `PngInfo` iTXt 块写 XMP 包 | 无损 | 像素不变 |
| JPEG | APP1 段（namespace `http://ns.adobe.com/xap/1.0/`）字节级插入 | 无损 | **禁止重编码**（重存会损画质），直接在 APP0/APP1 后插入；保留原 EXIF APP1 |
| WebP | XMP chunk | 无损 | Pillow 支持 `image.info["xmp"]` |
| MP4/MOV | `ffmpeg -i in -c copy -movflags use_metadata_tags -metadata xmp="<包>" out` | 无损 remux | 秒级开销；输出临时文件后原子替换 |
| MP3 | `ffmpeg -i in -c copy -metadata aigc="<JSON>"` → ID3v2 TXXX | 无损 | 也可用 mutagen（不加依赖，先 ffmpeg） |
| WAV | `ffmpeg -i in -c copy -metadata aigc="<JSON>"`（LIST INFO） | 无损 | 同上 |

写入流程（aigc_service.mark_file）：
1. 判断文件类型（魔数，不信任扩展名）
2. 读回验证：图片用 Pillow 读回 XMP；MP4 用 `ffprobe` 读 tags —— 验证失败记 warning 日志，**不阻断业务**（标识失败不影响内容交付，重试由独立重试逻辑处理）
3. 幂等：文件已含 `AIGC` 标识则跳过（下载重试、重复落盘场景）

挂点：
- **主挂点**：`utils/media_cache.py download_and_cache` 成功回调后 —— 需要把 `ai_tool_id`/`task_type` 传入（当前签名只有 URL/path，需从 download_queue 行带过来，`task/download_queue_task.py` 调用处补参）
- **直接落盘路径**：数字人分段拼接产物（compose_task.py）、故事板导出合成（storyboard_export_service.py）、TTS 落盘（api/tts.py）、voice_replace 产物 —— 逐一在产出文件处调用 `aigc_service.mark_file`
- **上游 URL 直接透传未落盘的场景**：`result_url` 为上游供应商 URL 且未进缓存时，用户拿到的是外链、无标识 —— 需要排查所有此类出口，统一改为先落盘再发链接（download_queue 机制已存在，确认全覆盖）

### 3.3 显式标识分级策略（合规风险从高到低）

**L1 强制显式标识**（第 17 条明确列举"合成人声、人脸生成"，默认烧录，用户可申请关闭但须走第 9 条留痕流程）：
- 数字人视频（task 13/32/35）：视频起始画面添加文字提示"AI生成"（ffmpeg drawtext，白底黑字角标，位置画面角落，占比不超画面高度 1/10，起始画面展示时长以实践指南为准）
- 音色克隆/TTS 音频（task 9、api/tts.py）：音频起始处语音提示或"AI生成"节奏提示（火山 TTS 可直接合成提示语音，零成本）
- 真人参考图生视频（参考生视频类驱动）：同数字人处理
- 数字人拼接链（compose_task.py）：拼接后统一烧录，避免每段重复

**L2 显著标识功能（第 17 条第 2 款"提供显著标识功能 + 提示使用者"）**：
- 所有图片/视频生成入口提供"添加 AI 生成标识"开关，**默认开启**
- 开启时：图片用 Pillow 在角标位置合成"AI生成"标识（一次像素合成）；视频用 ffmpeg drawtext 烧起始画面
- 关闭时：仅保留隐式标识，并**写入 opt-out 日志**（见 3.5 表结构）
- 上游水印参数：各驱动 `watermark=False` 保持不动（避免双重水印），由本平台统一打标

**L3 文本/界面提示**（低成本，先行）：
- LLM 对话输出（聊天流）：统一渲染"以下内容由 AI 生成"提示条（前端模板统一加，勿逐卡片散改）
- 剧本写作/拆解输出头部：同上提示条
- 灵感广场（marketing_publications）：发布声明 + 列表/详情页"AI生成"角标；发布流程加"确认内容为 AI 生成并已声明"勾选

**用户协议**（第 8 条）：增加 AIGC 标识条款章节——说明本平台自动添加隐式标识、显式标识的方法与样式规范、用户申请不添加显式标识的责任与义务、禁止删标条款（第 10 条）。**此项是第 9 条关闭申请生效的前置条件。**

### 3.4 出口保标识（卡点B）

- `/api/download`（server.py:1104）：本地 FileResponse 模式返回前调 `aigc_service.ensure_marked(path)`（读回验证，缺则补写）；CDN 重签名模式文件本身已带元数据，无需处理，但**必须确认 CDN 上传前已完成标记**（trigger_cdn_upload 异步上传时机在 download_and_cache 之后，时序安全，需在代码里断言）
- 故事板整片导出（storyboard.py:6555 后台合成）：合成后、上传 CDN 前标记 + 显式标识烧录
- 剪映草稿导出 / 时间轴素材包 / 世界包导出：素材逐一标记（草稿导出若只导 JSON+素材引用，素材文件本身已带标）
- 资产库入库（asset_library.py:161）：入库复制文件时保留元数据（复制操作天然保留）；**校验入库文件已带标**
- Agent CLI `/generate-image`：出口走同一落盘链路，自动覆盖，验收时确认

### 3.5 数据库与配置改动

**迁移**（`python scripts/new_migration.py`，遵守 no_N_YYYYMMDD 规则）：
1. `media_file_mapping` 追加字段：`aigc_marked`(bool)、`aigc_marked_at`、`aigc_produce_id`(varchar)——标记状态可审计
2. 新表 `aigc_explicit_opt_out_log`（第 9 条留痕）：`id, user_id, ai_tool_id, produce_id, content_type, opt_out_at, ip, user_agent`——留存 ≥6 个月（按深度合成规定第 14 条建议 1 年以上更稳妥）
3. `ai_tools` 追加字段：`explicit_label`(int: 0未加/1强制/2用户开启/3用户关闭) —— 记录每条任务显式标识决策

（同步更新 model 目录对应文件末尾 SQL，挂当前唯一 head。）

**常量/配置**（config/constant.py + unified_config.py）：
- `AIGC_CONTENT_PRODUCER_CODE`（服务提供者编码，申请后填入；未申请完成前用平台名称占位——第 5 条允许"名称或编码"）
- `AIGC_LABEL_TEXT = "AI生成"`、显式标识位置/尺寸/起始时长参数
- `AIGC_EXPLICIT_DEFAULT_ON = True`（L2 默认开启）
- 各任务类型 → 显式标识级别（L1/L2）映射表

### 3.6 存量补标

办法 2025-09-01 已施行，存量生成内容（upload/cache、七牛桶、资产库）同样应携带标识：
- `scripts/backfill_aigc_metadata.py`：按 `media_file_mapping` 遍历 + join `ai_tools` 取 ProduceID，批量补写元数据（显式标识不回溯烧录——只补隐式，因为显式会破坏历史内容且用户已可能使用）
- 本地文件直接补；七牛已上传对象需重新上传（或仅在长期桶标记）
- 分批限速执行，避免磁盘/带宽冲击；`aigc_marked` 字段记录进度

### 3.7 去水印功能合规改造（task 49）

- **硬规则**：去水印工作流输出（remux/重编码后）必须重新写入 AIGC 隐式标识——如果输入是本平台生成内容，ProduceID 继承原值；输入是外部内容，作为"编辑"行为也应标注（深度合成规定第 2 条"编辑"场景）
- UI 层面：使用提示改为"仅限处理您拥有合法权利的内容"
- 上游关闭水印的驱动（watermark=False）与去水印功能不冲突，保留

### 3.8 行政流程（与开发并行）

1. 在标识服务平台（aigc.cac.gov.cn）完成服务提供者编码申请/信息登记
2. 算法备案材料更新（标识办法第 12 条：备案/安全评估须提供标识材料——备案在审/已备案的需补充标识技术说明）
3. 用户协议文本更新 + 法务审核
4. 上线前自查：对照 GB 45438-2025 与实践指南做样例验证（PNG/JPEG/MP4/MP3 各抽检）

---

## 四、实施计划

| 阶段 | 内容 | 涉及文件（主要） |
|------|------|----------------|
| **P0（立即）** | 隐式标识模块 + download_and_cache 挂点 + /api/download 兜底 + TTS/数字人拼接直接落盘点接入；L1 显式标识（数字人视频 drawtext + TTS 提示语音）；服务提供者编码申请启动 | services/aigc_marking/*（新建）、utils/media_cache.py、task/download_queue_task.py、api/download、task/compose_task.py、api/tts.py、services/volcengine_tts_service.py |
| **P1（P0 后一周内）** | L2 开关（前端生成选项 + 后端烧录）、LLM 输出提示条、灵感广场声明与角标、用户协议条款、opt-out 日志表 | web/js（marketing_agent.js、video_workflow 相关）、api/marketing_publications.py、迁移脚本 |
| **P2** | 存量补标脚本 + 执行、去水印功能改造、故事板/剪映/世界包导出全覆盖验证、上线自查报告 | scripts/backfill_aigc_metadata.py、video_watermark 驱动、storyboard 导出链 |

## 五、风险与注意事项

1. **性能**：MP4 remux（-c copy）秒级、不动视频流；只有 L1/L2 显式烧录才转码，数字人本就有 ffmpeg 链路，增量可控。落盘标记在 worker 内同步执行不占 API 事件循环（遵守 AGENTS.md 第 1 条，不得在异步接口中同步阻塞）。
2. **JPEG 不重编码**：任何"重新打开再 save"都会损画质，必须字节级插入 APP1。
3. **字体**：ffmpeg drawtext 中文"AI生成"需要字体文件，系统已有 `files/fonts`（storyboard_subtitle 在用），路径处理沿用 `_get_ffmpeg_path()` 的经验（**不得硬编码路径**，Windows/Linux/macOS 三平台兼容，参考 dev2 事故 86a652f9）。
4. **幂等与失败隔离**：标记失败不得影响内容交付（警告日志 + 重试），文件二次处理（如导出再压缩）后必须重新校验。
5. **CDN 时序**：trigger_cdn_upload 必须在标记完成之后（当前异步链路时序正确，代码需显式保证并加断言/日志）。
6. **常量入库**：所有文案、编码、默认开关进 config/constant.py / unified_config.py（AGENTS.md 第 5 条）。
7. **文档同步**：实施后同步 docs（AGENTS.md 第 2 条），本方案实施后升级为设计文档 + 实施记录。

## 六、参考

- 《互联网信息服务深度合成管理规定》第 16、17 条
- 《人工智能生成合成内容标识办法》全文：https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm
- GB 45438-2025《网络安全技术 人工智能生成合成内容标识方法》（2025-09-01 实施）
- 网安标委 6 项配套实践指南（标识服务平台：https://aigc.cac.gov.cn）
