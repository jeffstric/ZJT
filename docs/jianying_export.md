# 剪影草稿导出功能文档

## 功能概述

视频工作流支持将时间轴导出为剪影（JianyingPro）草稿文件，方便用户在剪映中进一步编辑。

## 主要特性

### 1. 支持柱子系统（Pillar System）

- **柱子定义**：每个柱子对应一个分镜（shot），是时间轴的基本分区单位
- **不连续视频处理**：即使某些镜头没有视频（如镜头1、2有视频，镜头3无视频，镜头4、5有视频），也能正确导出所有镜头
- **占位符机制**：对于没有视频的柱子，自动创建占位符片段（使用已有视频素材，但设置为不可见、静音），确保时间轴连续
- **时长计算**：每个柱子使用默认时长（来自分镜组最长时长）作为基准，实际时长取默认时长、视频时长、音频时长中的最大值

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
  workflow_name: "工作流名称"
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

1. 输入剪影草稿路径前缀（如：`C:\Users\Administrator\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft`）
2. 系统收集时间轴数据（视频片段、音频片段、柱子信息）
3. 发送到后端 `/api/export_timeline_draft` 接口

### 2. 后端处理

1. **下载媒体文件**：
   - 从URL下载视频和音频文件
   - 支持本地上传文件复用
   - 使用缓存避免重复下载相同素材

2. **生成剪影草稿**：
   - 创建 `JianyingMultiTrackLibrary` 实例
   - 根据柱子系统或经典模式添加视频和音频片段
   - 生成草稿文件（`draft_content.json` 和 `draft_meta_info.json`）
   - 复制媒体文件到草稿的 `Resources/local` 目录

3. **打包下载**：
   - 创建包含草稿文件夹和导入指南的ZIP压缩包
   - 返回下载链接给前端

### 3. 导入剪影

1. 下载ZIP压缩包并解压
2. 将草稿文件夹复制到剪影草稿路径
3. 打开剪映，在草稿列表中找到导入的草稿

## 技术细节

### 时间单位

- **前端**：秒（浮点数）
- **后端**：微秒（整数），通过 `seconds_to_microseconds()` 转换

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
  "workflow_name": "工作流名称"
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

## 注意事项

1. **路径格式**：Windows路径使用反斜杠（`\`），需要在输入时正确转义
2. **文件大小**：大量视频和音频会导致下载时间较长，建议优化素材大小
3. **临时文件清理**：系统会自动清理下载的临时文件，但草稿压缩包会保留在服务器上
4. **兼容性**：支持新旧两种数据格式，确保向后兼容
