# 剪映多轨道草稿生成库

一个专业的Python库，用于生成剪映（CapCut）多轨道草稿项目，支持动态轨道创建、精确媒体时长获取和完整的素材管理。

## 特性

- ✅ **多轨道支持**: 创建任意数量的视频和音频轨道
- ✅ **精确时长获取**: 通过FFmpeg/FFprobe获取准确的媒体文件时长
- ✅ **配置管理**: 灵活的配置文件系统
- ✅ **自动素材复制**: 自动复制媒体文件到草稿目录
- ✅ **回退机制**: 当FFmpeg不可用时的智能回退
- ✅ **完整兼容**: 生成的草稿完全兼容剪映专业版

## 安装

### 前置要求

1. **Python 3.7+**
2. **FFmpeg** (推荐，用于精确获取媒体时长)
   - Windows: 下载 [FFmpeg](https://ffmpeg.org/download.html) 并添加到PATH
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt install ffmpeg`

### 安装库

```bash
# 克隆项目
git clone <repository-url>
cd jianying_multi_track_lib

# 安装依赖
pip install -r requirements.txt
```

## 快速开始

### 1. 配置FFmpeg路径

编辑 `config.json` 文件：

```json
{
  "ffmpeg": {
    "ffmpeg_path": "ffmpeg",
    "ffprobe_path": "ffprobe",
    "timeout": 30,
    "fallback_enabled": true
  }
}
```

### 2. 基础使用

```python
from src.core import JianyingMultiTrackLibrary
from src.utils import seconds_to_microseconds

# 创建库实例
library = JianyingMultiTrackLibrary(
    draft_name="我的项目",
    output_dir="./output"
)

# 创建轨道
video_track = library.create_video_track("主视频")
audio_track = library.create_audio_track("背景音乐")

# 添加媒体文件（自动获取时长）
library.add_video_to_track(
    track_id=video_track,
    file_path="video.mp4",
    start_time=0
    # duration 会自动通过FFprobe获取
)

library.add_audio_to_track(
    track_id=audio_track,
    file_path="audio.mp3",
    start_time=0,
    volume=0.6
)

# 生成草稿
from src.draft_generator import DraftGenerator
generator = DraftGenerator(library)
draft_path = generator.generate_draft(copy_media_files=True)
```

### 3. 高级用法

```python
# 指定具体时长和源位置
library.add_video_to_track(
    track_id=video_track,
    file_path="video.mp4",
    start_time=0,
    duration=seconds_to_microseconds(30),  # 30秒
    source_start=seconds_to_microseconds(10),  # 从源文件10秒开始
    width=1920,
    height=1080
)

# 音频混合
library.add_audio_to_track(
    track_id=audio_track,
    file_path="bgm.mp3",
    start_time=seconds_to_microseconds(15),
    duration=seconds_to_microseconds(20),
    volume=0.3,
    source_start=seconds_to_microseconds(30)
)
```

## 配置说明

### config.json 配置项

```json
{
  "ffmpeg": {
    "ffmpeg_path": "ffmpeg",           // FFmpeg可执行文件路径
    "ffprobe_path": "ffprobe",         // FFprobe可执行文件路径
    "timeout": 30,                     // 命令超时时间（秒）
    "fallback_enabled": true           // 是否启用回退机制
  },
  "media": {
    "supported_video_formats": [".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"],
    "supported_audio_formats": [".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"]
  }
}
```

### 动态配置FFmpeg路径

```python
from src.config import Config

config = Config()
config.update_ffmpeg_paths(
    ffmpeg_path="/usr/local/bin/ffmpeg",
    ffprobe_path="/usr/local/bin/ffprobe"
)
```

## API 文档

### JianyingMultiTrackLibrary

主要的库类，用于管理多轨道草稿项目。

#### 方法

- `create_video_track(name: str = "") -> str`: 创建视频轨道
- `create_audio_track(name: str = "") -> str`: 创建音频轨道
- `add_video_to_track(...)`: 添加视频片段到轨道
- `add_audio_to_track(...)`: 添加音频片段到轨道
- `get_media_duration(file_path: str) -> int`: 获取媒体文件时长

### MediaUtils

媒体文件处理工具类。

#### 方法

- `get_media_duration(file_path: str) -> int`: 获取媒体时长
- `get_media_info(file_path: str) -> dict`: 获取媒体详细信息
- `check_ffmpeg_availability() -> tuple`: 检查FFmpeg可用性

### 工具函数

```python
from src.utils import (
    seconds_to_microseconds,
    microseconds_to_seconds,
    time_to_microseconds,
    format_duration
)

# 时间转换
microseconds = seconds_to_microseconds(30.5)  # 30.5秒 -> 微秒
seconds = microseconds_to_seconds(30500000)   # 微秒 -> 30.5秒
microseconds = time_to_microseconds("1:30")   # 1分30秒 -> 微秒
formatted = format_duration(90000000)         # 微秒 -> "1分30.0秒"
```

## 项目结构

```
jianying_multi_track_lib/
├── config.json              # 配置文件
├── requirements.txt          # 依赖文件
├── README.md                # 说明文档
├── src/                     # 源代码
│   ├── __init__.py
│   ├── core.py              # 核心库类
│   ├── config.py            # 配置管理
│   ├── media_utils.py       # 媒体工具
│   ├── utils.py             # 工具函数
│   └── draft_generator.py   # 草稿生成器
└── examples/                # 示例代码
    └── basic_example.py     # 基础示例
```

## 使用说明

### 1. 在剪映中使用生成的草稿

1. 运行脚本生成草稿项目
2. 将生成的草稿文件夹复制到剪映草稿目录：
   ```
   Windows: C:\Users\<用户名>\AppData\Local\JianyingPro Drafts\
   macOS: ~/Movies/JianyingPro/
   ```
3. 重启剪映，在草稿列表中找到项目并打开

### 2. 媒体文件要求

- 支持剪映兼容的所有视频格式（MP4, AVI, MOV等）
- 支持剪映兼容的所有音频格式（MP3, WAV, AAC等）
- 文件路径支持中文和特殊字符
- 自动复制素材文件到草稿目录

### 3. 故障排除

**FFprobe不可用**:
- 确保FFmpeg已正确安装
- 检查PATH环境变量
- 在config.json中配置正确的路径

**素材缺失**:
- 确保媒体文件存在且可访问
- 检查文件路径是否正确
- 确保copy_media_files=True

**时长不准确**:
- 安装FFmpeg获取精确时长
- 检查媒体文件是否损坏
- 启用fallback_enabled作为备选

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！
