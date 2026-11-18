# AIGC 内容标识（深度合成合规）：隐式 + 显式

> 状态：隐式标识已实施（2026-11-08，develop_f1163）；**显式标识（明水印）已实施**（同分支第二批）
> 合规依据与整体方案：[docs/compliance/aigc_labeling_plan.md](../compliance/aigc_labeling_plan.md)

## 一、法规义务摘要

- 《互联网信息服务深度合成管理规定》第 16 条：生成/编辑内容须添加**隐式标识**（文件元数据）
- 《人工智能生成合成内容标识办法》（2025-09-01 施行）第 5 条：元数据须含**内容属性、服务提供者名称/编码、内容编号**
- GB 45438-2025 附录 E：XMP 元数据格式（TC260 命名空间 `http://www.tc260.org.cn/ns/AIGC/1.0/`）
- 标识办法第 4 条：下载/复制/导出时确保文件含有标识（出口兜底的依据）

## 二、标识内容（写入文件元数据的 JSON）

```json
{"Label":"1","ContentProducer":"zjt","ProduceID":"<ai_tools.id>","ReservedCode1":"<生成时间>","ContentProp":"image|video|audio"}
```

- `ContentProducer` 当前为占位值 `zjt`（config/constant.py `AIGC_CONTENT_PRODUCER`），**标识服务平台申请到正式编码后必须替换**
- `ProduceID`：主链路为 ai_tools.id；数字人拼接链为 `compose_<compose_id>`；TTS 为音频文件名

## 三、承载格式与写入方式（全部无损）

| 格式 | 方式 | 说明 |
|------|------|------|
| PNG | Pillow iTXt `XML:com.adobe.xmp` | 像素不变，保留 ICC profile |
| JPEG | APP1 段字节级插入/替换 | 不重编码，保留原 EXIF |
| MP4/MOV | ffmpeg `-c copy -movflags use_metadata_tags -metadata xmp=` | 无损 remux，秒级 |
| MP3 | ffmpeg `-metadata AIGC=<json>` | ID3 TXXX |
| WAV | ffmpeg `-metadata comment=<json>` | LIST INFO ICMT（wav muxer 不支持任意自定义 key） |
| GIF/WebP | 暂不支持 | `has_aigc_label` 返回 None，告警跳过，不阻断 |

## 四、挂点清单（写入时序保证先于 CDN 上传）

| 挂点 | 文件 | 覆盖范围 |
|------|------|---------|
| **落盘主挂点** | `utils/media_cache.py download_and_cache` | 全部生成驱动产物（45+ 驱动经 download_queue 汇聚到此处下载落盘） |
| **裁剪后兜底** | `task/download_queue_task.py _process_one` | 宫格人脸网格裁剪重写文件后重新补标（trim 会丢 XMP） |
| **下载出口兜底** | `server.py /api/download` 本地 FileResponse 分支 | 漏标文件下载时补标（幂等，已标识毫秒级返回） |
| **数字人拼接** | `task/compose_task.py` 拼接完成后、`_attach_cdn_mapping` 前 | 分段拼接成片（同步主循环上下文） |
| **TTS 合成** | `services/volcengine_tts_service.py _write_file` | 正式合成音频（to_thread 同步上下文） |
| **TTS 克隆/配音** | `task/audio_task.py _submit_new_task` 落盘后、CDN 注册前 | /audio-generate 页面与 storyboard 配音（IndexTTS 克隆+情感控制，async worker 内 asyncio.to_thread 同步执行） |
| **TTS 试听缓存** | `api/tts.py preview_voice._write_preview` | 试听缓存首次生成（仅隐式标识，按设计不烧显式） |

**时序链**：download_and_cache（标记）→ 宫格 trim（重写→重新兜底）→ transition_with_cdn_sync（建 mapping + 触发 CDN 上传）——标记先于 CDN，保证云端对象与本地文件一致带标。

## 五、可靠性设计

- **失败不阻断交付**：所有写入经 `mark_file_for_task`/`ensure_marked` 全容错（仅告警日志）；异步挂点用 `asyncio.wait_for(AIGC_MARK_TIMEOUT_SECONDS=90s)` 防 ffmpeg 卡死
- **幂等**：写入前 `has_aigc_label` 读回校验，已带标识直接返回（重试/重复落盘/重复下载不重写）
- **写后校验**：写入成功后再读回一次，校验不过返回 False 并告警
- **tmp 原子替换**：所有写入写 `.aigc_<pid>.tmp` 后 `os.replace`（含 pid 防并发撞名）
- **判定子串**：统一用 `ProduceID`（JSON 必含字段）判定，不用 `"AIGC"`——XMP 标签 `<TC260:AIGC>` 无引号、JSON 键中也不存在带引号的 AIGC
- **字符集**：模块内 subprocess 显式 `encoding='utf-8'`（Windows 默认 GBK 崩坏，AGENTS.md 第 6 条）；ffprobe 用 xml 输出（json 输出遇值内引号解析失败）

## 六、验证方法

自测脚本 `temp/test_aigc_marking.py`（不入库，本机执行）：

```bash
python -I temp/test_aigc_marking.py
# 覆盖：格式识别 8 种 / 写入+读回 6 格式 / EXIF 保留 / 幂等 / 出口兜底 / 不支持格式 / mp4 解码完整性
# 本机无 config_dev.yml 时脚本自动指向 bin/ffmpeg/，无需配置
```

端到端冒烟（本地 HTTP 服务 + `download_and_cache` 全链路）已于实施时验证通过。

## 八、显式标识（明水印）——已实施

实现 `utils/aigc_explicit_marker.py`，分级策略（法规依据：《深度合成规定》第 17 条、《标识办法》第 4/9 条）：

| 级别 | 内容类型 | 策略 | 实现 |
|------|---------|------|------|
| **L1 强制默认烧录** | **全部生成图片与生成视频**（2026-11-11 产品决策：系统无法检测产出是否含人脸，保守按"人脸生成/可能混淆"对待）+ 数字人视频（人脸生成）、TTS 合成人声 | 默认烧录；用户可申请关闭（第 9 条留痕，用户级全局） | 图片右下角 Pillow 角标（NotoSansSC，overlay alpha_composite 真混合的黑底半透明条，JPEG 混合后落 RGB 与 PNG 观感一致，几十~几百 ms/张）；视频起始画面右下角 ffmpeg drawtext 角标（位置/黑底半透明条样式与图片一致，全片重编码 libx264，preset/CRF 常量可调，音频 copy，1080p 10s 片约 10~40s/条）；音频开头拼接节奏提示资产 `files/audio/aigc_notice_v2.mp3`（880Hz 三短音 0.8s，峰值约 -9 dBFS；v1 峰值 -24dB 不可闻，v2 改文件名强制各环境重新生成） |
| **L2 提供显著标识功能** | （保留）存量内容、opt-out 恢复后的单件需求 | 结果卡按钮按需烧录 | 聊天流弹窗"添加AI标识"按钮 → POST /api/aigc/explicit-label |

总开关常量（config/constant.py）：`AIGC_EXPLICIT_IMAGE_BURN_ENABLED` / `AIGC_EXPLICIT_VIDEO_BURN_ENABLED`（视频吞吐吃紧可独立关闭）、`AIGC_EXPLICIT_X264_PRESET` / `AIGC_EXPLICIT_VIDEO_CRF`（画质/CPU 调优）。

### 关键机制

- **关闭申请留痕**（第 9 条硬要求）：表 `aigc_explicit_opt_out_log`（迁移 no_163，`model/aigc_explicit_opt_out.py`，append-only 禁删；`action` 列为 opt_out/resume 状态机，最新记录决定当前状态）。**用户自助入口：index.html「设置 → 内容标识」tab**——勾选框控制全部显式标识（图片/视频/数字人/语音）全局开关（`scope: "user"` 记 `request_source=user_settings`，一次申请对其后续所有生成均跳过烧录；取消勾选走 resume 恢复）。任务级 API：`POST /api/aigc/explicit-optout`（`ai_tool_id`，来源 `chat_result_card`），状态查询：`GET /api/aigc/explicit-optout/status`（只读用户设置来源）。两个写接口都要登录，并且 `ai_tool_id` 必须属于当前用户：任务不存在或不属于本人都返回 404「任务不存在」，不烧录、不写留痕。`scope=user` 可以不带任务 id；若同时带了别人的 `ai_tool_id`，整次请求 404，不会记成全局关闭。`has_opt_out_user` 只看 `user_settings` 的最新一条。任务卡和开放 API（`api`）的 opt_out 只影响那一条任务，不会关掉该用户之后的图片、视频、数字人和语音水印。查询异常仍按未关闭处理（宁可多标识）。任务级成功文案只说「该任务」，用户级才说后续图片/视频/数字人/语音。
- **幂等判定**：显式烧录后统一 `mark_file(extra_fields={'ExplicitLabel':'1'})` 重写隐式标识（烧录重编码丢原元数据，隐式是强制义务必须补回）；`has_explicit_label` 读该字段防角标叠加。
- **L1 生成链挂点**（统一入口 `utils/aigc_explicit_marker.maybe_burn_generated_media`：开关判定→本地文件解析→查 user→opt-out 跳过→烧录）：
  1. `task/download_queue_task.py::_process_one`——主链路（45+ 驱动经 download_queue 汇聚），**宫格裁剪之后、transition_with_cdn_sync 之前**；
  2. `task/visual_task.py`——入队 DB 异常时的同步下载兜底分支（trim 后、状态更新前）；
  3. `task/sync_task_executor.py`——同步执行器 worker 子进程（trim_sync 后、return 前）；
  4. 数字人拼接 `compose_task.py`（拼接后、CDN 前）与 TTS `volcengine_tts_service.py _write_file` 沿用原挂点（幂等，与上面不叠加）。数字人成片是否跳过明水印走 `compose_explicit_label_opted_out`：用户级 `has_opt_out_user`，或 `segment_ai_tool_ids` 里任一段 `ai_tools.id` 已 `has_opt_out`。不用 `compose_jobs.id` 去对 `ai_tool_id`（两套自增序号会撞号，整段拼接会漏标）。
  烧录失败降级交付无显式版本并告警（隐式已先行写入，不阻断交付）。
- **CDN 时序保证**：烧录在 `transition_with_cdn_sync`（建 media_file_mapping）之前完成——上传线程（`trigger_cdn_upload` 独立线程/mapping 后台处理）触发后才读本地文件，故 CDN 对象必为烧录版。download_queue 与 visual_task 同步下载兜底走 `await_explicit_burn`：超时（`AIGC_EXPLICIT_BURN_TIMEOUT_SECONDS`）先 `ExplicitBurnSession.cancel()`，再等到烧录线程退出（最多 `AIGC_EXPLICIT_BURN_CANCEL_JOIN_SECONDS`）才上传。取消与 `os.replace` 共用一把锁，取消返回后要么替换已经完成，要么之后的替换看到取消标志并放弃，避免云端已是无标文件、本地随后被换成有标文件。同步执行器仍直接调用 `maybe_burn_generated_media`（`session=None`，与原来的 `os.replace` 相同）。`os.replace` 同路径替换，对象 key/签名 URL 不受影响；新内容首次上传前已带标，无边缘缓存旧对象问题。**边界**：L2 手动烧录存量内容时覆盖 CDN 对象，边缘节点可能在 TTL 内仍返回旧无水印版（未接七牛对象刷新 API，后续可选）。
- **用户引导五触点**（2026-11-11）：① **弹窗公告**——公告系统新增 `popup` 字段（迁移 no_165，`announcement_popup.js` 组件接入 index/marketing_agent/video_workflow 三页，进页强弹窗、已读服务端记录不再弹），运营在 /admin 发布勾选"弹窗通知"的公告即可主动触达全部活跃用户；首个全局弹窗公告（AIGC 标识规则变更通知，链接 `/index.html?aigc_tab=1` 直达"设置→内容标识"）已由迁移 no_166 以数据迁移植入（`popup=1`+`published`，幂等按标题判重）；② 条款重新同意（迁移 no_164）；③ marketing_agent 首次出现生成结果的一次性引导条（localStorage `marketing_aigc_notice_dismissed`，`augmentGeneratedImageCards` MutationObserver 钩子触发）；④ `index.html?aigc_tab=1` 直达"设置→内容标识"（index_app.js mounted 解析 + sessionStorage `pending_aigc_settings` 暂存，登录态就绪后打开）。
- **协议前置**（第 8 条）：默认用户条款《AI工具服务使用条款》/《AI Tool Service Terms》（files/ 目录）已于 2026-11-11 补充"AI生成内容标识"章节（隐式/显式标识说明、关闭申请与 ≥6 个月留痕告知、禁止删标），并修订原 6.1"不含水印版本"表述；线上无自定义条款覆盖，随版本发布即生效。**待法务审核定稿**；前端确认弹窗文案作为过渡保留。
- **条款重新同意**（迁移 no_164，2026-11-11）：`UPDATE users SET terms_agreed=0`，全体用户下次登录必须重新勾选新版条款——登录时未勾选则返回"请阅读并同意AI工具服务使用条款"（auth_service.py login），前端收到该错误自动弹出条款弹窗（index_app.js loginShowTerms），勾选后重新提交登录并回写 terms_agreed=1。注意：已登录会话（token 未过期）不受影响，下次登录才触发。**须与新条款文件同版本发布**（避免用户重新同意的还是旧版条款）。
- **L2 按钮跟踪时序**（修复 2026-11-10）：`web/js/aigc_label.js` 跟踪弹窗当前 `aiToolId` 走两条路径：**主路径=点击捕获**——marketing_agent.js 打开弹窗的委托直调闭包函数（不经 window），包装 window 函数收不到通知（e2e 实测按钮恒报"缺少任务信息"）；捕获阶段从被点媒体卡（`[data-modal-src]`/`img[data-full-src]`）外层 `[data-tool-id]` 记录，弹窗打开后采纳。辅路径=晚绑定访问器包装 `window.setModalImageInfo/resetModalImageInfo`（其赋值在 Vue `setup()` 挂载时才执行，**不可回退为加载时浅包装**，会被后到赋值覆盖）。

### 已知边界

1. L2 入口目前仅聊天流弹窗（marketing_agent）；视频工作流/画布节点菜单下轮接入（API 已就绪，传 ai_tool_id 即可）
2. GIF/WebP 不支持显式烧录；音频提示音为节奏提示（合成语音提示需 TTS 资产，后续可换语音版）
3. `/api/download` 外链代理与 max_try 兜底 remote_url 不落盘场景同隐式标识边界
4. **绕过 download_queue 的资产类图片未挂显式烧录**：宫格批量图（`grid_image_task.py` 裸 requests 直存+PIL 拆分）、多角度图（`location_multi_angle_task.py`）、storyboard 宫格拆分 driver 重写文件——这些是世界资产而非用户直接下载的生成结果，隐式标识部分亦未覆盖，后续阶段统一补
5. L2 手动烧录存量内容后 CDN 边缘缓存可能在 TTL 内返回旧无水印对象（见上方 CDN 时序说明）

## 九、自测脚本

- `temp/test_aigc_marking.py`：隐式标识 30 项（不入库）
- `temp/test_aigc_explicit.py`：显式烧录 20 项（图片角标/视频 drawtext/音频提示/幂等/隐式重写回补/时长校验）

## 十、已知边界与后续阶段（隐式部分原述）

1. **下载 max_try 兜底 remote_url**（`download_queue_task.py` 达上限用上游 URL 兜底 COMPLETED）与 `/api/download` 外链代理模式：文件不落盘，无法写标识——属已知边界，需后续评估改为"先落盘再交付"
2. **存量补标**：本轮不做（用户决策）；方案见 labeling_plan 3.6 节
3. ~~**显式标识**（视频起始画面 drawtext / 音频提示 / 图片角标，L1/L2 分级）：后续阶段~~ → **已实施**（2026-11-08 数字人/TTS；2026-11-11 图片/视频全量纳入 L1，见第八节）
4. **正式编码替换**：`AIGC_CONTENT_PRODUCER` 占位值待申请后更新
5. storyboard/剪映/世界包导出链路暂未接（导出源文件已带标，仅二次压缩场景需复查）
