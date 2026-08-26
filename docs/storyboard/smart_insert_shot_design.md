# 分镜智能插入功能设计文档

## 功能概述

在视频工作流的分镜组编辑界面中，支持在每个分镜之间智能插入新分镜。点击"✦ 智能插入"按钮后，系统会调用 LLM 智能体分析前后分镜内容，自动生成新分镜的各项属性（描述、画面、动作、镜头语言、情绪等），确保剧情连贯衔接。

## 功能特性

### 两种插入模式

1. **快速插入（+ 插入分镜）**
   - 保持原有逻辑
   - 从相邻分镜继承共性字段（location_id、time_of_day、weather 等）
   - 独有字段（description、action、opening_frame_description 等）留空，由用户手动填写

2. **智能插入（✦ 智能插入）**
   - 调用后端 LLM 智能体 API
   - 自动分析前后分镜上下文
   - 智能生成新分镜的所有属性
   - 生成失败时自动降级为快速插入

### 智能生成的分镜属性

| 字段 | 类型 | 说明 |
|------|------|------|
| description | string | 新分镜的描述 |
| opening_frame_description | string | 起始画面描述 |
| scene_detail | string | 场景细节 |
| action | string | 动作描述 |
| shot_type | string | 镜头类型 |
| camera_movement | string | 运镜方式 |
| mood | string | 情绪氛围 |
| characters_present | string[] | 出场角色列表 |
| dialogue | object[] | 对话列表 |
| duration | number | 时长（秒） |
| time_of_day | string | 时间段 |
| weather | string | 天气 |
| environment_sound | string | 环境音 |
| background_music | string | 背景音乐 |
| audio_notes | string | 音频备注 |

## 技术实现

### 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端 (nodes.js)                          │
├─────────────────────────────────────────────────────────────────┤
│  insertBtnHtml()                                                │
│    ├── "+ 插入分镜" 按钮 → addNewShot()                         │
│    └── "✦ 智能插入" 按钮 → addNewShotSmart()                    │
│                              │                                   │
│                              ▼                                   │
│                    POST /api/video-workflow/                     │
│                         smart-insert-shot                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    后端 (server.py)                              │
├─────────────────────────────────────────────────────────────────┤
│  smart_insert_shot()                                             │
│    ├── 1. 获取用户偏好 LLM 模型 (user_preferences)              │
│    ├── 2. 加载 storyboard-insert skill 提示词                   │
│    ├── 3. 构建上下文消息                                          │
│    ├── 4. 调用 LLM API                                          │
│    └── 5. 解析返回 JSON                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Skill (script_writer_core/skills/)                  │
├─────────────────────────────────────────────────────────────────┤
│  storyboard-insert/SKILL.md                                      │
│    - 分镜智能插入专家提示词                                       │
│    - 输入输出格式定义                                              │
│    - 创作原则（剧情连贯、画面连续、镜头合理等）                   │
└─────────────────────────────────────────────────────────────────┘
```

### 关键文件

| 文件 | 说明 |
|------|------|
| `web/js/nodes.js` | 前端分镜组编辑逻辑 |
| `server.py` | 后端 API 路由 |
| `script_writer_core/skills/storyboard-insert/SKILL.md` | 智能插入提示词 |
| `config/constant.py` | 常量配置 |

### LLM 模型选择

优先使用 `user_preferences` 表中该世界配置的 `default_llm_model`：

```python
from api.script_writer import get_default_llm_model
llm_config = get_default_llm_model(user_id, world_id)
model = llm_config['model'] if llm_config else SMART_INSERT_SHOT_DEFAULT_MODEL
```

未配置时降级为默认模型 `deepseek-v4-flash`（`SMART_INSERT_SHOT_DEFAULT_MODEL`，无斜杠形式——DeepSeek 客户端不剥离 `deepseek/` 前缀）。

### 提示词管理

提示词独立维护在 `script_writer_core/skills/storyboard-insert/SKILL.md`，支持：
- 文件系统默认版本
- 数据库用户级自定义覆盖（通过 `SkillLoader` 实现）

## API 接口

### POST /api/video-workflow/smart-insert-shot

**请求体：**

```json
{
  "prev_shot": {
    "shot_id": "5",
    "description": "前一个分镜描述",
    "opening_frame_description": "前一个分镜起始画面",
    "action": "前一个分镜动作",
    "shot_type": "中景",
    "camera_movement": "固定",
    "mood": "紧张",
    "characters_present": ["角色A"],
    "dialogue": [...]
  },
  "next_shot": {
    "shot_id": "7",
    "description": "后一个分镜描述",
    ...
  },
  "group_id": "分镜组ID",
  "script_data": {
    "world_id": "世界ID",
    "title": "剧本名称",
    "genre": "剧本类型",
    "synopsis": "故事梗概"
  }
}
```

**响应：**

```json
{
  "success": true,
  "shot": {
    "description": "生成的新分镜描述",
    "opening_frame_description": "生成的起始画面",
    "action": "生成的动作",
    "shot_type": "特写",
    "camera_movement": "推",
    "mood": "平静",
    "characters_present": ["角色A", "角色B"],
    "dialogue": [...],
    "duration": 5,
    ...
  }
}
```

**错误响应：**

```json
{
  "success": false,
  "error": "错误信息"
}
```

## 常量配置

```python
# config/constant.py
SMART_INSERT_SHOT_TIMEOUT = 30  # 智能体调用超时（秒）
SMART_INSERT_SHOT_DEFAULT_MODEL = 'deepseek-v4-flash'  # 降级默认模型（无斜杠，见上文说明）
```

## 使用流程

1. 用户在视频工作流中点击分镜组节点的"编辑"按钮
2. 在分镜编辑弹窗中，找到想要插入新分镜的位置
3. 点击"✦ 智能插入"按钮
4. 按钮显示"⏳ AI 生成中..."加载状态
5. 后端调用 LLM 分析前后分镜上下文
6. 生成成功后，新分镜自动插入到列表中
7. 生成失败时，自动降级为快速插入模式

## 故事板页面（storyboard.html）的智能插入

故事板页面与工作流共用 `services/smart_insert_service.py` 公共服务（端点 `POST /api/storyboard/{storyboard_id}/smart-insert-scene`）。点击时间轴/宫格视图中两个分镜之间的插入按钮时，默认走智能插入，LLM 失败时降级为普通插入。

### 字段完整性（与剧本解析生成分镜对齐）

后端端点在 LLM 生成后**直接创建分镜行**（`_create_smart_insert_scene`），字段与 `build_storyboard_scenes_from_parsed_script` 保持一致，返回 `{success, scene}`：

| 字段 | 来源 |
|------|------|
| 幕（group_id/group_name/act_name） | 继承相邻分镜（优先 prev，缺失回落 next），幕必然是插入位置前后两个分镜之一 |
| perspective（如"平视 / 中景"） | LLM 输出的 camera_angle / shot_type（SKILL.md 已补充 camera_angle 字段，对齐 script_parser 九列分镜表） |
| 场景 location / 道具 props / 画风 style | 从相邻分镜继承，避免新分镜卡片显示"未选场景" |
| character_desc | LLM 输出的 characters_present（剔除【【】】包裹） |
| video_config_json | {shot_type, camera_angle, camera_movement} |
| difficulty / title / duration / video_prompt | 与剧本解析生成分镜同规则 |

由于 LLM 生成耗时较长，为避免用户误以为无响应而重复点击，前端提供三重反馈：

1. **in-flight 守卫**：`state.isSmartInserting` 为真时再次点击直接忽略（`web/js/storyboard/events.js`）
2. **按钮加载态**：所有插入按钮变为禁用状态并显示旋转加载圈 + 呼吸动画（`renderInsertSceneSlot` + `.inserting` 样式）
3. **Toast 提示**：显示"AI 正在生成新分镜，请稍候…"

生成完成（成功或降级）后，`finally` 块复位 `state.isSmartInserting` 并重新渲染，插入按钮恢复正常。

## 注意事项

1. **LLM 调用超时**：设置 30 秒超时，超时后返回错误，前端降级为快速插入
2. **JSON 解析容错**：支持从 markdown 代码块中提取 JSON
3. **算力消耗**：智能插入会消耗 LLM 算力，按钮上有明确标识
4. **工作流重新加载**：智能插入按钮在节点重新加载后会正确复原
5. **降级策略**：LLM 调用失败时自动降级为普通插入，不影响用户使用

## 后续优化

1. 支持批量智能插入（一次插入多个分镜）
2. 支持指定插入分镜的风格/情绪倾向
3. 支持预览多个生成结果供用户选择
4. 优化提示词，提升生成质量
