# 世界故事类型

`world.story_type` 用于记录当前世界的剧本表达方式，历史世界默认都是 `dialogue`。

## 可选值

- `dialogue`：对话剧情。角色台词由对应角色说出，原有剧本生成逻辑保持不变。
- `narration`：旁白解说。剧本中的对白和讲述统一交给“旁白”角色说明，其他角色主要通过动作、表情和画面行为参与剧情。
- `music_mv`：音乐MV。用于未来“输入音频并生成匹配画面”的能力，目前只保存类型，生成链路尚未实现。

## 数据流

- 数据库存储字段：`world.story_type`，默认 `dialogue`。
- 常量定义：`config.constant.StoryType`。
- 智能体读写：`read_world()` 返回 `story_type`，`update_world(story_type=...)` 保存用户确认的类型。
- 剧本技能：`plot-analyzer` 负责确认故事类型；`story-writer` 和 `character-creator` 根据类型调整输出。

## 前端拆分

`video_workflow.html` 的剧本节点不再提供“解说剧（仅旁白说话）”选项，也不再向 `/api/parse-script` 发送 `narration_as_dialogue`。故事表达方式统一由世界的 `story_type` 管理。

后端同样已移除旧的 `narration_as_dialogue` 参数、对话剧本转纯旁白剧本的转换函数，以及解说模式的兜底旁白后处理。旁白解说不再作为剧本拆分的特殊模式存在。

## 剧本智能体页面

`web/script_writer.html` 的世界界面会在查看、编辑 world_json、新建世界、编辑世界时展示并保存 `story_type`。旧的 `world_json` 如果没有该字段，前端和后端文件读写路径都会默认补为 `dialogue`，与数据库默认值保持一致。

## 模型导入兼容

`storyboard_scene` 表的业务模型仍集中在 `model.storyboard` 中维护；同时提供 `model.storyboard_scene` 兼容模块，供按表名导入 `StoryboardScene` / `StoryboardSceneModel` 的代码使用。
