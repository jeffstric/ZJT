# 图片功能文档

本目录包含与图片生成、编辑、处理相关的功能文档。

## 文档列表

| 文档 | 说明 |
|------|------|
| [qwen_image_edit.md](./qwen_image_edit.md) | Qwen Image Edit 空壳任务（task_id=38，用接口模块导入本地 ComfyUI 工作流后绑定） |
| [z_index.md](./z_index.md) | Z-index 空壳任务（task_id=48，待接入实现方） |
| [camera_control_implementation.md](./camera_control_implementation.md) | 图片节点相机控制功能（Yaw/Dolly/Pitch 参数） |
| [image_node_text_to_image.md](./image_node_text_to_image.md) | 图片节点文生图（无底图按提示词直接生成，自动切换文生图/图生图模式） |
| [prompt_reverse_node.md](./prompt_reverse_node.md) | 提示词反推节点（图片 → VL 反推文生图提示词 → 自动创建图片节点） |
| [grid_image_generation.md](./grid_image_generation.md) | 宫格图片生成功能（AI 生成 4/9 宫格分镜图） |
| [grid_image_validation.md](./grid_image_validation.md) | 宫格图片切图前的轻量几何校验 |
| [doodle_editor/](./doodle_editor/) | 图片涂鸦编辑功能（画笔/橡皮/文字/矩形；旧版涂色编辑已于 2026-09 下线） |
| [image_node_reference_connections.md](./image_node_reference_connections.md) | 图片节点多图参考连接功能 |
| [content_moderation_error_design.md](./content_moderation_error_design.md) | 内容审核友好展示 A+D（规则解释 + 按需 LLM 改写，已实现） |
