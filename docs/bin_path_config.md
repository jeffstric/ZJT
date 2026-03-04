# 配置说明 - FFmpeg 路径配置

## 简介

本项目支持配置 FFmpeg 和 FFprobe 可执行文件的路径，支持绝对路径、相对路径和系统 PATH 查找三种方式。

**统一配置原则**：主服务 (`server.py`) 和剪映模块 (`jianying`) 现在都从 **主配置文件** 读取 FFmpeg 路径。

## 配置项

在主配置文件（`config_dev.yml` 或 `config_prod.yml`）中配置：

```yaml
bin:
  # FFmpeg 可执行文件路径配置
  # 支持三种格式：
  # 1. 绝对路径（向后兼容）: "/usr/bin/ffmpeg"
  # 2. 相对路径（基于项目根目录）: "bin/ffmpeg/ffmpeg.exe"
  # 3. 使用系统 PATH 查找: "ffmpeg"
  ffmpeg: "bin/ffmpeg/ffmpeg"
  ffprobe: "bin/ffmpeg/ffprobe"
```

## 配置方式

### 1. 相对路径（推荐）

适用于将 FFmpeg 打包在项目目录中的情况：

**Windows:**
```yaml
bin:
  ffmpeg: "bin/ffmpeg/ffmpeg.exe"
  ffprobe: "bin/ffmpeg/ffprobe.exe"
```

**macOS/Linux:**
```yaml
bin:
  ffmpeg: "bin/ffmpeg/ffmpeg"
  ffprobe: "bin/ffmpeg/ffprobe"
```

目录结构示例：
```
comfyui_server/
├── bin/
│   └── ffmpeg/
│       ├── ffmpeg.exe      # Windows
│       ├── ffprobe.exe
│       ├── ffmpeg          # Linux/Mac
│       └── ffprobe
├── config_dev.yml          # ← 统一配置 FFmpeg 路径
└── ...
```

### 2. 绝对路径（向后兼容）

适用于系统已安装 FFmpeg 的情况：

```yaml
bin:
  ffmpeg: "/usr/bin/ffmpeg"
  ffprobe: "/usr/bin/ffprobe"
```

### 3. 系统 PATH 查找

如果 FFmpeg 已在系统 PATH 中，可以直接使用命令名：

```yaml
bin:
  ffmpeg: "ffmpeg"
  ffprobe: "ffprobe"
```

## 向后兼容性

- 现有绝对路径配置继续有效
- 如果配置项不存在，默认使用 `"ffmpeg"` 和 `"ffprobe"`（依赖系统 PATH）

## 统一配置说明

### 受影响的功能模块

| 功能模块 | 文件 | 说明 |
|---------|------|------|
| 音频修剪 | `server.py` | 检查音频时长，超过20秒自动修剪 |
| 视频提取音频 | `server.py` | 从视频下载并提取音频（数字人功能）|
| 剪映媒体时长 | `jianying/src/media_utils.py` | 获取视频/音频文件时长 |

### 剪映配置变更

- **之前**：剪映使用独立的 `jianying/config.json` 配置 FFmpeg 路径
- **现在**：剪映从主配置文件 (`config_dev.yml` / `config_prod.yml`) 的 `bin` 配置项读取 FFmpeg 路径
- **jianying/config.json**：仍保留，但 `ffmpeg.ffmpeg_path` 和 `ffmpeg.ffprobe_path` 配置项已不再使用

### 跨平台说明

- **Windows**: 相对路径使用反斜杠或正斜杠均可，程序会自动处理
- **macOS/Linux**: 使用正斜杠作为路径分隔符
- 配置文件中统一使用正斜杠 `"bin/ffmpeg/ffmpeg"`，程序会根据平台自动转换
