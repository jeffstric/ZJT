# 内置 CJK 字体

本目录存放视频导出字幕硬烧（ASS via ffmpeg `subtitles=` 滤镜）所需的 CJK 字体，
用于规避宿主机未安装中文字体 / Windows fontconfig 解析失败时字幕渲染为豆腐块（蚂蚁文）的问题。

## 字体清单

| 文件 | 用途 | 来源 |
|------|------|------|
| `NotoSansSC-Regular.otf` | 字幕默认字体（思源黑体 简中子集，~8MB） | notofonts/noto-cjk |

## 许可证

- 字体遵循 [SIL Open Font License 1.1](./LICENSE-OFL.txt)
- 随项目分发已包含 OFL 全文，符合 OFL 重分发要求

## 使用方式

- `services/storyboard_subtitle.py::resolve_builtin_font()` 解析本目录
- 每次导出烧录字幕时，由 `services/storyboard_export_service.py` 拷贝当前字体到 work_dir/fonts/
- ffmpeg `-vf subtitles=xxx.ass:fontsdir=fonts` 让 libass 从该相对目录加载字体
