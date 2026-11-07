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
| **TTS 试听缓存** | `api/tts.py preview_voice._write_preview` | 试听缓存首次生成 |

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
| **L1 强制默认烧录** | 数字人视频（人脸生成）、TTS 合成人声 | 默认烧录；用户可申请关闭（第 9 条留痕） | 视频起始画面 ffmpeg drawtext"AI生成"（全片重编码 libx264 fast crf20，音频 copy）；音频开头拼接节奏提示资产 `files/audio/aigc_notice.mp3`（第 4 条允许"语音或节奏提示"，资产由 ffmpeg 合成生成一次复用） |
| **L2 提供显著标识功能** | 普通图片/视频 | 结果卡按钮按需烧录 | 聊天流弹窗"添加AI标识"按钮 → POST /api/aigc/explicit-label；图片右下角 Pillow 角标（NotoSansSC，黑底半透明条），视频同 drawtext |

### 关键机制

- **关闭申请留痕**（第 9 条硬要求）：表 `aigc_explicit_opt_out_log`（迁移 no_163，`model/aigc_explicit_opt_out.py`，append-only 禁删）；任务级（`ai_tool_id`）与用户级（`scope: "user"`，**全局生效**——一次申请对其后续所有 TTS 与数字人合成均跳过明水印烧录）。API `POST /api/aigc/explicit-optout`（前端确认弹窗文案即"通过协议明确义务责任"的落地）。
- **幂等判定**：显式烧录后统一 `mark_file(extra_fields={'ExplicitLabel':'1'})` 重写隐式标识（烧录重编码丢原元数据，隐式是强制义务必须补回）；`has_explicit_label` 读该字段防角标叠加。
- **L1 挂点**：`compose_task.py`（拼接后、CDN 前，查 `has_opt_out(compose_id)` 跳过）+ `volcengine_tts_service.py _write_file`（查 `has_opt_out_user` 跳过）；烧录失败降级交付无显式版本并告警（隐式已先行写入）。
- **CDN 重传**：explicit-label API 烧录后触发 `trigger_cdn_upload` 覆盖旧对象。
- **协议前置**（第 8 条）：正式上线前用户协议须补 AIGC 标识条款章节；前端确认弹窗文案已含义务声明作为过渡。

### 已知边界

1. L2 入口目前仅聊天流弹窗（marketing_agent）；视频工作流/画布节点菜单下轮接入（API 已就绪，传 ai_tool_id 即可）
2. 数字人/TTS 关闭申请的前端独立入口下轮接入（API+留痕表已就绪，暂可经客服/后台渠道申请）
3. GIF/WebP 不支持显式烧录；音频提示音为节奏提示（合成语音提示需 TTS 资产，后续可换语音版）
4. `/api/download` 外链代理与 max_try 兜底 remote_url 不落盘场景同隐式标识边界

## 九、自测脚本

- `temp/test_aigc_marking.py`：隐式标识 30 项（不入库）
- `temp/test_aigc_explicit.py`：显式烧录 20 项（图片角标/视频 drawtext/音频提示/幂等/隐式重写回补/时长校验）

## 十、已知边界与后续阶段（隐式部分原述）

1. **下载 max_try 兜底 remote_url**（`download_queue_task.py` 达上限用上游 URL 兜底 COMPLETED）与 `/api/download` 外链代理模式：文件不落盘，无法写标识——属已知边界，需后续评估改为"先落盘再交付"
2. **存量补标**：本轮不做（用户决策）；方案见 labeling_plan 3.6 节
3. **显式标识**（视频起始画面 drawtext / 音频提示 / 图片角标，L1/L2 分级）：后续阶段，见 labeling_plan 3.3 节
4. **正式编码替换**：`AIGC_CONTENT_PRODUCER` 占位值待申请后更新
5. storyboard/剪映/世界包导出链路暂未接（导出源文件已带标，仅二次压缩场景需复查）
