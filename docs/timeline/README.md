# 时间轴与导出文档

本目录包含与时间轴系统、导出功能相关的文档。

## 文档列表

| 文档 | 说明 |
|------|------|
| [timeline_pillar_system.md](./timeline_pillar_system.md) | 时间轴柱子系统（核心架构文档） |
| [jianying_export.md](./jianying_export.md) | 剪影草稿导出功能 |
| [assets_export.md](./assets_export.md) | 时间轴素材包导出功能 |

## 文档关系

`jianying_export.md` 依赖 `timeline_pillar_system.md` 中定义的柱子系统概念。
`assets_export.md`（素材包导出）与 `jianying_export.md`（草稿导出）共用
`server.py` 的素材下载函数 `_download_timeline_media_clips` 与前端片段收集逻辑
`collectTimelineExportClips`。
