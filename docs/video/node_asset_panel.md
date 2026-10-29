# 节点管理面板

## 概述

节点管理面板提供画布上全部节点的列表视图（交互参考 LibLibTV 的节点列表）：缩略图 + 标题 + 类型徽标，支持搜索、类型筛选、一键定位与更多操作（下载/删除），底部实时统计节点总数。入口为画布左下角小地图上方的「节点管理」按钮（与「资产库」无关，仅管理画布节点）。

数据只读自 `state.nodes`（页面内存）；下载经 `/api/download` 服务端重签名通道（复用 `downloadWithAuth`，登录 token 走 Authorization 头不进 URL）；节点缩略图复用节点自身的资源 URL。

## 入口

画布左下角，小地图（minimap）正上方的「节点管理」横条按钮（`#nodeAssetPanelBtn`，与小地图同宽对齐）。

- 点击开合面板（toggle），`Esc` 也可关闭。
- 面板为画布左侧悬浮抽屉（`.node-asset-panel`），打开期间不阻塞画布操作。

## 功能

| 功能 | 说明 |
|------|------|
| 节点列表 | 画布全部节点，按标题字典序排序（`localeCompare('zh-CN')`，同标题按 id 稳定排序） |
| 缩略图 | 44×44 圆角；图片类节点显示图片，视频类节点显示首帧，无图节点显示类型名前两字占位 |
| 搜索 | 按标题或类型名实时过滤（大小写不敏感） |
| 类型筛选 | 下拉只列出画布上实际存在的类型；当前选中类型在画布上消失时自动重置为「全部类型」 |
| 定位 | 点击行（或行内 ◎ 按钮）调用 `focusOnNode` 居中该节点并闪烁高亮，行保留 active 状态 |
| 更多菜单 | 行内 "..." 按钮弹出 下载/删除 下拉菜单；单例菜单挂 `document.body`（避免被面板 overflow 裁剪），右对齐按钮、视口边缘自动翻到上方；点击菜单外 / Esc / 列表滚动 / 面板关闭时收起 |
| 下载 | 有媒体文件（图片/视频，音频节点取 `data.url`）走 `downloadWithAuth`（`/api/download` 重签名，跨域 302 不丢 `download` 属性），文件名「节点标题.扩展名」；剧本节点导出 `标题.txt`；无文件节点 toast 提示 |
| 删除 | 菜单内删除 → 确认弹窗（`showConfirmModal`）→ `removeNode`，列表与统计随之刷新 |
| 统计 | 底部「共 N 节点」；过滤时显示「M / N」（悬浮 title 保留总数） |
| 刷新 | 头部刷新按钮手动重建列表（节点标题在画布上被改名后可同步） |

## 缩略图解析规则

`NodeAssetPanel.getNodeThumb(node)` 返回 `{ kind, url }`：

| 节点类型 | 取值字段 | kind |
|----------|----------|------|
| image / character / location / props / panorama | `getNodeImageUrl`（url / preview / reference_image） | image |
| shot_frame | `data.imageUrl` | image |
| digital_human | `data.imageUrl` / `data.imagePreview` | image |
| video | `data.url` | video |
| image_to_video | `data.videoUrls[0]`（无成片时回退 startUrl / endUrl，按图片处理） | video / image |
| video_watermark / extract_frame | `data.videoUrl` | video |
| text / script / audio / text_to_speech / dialogue_group / shot_group / director_stage / camera_control / prompt_reverse / script_extract | 无图占位 | none |

- 图片地址统一经 `normalizeImageUrl` + `proxyImageUrl`（跨域图走服务端代理，与画布行为一致）。
- 视频首帧：懒加载 `<video preload="metadata">`，metadata 就绪后 seek 到 0.1s 显示封面（与节点内 `setupVideoThumbnail` 同策略，不循环播放）。
- 懒加载：`IntersectionObserver`（root 为列表容器，rootMargin 120px），滚动进入视口才创建 `<img>`/`<video>`，避免大画布一次性解码全部媒体；图片加载失败时移除元素回退占位。

## 实现与文件

| 文件 | 职责 |
|------|------|
| `web/js/node_asset_panel.js` | 面板骨架（首次打开动态创建，降低主 HTML 体积）、列表渲染、过滤排序、定位/删除交互、画布联动 |
| `web/css/node_asset_panel.css` | 入口按钮与面板样式；配色全部走 `video_workflow.css` 的主题变量，浅色/暗色（`html.theme-dark`）自动适配 |
| `web/video_workflow.html` | 左下角入口按钮 + CSS/JS 引用 |
| `web/i18n/locales/*/video_workflow.json` | `node_asset_*` 词条 |

关键设计：

- **增删自动刷新**：`MutationObserver` 监听 `#canvas` 子节点增删（rAF 合帧），覆盖所有节点创建路径与工作流重新加载（全量重建节点）场景，列表随之复原，面板自身不持久化任何状态。
- **XSS 红线**：节点标题、类型名、URL 等所有动态内容渲染前经 `escapeHtml` 转义。
- **观察降级**：环境不支持 `MutationObserver` / `IntersectionObserver` 时自动降级（手动刷新按钮 / 直接填充缩略图）。

## i18n 词条

`node_asset_panel_btn`（节点管理）、`node_asset_panel_title`（节点管理）、`node_asset_search_placeholder`、`node_asset_filter_all`、`node_asset_total`（共 {n} 节点）、`node_asset_total_filtered`、`node_asset_empty`、`node_asset_no_match`、`node_asset_locate`、`node_asset_delete_confirm`、`node_asset_refresh`、`node_asset_close`、`node_asset_more`、`node_asset_menu_download`、`node_asset_menu_delete`、`node_asset_download_no_file`、`node_asset_download_failed`。

节点类型展示名复用既有词条（image / video / image_to_video / shot_frame_group 等），新类型未收录时回退显示类型标识。
