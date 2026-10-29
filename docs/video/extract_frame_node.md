# 提取帧节点

## 概述

提取帧节点用于从视频中提取指定帧（首帧、尾帧、自定义时间点、关键帧候选）并创建图片节点。

## 功能特点

1. **四种帧类型**：首帧 / 尾帧 / 自定义时间点（时间轴选帧）/ 关键帧候选（场景切换自动截取）
2. **自动创建图片节点**：单帧提取成功后自动创建新的图片节点
3. **支持视频节点连接**：可连接视频节点，直接使用其视频URL
4. **避免重复下载**：连接的视频已在服务器时，直接使用本地路径，无需重新下载上传
5. **源地址实时回读**：连接场景下提取前实时回读源视频节点的最新地址——若连线发生在源
  视频上传完成前，复制到本节点的是 `blob:` 临时地址，直接提交会被后端拒绝（"不支持外部
  视频URL"）；回读机制自动纠正，源视频仍在上传时给出明确提示
6. **工作流重载复原**：时间点选择、关键帧候选网格与选中态均随工作流保存恢复；连线来源
  的视频地址不入库（`blob:` 地址保存时被清空），重载后自动从源视频节点回读复原预览

## 使用方法

### 1. 创建节点

通过左侧菜单点击"提取帧"按钮创建节点。

### 2. 输入视频

有两种方式输入视频：

- **上传视频文件**：点击"视频"字段的上传按钮，选择本地视频文件
- **连接视频节点**：从视频节点的输出端口拖拽连接到提取帧节点的输入端口

### 3. 选择帧类型

在下拉菜单中选择：
- **首帧**：提取视频的第一帧
- **尾帧**：提取视频的最后一帧
- **自定义时间**：出现时间轴滑杆（0 ~ 视频时长，步进 0.01s），预览播放器同时开启原生
  控件，可播放/拖动定位；拖动滑杆后点击"提取帧"提取该时刻的帧
- **关键帧（自动）**：通用"提取帧"按钮隐藏，起始时间滑杆下方出现"提取关键帧列表"
  按钮；后端自动检测场景切换点，返回候选帧网格（3 列、带时间标签、每批最多 9 张）；
  点击候选选中后，点"使用选中帧"创建图片节点

### 4. 关键帧翻页提取（起始时间）

关键帧模式下，起始时间滑杆下方是**"提取关键帧列表"按钮**（通用"提取帧"按钮在该模式
下隐藏）：

1. 点击"提取关键帧列表"→ 提取起始时间之后最早的最多 9 个场景切换点
2. 提取成功后**起始时间自动推进到本批最后一帧**（滑杆与时间码同步）
3. 继续点击"提取关键帧列表"→ 提取下一批，不断点击即可逐批向后浏览整个视频
4. 切换点已取尽时，最后一批自动补上视频末尾帧；之后再次点击提示"已到视频末尾"

拖动滑杆可手动调整起始位置（如跳回开头或跳到任意段落重新提取）；更换视频后起点自动
归零。起始时间随工作流保存，重载后恢复。

切离关键帧模式（首帧/尾帧/自定义时间）时，"提取关键帧列表"按钮、候选帧网格与"使用
选中帧"按钮自动隐藏；切回时若仍有候选数据则恢复显示。

### 5. 提取帧

点击"提取帧"按钮：
- 首帧/尾帧/自定义时间：提取指定帧 → 创建新的图片节点 → 自动建立连接线
- 关键帧（自动）：返回候选帧网格 → 用户点选 → "使用选中帧" → 创建图片节点并连线

## 节点数据

```javascript
{
  type: 'extract_frame',
  data: {
    videoFile: null,        // 上传的视频文件（不保存）
    videoUrl: '',           // 视频URL（服务器URL会保存）
    videoName: '',          // 视频名称
    frameType: 'first',     // 帧类型：'first' | 'last' | 'custom' | 'keyframes'
    timeSec: null,          // custom 模式选中的时间点（秒），随工作流保存，重载后恢复
    keyframeStartSec: 0,    // keyframes 模式的翻页起始时间（秒），每批提取后自动推进
    candidateFrames: null,  // keyframes 模式的候选帧 [{url, time_sec}]，随工作流保存
    selectedFrameTime: null,// keyframes 模式选中的候选帧时间（秒），随工作流保存
    extractedImageNodeId: null,  // 提取后创建的图片节点ID
    status: 'idle'          // 状态：idle, extracting, success, error
  }
}
```

## 后端 API

### 提取帧接口

```
POST /api/video-workflow/extract-frame
```

参数：
- `file`：视频文件（可选，与 video_url 二选一）
- `video_url`：视频URL（可选，服务器上的视频路径）
- `frame_type`：帧类型，`first` | `last` | `custom` | `keyframes`（默认 `first`）
- `time_sec`：自定义时间点（秒），`frame_type=custom` 时必填，须小于视频流时长
- `start_time`：关键帧起始时间（秒），`frame_type=keyframes` 时生效，只提取该时刻之后的关键帧

单帧返回（first / last / custom）：
```json
{
  "code": 0,
  "data": {
    "url": "http://host/upload/temp/xxx/last_frame_xxx.jpg",
    "filename": "last_frame_xxx.jpg",
    "frame_type": "last",
    "time_sec": 1.25
  }
}
```

关键帧候选返回（keyframes）：
```json
{
  "code": 0,
  "data": {
    "frames": [
      {"url": "http://host/upload/temp/xxx/keyframe_xxx_000.jpg", "time_sec": 0.0},
      {"url": "http://host/upload/temp/xxx/keyframe_xxx_001.jpg", "time_sec": 2.0}
    ],
    "frame_type": "keyframes",
    "start_time": 0.0,
    "last_time_sec": 2.0
  }
}
```

`last_time_sec` 为本批最后一帧的时间，前端将其写回起始时间实现翻页续批；
`frames` 为空数组表示起始时间之后已没有可提取的关键帧（已到视频末尾）。

### 视频URL优化

当 `video_url` 参数传入服务器上的视频路径时（如 `/upload/workflow/1/xxx.mp4`），后端会直接使用本地文件路径，避免重复下载。上传的临时视频文件在提取完成后自动清理。

## 实现位置

| 层 | 文件 |
|----|------|
| 前端节点 | `web/js/extract_frame_node.js` |
| 前端样式 | `web/css/video_workflow.css`（`.time-picker-field` / `.keyframe-grid`） |
| 后端接口 | `server.py` `extract_video_frame`（`POST /api/video-workflow/extract-frame`） |
| ffmpeg 服务 | `services/video_frame_extract_service.py`（全异步，超时 kill） |
| 常量 | `config/constant.py` `MediaConstants.VIDEO_FRAME_*` |
| 单元测试 | `tests/services/test_video_frame_extract_service.py` |

## ffmpeg 提取策略（两级回退）

| 帧类型 | 快路径 | 兜底 |
|--------|--------|------|
| first | `-i V -frames:v 1` | — |
| last | `-sseof -1.5 -i V -update 1`（尾部窗口全部帧覆盖写，留下最后一帧） | 全片 `-i V -update 1` |
| custom | `-ss T -i V -frames:v 1 -update 1`（input seek） | `-i V -vf select='gte(t,T)' -frames:v 1`（解码侧过滤） |
| keyframes | ffprobe 时长 → `select='gt(scene,0.3)'` 场景检测（`-ss start` 跳段解码，检测点加回偏移得绝对时间）→ 候选点逐点提取 | 单镜头剩余段（无切换点）均匀采样一批；尾点固定走 last 链 |

关键帧翻页选点策略（每批最多 9 张）：
- 首批（start=0）：首帧 + 最早 8 个切换点；续批：最早 9 个切换点，严格晚于起点
- 剩余切换点不足一批时，最后一批自动补尾帧；**恰好满批且切换点取尽时本批不补**
  （挤掉切换点会永久丢帧——下一批从末点续传回不去），尾帧由下一批均匀采样天然补上；
  切换点已取尽后再次提取返回空
- 相邻点间隔小于 0.2s 合并；单镜头剩余段均匀采样一批（含尾帧）
- 剩余时长超过 600s 跳过场景检测（需全片/跳段解码），退化为均匀采样

## 尾帧提取缺陷修复（背景）

旧实现 `ffmpeg -sseof -0.1 -i V -vframes 1` 在部分视频上必然失败：
`-sseof` 按容器 format duration（取所有流最长者）回退 0.1s 定位，**音轨长于视频轨**
的视频（配音视频、音轨拉长的生成视频）定位点落在视频流最后一帧之后，ffmpeg 报
`Output file is empty, nothing was encoded`，接口返回 500。回退窗口 0.1s 过窄也会在
VFR / 时间戳偏移视频上落空。

修复：`-sseof -1.5` 扩大窗口 + `-update 1` 覆盖写（不能配 `-frames:v 1`，会在窗口
第一帧后停止），最终文件为窗口内真正的最后一帧；窗口仍空输出时全片解码兜底。
回归用例见 `tests/services/test_video_frame_extract_service.py`
`test_last_frame_audio_longer_than_video`。

## 连接类型

提取帧节点创建的图片连接使用特殊的 `portType: 'extracted'`：
- 源端口：提取帧节点的 output 端口
- 目标端口：图片节点的 input 端口

## 注意事项

1. **视频格式**：支持常见视频格式（MP4、MOV、AVI等），解码能力以本机 ffmpeg 为准
2. **提取时长**：关键帧模式对短视频（<120s）需全片解码做场景检测，耗时略长；长视频自动跳过
3. **图片格式**：提取的帧保存为 JPG 格式（质量 q:v 2）
4. **工作流保存**：提取成功后会自动保存工作流；候选帧 URL 位于 `/upload/temp`，与首尾帧一致受临时目录清理策略约束
5. **时间点校验**：custom 模式后端按视频流时长校验 time_sec 越界（探测失败时跳过校验，由提取链兜底报错）

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 请先上传视频或连接视频节点 | 未提供视频 | 上传视频或连接视频节点 |
| 源视频节点还没有视频，请先上传 | 连接的视频节点未上传视频 | 先在源视频节点上传视频 |
| 源视频还在上传中，请稍候再试 | 连线复制地址时源视频未上传完成（`blob:` 临时地址） | 等源视频上传完成后再提取 |
| 视频文件不存在 | video_url 指向的文件不存在 | 检查视频URL是否正确 |
| 请先在时间轴上选择时间点 | custom 模式未选时间 | 拖动时间轴滑杆选择时间点 |
| 时间点 X.XXs 超出视频时长 X.XXs | time_sec 大于视频流时长 | 重新选择时间点 |
| 时间点 X.XXs 之后没有可解码的视频帧 | 两级提取链都取不到帧 | 检查视频是否损坏 |
| 未提取到关键帧 | 视频无法解码或时长不可读 | 检查视频格式是否支持 |
| 提取失败 / 尾帧提取失败 | FFmpeg 处理错误或超时 | 检查视频格式，稍后重试 |
