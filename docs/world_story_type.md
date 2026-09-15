# 世界故事类型

`world.story_type` 用于记录当前世界的剧本表达方式，历史世界默认都是 `dialogue`。

## 可选值

- `dialogue`：对话剧情。角色台词由对应角色说出，原有剧本生成逻辑保持不变。
- `narration`：旁白解说。剧本中的对白和讲述统一交给“旁白”角色说明，其他角色主要通过动作、表情和画面行为参与剧情。
- `music_mv`：音乐MV。用于未来“输入音频并生成匹配画面”的能力，生成链路尚未实现；剧本智能体页面中的该选项目前为禁用状态，用户不能新选此类型。

## 数据流

- 数据库存储字段：`world.story_type`，默认 `dialogue`。
- 常量定义：`config.constant.StoryType`。
- 智能体读写：`read_world()` 返回 `story_type`，`update_world(story_type=...)` 保存用户确认的类型。
- 剧本技能：`plot-analyzer` 负责确认故事类型；`story-writer` 和 `character-creator` 根据类型调整输出。

## 旁白角色硬保证

解说剧（`narration`）世界中必须存在名为“旁白”的角色卡，由代码层硬保证，不再仅依赖提示词约束：

- 核心函数：`script_writer_core.mcp_tool.ensure_narrator_character()`。检查世界的 `story_type`，若为 `narration` 且“旁白”角色卡缺失，则按默认设定（身份为叙事旁白/解说者，性格稳定清晰，行为习惯为用简洁、有画面感的语言解说全部剧情）自动补建；幂等，已存在时不修改。
- 触发挂载点：
  - `read_world()`：智能体获知故事类型的必经点，返回 `narration` 时触发；
  - `list_character_jsons()`：智能体查看角色列表的必经点，列出文件前触发，保证旁白角色必然出现在列表中。
- 兜底隔离：保障函数内部异常只记录日志并跳过，绝不影响 `read_world` / `list_character_jsons` 的正常返回。
- 提示词兜底：`skills/character-creator/SKILL.md` 同步要求角色智能体在角色列表中未见“旁白”时，必须先用 `create_character_json` 创建“旁白”角色，才能继续创建其他角色。
- 单元测试：`tests/script_writer_core/test_ensure_narrator_character.py`。

## 前端拆分

`video_workflow.html` 的剧本节点不再提供“解说剧（仅旁白说话）”选项，也不再向 `/api/parse-script` 发送 `narration_as_dialogue`。故事表达方式统一由世界的 `story_type` 管理。

后端同样已移除旧的 `narration_as_dialogue` 参数、对话剧本转纯旁白剧本的转换函数，以及解说模式的兜底旁白后处理。旁白解说不再作为剧本拆分的特殊模式存在。

## 剧本智能体页面

`web/script_writer.html` 的世界界面会在查看、编辑 world_json、新建世界、编辑世界时展示并保存 `story_type`。旧的 `world_json` 如果没有该字段，前端和后端文件读写路径都会默认补为 `dialogue`，与数据库默认值保持一致。

## 模型导入兼容

`storyboard_scene` 表的业务模型仍集中在 `model.storyboard` 中维护；同时提供 `model.storyboard_scene` 兼容模块，供按表名导入 `StoryboardScene` / `StoryboardSceneModel` 的代码使用。
