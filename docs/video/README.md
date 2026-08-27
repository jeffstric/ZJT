# 视频功能文档

本目录包含视频工作流的所有功能文档。

## 画布与工作流

| 文档 | 说明 |
|------|------|
| [canvas_system.md](./canvas_system.md) | 画布系统 - 缩放、平移、小地图、节点操作 |
| [world_management.md](./world_management.md) | 世界管理 - 世界 CRUD、画风继承、公共空间 |
| [workflow_save_load.md](./workflow_save_load.md) | 工作流保存与加载 - 手动保存、自动恢复、撤销重做 |
| [connection_system.md](./connection_system.md) | 连接线系统 - 5 种连接类型、创建删除、连接规则 |
| [node_registry.md](./node_registry.md) | 节点注册表系统 - 节点类型注册、工厂模式、工作流恢复 |

## 全局设置

| 文档 | 说明 |
|------|------|
| [style_settings.md](./style_settings.md) | 画风设置 - 画风名称、参考图、构图倾向、世界同步 |
| [video_ratio.md](./video_ratio.md) | 视频比例设置 - 9:16/3:4/1:1/4:3/16:9 |
| [video_prompt_suffix.md](./video_prompt_suffix.md) | 视频提示词后缀 - 全局后缀设置 |
| [dark_mode.md](./dark_mode.md) | 暗色模式 - 浅色/暗色切换、本地偏好、token 体系 |

## 节点文档

| 文档 | 说明 |
|------|------|
| [video_node.md](./video_node.md) | 视频节点 - 上传、预览、时间轴、连接接收 |
| [audio_node.md](./audio_node.md) | 音频节点 - 上传、预览、时间轴、连接接收 |
| [image_node.md](./image_node.md) | 图片节点 - 上传、上色编辑、网格图、连接输出 |
| [image_to_video_node.md](./image_to_video_node.md) | 图生视频节点 - 三种输入模式、多视频模型、参数设置 |
| [script_node.md](./script_node.md) | 剧本节点 - 导入、解析、自动拆分、角色匹配 |
| [shot_group_node.md](./shot_group_node.md) | 分镜组节点 - 分镜详情、批量管理 |
| [shot_frame_node.md](./shot_frame_node.md) | 分镜帧节点 - 帧图片/视频生成、AI 生成、参考素材收集 |
| [extract_frame_node.md](./extract_frame_node.md) | 提取帧节点 - 从视频提取首帧/尾帧 |
| [text_to_speech_node.md](./text_to_speech_node.md) | 文字转语音节点 - 参考语音、情感控制、情感权重 |
| [digital_human_node.md](./digital_human_node.md) | 数字人节点 - 图片+音频生成数字人视频、绘制功能 |
| [dialogue_group_node.md](./dialogue_group_node.md) | 对话组节点 - 多角色对话、自动 TTS、时间轴关联 |
| [camera_control_node.md](./camera_control_node.md) | 相机控制节点 - 水平/垂直角度、缩放、3D 预览、预设运动 |
| [panorama_node.md](./panorama_node.md) | 360全景图节点 - equirectangular 全景生成、Pannellum 拖拽查看、全屏、提示词模板 |
| [text_node.md](./text_node.md) | 文本节点 - 纯文本注释 |

## 资产管理

| 文档 | 说明 |
|------|------|
| [assets_management.md](./assets_management.md) | 资产管理 - 角色/场景/道具的创建、编辑、分镜关联 |

## 视频生成

| 文档 | 说明 |
|------|------|
| [video_generate_node.md](./video_generate_node.md) | 生视频节点（支持首尾帧/多参考图/文生视频三种模式） |
| [shot_group_video_generation.md](./shot_group_video_generation.md) | 分镜组节点视频生成功能 |
| [shot_frame_video_mode.md](./shot_frame_video_mode.md) | 分镜节点视频生成模式（首帧模式/参考图模式） |
| [video_resolution.md](./video_resolution.md) | 视频分辨率选择、算力联动与退款回算 |
| [grid_merge_video_generation.md](./grid_merge_video_generation.md) | 分镜组多宫格图片合并 & 视频生成 |

## 功能说明

- **extract_frame_node**: 从视频中提取首帧或尾帧，自动创建图片节点
- **grid_merge_video_generation**: 将多个分镜首帧合并为宫格图后生成视频
- **shot_group_video_generation**: 拼接所有分镜视频提示词，使用第一个分镜首帧生成视频
- **video_generate_node**: 生视频节点，支持首尾帧模式、多参考图模式和文生视频模式
- **video_resolution**: 视频分辨率选项、算力倍率、接口参数和退款上下文说明

## 其他

| 文档 | 说明 |
|------|------|
| [video_compressor.md](./video_compressor.md) | 视频压缩模块 - 前端 Canvas 压缩、后端 ffmpeg 压缩 |
| [../drivers/seedance_volcengine_v1_driver.md](../drivers/seedance_volcengine_v1_driver.md) | Seedance 火山引擎驱动（支持参考音频/视频） |
