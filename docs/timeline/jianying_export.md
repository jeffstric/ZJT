# 剪影草稿导出功能文档

## 功能概述

视频工作流支持将时间轴导出为剪影（JianyingPro）草稿文件，方便用户在剪映中进一步编辑。

## 主要特性

### 1. 支持柱子系统（Pillar System）

> 柱子系统的详细说明请参考 [时间轴柱子系统文档](./timeline_pillar_system.md)

导出时的柱子处理特性：
- **不连续视频处理**：即使某些镜头没有视频，也能正确导出所有镜头
- **占位符机制**：对于没有视频的柱子，自动创建占位符片段（不可见、静音），确保时间轴连续

### 2. 多轨道支持

- **视频轨道**：主轨道，包含所有视频片段
- **音频轨道**：独立的音频轨道，包含所有音频片段
- **轨道同步**：视频和音频在各自轨道上按柱子顺序排列

### 3. 兼容性

- **新版本**：支持柱子系统，可处理不连续的视频和音频
- **旧版本**：兼容旧的时间轴格式（经典模式），按顺序连续排列视频

## 数据结构

### 前端发送的数据格式

```javascript
{
  draft_path: "C:\\Users\\...\\JianyingPro\\User Data\\Projects\\com.lveditor.draft",
  video_clips: [
    {
      url: "视频URL",
      name: "视频名称",
      duration: 10.5,
      startTime: 0,
      endTime: 10.5,
      pillarId: "scriptId_shotNumber"  // 所属柱子ID
    }
  ],
  audio_clips: [
    {
      url: "音频URL",
      name: "音频名称",
      duration: 8.0,
      startTime: 0,
      endTime: 8.0,
      pillarId: "scriptId_shotNumber"  // 所属柱子ID
    }
  ],
  pillars: [
    {
      id: "scriptId_shotNumber",
      scriptId: 123,
      shotNumber: 1,
      defaultDuration: 15,
      videoClipIds: ["clip_id_1"],
      audioClipIds: ["clip_id_2"]
    }
  ],
  workflow_name: "工作流名称",
  ratio: "9:16"  // 画布比例：9:16/16:9/1:1/3:4/4:3，决定草稿画布尺寸（竖屏/横屏）
}
```

### 后端处理逻辑

#### 柱子系统模式（有pillars数据）

1. **按柱子顺序处理**：根据 `scriptId` 和 `shotNumber` 排序
2. **处理每个柱子**：
   - 收集该柱子内的所有视频片段（通过 `pillarId` 匹配）
   - **如果柱子没有视频**：创建占位符片段（使用任意已下载的视频素材，设置为不可见、静音、时长为默认时长）
   - 收集该柱子内的所有音频片段（通过 `pillarId` 匹配）
   - 计算柱子实际时长 = max(默认时长, 视频总时长, 音频总时长)
3. **时间轴累加**：每个柱子结束后，时间轴向前推进该柱子的实际时长

#### 经典模式（无pillars数据）

1. **视频轨道**：按 `video_clips` 数组顺序连续排列
2. **音频轨道**：按 `audio_clips` 数组顺序连续排列
3. **兼容旧版本**：支持旧的 `timeline_clips` 字段

## 使用流程

### 1. 前端导出

在视频工作流页面，点击"导出到剪影"按钮：

1. 弹出导出对话框，输入剪影草稿路径前缀（如：`C:\Users\Administrator\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft`）
   - 系统会从 Cookie 中读取上次保存的路径（有效期 90 天），自动填充到输入框
   - 对话框中包含获取剪影草稿路径的图文说明
2. 点击"开始导出"按钮
3. 系统自动保存路径到 Cookie（`jianying_draft_path`），有效期 3 个月
4. 系统收集时间轴数据（视频片段、音频片段、柱子信息）
5. 发送到后端 `/api/export_timeline_draft` 接口

### 2. 后端处理

1. **下载媒体文件**：
   - 从URL下载视频和音频文件
   - 支持本地上传文件复用
   - 使用缓存避免重复下载相同素材

2. **生成剪影草稿**：
   - 根据前端 `ratio` 设置画布尺寸（查 `JIANYING_RATIO_RESOLUTION` 映射，写入 `canvas_config`）
   - 用 ffprobe 预取每个已下载文件的真实时长与视频尺寸（`asyncio.to_thread` + 信号量限流，不阻塞事件循环）
   - 创建 `JianyingMultiTrackLibrary` 实例，根据柱子系统或经典模式添加视频和音频片段
   - 视频素材声明真实尺寸，`clip.scale` 保持 1.0（剪映默认适配基准，素材自动等比适应画布、保持长宽比、不裁切）；音视频用真实时长，超出部分完整保留
   - 生成草稿文件（`draft_content.json` 和 `draft_meta_info.json`）
   - 复制媒体文件到草稿的 `Resources/local` 目录

3. **打包下载**：
   - 创建包含草稿文件夹和导入指南的ZIP压缩包
   - 根据 `server.is_local` 配置决定下载方式：
     - **本地环境 (`is_local: true`)**：返回本地服务器的下载链接
     - **非本地环境 (`is_local: false`)**：先上传到七牛云，返回 CDN 下载链接

### 3. 导入剪影

1. 下载ZIP压缩包并解压
2. 将草稿文件夹复制到剪影草稿路径
3. 打开剪映，在草稿列表中找到导入的草稿

## 技术细节

### 时间单位

- **前端**：秒（浮点数）
- **后端**：微秒（整数），通过 `seconds_to_microseconds()` 转换

### 画布比例与素材适配

- **画布尺寸**：由前端 `ratio` 决定，经 `JIANYING_RATIO_RESOLUTION`（`config/constant.py`）映射为像素尺寸（如 9:16 → 1080×1920），写入 `canvas_config.width/height/ratio` 与 `draft_meta_info.resolution`。
- **素材尺寸与适配**：视频素材的 `width/height` 用 ffprobe 探测的真实值（非画布尺寸）。`clip.scale` 保持 `1.0`——这是剪映的**默认适配基准**（导入素材时剪映自动等比适应画布，保持长宽比、不裁切、不变形）。**切勿**按"画布/素材尺寸比例"计算后写入 scale，否则剪映会在适配基准上叠加缩放，导致画面过度放大、双向溢出只看到中间。竖屏素材进竖屏画布（比例一致）会铺满无黑边；横屏素材进竖屏画布则完整显示、上下留黑边。
- **超出不切除**：音视频用 ffprobe 真实时长（前端用浏览器元素取时长不可靠、失败回退默认值），在未手动裁剪时（`startTime==0 && endTime>=duration`）用真实时长覆盖前端预估；`material.duration` 存文件完整时长，草稿顶层 `duration` 自动延长以完整容纳最长素材。

### 素材路径

- **草稿中的路径**：使用用户提供的 `draft_path` 作为前缀
- **实际文件位置**：`草稿文件夹/Resources/local/文件名`

### 文件命名

- **视频**：`video_{序号}_{随机ID}.{扩展名}`
- **音频**：`audio_{序号}_{随机ID}.{扩展名}`

## 问题修复记录

### 2025-01-07 修复

**问题1：视频不连续时，后续镜头丢失**
- **原因**：旧版本只处理成功下载的视频，如果某个镜头没有视频，会导致时间轴错位
- **解决**：引入柱子系统和占位符机制
  - 按柱子顺序处理，为没有视频的柱子创建占位符片段
  - 占位符使用已有视频素材，但设置为不可见（`visible=false`）、静音（`volume=0`）
  - 占位符时长等于柱子的默认时长，确保时间轴连续

**问题2：时间轴中的音频没有导出**
- **原因**：旧版本只处理视频轨道，没有处理音频轨道
- **解决**：
  - 前端：导出时包含 `audio_clips` 数据
  - 后端：创建独立的音频轨道，下载并添加音频片段

**问题3：时间轴刻度尺显示不正确**
- **原因**：刻度尺没有与轨道标签对齐，导致0秒刻度与视频片段位置不匹配
- **解决**：
  - 刻度尺DOM结构：添加60px左侧占位，与轨道标签宽度一致
  - 轨道padding：移除左右padding（改为只有上下padding），让片段从真正的0位置开始
  - 刻度线样式：添加主刻度线（12px高）和次刻度线（6px高），提升可读性
  - 刻度线层级：设置 `z-index: 10`，确保刻度线显示在视频片段上方

**问题4：清空时间轴功能不完整**
- **原因**：只清空了视频片段，没有清空音频片段和柱子引用
- **解决**：
  - 同时清空 `clips`、`audioClips`、`selectedClipId`、`selectedAudioClipId`
  - 清空所有柱子中的 `videoClipIds` 和 `audioClipIds` 引用

## API 接口

### POST /api/export_timeline_draft

**请求参数**：
```json
{
  "draft_path": "剪影草稿路径前缀",
  "video_clips": [...],
  "audio_clips": [...],
  "pillars": [...],
  "workflow_name": "工作流名称",
  "ratio": "画布比例（可选，如 9:16 / 16:9，默认 16:9）"
}
```

**响应**：
```json
{
  "success": true,
  "download_url": "下载链接",
  "zip_filename": "压缩包文件名"
}
```

## 相关文件

- **前端**：`/web/js/timeline.js` - `exportTimelineToDraft()` 函数
- **后端**：`/server.py` - `/api/export_timeline_draft` 接口
- **剪影库**：`/jianying/src/` - 草稿生成核心代码
  - `core.py` - 多轨道库核心
  - `draft_generator.py` - 草稿生成器
  - `jianying_utils.py` - 工具函数

### 2026-06-14 修复

**问题1：竖屏设置下导出的草稿画布/首个素材仍为横屏**
- **原因**：前端 `state.ratio`（竖屏 9:16）从未传给后端导出接口；后端用硬编码 1920×1080 初始化剪映库，`canvas_config` 永远是横屏。次要：视频素材 material 的宽高用了画布尺寸而非真实文件尺寸，`clip.scale` 固定 1.0 无画布适配。
- **解决**：
  - 前端导出请求体增加 `ratio` 字段（`web/js/timeline.js`）
  - 新增画布比例映射常量 `JIANYING_RATIO_RESOLUTION`（`config/constant.py`），后端按 `ratio` 设置画布 width/height 并写入 `canvas_config.ratio`（`server.py` / `jianying/src/core.py` / `draft_generator.py`）
  - 视频素材用 ffprobe 真实尺寸，`clip.scale` 保持 `1.0`（剪映默认适配基准，素材自动等比适应画布、保持长宽比、不裁切）

**问题2：音频/视频超出预设时长被切除**
- **原因**：`source_timerange.duration` 钉死在前端预估时长上（前端用浏览器 `<audio>`/`<video>` 取时长，失败回退默认值，不可靠），剪映只播放这段，超出被切。
- **解决**：
  - 新增 `probe_safe`（`jianying/src/media_utils.py`）：单次 ffprobe 安全取时长/尺寸，失败返回零值不抛异常
  - 后端导出时用 `asyncio.to_thread` 预取真实时长（按 file_path 去重、`Semaphore(8)` 限流），在「未手动裁剪」时（`startTime==0 && endTime>=duration`）用真实时长覆盖前端预估
  - `material.duration` 存文件完整时长，`segment` 用使用片段时长；`total_duration` 自动延长以完整容纳长素材

**后续修正：clip.scale 的剪映适配语义**
- **现象**：首版按 `max(画布宽/素材宽, 画布高/素材高)` 计算 cover scale 写入 `clip.scale`，但导出后画面长宽双向溢出、只看到中间。
- **根因**：剪映的 `clip.scale=1.0` 是**默认适配基准**（导入素材时剪映已自动等比适应画布），scale 字段是相对该基准的额外缩放。把 cover 比例写入会被叠加，导致过度放大。（与开源库 pyJianYingDraft 的 `ClipSettings` 默认 `scale=1.0`、添加视频时不计算 scale 的做法一致。）
- **解决**：`clip.scale` 恢复 `1.0`，依赖剪映默认适配（保持长宽比、不裁切、不变形）。

### 2026-06-06 修复

**问题：导出剪影草稿时视频下载 403 Forbidden**
- **原因**：视频生成后，CDN URL 带有签名 token（`e` 过期时间戳 + `token` 签名），存入 `clip.url`。导出草稿时后端直接用 httpx 下载该 URL，但 token 已过期，CDN 返回 403。
- **解决**：
  - 使用 `CDNUtil.refresh_cdn_signed_url()` 辅助函数（`utils/cdn_util.py`），在下载视频/音频前检测 CDN URL 并重新生成签名
  - 仅对匹配已配置 CDN 域名的 URL 进行刷新，非 CDN URL 原样返回
  - 刷新签名有效期为 28 小时（100800 秒），使用七牛云 `private_download_url` 重新签名
  - 视频和音频下载流程均增加了此步骤

## 注意事项

1. **路径格式**：Windows路径使用反斜杠（`\`），需要在输入时正确转义
2. **文件大小**：大量视频和音频会导致下载时间较长，建议优化素材大小
3. **临时文件清理**：系统会自动清理下载的临时文件
   - 本地环境：草稿压缩包会保留在服务器上
   - 非本地环境：上传到七牛云后会删除本地压缩包以节省空间
4. **兼容性**：支持新旧两种数据格式，确保向后兼容
5. **云存储配置**：非本地环境需要正确配置 `file_storage.qiniu` 的七牛云存储参数
6. **CDN 签名刷新**：导出草稿时会自动刷新 CDN URL 签名，避免因 token 过期导致下载失败
