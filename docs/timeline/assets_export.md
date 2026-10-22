# 时间轴素材包导出功能文档

## 功能概述

视频工作流（video_workflow.html）时间轴支持一键导出素材包 zip：把时间轴上的视频、音频
原始素材下载后打包上传，返回下载链接。交付方式对齐故事板页的「导出素材包」
（`POST /api/storyboard/{id}/export-all-scenes`），区别在于数据源是工作流时间轴片段，
而非故事板分镜。

入口位于时间轴面板右上角，「导出剪影草稿」按钮旁边的「导出素材包」按钮
（`#timelineExportAssetsBtn`）。

## 与剪影草稿导出的区别

| | 导出剪影草稿 | 导出素材包 |
|---|---|---|
| 产物 | 剪映（JianyingPro）可导入的草稿目录 zip | 原始素材文件 zip（`视频/`、`音频/`、`manifest.json`） |
| 是否剪辑 | 是（按柱子系统排列轨道、支持占位符） | 否（素材原样交付，可在任意剪辑软件使用） |
| 需要用户输入 | 剪影草稿路径前缀 | 无 |
| 接口 | `POST /api/export_timeline_draft` | `POST /api/export_timeline_assets` |

## 前端

- `web/video_workflow.html`：`#timelineExportAssetsBtn` 按钮（i18n key
  `timeline_export_assets`）。
- `web/js/events.js`：按钮点击绑定，调用 `exportTimelineAssets()`。
- `web/js/timeline.js`：
  - `isValidMediaUrl` / `resolveClipExportUrl` / `collectTimelineExportClips`
    为草稿导出与素材包导出的共用逻辑（blob: 失效地址回退所属节点当前地址）。
  - `exportTimelineAssets()` 收集时间轴片段 POST 到后端，成功后用
    `window.downloadWithAuth(download_url, filename)` 触发下载（带 Authorization 走
    `/api/download` 代理，兼容本地 `/upload` 相对路径与 CDN 签名地址）。
- `web/i18n/locales/{zh-CN,en}/video_workflow.json`：`timeline_assets_*` 系列 key。

### 请求体

```json
{
  "video_clips": [
    {
      "url": "视频URL",
      "name": "视频名称",
      "duration": 10.5,
      "startTime": 0,
      "endTime": 10.5,
      "pillarId": "scriptId_shotNumber"
    }
  ],
  "audio_clips": [ { "...": "同上" } ],
  "workflow_name": "工作流名称",
  "request_origin": "https://..."
}
```

片段结构与草稿导出完全一致（`collectTimelineExportClips` 生成）。

## 后端（server.py）

### 共享下载函数 `_download_timeline_media_clips`

草稿导出与素材包导出共用的素材下载逻辑：

- 本站 `/upload/` 文件直接复用本地路径（`_get_local_upload_file`），其余 URL 经
  `CDNUtil.refresh_cdn_signed_url` 刷新签名后 httpx 异步流式下载；
- 相同素材（同 URL / 同本地文件）通过 `asset_cache` 去重，只下载一次；
- 扩展名按 Content-Type / URL 后缀推断（视频 mp4/mov/avi，音频 mp3/wav/aac）；
- 无协议头地址（blob:、已被到期清理的 `/upload/`）抛 `_TimelineMediaExportError`
  （400），由接口转成用户可行动的报错。

### `POST /api/export_timeline_assets`

1. 校验时间轴非空；
2. `_download_timeline_media_clips` 下载全部视频/音频到
   `files/tmp/jianying_export/<日期>/<包名>/downloads/`；
3. 在线程池中打 zip（`asyncio.to_thread`，不阻塞事件循环）：
   - `视频/01_<片段名>.<ext>`、`音频/01_<片段名>.<ext>`（按 order 排序编号，
     片段名经 `_sanitize_timeline_asset_name` 清洗为跨平台安全文件名，冲突加序号）；
   - `manifest.json`：工作流名、导出时间、每个素材的 file/name/url/duration/
     startTime/endTime/order/pillarId；
4. 分发：
   - `is_local=true`：zip 复制到 `upload/draft/<日期>/`（与草稿 zip 同区），
     返回**相对路径** `/upload/draft/<日期>/<包名>.zip`（避免 host=0.0.0.0 时
     浏览器拿到不可访问的绝对地址）；
   - 云环境：上传七牛后返回 CDN 签名地址，并删除本地 zip；
5. `finally` 清理临时目录（`shutil.rmtree(..., True)` 放线程池）。

### 响应

```json
{
  "success": true,
  "download_url": "/upload/draft/2026-10-20/xxx_素材_20261020_120000.zip",
  "filename": "xxx_素材_20261020_120000.zip",
  "video_count": 3,
  "audio_count": 2
}
```

失败时返回 `{"success": false, "error": "..."}`（400：时间轴为空 / 素材地址失效；
500：下载或打包异常）。

## 注意事项

- 接口为纯异步（httpx 异步下载、zip 打包与文件清理走 `asyncio.to_thread`），
  不阻塞其他请求；
- 素材包与草稿导出共用 `upload/draft/` 静态目录，不新增上传路径常量；
- 片段名清洗规则：过滤 `<>:"/\|?*` 与控制字符、去尾部 `. `、截断 80 字符，
  兼容 Windows/Linux/macOS 解压。
