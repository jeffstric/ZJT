# AIGC 隐式标识（深度合成合规）

> 状态：已实施（增量覆盖，2026-11-08，develop_f1163）
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

## 七、已知边界与后续阶段

1. **下载 max_try 兜底 remote_url**（`download_queue_task.py` 达上限用上游 URL 兜底 COMPLETED）与 `/api/download` 外链代理模式：文件不落盘，无法写标识——属已知边界，需后续评估改为"先落盘再交付"
2. **存量补标**：本轮不做（用户决策）；方案见 labeling_plan 3.6 节
3. **显式标识**（视频起始画面 drawtext / 音频提示 / 图片角标，L1/L2 分级）：后续阶段，见 labeling_plan 3.3 节
4. **正式编码替换**：`AIGC_CONTENT_PRODUCER` 占位值待申请后更新
5. storyboard/剪映/世界包导出链路暂未接（导出源文件已带标，仅二次压缩场景需复查）
