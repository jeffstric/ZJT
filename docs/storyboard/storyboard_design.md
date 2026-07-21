# 故事板（Storyboard）页面设计方案 — 可执行版

## 相关补充文档

- [分镜助手对话生图](storyboard_agent_image_chat.md)
- [分镜间插入分镜](storyboard_insert_scene_slots.md)

## 2026-06-24 更新：demo2 前端正式化

本轮实现将 `demo2` 的原生前端页面作为正式故事板编辑器的视觉与交互基底，但不引入 `demo2` 的 Express 服务和静态样例数据。正式入口仍为 `/storyboard`，由 `server.py` 返回 `web/storyboard.html`，静态资源继续放在 `web/css/storyboard.css` 与 `web/js/storyboard/` 下，保持现有缓存版本号和部署方式。

### 前端落地结构

```text
web/storyboard.html
web/css/storyboard.css
web/js/storyboard/
  adapters.js    # 后端 storyboard/storyboard_scene/资产接口 -> demo2 UI 模型
  api.js         # 真实接口层，统一 X-User-Id 与 Authorization
  state.js       # 页面状态，保留 demo2 的工作台交互状态
  render.js      # demo2 风格渲染：顶部、左栏、中央预览、底部分镜序列、右侧参考帧
  events.js      # 事件委托，调用真实 storyboard API
  bootstrap.js   # URL 初始化、幂等创建/加载、资产加载、算力加载
  icons.js       # 内联 SVG 图标
```

### 入口链路

`script_writer.html` 的“故事板模式”跳转会先提交当前资产，再按 `world_id + episode_number` 查询当前集剧本 ID，生成如下 URL：

```text
/storyboard?world_id={world_id}&episode_number={n}&script_id={sid}&user_id={uid}&workflow_id={wid}
```

如果前端未查到 `script_id`，后端 `api/storyboard.py` 会继续用 `ScriptModel.get_by_episode(world_id, episode_number)` 兜底，避免首次进入故事板时创建空分镜。

### 数据适配规则

故事板页面不再消费 `demo2/js/data.js` 的样例数据，所有分镜来自 `storyboard_scene`。**2026-06-24 重构后**：前端 `scene` 对象命名与后端模型对齐，废弃 demo2 照搬的 `thumbnail / previewImageUrl / sceneInfo / charDesc / voiceoverText / status / errors` 等命名；配音拆为 `dialogues`，图片/视频来自选中 asset。

| 后端字段 | 前端字段 | 说明 |
| --- | --- | --- |
| `title` | `scene.title` | 分镜标题 |
| `duration` | `scene.duration / durationLabel` | 秒数与 `mm:ss` 展示 |
| `sort_order` | `scene.sortOrder` | 排序（DOUBLE 浮点二分，见 2.3.2） |
| `prompt_json.perspective` | `scene.promptJson.perspective` | 视角 |
| `prompt_json.style` | `scene.promptJson.style` | 风格 |
| `prompt_json.scene_desc` | `scene.promptJson.scene_desc` | 场景描述 |
| `prompt_json.character_desc` | `scene.promptJson.character_desc` | 角色描述 |
| `video_prompt` | `scene.videoPrompt` | 视频提示词（生视频/数字人动作描述） |
| `video_type` | `scene.videoType` | 分镜类型 image/video/digital_human |
| `audio_embedded` | `scene.audioEmbedded` | 音频来源：1=使用视频原声并跳过 TTS，0=静音视频并使用对话配音；时间轴预览与完整视频导出共用该规则，digital_human 默认 1 |
| `video_config_json` | `scene.videoConfigJson` | 视频生成参数偏好 |
| `difficulty` | `scene.difficulty` | 分镜难易程度 易/中/难（见 2.3.1.1），卡片 badge 展示 |
| `act_name` | `scene.actName` | 所属幕/分镜组名称（见 2.3.1.2），卡片标签展示 |
| `selected_first_frame_id` | `scene.selectedFirstFrameId` | 当前选中首帧 asset 指针 |
| `selected_last_frame_id` | `scene.selectedLastFrameId` | 当前选中尾帧 asset 指针 |
| `selected_video_id` | `scene.selectedVideoId` | 当前选中视频 asset 指针 |
| `first_frame_url / last_frame_url / video_url`（后端 `list_by_storyboard` LEFT JOIN 选中 asset 得出） | `scene.firstFrameUrl / lastFrameUrl / videoUrl` | 当前选中资产结果，用于画面预览 |
| `dialogues`（后端 `_attach_dialogues` 附加，见 `storyboard_dialogue`） | `scene.dialogues[]` | 对话列表，每行 `characterId / text / speed / volume / audioUrl` |
| `last_modified_user_id` | `scene.lastModifiedUserId` | 最后修改人 |

**任务状态**（不再冗余在 scene，由各自任务表得出，经 `GET /scene/{id}/task-status` 聚合返回）：
- 图片/视频状态：选中 asset 关联的 `ai_tools.status`（接口返回 `first_frame / last_frame / video` 各自的 `status / result_url / error`）
- 配音状态：各对话选中配音关联的 `ai_audio.status`（接口返回 `dialogues` 各自的 `status / audio_url / error`）

**缩略图/预览**：重构后 `storyboard_scene` 不再有 `thumbnail_url` / `preview_image_url` 字段；分镜画面直接取当前选中首帧的 `result_url`（后端 `list_by_storyboard` LEFT JOIN 提供），需要小图时由基础缩略图服务从该原图按需生成。

资产 `@` 提及统一读取 DB 风格接口 `/api/characters`、`/api/locations`、`/api/props`（三者统一为 `{code, message, data:{total,page,page_size,data:[...]}}` 信封），由 `adapters.normalizePagedList()` 收敛解析为 `data.data` 数组。

### 后端修正

- `create_storyboard` 不再访问不存在的 `World.style_reference_image` 字段，统一通过 `build_storyboard_defaults()` 安全继承。
- `script_id` 缺失时通过 `resolve_storyboard_script_id()` 兜底查找当前集剧本。
- 建表 SQL 按模型拆分保存：`storyboard` 主表在 `model/storyboard.py` 末尾的 `CREATE_TABLE_SQL`；`storyboard_scene` / `storyboard_dialogue` / `storyboard_dialogue_audio` / `storyboard_scene_asset` 分别在对应 `model/storyboard_*.py` 文件末尾；正式建表由 Alembic 迁移脚本负责；不向 `model/sql/baseline.sql` 或 `model/sql/baseline_with_db.sql` 写入新表结构。

> 基于 demo2 原型 + 项目实际架构修订，修正字段命名、接口地址、异步约束、幂等设计、任务状态模型等关键问题。

> **实施进度 (2026-06-22)**: Task 1-5 已实施完成，Task 6 待联调，Task 7 已同步。详见“第8节 实现任务拆解”。

## 1. 概述

### 1.1 功能定位

故事板是「智剧通」短剧制作流程中的核心编辑页面，为用户提供可视化的分镜编辑和管理能力。用户在 `script_writer.html`（剧本资产）完成剧本对话后，可以选择进入**画布模式**（现有 `video_workflow.html`）或**故事板模式**（新页面 `storyboard.html`）进行短剧制作。

### 1.2 用户流程

```
剧本资产（script_writer.html）
       │
       ▼
   完成剧本对话
       │
       ▼
  ┌────────────┐
  │ 模式选择弹窗 │
  └─────┬──────┘
        │
   ┌────┴────┐
   ▼         ▼
画布模式    故事板模式
(video_     (storyboard.
workflow.    html)
html)
```

### 1.3 参考原型

UI 参考 `demo2/` 目录的纯 JS 实现。demo2 是**静态原型**，所有数据均为前端常量（见 `demo2/js/data.js`），落地时需要：
- 将 demo2 中硬编码的场景/角色/模型/图片 URL 替换为后端 API 返回的真实数据
- 角色/场景/道具 → 从 DB 风格接口获取：`GET /api/characters?world_id=xxx`、`GET /api/locations?world_id=xxx`、`GET /api/props?world_id=xxx`（均在 `server.py` 中实现），映射到 @提及功能
  > 注：另有文件风格接口 `/api/characters-files`、`/api/locations-files`、`/api/props-files`（在 `api/script_writer.py` 中），用于读取角色卡/场景卡文件。故事板统一使用 **DB 风格接口**。
- 模型列表 → 从 `/api/text-to-image-models`、`/api/video-model`、`/api/models` 动态获取
- 分镜缩略图 → 使用用户生成的资产图片 URL，非 demo2 中的外链占位图
- 任务完成后 → 回写 `storyboard_scene` 表对应字段

### 1.4 技术栈决策

**明确使用原生模块化 JS，不引入 Vue/React。**

理由：
- demo2 原型是纯 JS，保持一致降低迁移成本
- 项目要求 CSS/JS 独立文件以降低 SSE token 消耗
- 避免与现有 `video_workflow.html`（原生 JS）风格割裂
- 项目 `script_writer.html` 仅在少量地方使用 Vue CDN，主体也是原生 JS

---

## 2. 实体关系与核心约束

### 2.0 数据关系模型

```
World (世界)
  ├── visual_style / era_environment / color_language / composition_preference
       │
       ├─→ Script (剧本) / Character (角色) / Location (场景) / Props (道具)  — 属于世界
       ├─→ VideoWorkflow (画布)  — default_world_id + style + style_reference_image
       │
       └─→ Storyboard (故事板)  — world_id + episode_number + style + style_reference_image
             │
             └─→ StoryboardScene (分镜)   video_type: 图片 / 视频 / 数字人（见 SceneVideoType）
                   │
                   ├─ prompt_json        画面提示词（生图: perspective/style/scene_desc/character_desc）
                   ├─ video_prompt       视频提示词（生视频/数字人的动作描述）
                   ├─ selected_first_frame_id / selected_last_frame_id / selected_video_id
                   │        └─→ 指向当前选中的 asset（用户在多个候选中选定）
                   │
                   ├─① 1对N → StoryboardSceneAsset (图片/视频候选与历史)
                   │              └─ ai_tool_id → ai_tools
                   │                  (首帧/尾帧=图片任务 type1/4/16/25/26；
                   │                   视频=图生视频 type2/3；数字人=type13/32)
                   │
                   └─② 1对N → StoryboardDialogue (对话/旁白，一个分镜多句)
                                   ├─ character_id → character（取 default_voice 作参考声音；NULL=旁白）
                                   ├─ text / speed(语速) / volume(音量)
                                   ├─ selected_audio_id → 当前选中配音
                                   │
                                   └─ 1对N → StoryboardDialogueAudio (配音生成历史)
                                                   └─ ai_audio_id → ai_audio
```

**关键约束**：
- **每个故事板只处理一集**：通过 `episode_number` 字段绑定具体集数
- **必须关联世界**：通过 `world_id` 获取角色/场景/道具资产
- **必须设置画风**：`style` + `style_reference_image`，首次创建时自动从世界继承（参考 `workflow.js:678-716`）
- **画幅比例**：`workflow_ratio`（16:9 横屏 / 9:16 竖屏），与世界配置同步

### 2.1 字段命名约定

**新表统一使用 `create_at` / `update_at`**，与近期迁移（`chat_messages`、`user_preferences`、`implementation_attempts`、`commission_withdraw` 等）及 AGENTS.MD 约定保持一致。

> 注：老表 `script`、`video_workflow` 使用 `create_time`/`update_time`，故事板作为新模块不沿用旧命名。

### 2.2 新增表：`storyboard`（故事板主表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT UNSIGNED AUTO_INCREMENT | 主键 |
| world_id | INT UNSIGNED | 关联世界 ID |
| user_id | INT UNSIGNED | 用户 ID |
| **episode_number** | **INT** | **集数（一集一个故事板）** |
| workflow_id | INT UNSIGNED | 关联工作流 ID（可选，用于一键转视频） |
| script_id | INT UNSIGNED | 关联剧本 ID |
| title | VARCHAR(255) | 故事板标题（如 "第1集：虚实之间"） |
| total_duration | DECIMAL(10,3) | 总时长（秒，毫秒级精度，由各分镜 duration 求和） |
| status | TINYINT | 状态：1=编辑中, 2=已完成 |
| **style** | **VARCHAR(255)** | **画风名称（参考 video_workflow.style）** |
| **style_reference_image** | **VARCHAR(500)** | **画风参考图 URL（参考 video_workflow.style_reference_image）** |
| **workflow_ratio** | **VARCHAR(10)** | **画幅比例：16:9 横屏 / 9:16 竖屏** |
| **composition_preference** | **VARCHAR(500)** | **构图倾向（来自 world.composition_preference，生成图片提示词时使用）** |
| config_json | JSON | 全局配置（分辨率、默认模型等前端 UI 状态） |
| create_at | DATETIME | 创建时间 |
| update_at | DATETIME | 更新时间 |

```sql
CREATE TABLE storyboard (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    world_id INT UNSIGNED NOT NULL COMMENT '关联世界ID',
    user_id INT UNSIGNED NOT NULL,
    episode_number INT NOT NULL DEFAULT 1 COMMENT '集数，一集一个故事板',
    workflow_id INT UNSIGNED DEFAULT NULL COMMENT '关联工作流ID（可选，一键转视频用）',
    script_id INT UNSIGNED DEFAULT NULL COMMENT '关联剧本ID',
    title VARCHAR(255) DEFAULT '' COMMENT '故事板标题',
    total_duration DECIMAL(10,3) DEFAULT 0.000 COMMENT '总时长（秒），由各分镜 duration 求和（毫秒级精度）',
    status TINYINT DEFAULT 1 COMMENT '1=编辑中 2=已完成',
    style VARCHAR(255) DEFAULT NULL COMMENT '画风名称（同 video_workflow.style）',
    style_reference_image VARCHAR(500) DEFAULT NULL COMMENT '画风参考图URL',
    workflow_ratio VARCHAR(10) DEFAULT NULL COMMENT '画幅比例: 16:9 | 9:16',
    composition_preference VARCHAR(500) DEFAULT NULL COMMENT '构图倾向，来自 world.composition_preference',
    config_json JSON DEFAULT NULL COMMENT '全局配置: 分辨率/默认模型/UI状态',
    create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_world_episode (user_id, world_id, episode_number),
    INDEX idx_world_user (world_id, user_id),
    INDEX idx_workflow (workflow_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**幂等设计**：`UNIQUE KEY uk_user_world_episode (user_id, world_id, episode_number)` 确保同一用户、同一世界、同一集数只能创建一个故事板。创建时先查后建（get-or-create）。

> **与 `video_workflow` 字段对照**：
> | 字段 | video_workflow | storyboard | 说明 |
> |------|---------------|-----------|------|
> | style | `style` VARCHAR(255) | `style` VARCHAR(255) | 画风名称 |
> | style_reference_image | `style_reference_image` VARCHAR(500) | `style_reference_image` VARCHAR(500) | 画风参考图 |
> | workflow_ratio | `workflow_ratio` VARCHAR(10) | `workflow_ratio` VARCHAR(10) | 画幅比例 |
> | 世界关联 | `default_world_id` INT | `world_id` INT | storyboard 直接命名 world_id |
> | 集数 | 无 | `episode_number` INT | storyboard 新增，一集一板 |

### 2.2.1 画风继承机制

参考 `web/js/workflow.js:678-716` 中画布模式的画风继承逻辑：

```
创建故事板时的画风继承链：

World.visual_style  ──继承──→  Storyboard.style
World.composition_preference  ──继承──→  Storyboard.composition_preference
World 对象通过 world_id 查询

后端创建逻辑（伪代码）:
1. 查询世界：world = await asyncio.to_thread(WorldModel.get_by_id, world_id)
2. 继承画风：style = world.visual_style if world else None
3. 继承构图：composition_preference = world.composition_preference if world else None
4. 在事务中原子创建 storyboard（含继承的画风）+ scenes
```

**用户可覆盖**：继承后，用户可在故事板内修改画风（同画布模式的画风选择器），修改后保存到 storyboard 表自身字段，不再跟随世界。

### 2.2.2 世界资产关联

故事板通过 `world_id` 获取以下资产（全部已有现成接口）：

| 资产类型 | Model | API 接口（server.py） | 用途 |
|---------|-------|---------|------|
| 角色 | `CharacterModel` | `GET /api/characters?world_id=xxx` | @提及角色、角色参考图 |
| 场景 | `LocationModel` | `GET /api/locations?world_id=xxx` | @提及场景、场景参考图 |
| 道具 | `PropsModel` | `GET /api/props?world_id=xxx` | @提及道具 |
| 剧本 | `ScriptModel` | `GET /api/scripts?world_id=xxx` | 自动拆分分镜的源数据 |

> 故事板统一使用 **DB 风格接口**（`/api/characters`、`/api/locations`、`/api/props`），不使用文件风格接口（`/api/characters-files` 等）。

### 2.3 新增表：`storyboard_scene`（分镜表）

> **2026-06-24 重构**：原 scene 表把音频/图片/视频/任务状态全部堆在一张表（24 字段），存在职责不清、无法 1对N、缺少视频提示词与分镜类型等问题。本次重构：
> - **删除音频字段**（`voiceover_text / voiceover_audio_url / voice_config_json / music_json / voice_task_id / voice_status / voice_error`）→ 台词与配音拆到 `storyboard_dialogue`（2.4）、配音历史入 `storyboard_dialogue_audio`（2.5）；`music_json` 一并删除（音乐属时间轴，本期不做）；
> - **删除图片/视频单值字段**（`thumbnail_url / preview_image_url / first_frame_url / last_frame_url / video_url / image_task_id / image_status / image_error / video_task_id / video_status / video_error`）→ 改由 `storyboard_scene_asset`（2.6）关联 `ai_tools` 实现 1对N，scene 只保留「当前选中」指针；缩略图不再存字段，由基础缩略图服务从所选首帧原图生成；
> - **新增** `video_prompt`（视频提示词）、`video_type`（分镜类型）、`selected_*_id`（选中指针）、`last_modified_user_id`（最后修改人）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT UNSIGNED AUTO_INCREMENT | 主键 |
| storyboard_id | INT UNSIGNED | 关联故事板 ID（FK CASCADE） |
| sort_order | DOUBLE | 排序序号（浮点二分，见 2.3.2） |
| title | VARCHAR(255) | 分镜标题，如"分镜1" |
| duration | INT | 时长（秒） |
| prompt_json | JSON | 画面提示词（生图）：perspective / style / scene_desc / character_desc |
| **video_prompt** | **TEXT** | **视频提示词（生视频/数字人的动作描述）** |
| **video_type** | **VARCHAR(32)** | **分镜类型，取 `SceneVideoType`：image / video / digital_human（见 2.3.1）** |
| video_config_json | JSON | 视频生成参数快照（生成时写入）：`task_id` / `duration_mode` / `duration_seconds` / `resolution` / `clip_to_audio_duration` / `audio_duration`；导出时若 `clip_to_audio_duration=true` 将视频裁到分镜配音时长 |
| **difficulty** | **VARCHAR(8)** | **分镜难易程度：易/中/难，见 `SceneDifficulty`（config/constant.py），由 LLM 综合人物数量/动作/时长/道具/镜头运动判定，默认"中"** |
| **act_name** | **VARCHAR(255)** | **所属幕/分镜组名称，源自 LLM `shot_group.group_name`（提升为独立列；`prompt_json.source.group_name` 仍保留作溯源）** |
| **selected_first_frame_id** | **INT UNSIGNED** | **当前选中首帧 → storyboard_scene_asset.id** |
| **selected_last_frame_id** | **INT UNSIGNED** | **当前选中尾帧 → storyboard_scene_asset.id** |
| **selected_video_id** | **INT UNSIGNED** | **当前选中视频 → storyboard_scene_asset.id** |
| **last_modified_user_id** | **INT UNSIGNED** | **最后修改人 user_id** |
| create_at | DATETIME | 创建时间 |
| update_at | DATETIME | 更新时间 |

> **选中指针说明**：一个分镜可生成多张首帧/尾帧、多段视频（1对N，见 `storyboard_scene_asset`）。用户在候选中选定的那个，由 `selected_first_frame_id / selected_last_frame_id / selected_video_id` 三个指针指向对应 asset 记录；指针为空表示该类型尚未生成或未选中。生成状态（生成中/成功/失败）不再冗余在 scene，统一由所选 asset 关联的 `ai_tools.status` 得出。

```sql
CREATE TABLE storyboard_scene (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    storyboard_id INT UNSIGNED NOT NULL,
    sort_order DOUBLE DEFAULT 0 COMMENT '排序序号（浮点二分，见 2.3.2）',
    title VARCHAR(255) DEFAULT '',
    duration DECIMAL(10,3) DEFAULT 5.000 COMMENT '分镜时长（秒），音频全部完成时自动同步为选中配音求和（毫秒级精度）',
    prompt_json JSON DEFAULT NULL COMMENT '画面提示词: perspective/style/scene_desc/character_desc',
    video_prompt TEXT DEFAULT NULL COMMENT '视频提示词（生视频/数字人动作描述）',
    video_type VARCHAR(32) NOT NULL DEFAULT 'video' COMMENT '分镜类型 image/video/digital_human，见 SceneVideoType',
    video_config_json JSON DEFAULT NULL COMMENT '视频生成参数偏好: 模型/分辨率/时长',
    difficulty VARCHAR(8) NOT NULL DEFAULT '中' COMMENT '分镜难易程度: 易/中/难，见 SceneDifficulty',
    act_name VARCHAR(255) DEFAULT NULL COMMENT '所属幕/分镜组名称（源自 LLM shot_group.group_name）',
    selected_first_frame_id INT UNSIGNED DEFAULT NULL COMMENT '当前选中首帧 asset id',
    selected_last_frame_id INT UNSIGNED DEFAULT NULL COMMENT '当前选中尾帧 asset id',
    selected_video_id INT UNSIGNED DEFAULT NULL COMMENT '当前选中视频 asset id',
    last_modified_user_id INT UNSIGNED DEFAULT NULL COMMENT '最后修改人',
    create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_storyboard (storyboard_id),
    INDEX idx_sort (storyboard_id, sort_order),
    INDEX idx_video_type (video_type),
    INDEX idx_selected_video (selected_video_id),
    FOREIGN KEY (storyboard_id) REFERENCES storyboard(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

> `selected_*_id` 不建外键约束（避免与 `storyboard_scene_asset.scene_id` 形成循环外键），由应用层保证一致性。

### 2.3.1 分镜类型枚举 `SceneVideoType`（config/unified_config.py）

分镜的呈现形式用独立枚举类维护，模仿 `TaskCategory`（`config/unified_config.py:29`）的 `_CONSTANT_GROUP` + `_LABELS` 写法：

```python
class SceneVideoType:
    """分镜视频类型（分镜的呈现形式）"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'IMAGE': '图片分镜',
        'VIDEO': '视频分镜',
        'DIGITAL_HUMAN': '数字人分镜',
    }
    IMAGE = 'image'                  # 静态图片分镜（仅首帧，不生成视频）
    VIDEO = 'video'                  # AI 视频分镜（首帧 → 图生视频）
    DIGITAL_HUMAN = 'digital_human'  # 数字人分镜（人物形象图 + 配音 → 数字人视频）
    ALL_TYPES = [IMAGE, VIDEO, DIGITAL_HUMAN]
```

各类型对应的生成任务（`TaskTypeId`）：

| video_type | 生成任务 | asset 记录 |
|------|------|------|
| `image` | 文生图/图片编辑（16/1/25/26） | 首帧 |
| `video` | 图生视频（3/10/12/14/15/21/22/23…） | 首帧 + 尾帧 + 视频 |
| `digital_human` | **仅 LTX2.3 数字人（32）** | 视频（对口型），输入=人物形象图 + **已生成的说话音频** |

> 对口型（`digital_human`）一期规则：拆分时仅 **单说话人** 对话分镜可标此类型，多人对话强制 `video`。生成必须先完成 TTS 配音，再提交 LTX2.3（不接 wan type=13）。详见 `docs/storyboard/storyboard_digital_human.md`。

### 模型配置弹窗

- 视频分辨率选择即时写入前端状态并刷新弹窗选中态，随后持久化到 `storyboard.config_json`；弹窗保持打开，便于继续设置时长和裁剪选项。
- 弹窗只保留右上角圆形关闭按钮，底部不再重复提供关闭操作。

### 2.3.1.1 分镜难易程度枚举 `SceneDifficulty`（config/constant.py）

分镜的难易程度用独立枚举类维护，由 LLM 在剧本解析时根据**人物数量、动作复杂度、时长、道具、镜头运动**综合判定。写法参照 `StoryType`（`config/constant.py`）的 `_CONSTANT_GROUP` + `_LABELS` + `normalize()` 范式：

```python
class SceneDifficulty:
    """分镜难易程度"""
    _CONSTANT_GROUP = True
    _LABELS = {'EASY': '易', 'MEDIUM': '中', 'HARD': '难'}
    EASY = "易"
    MEDIUM = "中"
    HARD = "难"
    VALID_VALUES = (EASY, MEDIUM, HARD)
    DEFAULT = MEDIUM

    @classmethod
    def normalize(cls, value) -> str:
        ...
```

判定标准（写入 `llm/script_parser.py` 的 system prompt，作为 LLM 输出 `difficulty` 字段的依据）：

| 难度 | 判定条件（综合权衡，取整体倾向） |
|------|------|
| 易 | 单人或无角色、静态/轻微动作、短镜头（≤5秒）、无关键道具或仅普通道具、固定镜头/简单构图 |
| 中 | 2-3 人有互动、有连续但常规的动作、中等时长（6-10秒）、1-2 个关键道具、简单镜头运动（推进/跟随） |
| 难 | 4 人以上群体调度、打斗/追逐/复杂连续动作、长镜头（>10秒）且动作密集、多个关键道具且强交互、复杂镜头运动/强透视/多层景深 |

数据流：
- LLM 在每个 shot 输出 `difficulty`（易/中/难）+ `difficulty_reason`（一句话依据）。
- `api/storyboard.py::build_storyboard_scenes_from_parsed_script` 用 `SceneDifficulty.normalize()` 规范化后写入 scene payload 的 `difficulty` 顶层键；`difficulty_reason` 进 `prompt_json.source` 供溯源。
- 前端 `adapters.js::sceneFromApi` 映射为 `scene.difficulty`，卡片渲染 `difficultyBadge`（易=绿/中=橙/难=红）。

### 2.3.1.2 幕字段 `act_name`

"幕"（act）在重构前并未真正持久化——`shot_group` 只有 `group_name`（如"开场镜头"/"第一幕：迷雾森林"）和 `group_type`，`prompt_json.source` 存的就是这两个。本次将 **`group_name` 提升为独立的 DB 列 `act_name`**，便于后续按幕筛选/排序/统计/批量生图策略。

- **数据流**：`build_storyboard_scenes_from_parsed_script` 从 `group.group_name` 提取 `act_name`，并用正则 `r"\s*-\s*片段\d+$"` 剥掉 `reorganize_shot_groups` 时长拆组产生的" - 片段N"后缀，避免污染。
- **兼容**：`prompt_json.source.group_name` 仍保留（下游 `_enrich_scene_location_props` 依赖 source 结构）；前端 `sceneFromApi` 在 `act_name` 为空时回落到 `source.group_name`。
- **旧数据**：不回填，`act_name` 保持 NULL（迁移 no_113 仅加列）。

### 2.3.2 排序策略：浮点二分（sort_order）

`storyboard_scene.sort_order` 与 `storyboard_dialogue.sort_order` 均采用**浮点二分**排序，解决「在两个分镜/对话中间新增」时必须重排其后所有记录的麻烦。

**字段类型：`DOUBLE`（双精度浮点）**，不用 `INT` / `FLOAT` / `DECIMAL`：

| 备选类型 | 问题 |
|---------|------|
| `INT` | 中间插入需重排其后所有记录，麻烦且并发不友好 |
| `FLOAT`（单精度，尾数 23 位） | 连续二分约 20 余次即触底，不够用 |
| `DECIMAL(n,m)` | 固定小数位，二分 m 次就到小数极限，更差 |
| **`DOUBLE`（尾数 52 位）** | **单处可连续二分约 52 次才触底，正常使用几乎不会触底** |

**排序规则**：

| 操作 | 计算 | 示例 |
|------|------|------|
| 首个 | `0` | 0 |
| 末尾追加 | `max(sort_order) + 1` | 1, 2, 3, … |
| 在 A、B 之间插入 | `(A.sort_order + B.sort_order) / 2` | 1 与 2 之间 → 1.5；再在 1 与 1.5 之间 → 1.25 |

**精度下限检测（关键）**：计算 `mid = (left + right) / 2` 后，若 `mid == left` 或 `mid == right`（IEEE-754 舍入导致无法区分相邻值），判定该处精度耗尽，**禁止中间插入**。处理流程：

1. 拒绝本次插入，返回「排序精度耗尽」；
2. 后端自动对该序列**重排（rebalance）**：按当前顺序重新均匀分配 `0, 1, 2, 3, …`，间距恢复为 1；
3. 重排后重新计算插入位置并完成插入（对用户无感）。

> **前端拖拽排序协议**：前端不直接传 sort_order 数值，而是传「目标位置的前后分镜/对话 id」（拖到最前/最后只传一侧），后端据此取左右 sort_order 计算中值，并统一做下限检测与重排。这样避免前端猜测数值，也保证并发安全——`batch_reorder` 不再是「批量写入指定值」，而是「相对位置插入 + 必要时重排」。

### 2.4 新增表：`storyboard_dialogue`（分镜对话表）

把原 scene 的配音台词拆成「一个分镜多句对话」，每句对话绑定说话角色（取其参考声音）、语速、音量。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT UNSIGNED AUTO_INCREMENT | 主键 |
| scene_id | INT UNSIGNED | 关联分镜 ID（FK CASCADE） |
| sort_order | DOUBLE | 对话顺序（浮点二分，同 2.3.2） |
| character_id | INT UNSIGNED NULL | → `character.id`；**NULL = 旁白/画外音** |
| text | TEXT | 台词 |
| speed | DECIMAL(4,2) | 语速，默认 1.00 |
| volume | INT | 音量 0-100，默认 100 |
| selected_audio_id | INT UNSIGNED NULL | 当前选中配音 → `storyboard_dialogue_audio.id`（见 2.5） |
| last_modified_user_id | INT UNSIGNED | 最后修改人 |
| create_at | DATETIME | 创建时间 |
| update_at | DATETIME | 更新时间 |

> **参考声音来源**：`character_id` 关联 `character` 表，配音时取 `character.default_voice` 作为参考音频（`ai_audio.ref_path`）。旁白行 `character_id` 为空，使用系统默认音色。

```sql
CREATE TABLE storyboard_dialogue (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    scene_id INT UNSIGNED NOT NULL,
    sort_order DOUBLE DEFAULT 0 COMMENT '对话顺序（浮点二分，同 2.3.2）',
    character_id INT UNSIGNED DEFAULT NULL COMMENT '说话角色; NULL=旁白',
    text TEXT DEFAULT NULL COMMENT '台词',
    speed DECIMAL(4,2) NOT NULL DEFAULT 1.00 COMMENT '语速',
    volume INT NOT NULL DEFAULT 100 COMMENT '音量 0-100',
    selected_audio_id INT UNSIGNED DEFAULT NULL COMMENT '当前选中配音 → storyboard_dialogue_audio.id',
    last_modified_user_id INT UNSIGNED DEFAULT NULL COMMENT '最后修改人',
    create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_scene (scene_id, sort_order),
    INDEX idx_character (character_id),
    FOREIGN KEY (scene_id) REFERENCES storyboard_scene(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 2.5 新增表：`storyboard_dialogue_audio`（配音生成历史）

一句对话可重新生成多次配音，每次生成对应一条 `ai_audio` 任务；本表记录归属与历史，`storyboard_dialogue.selected_audio_id` 指向当前选中的那条。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT UNSIGNED AUTO_INCREMENT | 主键 |
| dialogue_id | INT UNSIGNED | 关联对话 ID（FK CASCADE） |
| ai_audio_id | INT（有符号） | → `ai_audio.id`（**源表为 `int`，不加外键**） |
| audio_url | VARCHAR(512) | 冗余结果 URL（便于列表展示，避免 join `ai_audio`） |
| create_at | DATETIME | 生成时间 |

```sql
CREATE TABLE storyboard_dialogue_audio (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    dialogue_id INT UNSIGNED NOT NULL,
    ai_audio_id INT DEFAULT NULL COMMENT '→ ai_audio.id（源表 int，不加外键）',
    audio_url VARCHAR(512) DEFAULT NULL COMMENT '配音结果 URL（冗余）',
    create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_dialogue (dialogue_id),
    INDEX idx_ai_audio (ai_audio_id),
    FOREIGN KEY (dialogue_id) REFERENCES storyboard_dialogue(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 2.6 新增表：`storyboard_scene_asset`（分镜图片/视频资产）

一个分镜可生成多张首帧/尾帧、多段视频（1对N）；每次生成对应一条 `ai_tools` 任务，本表记录归属、类型与结果，scene 的 `selected_*_id` 指针指向当前选中的记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT UNSIGNED AUTO_INCREMENT | 主键 |
| scene_id | INT UNSIGNED | 关联分镜 ID（FK CASCADE） |
| ai_tool_id | INT（有符号） | → `ai_tools.id`（**源表为 `int`，不加外键**） |
| asset_type | VARCHAR(32) | `first_frame` / `last_frame` / `video` |
| result_url | VARCHAR(512) | 冗余结果 URL（图片或视频，便于列表展示） |
| create_at | DATETIME | 生成时间 |

> `asset_type` 说明：`first_frame`/`last_frame` 为图片候选（`ai_tools.type` 1/4/16/25/26），`video` 为视频候选（图生视频 type 2/3，或数字人 type 13/32）。生成状态由 `ai_tools.status` 得出，本表不冗余状态字段。

```sql
CREATE TABLE storyboard_scene_asset (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    scene_id INT UNSIGNED NOT NULL,
    ai_tool_id INT DEFAULT NULL COMMENT '→ ai_tools.id（源表 int，不加外键）',
    asset_type VARCHAR(32) NOT NULL COMMENT 'first_frame / last_frame / video',
    result_url VARCHAR(512) DEFAULT NULL COMMENT '结果 URL（图片或视频，冗余）',
    create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_scene (scene_id, asset_type),
    INDEX idx_ai_tool (ai_tool_id),
    FOREIGN KEY (scene_id) REFERENCES storyboard_scene(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 2.7 字段类型与外键约定

- **关联 `ai_tools` / `ai_audio` 的字段用 `INT`（有符号）**：`ai_tools.id`、`ai_audio.id` 在源表均为 `int`（非 unsigned，见 `model/ai_tools.py` / `model/ai_audio.py` 的 CREATE_TABLE_SQL），故 `storyboard_scene_asset.ai_tool_id`、`storyboard_dialogue_audio.ai_audio_id` 必须用 `INT` 且**不加外键约束**，否则 MySQL 报外键类型不一致。
- **关联本项目 `int unsigned` 主键的字段用 `INT UNSIGNED`**：`character.id`、`storyboard_scene.id` 等为 unsigned。
- **`selected_*_id` 指针不建外键**：避免与 `storyboard_scene_asset.scene_id` 形成循环外键，由应用层保证一致性。
- **缩略图不落库**：分镜缩略图由基础缩略图服务从所选首帧原图按需生成，`storyboard_scene` 不再保留 `thumbnail_url` / `preview_image_url` 字段。

---

## 3.0 2026-07 更新：画风设置与模型选择 UI

- 新增左侧“画风设置”卡片，支持直接编辑全局 `style`（画风）和 `composition_preference`（构图倾向），blur/Enter 自动持久化。
- 后端 `/api/storyboard/models` 返回结构扩展为 4 类（text_to_image_models、image_edit_models、text_to_video_models、image_to_video_models），旧字段保留兼容。
- 左下角分镜助手第一版**仅展示已支持类型**：
  - 图片生成 → 文生图模型
  - 视频生成 → 图生视频模型
- 对话模型（LLM）选择器已加入（参考 script_writer，使用专用 localStorage key + persistUiConfig 写入 config_json + 启动 fallback），明确标注“功能开发中”。
- 所有新状态纳入 config_json 保证重新加载复原（已修复 persist + localStorage 恢复逻辑）。
- 详见独立设计文档：`docs/storyboard/storyboard_ui_style_and_models.md`

---

## 3.1 2026-07 更新：分镜间插入

- 时间轴 `.scene-timeline-list` 在每两个分镜之间提供 hover/focus 插入槽，点击后在相邻分镜之间创建新分镜。
- 网格 `.storyboard-grid` 使用卡片右侧浮层插入按钮表达“在此分镜后添加”，避免独立 grid item 打乱总览排版。
- 前端通过 `prev_id` / `next_id` 调用 `POST /api/storyboard/{storyboard_id}/scene`，后端按浮点二分计算 `sort_order`，刷新后顺序稳定。
- 详见独立设计文档：`docs/storyboard/storyboard_insert_scene_slots.md`

---

## 3. 后端 API 设计

### 3.0 异步约束规范（P1 关键）

**项目数据库封装是同步 pymysql**（见 `model/database.py`），所有 DB 操作都是同步阻塞调用。在 FastAPI 异步路由中**必须**使用 `asyncio.to_thread()` 包装，否则会阻塞事件循环。

```python
# ✅ 正确写法 — 已有模式参考（api/script_writer.py）
entity = await asyncio.to_thread(ScriptModel.get_by_id, script_id)

# ❌ 错误写法 — 会阻塞整个事件循环
entity = ScriptModel.get_by_id(script_id)  # 同步调用，禁止！
```

**完整规则**：

| 调用类型 | 约束 | 示例 |
|---------|------|------|
| Model DB 操作 | `await asyncio.to_thread(Model.method, args)` | `await asyncio.to_thread(StoryboardModel.get_by_id, id)` |
| 文件 IO | `await asyncio.to_thread(read_file/write_file)` | 读取/写入本地文件 |
| requests 库 | **禁止使用**，改用 `httpx.AsyncClient` 或 `aiohttp` | 调用第三方 API |
| 项目内同步驱动 | `await asyncio.to_thread(driver.call, args)` | 视频驱动、音频驱动 |
| LLM 调用 | 已有异步封装，直接 `await` | `await llm_client.chat(...)` |

**文件 IO 示例**：
```python
import aiofiles

# 方式一：aiofiles（推荐）
async def read_file_async(path: str) -> str:
    async with aiofiles.open(path, mode='r', encoding='utf-8') as f:
        return await f.read()

# 方式二：同步 helper + asyncio.to_thread
def read_file_sync(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

content = await asyncio.to_thread(read_file_sync, path)

# ❌ 错误写法 — open() 在事件循环里执行，且文件没有显式关闭
# content = await asyncio.to_thread(open(path, 'r', encoding='utf-8').read)
```

### 3.1 路由前缀与权限（二期/暂缓）

路由使用 `APIRouter(prefix="/api/storyboard", tags=["storyboard"])`，在 `server.py` 中注册。
`@require_permission("storyboard:xxx")` 权限装饰器 —— **本期暂不启用**，`require_permission` 装饰器当前为空实现（见 `perseids_server/utils/permission.py:54-61`），保留接口签名以便二期接入。

### 3.1.1 认证与身份校验

每个接口都需要通过 Header 获取用户身份，参考 `server.py` 中 `_get_user_id_from_header` 和 `api/script_writer.py` 中 `verify_auth_token` 的模式：

```python
from fastapi import Header
from config.constant import Edition, Action

@router.get('/{storyboard_id}')
@require_permission("storyboard:view")
async def get_storyboard(
    request: Request,
    storyboard_id: int,
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
    auth_token: Optional[str] = Header(None, alias="Authorization")
):
    user_id = _get_user_id_from_header(user_id)         # 校验 user_id 必填且为合法整数
    # is_valid, err = await verify_auth_token(user_id, auth_token)  # 按需验证 token
    # if not is_valid: return JSONResponse(err, status_code=401)
    ...
```

**Header 规范**：

| Header | 必填 | 说明 |
|--------|------|------|
| `X-User-Id` | 是 | 用户 ID，所有接口必须传入并校验 |
| `Authorization` | 按需 | 创建会话/敏感操作时校验 auth_token |

### 3.1.2 空间隔离与资源归属校验（防越权）

参考 `server.py` 中 `_check_resource_permission` / `_ensure_resource_access` / `_ensure_world_access` 的实现模式：

**核心原则**：
- **商业版（`Edition.is_space_isolated() == True`）**：用户只能访问自己创建的资源（`resource.user_id == user_id`），查询列表时自动按 `user_id` 过滤
- **开源版（`Edition.is_space_isolated() == False`）**：所有用户共享资源，查询列表不过滤 `user_id`，但**删除操作仍限制为创建者**

**A. 单资源访问校验（GET/PUT/DELETE 单个故事板或分镜）**：

```python
# 从公共模块导入（避免从 server.py 反向导入导致循环依赖）
# 实施时需将 server.py 中的 _get_user_id_from_header / _ensure_resource_access /
# _ensure_world_access / _check_resource_permission 抽取到 utils/resource_access.py
from utils.resource_access import _get_user_id_from_header, _ensure_resource_access, _ensure_world_access

@router.get('/{storyboard_id}')
async def get_storyboard(request, storyboard_id, user_id=Header(None, alias="X-User-Id")):
    user_id = _get_user_id_from_header(user_id)
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
    if not sb:
        return JSONResponse(status_code=404, content={'error': '故事板不存在'})
    
    # 空间隔离校验：商业版检查 user_id 归属，开源版放行（删除除外）
    _ensure_resource_access(sb, user_id, Action.VIEW, "故事板")
    ...
```

**B. 列表查询隔离（GET /list）**：

```python
# Model 层查询方法中（与 video_workflow.py:165-168 一致）
where_conditions = []
params = []

# 独立空间模式才按 user_id 过滤
if Edition.is_space_isolated():
    where_conditions.append("user_id = %s")
    params.append(user_id)
```

**C. 世界归属校验（创建故事板时）**：

```python
@router.post('/create')
async def create_storyboard(request, user_id=Header(None, alias="X-User-Id")):
    user_id = _get_user_id_from_header(user_id)
    world_id = data['world_id']
    
    # 校验世界存在且用户有权访问
    _ensure_world_access(world_id, user_id, Action.VIEW)  # server.py 已有
    ...
```

**D. 分镜操作的归属校验**：

```python
@router.delete('/scene/{scene_id}')
async def delete_scene(request, scene_id, user_id=Header(None, alias="X-User-Id")):
    user_id = _get_user_id_from_header(user_id)
    scene = await asyncio.to_thread(StoryboardSceneModel.get_by_id, scene_id)
    if not scene:
        return JSONResponse(status_code=404, content={'error': '分镜不存在'})
    
    # 先查所属故事板，再校验归属
    sb = await asyncio.to_thread(StoryboardModel.get_by_id, scene.storyboard_id)
    _ensure_resource_access(sb, user_id, Action.EDIT, "故事板")
    ...
```

**各接口的校验要求汇总**：

| 接口 | X-User-Id | 空间隔离 | 资源归属 | 世界校验 |
|------|-----------|---------|---------|----------|
| POST /create | 必填 | — | — | `_ensure_world_access(world_id, user_id)` |
| GET /{id} | 必填 | `_ensure_resource_access(sb, user_id, VIEW)` | 自动 | — |
| PUT /{id} | 必填 | `_ensure_resource_access(sb, user_id, EDIT)` | 自动 | — |
| DELETE /{id} | 必填 | `_ensure_resource_access(sb, user_id, DELETE)` | 仅创建者 | — |
| GET /list | 必填 | Model 层 `Edition.is_space_isolated()` 过滤 | 自动 | — |
| POST /scene (增/改/删) | 必填 | 通过所属 storyboard 校验 | 自动 | — |
| POST /generate-* | 必填 | 通过所属 storyboard 校验 | 自动 | — |
| GET /task-status | 必填 | 通过所属 storyboard 校验 | 自动 | — |
| POST /export-* | 必填 | `_ensure_resource_access(sb, user_id, VIEW)` | 自动 | — |

### 3.2 故事板 CRUD

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/storyboard/create` | `storyboard:create` | 创建故事板（幂等，get-or-create） |
| GET | `/api/storyboard/{id}` | `storyboard:view` | 获取故事板详情及所有分镜 |
| PUT | `/api/storyboard/{id}` | `storyboard:update` | 更新故事板信息 |
| DELETE | `/api/storyboard/{id}` | `storyboard:delete` | 删除故事板及所有分镜 |
| GET | `/api/storyboard/list` | `storyboard:list` | 获取用户故事板列表 |

### 3.3 幂等创建逻辑（P1 关键）

```python
@router.post('/create')
@require_permission("storyboard:create")
async def create_storyboard(request: Request):
    """
    幂等创建故事板：
    1. 先按 user_id + world_id + episode_number 查询是否已存在
    2. 已存在 → 返回现有记录（不重复创建）
    3. 不存在 → 在事务中原子创建 storyboard + scenes
    """
    data = await request.json()
    user_id = data['user_id']
    world_id = data['world_id']
    episode_number = data.get('episode_number', 1)
    script_id = data.get('script_id')
    
    # Get-or-Create: 按 user_id + world_id + episode_number 查询
    existing = await asyncio.to_thread(
        StoryboardModel.get_by_user_world_episode,
        user_id, world_id, episode_number
    )
    if existing:
        scenes = await asyncio.to_thread(
            StoryboardSceneModel.list_by_storyboard, existing.id
        )
        return JSONResponse({'success': True, 'storyboard': existing.to_dict(), 'scenes': scenes})
    
    # 不存在 → 事务创建（注意：必须是同步函数，asyncio.to_thread 会把同步函数放进线程执行）
    def _create():
        with transaction() as conn:
            sb_id = execute_insert_in_transaction(conn, insert_storyboard_sql, params)
            for i, scene_data in enumerate(auto_split_scenes):
                execute_insert_in_transaction(conn, insert_scene_sql, (sb_id, i, ...))
            return sb_id
    
    sb_id = await asyncio.to_thread(_create)
    # ...
```

### 3.4 分镜 CRUD

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/storyboard/{id}/scene` | `storyboard:update` | 新增分镜（默认追加末尾；可传 `prev_id`/`next_id` 指定位置） |
| PUT | `/api/storyboard/scene/{scene_id}` | `storyboard:update` | 更新分镜内容（title/duration/prompt_json/video_prompt/video_type/video_config_json；选中指针由 asset/select 维护） |
| PUT | `/api/storyboard/scene/{scene_id}/video-type` | `storyboard:update` | 在普通视频/对口型之间切换；保留已有候选，运行中的旧模式任务完成后不自动替换当前视频 |
| DELETE | `/api/storyboard/scene/{scene_id}` | `storyboard:update` | 删除分镜（CASCADE 删除其对话与资产） |
| PUT | `/api/storyboard/{id}/scene/reorder` | `storyboard:update` | 移动单个分镜（浮点二分，Body: `{scene_id, prev_id, next_id}`） |
| POST | `/api/storyboard/scene/{scene_id}/duplicate` | `storyboard:update` | 复制分镜（含对话，不含生成资产） |

### 3.5 分镜内容操作（生成 / 提示词 / 状态）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/storyboard/scene/{scene_id}/generate-image` | `storyboard:generate` | 生成首帧/尾帧：预扣算力→`ai_tools`(文生图)+`TasksModel`→`scene_asset`+设选中。Body: `asset_type/task_type/prompt/ratio/image_size` |
| POST | `/api/storyboard/scene/{scene_id}/generate-video` | `storyboard:generate` | 生成视频/数字人（按 `video_type`）：需已选中首帧；数字人需 `audio_path`。Body: `task_type/prompt/duration/audio_path` |
| POST | `/api/storyboard/scene/{scene_id}/ai-chat` | `storyboard:generate` | AI 对话改图（SSE 流，占位） |
| PUT | `/api/storyboard/scene/{scene_id}/prompt` | `storyboard:update` | 更新画面提示词 `prompt_json` |
| GET | `/api/storyboard/scene/{scene_id}/task-status` | `storyboard:view` | 轮询任务状态：返回选中 asset 的 `first_frame/last_frame/video`（来自 `ai_tools.status/result_url`）+ `dialogues`（来自 `ai_audio.status`）+ `scene_duration`（当前分镜时长浮点秒；分镜下所有配音完成后由后端自动同步为音频求和） |

> 生成任务由后台 scheduler 异步处理（图片/视频/数字人走 `TASK_TYPE_GENERATE_VIDEO`，配音走 `TASK_TYPE_GENERATE_AUDIO`），完成后回填 `ai_tools.result_url`/`ai_audio.result_url`；前端轮询 `task-status` 取结果并刷新画面。算力在接口预扣（`async_make_perseids_request` deduct），任务失败由 scheduler 按 `transaction_id` 退还。

### 3.5.1 对话 CRUD（storyboard_dialogue）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/storyboard/scene/{scene_id}/dialogues` | `storyboard:view` | 列出分镜对话（按 sort_order） |
| POST | `/api/storyboard/scene/{scene_id}/dialogue` | `storyboard:update` | 新增对话（Body: `character_id/text/speed/volume`，可选 `prev_id/next_id`） |
| PUT | `/api/storyboard/dialogue/{dialogue_id}` | `storyboard:update` | 更新对话（角色/台词/语速/音量） |
| DELETE | `/api/storyboard/dialogue/{dialogue_id}` | `storyboard:update` | 删除对话（CASCADE 删除配音历史） |
| PUT | `/api/storyboard/scene/{scene_id}/dialogue/reorder` | `storyboard:update` | 移动单个对话（浮点二分，Body: `{dialogue_id, prev_id, next_id}`） |
| POST | `/api/storyboard/dialogue/{dialogue_id}/generate-voiceover` | `storyboard:generate` | 生成配音：取 `character.default_voice` 作参考音频→`ai_audio`+`TasksModel`→`dialogue_audio`+设选中。**不消耗算力** |
| POST | `/api/storyboard/dialogue/{dialogue_id}/audio/select` | `storyboard:update` | 设置对话当前选中配音（Body: `{dialogue_audio_id}`） |

### 3.5.2 资产与选中（storyboard_scene_asset）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/storyboard/scene/{scene_id}/assets?asset_type=` | `storyboard:view` | 列出分镜图片/视频候选（可选类型过滤）+ 当前选中指针 |
| POST | `/api/storyboard/scene/{scene_id}/asset/select` | `storyboard:update` | 设置某类型当前选中资产（Body: `{asset_type, asset_id}`），更新 scene 的 `selected_*_id` |

### 3.6 导出操作

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/storyboard/{id}/export-full-video` | `storyboard:export` | 导出完整视频 |
| POST | `/api/storyboard/{id}/export-all-scenes` | `storyboard:export` | 导出全部分镜 |

### 3.7 可复用的现有模型接口

| 接口 | 路径（含 router prefix） | 来源 | 用途 |
|------|--------------------------|------|------|
| 生图模型列表 | `GET /api/text-to-image-models` | `api/script_writer.py:1626` | 图片生成模式选择模型 |
| 设置生图模型 | `POST /api/text-to-image-model` | `api/script_writer.py:1653` | 保存模型选择 |
| 获取当前生图模型 | `GET /api/text-to-image-model` | `api/script_writer.py:1751` | 加载已选模型 |
| 视频模型列表 | `GET /api/video-model` | `api/script_writer.py:1776` | 视频生成模式选择模型 |
| 设置视频模型 | `POST /api/video-model` | `api/script_writer.py:1829` | 保存视频模型选择 |
| LLM 模型列表 | `GET /api/models` | `api/script_writer.py:2051` | 对话改图模式选择模型 |
| LLM 供应商列表 | `GET /api/vendors` | `api/script_writer.py:~2040` | 按供应商分组显示 |

> 注意：`api/script_writer.py` 的 router prefix 是 `/api`（见第63行），所以实际路径是 `/api/text-to-image-models`，而非 `/api/vendor-models`。

> **故事板模型选择**：故事板不直接用上述接口，而是用统一的 `GET /api/storyboard/models` 一次返回 `image_models / video_models / digital_human_models`（含数字人——`/api/video-model` 仅支持 text_to_video/image_to_video，不含 digital_human）。前端 AI 助手按模式（图片 / 图生视频 / 数字人）渲染模型 `<select>`，选中 `task_id` 作为生成接口的 `task_type` 覆盖默认模型。

### 3.8 剧本自动拆分分镜

```python
async def auto_split_script_to_scenes(
    script_content: str,
    characters: list,
    locations: list
) -> list:
    """
    调用 LLM 将剧本内容自动拆分为分镜列表。

    返回格式（重构后：台词拆为 dialogues，prompt 用 character_desc）：
    [
        {
            "title": "分镜1",
            "duration": 5,
            "video_type": "video",
            "prompt": {
                "perspective": "中景侧拍视角",
                "style": "写实",
                "scene_desc": "[场景名]环境描述...",
                "character_desc": "[角色名](外观)动作描述..."
            },
            "video_prompt": "镜头缓慢推进...",
            "dialogues": [
                {"character_id": 1, "text": "角色台词", "speed": 1.0, "volume": 100},
                {"character_id": null, "text": "旁白", "speed": 1.0, "volume": 100}
            ]
        },
        ...
    ]
    """
    llm_client = await get_llm_client()
    # ... 构建 prompt，调用 LLM，解析 JSON 响应；由 create_with_scenes 写入 scene + dialogues
```

---

## 4. 前端页面设计

### 4.1 文件结构

```
web/
├── storyboard.html              # 故事板页面入口
├── css/
│   └── storyboard.css           # 故事板样式（独立文件，降低 token 消耗）
├── js/
│   └── storyboard/
│       ├── state.js             # 状态管理 + serialize/restore
│       ├── render.js            # 渲染函数
│       ├── api.js               # API 调用层（全部异步 fetch，统一携带 X-User-Id Header）
│       ├── events.js            # 事件绑定
│       ├── icons.js             # SVG 图标（复用 demo2 图标集）
│       └── utils.js             # 工具函数
├── i18n/
│   └── locales/
│       ├── zh-CN/
│       │   └── storyboard.json  # 故事板中文语言包
│       └── en/
│           └── storyboard.json  # 故事板英文语言包
```

### 4.2 URL 路由

```
/storyboard?id={storyboard_id}                                        # 打开已有故事板
/storyboard?world_id={world_id}&episode_number={n}&script_id={sid}    # 从剧本资产创建/打开
/storyboard?world_id={world_id}&episode_number={n}&workflow_id={wid}  # 关联工作流
```

> `episode_number` 从当前编辑的剧本中获取（`script.episode_number`），如果没有剧本则默认为 1。

在 `server.py` 中添加路由：
```python
@app.get("/storyboard")
async def serve_storyboard():
    file_path = os.path.join(static_dir, "storyboard.html")
    if os.path.isfile(file_path):
        content = _get_processed_html(file_path)
        return Response(content=content, media_type="text/html")
    raise HTTPException(status_code=404, detail="Storyboard page not found")
```

### 4.3 i18n 初始化

参考 `script_writer.html` 的 i18n 初始化模式：
```javascript
// storyboard.html 中
await ZJTi18n.init(['common', 'storyboard']);
```

语言包文件 `web/i18n/locales/zh-CN/storyboard.json`：
```json
{
    "storyboard_title": "故事板编辑器",
    "tab_scene": "画面",
    "tab_voiceover": "配音",
    "tab_music": "音乐",
    "btn_edit_prompt": "编辑提示词",
    "btn_generate_image": "生成图片",
    "btn_generate_video": "生成视频",
    "btn_export_video": "导出视频",
    "chat_mode_dialogue": "对话改图",
    "chat_mode_image": "图片生成",
    "chat_mode_video": "视频生成",
    "msg_auto_splitting": "正在智能拆分分镜...",
    "label_perspective": "视角",
    "label_style": "风格",
    "label_scene_desc": "场景描述",
    "label_char_desc": "角色描述",
    ...
}
```

### 4.4 页面布局（三栏 + 底部时间线）

```
┌──────────────────────────────────────────────────────────────────────┐
│  Header：Logo | 标题 | [剧本策划] [画布] [编辑器●] | 一键转视频 | 导出  │
├──────────────┬───────────────────────────────────────────────────────┤
│              │                                                       │
│  Left        │  Center Content                                       │
│  Sidebar     │                                                       │
│              │  ┌─────────────────────────────────────────┐          │
│  [画面][配音] │  │  普通视图：单分镜预览 + 右侧首帧选择      │          │
│  [音乐]      │  │  故事板视图：3列网格卡片总览              │          │
│              │  │                                         │          │
│  编辑面板     │  │                                         │          │
│  内容...     │  │                                         │          │
│              │  └─────────────────────────────────────────┘          │
│  ──────────  │                                                       │
│  AI 智能助手  │                                                       │
│  对话改图     │                                                       │
│  图片生成     │                                                       │
│  视频生成     │                                                       │
├──────────────┴───────────────────────────────────────────────────────┤
│  Timeline：进度条 | ▶播放 | 字幕开关 | 分镜序列缩略图 | [网格切换]    │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.5 核心组件

#### 4.5.1 Header（顶部导航）

- **Logo + 标题**：显示当前集数标题，如 "第1集：虚实之间·流离中的微光"
- **导航 Tab**：剧本策划（跳回 script_writer） | 画布（跳 video_workflow） | 编辑器（当前页面，高亮）
- **操作按钮**：一键转视频 | 导出
- **算力显示**：⚡ 余额（`GET /api/user/computing_power`）；按余额着色（不足 100 红 / 不足 1000 橙 / 否则绿）。**点击**打开算力日志弹窗（iframe `/computing_power_logs.html`）；日志弹窗内提供 **算力充值** 入口（`GET /api/recharge/packages` + `POST /api/recharge/wechat-pay` 微信扫码；本地环境 `is_local` 禁用并提示走后台加算力）

#### 4.5.2 Left Sidebar（左侧编辑面板）

**顶部品牌区**：显示当前分镜的幕号与分镜编号。幕号标签（如「幕01」）来自剧本解析时的 `group_id`（`grp_001` → 幕01，提取数字部分并补零），存放在 `prompt_json.source.group_id`，由 `adapters.js` 的 `sceneFromApi` 提取为 `scene.groupId` 顶层字段；手动新增的分镜无 `group_id`，不显示幕号。

**Tab 切换（音乐 Tab 已移除——音乐属时间轴功能，本期后置）：**

| Tab | 内容 |
|-----|------|
| 🖼 画面 | 画面提示词卡片（perspective/style/scene_desc/character_desc）+ 编辑按钮 + 视频提示词编辑 + 当前选中首帧预览 |
| 🎤 对话 | 对话列表：每行「角色下拉（取自 `state.characters`，空=旁白）+ 台词 + 语速/音量 + 试听 + 生成配音/保存/删除」；一个分镜多句对话 |

**底部 AI 智能助手区域**（模型列表统一从 `GET /api/storyboard/models` 获取，按模式渲染 `<select>`，选中 `task_id` 作为 `task_type`）：
- 对话改图模式：文本输入（LLM 模型待接入）。**不显示 AI 优化标识**。
- 图片生成 / 视频生成模式：文本输入 + @提及角色/场景 + **魔法棒（wand）图标的 AI 优化开关**（仅此两模式出现；点击后使用大模型优化提示词） + 对应模型选择。
- 视频生成模式额外：按 `scene.video_type` 显示图生视频 / 数字人模型选择 + `video_prompt`（`task_type` 传入 `generate-video`；数字人音频取自当前说话角色配音、形象取角色 `reference_image`）

**生成状态来自任务表（不再冗余在 scene）**：图片/视频状态来自选中 asset 关联的 `ai_tools.status`，配音来自对话选中配音关联的 `ai_audio.status`，经 `task-status` 轮询填充 `scene.taskStatus`：
- 0/1（待处理/处理中）：蓝色旋转
- 2（完成）：绿色勾 + 结果预览（画面取 `firstFrameUrl/videoUrl`）
- -1（失败）：红色叉 + 错误信息（来自 `ai_tools.message`/`ai_audio.message`）

#### 4.5.3 Center Content（中央内容区）

**普通视图（默认）：**
- 大型视频/图片预览框（16:9 比例）
- 右侧浮动缩略图栏（首帧选择）

**故事板视图（网格切换）：**
- 自适应列卡片网格（`minmax(240px, 1fr)`）
- 每张卡片包含：
  - **缩略图叠加**：分镜类型徽章（视频/对口型/图片）、时长、幕号（`groupId`→幕01）
  - **标题行**：分镜标题 + 难度（易/中/难）
  - **状态行**：图/视频生成状态 + 配音进度（有对白时「配 a/b」）
  - **场景行**：场景头像 chip；未绑定时灰字「未选场景」
  - **角色行**：最多 3 头像叠放 + 名称/ +N（来源：对话角色 → 参考选择 → 提示词 `【【角色】】`）
  - **景别**：`prompt_json.perspective` 单行截断（空则不占位）
  - 复制/删除操作
- 底部 "添加分镜" 虚线卡片

#### 4.5.4 Timeline Controls（底部时间线）

- 进度条滑块
- 字幕开关
- 播放/暂停按钮 + 时间显示
- 网格/列表视图切换按钮
- 分镜序列缩略图横向滚动列表（含复制/删除悬浮操作）
- 添加分镜按钮

### 4.6 状态管理（state.js）

```javascript
const state = {
    // 基础信息
    storyboardId: null,
    worldId: null,
    episodeNumber: 1,             // 当前集数
    scriptId: null,
    workflowId: null,
    userId: null,
    authToken: null,
    title: '',

    // 画风配置（从世界继承，用户可覆盖）
    style: '',
    workflowRatio: '16:9',        // 画幅比例
    compositionPreference: '',
    computingPower: null,

    // 视图状态
    scenes: [],                   // 分镜列表（scene 对象结构见下）
    currentSceneId: null,
    activeTab: 'scene',           // 'scene' | 'dialogue'（音乐 Tab 已移除）
    viewMode: 'timeline',         // 'timeline' | 'grid'
    isPlaying: false,
    currentTime: 0,

    // AI 助手
    chatMode: 'image',            // 'dialogue' | 'image' | 'video'
    inputMessage: '',
    aiOptimize: true,             // 魔法棒优化，仅图片/视频生成模式显示按钮（对话改图不显示）
    subtitleEnabled: true,

    // 资产数据（@提及）：avatar = reference_image || reference_images[0]?.url || ''
    characters: [],               // 角色列表 { id, name, avatar }
    locations: [],                // 场景列表 { id, name, avatar }
    props: [],                    // 道具列表 { id, name, avatar }

    // UI 状态
    showEditPrompt: false,
    showExportDialog: false,
    showMentionPopup: false,
    mentionTab: 'character',
    error: '',
};

// scene 对象（与后端 storyboard_scene 对齐，废弃 demo2 照搬的 thumbnail/previewImageUrl/sceneInfo/charDesc/voiceoverText/status）：
// {
//   id, storyboardId, sortOrder, title, duration, durationLabel,
//   videoType,                       // image | video | digital_human
//   videoPrompt, videoConfigJson,
//   selectedFirstFrameId, selectedLastFrameId, selectedVideoId,   // 选中 asset 指针
//   firstFrameUrl, lastFrameUrl, videoUrl,   // 当前选中 asset 的 result_url（后端 list_by_storyboard join）
//   promptJson: { perspective, style, scene_desc, character_desc },
//   dialogues: [{ id, sceneId, sortOrder, characterId, text, speed, volume, selectedAudioId, audioUrl }],
//   taskStatus: { first_frame, last_frame, video }   // 轮询 task-status 填充
// }
```

### 4.7 序列化/恢复协议（serializeStoryboard / restoreStoryboard）

参考 `web/js/workflow.js` 中的 `serializeWorkflow()` / `restoreWorkflow()` 模式：

```javascript
/**
 * 序列化故事板状态（用于自动保存 / 刷新恢复）
 * 只保存前端可编辑的状态，不保存生成结果 URL（从后端重新加载）
 */
function serializeStoryboard() {
    return {
        version: 1,
        storyboardId: state.storyboardId,
        worldId: state.worldId,
        episodeNumber: state.episodeNumber,
        currentSceneId: state.currentSceneId,
        isStoryboardView: state.isStoryboardView,
        activeTab: state.activeTab,
        chatMode: state.chatMode,
        // 画风配置
        style: { ...state.style },
        workflowRatio: state.workflowRatio,
        // 模型配置
        selectedModel: { ...state.selectedModel },
        videoResolution: state.videoResolution,
        videoDuration: state.videoDuration,
        cropToVoice: state.cropToVoice,
        voiceSpeed: state.voiceSpeed,
        voiceVolume: state.voiceVolume,
        selectedVoiceStyle: state.selectedVoiceStyle,
        subtitleEnabled: state.subtitleEnabled,
        aiOptimize: state.aiOptimize,
        // ❗ 不序列化分镜内容（prompt_json/voiceover_text/voice_config_json）
        // 这些字段属于 storyboard_scene 表的正式字段，通过 scene API 单独保存
        // config_json 仅保存 UI 状态，避免双写
    };
}

/**
 * 恢复故事板状态
 * 从后端 API 加载完整数据后，合并本地可编辑状态
 */
async function restoreStoryboard(storyboardId) {
    // 1. 从后端加载完整数据
    const response = await fetch(`/api/storyboard/${storyboardId}`, {
        headers: { 'X-User-Id': state.userId }
    });
    const data = await response.json();
    
    // 2. 恢复基础状态
    state.storyboardId = data.storyboard.id;
    state.title = data.storyboard.title;
    state.scenes = data.scenes;  // 包含所有生成状态和 URL
    
    // 3. 从 config_json 恢复 UI 状态
    const config = data.storyboard.config_json || {};
    state.currentSceneId = config.currentSceneId || (data.scenes[0]?.id ?? null);
    state.isStoryboardView = config.isStoryboardView || false;
    state.selectedModel = config.selectedModel || state.selectedModel;
    state.videoResolution = config.videoResolution || '1080p';
    // ... 其他 UI 状态
    
    // 4. 加载资产数据（角色/场景/道具 → 用于 @提及）
    await loadWorldAssets();
    
    // 5. 恢复轮询中的生成任务
    resumePollingTasks();
    
    // 6. 渲染
    renderHome();
}
```

**自动保存**：每次关键操作后（切换分镜、编辑提示词、修改配置等），调用 `autoSaveStoryboard()` 将 `serializeStoryboard()` 的结果 PUT 到后端 `config_json` 字段。

---

## 5. 入口改造：script_writer.html 模式选择

### 5.1 修改导航条

在 `script_writer.html` 的左侧导览条中，将 `goToWorkflowCanvas()` 改为弹出模式选择：

```javascript
function showProductionModeSelector() {
    // 弹出模式选择对话框（两个卡片：画布模式 / 故事板模式）
}

async function goToStoryboard() {
    // 1. 提交当前数据（复用现有逻辑）
    try { await submitToDatabase(); } catch (e) {}
    
    // 2. 检查资产完成状态（复用现有逻辑）
    const assetsStatus = await checkAssetsComplete();
    const hasProblems = !assetsStatus.hasScript || assetsStatus.missingAssets.length > 0;
    if (hasProblems) {
        const confirmed = await showAssetConfirmModal(
            assetsStatus.hasScript, assetsStatus.missingAssets
        );
        if (!confirmed) return;
    }
    
    // 3. 获取当前剧本的集数
    const episodeNumber = getCurrentEpisodeNumber(); // 从 script 数据中获取
    
    // 4. 跳转到故事板页面（后端会做幂等 get-or-create）
    let url = `/storyboard?world_id=${WORLD_ID}&episode_number=${episodeNumber}`;
    if (SCRIPT_ID) url += `&script_id=${SCRIPT_ID}`;
    if (WORKFLOW_ID) url += `&workflow_id=${WORKFLOW_ID}`;
    window.location.href = url;
}
```

### 5.2 模式选择弹窗 UI

```
┌─────────────────────────────────┐
│        选择制作模式               │
├──────────────┬──────────────────┤
│  🖼 画布模式  │  📋 故事板模式    │
│  传统节点式   │  可视化分镜编辑   │
│  工作流编辑   │  逐帧精细控制    │
│  [进入]      │  [进入]          │
└──────────────┴──────────────────┘
```

---

## 6. 与现有系统的集成

### 6.1 数据流

```
World (世界)
    │
    ├─ visual_style  ──继承──→  storyboard.style
    ├─ composition_preference ──继承──→  storyboard.composition_preference
    │
    ├─ 剧本内容 (script 表)       ──── episode_number 集数
    ├─ 角色数据 (character 表) ──→ @提及 角色列表
    ├─ 场景数据 (location 表) ──→ @提及 场景列表
    └─ 道具数据 (props 表)   ──→ @提及 道具列表
         │
         ▼  (幂等 get-or-create by user_id + world_id + episode_number)
    故事板 (storyboard)
         │
         ├─ style / style_reference_image / workflow_ratio
         ├─ 分镜列表 (storyboard_scene 表)
         │    ├─ prompt_json    → 画面提示词
         │    ├─ voiceover_text → 配音台词
         │    ├─ image_status/video_status/voice_status → 独立任务状态
         │    └─ first_frame_url / last_frame_url / video_url → 生成结果
         │
         ▼
    一键转视频 → 复用现有视频合成逻辑
```

### 6.2 复用现有能力

| 能力 | 来源 | 复用方式 |
|------|------|---------|
| AI 对话（LLM） | `llm/` + `api/script_writer.py` | 直接调用 `get_llm_client()` |
| 图片生成 | `task/` 模块 | 调用现有生图任务接口，返回 task_id 后轮询 |
| 视频生成 | 视频驱动（可灵/Pixverse等） | 复用视频生成驱动，返回 task_id 后轮询 |
| 配音生成 | `task/audio_task` | 复用 `build_character_audio_text()` |
| 资产上传 | `/api/video-workflow/upload` | 复用上传接口 |
| 算力系统 | `model/computing_power` | 复用算力扣费逻辑 |
| 通知系统 | `api/notifications` | 复用任务完成通知 |
| 模型列表 | `api/script_writer.py` | 调用 `/api/text-to-image-models`、`/api/video-model`、`/api/models` |

### 6.3 任务轮询机制

分镜的图片/视频/配音生成都是异步任务，需要轮询：

```javascript
// 前端轮询
async function pollSceneTaskStatus(sceneId, taskType) {
    // taskType: 'image' | 'video' | 'voice'
    const response = await fetch(
        `/api/storyboard/scene/${sceneId}/task-status?type=${taskType}`,
        { headers: { 'X-User-Id': state.userId } }
    );
    const data = await response.json();
    
    // 更新对应分镜的状态
    const scene = state.scenes.find(s => s.id === sceneId);
    if (scene) {
        scene[`${taskType}_status`] = data.status;
        if (data.status === 2) { // 成功
            scene[`${taskType}_url`] = data.result_url;
        } else if (data.status === 3) { // 失败
            scene[`${taskType}_error`] = data.error;
        }
    }
    
    // 生成中 → 继续轮询
    if (data.status === 1) {
        setTimeout(() => pollSceneTaskStatus(sceneId, taskType), 3000);
    }
    
    renderHome();
}

// 页面加载时恢复轮询
function resumePollingTasks() {
    for (const scene of state.scenes) {
        if (scene.image_status === 1) pollSceneTaskStatus(scene.id, 'image');
        if (scene.video_status === 1) pollSceneTaskStatus(scene.id, 'video');
        if (scene.voice_status === 1) pollSceneTaskStatus(scene.id, 'voice');
    }
}
```

---

## 7. 关键交互流程

### 7.1 首次进入故事板

1. 用户在 `script_writer.html` 完成剧本对话
2. 点击 "制作工坊"，弹出模式选择
3. 选择 "故事板模式"
4. 系统自动提交剧本资产数据
5. 跳转到 `/storyboard?world_id=xxx&script_id=xxx`
6. 页面加载后调用 `POST /api/storyboard/create`（**幂等 get-or-create**）
7. 后端在事务中原子创建 storyboard + scenes（LLM 自动拆分剧本）
8. 前端调用 `restoreStoryboard(id)` 恢复完整状态
9. 渲染分镜列表到故事板网格

### 7.2 编辑分镜画面

1. 点击分镜卡片 → 左侧面板切换到 "画面" Tab
2. 显示当前分镜的提示词卡片（从 `prompt_json` 读取）
3. 点击 "编辑" 打开提示词编辑弹窗
4. 修改视角/风格/场景描述/角色描述后保存 → `PUT /api/storyboard/scene/{id}/prompt`
5. 在 AI 助手区选择 "图片生成" 模式
6. 可 @提及角色/场景（从后端资产接口获取列表）
7. 点击发送 → `POST /api/storyboard/scene/{id}/generate-image`
8. 后端返回 task_id → 前端开始轮询 `image_status`
9. 轮询到成功后更新 `thumbnail_url` 和 `preview_image_url`

### 7.3 生成视频

1. AI 助手区选择 "视频生成" 模式
2. 选择首帧/尾帧图片
3. 配置分辨率、时长、模型
4. 发送 → `POST /api/storyboard/scene/{id}/generate-video`
5. 后端返回 task_id → 前端轮询 `video_status`
6. 成功后更新 `video_url`，可在预览区播放

### 7.4 一键转视频

1. 所有分镜生成完毕后
2. 点击 Header "一键转视频"
3. 系统将所有分镜按 `sort_order` 顺序合成完整视频
4. 支持添加字幕、配音、背景音乐
5. 完成后弹出导出对话框

---

## 8. 实现任务拆解

### Task 0: 数据模型重构（2026-06-24）
- [x] 新增 `SceneVideoType` 枚举（`config/unified_config.py`：image / video / digital_human）
- [x] 精简 `storyboard_scene`（删 18 字段、加 `video_prompt` / `video_type` / `selected_*_id` / `last_modified_user_id`，`sort_order` 改 `DOUBLE`）
- [x] 新增 `storyboard_dialogue` / `storyboard_dialogue_audio` / `storyboard_scene_asset` 三表（实体 + Model + `CREATE_TABLE_SQL`）
- [x] 浮点二分排序（`compute_sort_between` / `is_precision_exhausted` + `rebalance`，scene 与 dialogue 共用）
- [x] 新建 Alembic 迁移 `no_102`（重构 scene + 建三新表，含 up/down）
- [x] 改造 `api/storyboard.py`：scene 字段精简、dialogue CRUD、asset 选中、`task-status` 走 `ai_tools`/`ai_audio`、reorder 浮点二分协议
- [x] 前端 5 文件归一（adapters/api/state/events/render）：对话列表、选中资产、删音乐 Tab、命名与后端模型对齐、`normalizePagedList` 收敛
- [ ] 生成接口接入真实驱动（图片→`ai_tools` 首帧/尾帧、视频/数字人→`ai_tools`、配音→`ai_audio`）— 数据链路已就绪，驱动待接
- [ ] 前端任务轮询（`GET /scene/{id}/task-status`）接入

### Task 1: 数据库迁移
- [x] 创建 `storyboard` 和 `storyboard_scene` 表的 Alembic 迁移脚本（使用 `create_at`/`update_at`）
- [x] 创建 `model/storyboard.py`（含 Storyboard + StoryboardScene 实体 + StoryboardModel + StoryboardSceneModel）
- [x] Model 层 list 查询方法中实现 `Edition.is_space_isolated()` 空间隔离过滤
- [x] 确保 UNIQUE KEY `uk_user_world_episode` (user_id, world_id, episode_number) 实现幂等

### Task 2: 后端 API
- [x] **前置重构**：将 `server.py` 中的鉴权函数抽取到 `utils/resource_access.py`，server.py 通过别名保持向后兼容
- [x] 创建 `api/storyboard.py`，使用 `APIRouter(prefix="/api/storyboard")`
- [x] 所有接口统一通过 `X-User-Id` Header 获取用户身份
- [x] 单资源访问使用 `ensure_resource_access(sb, user_id, action)` 校验归属
- [x] 创建时校验世界归属 `ensure_world_access(world_id, user_id)`
- [x] 分镜操作先查所属 storyboard 再校验归属（`_ensure_scene_access` helper）
- [x] 所有 DB 调用使用 `await asyncio.to_thread()` 包装
- [x] 实现幂等创建逻辑（get-or-create + 事务 + 唯一键冲突降级）
- [x] 实现画风继承逻辑（创建时从 World.visual_style 继承）
- [x] 实现故事板/分镜 CRUD
- [x] 实现任务状态轮询接口（返回 image/video/voice 各类型状态）
- [x] 在 `server.py` 中注册路由
- [ ] 实现生成接口（图片/视频/配音生成任务流）— 占位已建，待接入具体任务驱动
- [ ] 实现剧本自动拆分分镜（LLM 调用）— 当前为简单段落拆分，待替换为 LLM
- [ ] 【二期】添加 `@require_permission` 权限控制（当前为空实现，保留接口签名）

### Task 3: 前端 - 入口改造
- [x] 修改 `script_writer.html` 导航条，添加模式选择弹窗（画布 / 故事板）
- [x] 实现 `goToStoryboard()` 跳转函数（含资产检查、集数获取）
- [x] 更新 `web/i18n/locales/zh-CN/` 和 `en/` 的语言包

### Task 4: 前端 - 故事板页面骨架
- [x] `web/storyboard.html`（页面结构 + i18n 初始化 `['common', 'storyboard']`）
- [x] `web/css/storyboard.css`（全局样式，独立文件）
- [x] `web/js/storyboard/icons.js`（SVG 图标）
- [x] `web/js/storyboard/state.js`（状态管理 + serialize/restore + 资产字段映射）
- [x] `web/js/storyboard/api.js`（全部异步 fetch + 统一 `X-User-Id` Header）
- [x] `web/js/storyboard/render.js`（渲染函数：Header/Sidebar/Center/Timeline）
- [x] `web/js/storyboard/events.js`（事件绑定：Tab切换/增删复制/AI助手/提示词编辑）
- [x] `web/js/storyboard/utils.js`（工具函数：防抖/Toast/确认框/i18n）

### Task 5: 前端 - 核心功能
- [x] Header 导航和操作按钮（导航 Tab + 导出按钮 + 算力显示）
- [x] 左侧面板 Tab 切换（画面/配音/音乐）
- [x] 普通视图（单分镜预览 + 字幕叠加层）
- [x] 故事板视图（3列网格卡片总览，含独立任务状态指示器 + 复制/删除悬浮操作）
- [x] 底部时间线控制（进度条 + 播放/暂停 + 字幕开关 + 视图切换 + 缩略图列表）
- [x] AI 智能助手骨架（对话改图/图片生成/视频生成 模式切换 + 输入框）
- [x] 提示词编辑弹窗（视角/风格/场景描述/角色描述）
- [ ] 模型选择弹窗（调用真实模型接口）— 待集成
- [ ] @提及弹窗（角色/场景从后端资产接口获取）— 资产已加载，弹窗待实现
- [ ] 导出功能弹窗 — 后端占位已建，前端待实现
- [ ] 任务轮询 + 状态更新 — 后端接口已建，前端轮询逻辑待实现

### Task 6: 集成与联调
- [ ] 从剧本资产幂等创建故事板
- [ ] 分镜图片生成 + 轮询联调
- [ ] 分镜视频生成 + 轮询联调
- [ ] 配音生成 + 轮询联调
- [ ] 一键转视频联调
- [ ] serialize/restore 刷新恢复验证

### Task 7: 文档同步
- [x] 更新设计文档任务清单状态
- [x] 添加实施进度说明

---

## 9. 注意事项

1. **一集一板**：每个 storyboard 通过 `episode_number` 绑定具体集数，幂等键为 `(user_id, world_id, episode_number)`
2. **必须关联世界**：`world_id` 是必填字段，通过它获取角色/场景/道具资产，创建时校验 `_ensure_world_access(world_id, user_id)`
3. **画风继承**：创建时自动从 `World.visual_style` 继承画风，用户可覆盖
4. **画幅比例**：`workflow_ratio` 字段与 `video_workflow` 保持一致
5. **非阻塞原则（后端）**：所有同步 Model/DB 调用必须 `await asyncio.to_thread()`，文件 IO 用 `aiofiles` 或 `asyncio.to_thread()`，禁止 `requests` 库，使用 `httpx`
6. **非阻塞原则（前端）**：所有 API 调用使用 `fetch` + `async/await`
7. **幂等创建**：后端 get-or-create by `user_id + world_id + episode_number`
8. **任务状态来源**：图片/视频状态来自选中 asset 关联的 `ai_tools.status`，配音状态来自对话选中配音关联的 `ai_audio.status`；`storyboard_scene` 不再冗余状态字段，经 `GET /scene/{id}/task-status` 聚合返回
9. **字段命名**：新表统一 `create_at`/`update_at`
10. **模型接口**：使用 `/api/text-to-image-models`、`/api/video-model`、`/api/models`（非 `/api/vendor-models`）
11. **CSS/JS 独立文件**：降低 SSE token 消耗
12. **跨平台兼容**：路径使用 `os.path.join`，编码统一 UTF-8
13. **数据库迁移**：新增表必须创建 Alembic 迁移脚本
14. **i18n 支持**：语言包文件 `web/i18n/locales/{locale}/storyboard.json`，初始化 `ZJTi18n.init(['common', 'storyboard'])`
15. **序列化/恢复**：定义 `serializeStoryboard()` / `restoreStoryboard()`，支持页面刷新恢复
16. **权限控制（二期/暂缓）**：`@require_permission("storyboard:xxx")` 装饰器本期暂不启用（当前为空实现），保留接口签名以便二期接入
17. **错误处理**：全局错误捕获 + 用户友好的错误提示
18. **身份校验**：所有接口必须通过 `X-User-Id` Header 获取并校验用户身份，敏感操作需 `Authorization` Header
19. **空间隔离**：Model 层 list 查询统一使用 `Edition.is_space_isolated()` 条件过滤；API 层使用 `_ensure_resource_access` 校验资源归属。商业版用户数据相互隔离，开源版共享（删除除外）
20. **防越权**：分镜操作必须先查所属 storyboard 再校验归属，不能直接按 scene_id 操作而跳过归属校验
21. **INT UNSIGNED 兼容**：新表外键字段统一使用 `INT UNSIGNED`，与老表保持一致（`world.id`、`script.id`、`video_workflow.id`、`character.id` 等主键均为 `int unsigned`），避免 MySQL 外键类型不一致报错
22. **config_json 不双写**：`config_json` 仅保存 UI 状态（当前分镜、视图模式、选中模型等），分镜内容（prompt_json/voiceover_text/voice_config_json）通过 scene API 单独保存，禁止在 serializeStoryboard 中双写
23. **避免循环导入**：`_get_user_id_from_header`、`_ensure_resource_access`、`_ensure_world_access` 等公共函数抽取到 `utils/resource_access.py`，禁止 `api/storyboard.py` 从 `server.py` 反向导入
24. **资产字段映射**：DB 返回 `reference_image`/`reference_images`，前端统一映射为 `avatar`（规则：`reference_image || reference_images[0]?.url || ''`）
25. **选中指针**：`storyboard_scene` 用 `selected_first_frame_id / selected_last_frame_id / selected_video_id` 指向当前选中的 `storyboard_scene_asset`，由 `POST /scene/{id}/asset/select` 维护；指针不建外键（避免与 `scene_asset.scene_id` 循环），前端不直接写指针
26. **ai_tool_id / ai_audio_id 类型**：`storyboard_scene_asset.ai_tool_id`、`storyboard_dialogue_audio.ai_audio_id` 用 `INT`（有符号），匹配 `ai_tools.id` / `ai_audio.id` 的 `int`，**不加外键**，否则 MySQL 报外键类型不一致
27. **缩略图不落库**：`storyboard_scene` 不存 `thumbnail_url` / `preview_image_url`；画面取选中首帧的 `result_url`，小图由基础缩略图服务从原图按需生成
28. **分镜类型 video_type**：取 `SceneVideoType`（image / video / digital_human，见 2.3.1），决定该分镜走图片/图生视频/数字人生成任务
29. **浮点二分排序**：`storyboard_scene.sort_order` 与 `storyboard_dialogue.sort_order` 为 `DOUBLE`；中间插入取左右均值，精度耗尽（`mid == left` 或 `mid == right`）时自动 `rebalance`（见 2.3.2）；前端拖拽只传前后 id，不传数值
30. **配音拆表**：台词/语速/音量在 `storyboard_dialogue`（一个分镜多句，`character_id` 关联角色取 `default_voice` 作参考声音，NULL=旁白），配音历史在 `storyboard_dialogue_audio`（关联 `ai_audio`）；`storyboard_scene` 不再有音频字段，`music_json` 已删除（音乐属时间轴，本期后置）
