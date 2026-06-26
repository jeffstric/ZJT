# 故事板（Storyboard）页面设计方案 — 可执行版

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

故事板页面不再消费 `demo2/js/data.js` 的样例数据，所有分镜来自 `storyboard_scene`：

| 后端字段 | 前端字段 | 说明 |
| --- | --- | --- |
| `title` | `scene.title` | 分镜标题 |
| `duration` | `scene.duration / durationLabel` | 秒数与 `mm:ss` 展示 |
| `preview_image_url / thumbnail_url / first_frame_url` | `scene.thumbnail / previewImageUrl` | 分镜缩略图与预览 |
| `video_url` | `scene.videoUrl` | 中央视频预览 |
| `prompt_json.perspective` | `scene.sceneInfo.perspective` | 视角 |
| `prompt_json.style` | `scene.sceneInfo.style` | 风格 |
| `prompt_json.scene_desc` | `scene.sceneInfo.sceneDesc` | 场景描述 |
| `prompt_json.character_desc` | `scene.sceneInfo.charDesc` | 角色描述 |
| `voiceover_text` | `scene.voiceoverText` | 配音台词 |
| `image_status/video_status/voice_status` | `scene.status` | 分镜任务状态 |

资产 `@` 提及统一读取 DB 风格接口 `/api/characters`、`/api/locations`、`/api/props`，并通过 `adapters.normalizePagedList()` 兼容分页响应结构 `{ data: { data: [...] } }`。

### 后端修正

- `create_storyboard` 不再访问不存在的 `World.style_reference_image` 字段，统一通过 `build_storyboard_defaults()` 安全继承。
- `script_id` 缺失时通过 `resolve_storyboard_script_id()` 兜底查找当前集剧本。
- 建表 SQL 保存在 `model/storyboard.py` 末尾的 `CREATE_TABLE_SQL`，正式建表由 Alembic 迁移脚本负责；不向 `model/sql/baseline.sql` 或 `model/sql/baseline_with_db.sql` 写入新表结构。

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
  ├── visual_style          画面风格
  ├── era_environment       时代环境
  ├── color_language        色彩语言
  └── composition_preference 构图倾向
       │
       ├─→ Script (剧本)        — world_id + episode_number，一集一个剧本
       ├─→ Character (角色)     — 属于世界
       ├─→ Location (场景)      — 属于世界
       ├─→ Props (道具)         — 属于世界
       │
       ├─→ VideoWorkflow (画布)  — default_world_id + style + style_reference_image
       │
       └─→ Storyboard (故事板)  — world_id + episode_number + style + style_reference_image
             │
             └─→ StoryboardScene (分镜) — 属于故事板，每个分镜独立生成图片/视频/配音
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
| total_duration | INT | 总时长（秒） |
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
    total_duration INT DEFAULT 0 COMMENT '总时长（秒）',
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

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT UNSIGNED AUTO_INCREMENT | 主键 |
| storyboard_id | INT UNSIGNED | 关联故事板 ID |
| sort_order | INT | 排序序号 |
| title | VARCHAR(255) | 分镜标题，如"分镜1" |
| duration | INT | 时长（秒） |
| thumbnail_url | VARCHAR(512) | 缩略图 URL |
| preview_image_url | VARCHAR(512) | 预览大图 URL |
| prompt_json | JSON | 画面提示词（视角、风格、场景描述、角色描述） |
| voiceover_text | TEXT | 配音台词 |
| voiceover_audio_url | VARCHAR(512) | 配音音频 URL |
| voice_config_json | JSON | 配音配置（语速、音量、音色等） |
| music_json | JSON | 音乐配置 |
| first_frame_url | VARCHAR(512) | 首帧图片 URL |
| last_frame_url | VARCHAR(512) | 尾帧图片 URL |
| video_url | VARCHAR(512) | 生成的视频 URL |
| video_config_json | JSON | 视频生成配置 |
| **image_task_id** | VARCHAR(128) | 图片生成任务 ID |
| **image_status** | TINYINT | 图片状态: 0=未开始 1=生成中 2=成功 3=失败 |
| **image_error** | VARCHAR(512) | 图片生成错误信息 |
| **video_task_id** | VARCHAR(128) | 视频生成任务 ID |
| **video_status** | TINYINT | 视频状态: 0=未开始 1=生成中 2=成功 3=失败 |
| **video_error** | VARCHAR(512) | 视频生成错误信息 |
| **voice_task_id** | VARCHAR(128) | 配音生成任务 ID |
| **voice_status** | TINYINT | 配音状态: 0=未开始 1=生成中 2=成功 3=失败 |
| **voice_error** | VARCHAR(512) | 配音生成错误信息 |
| create_at | DATETIME | 创建时间 |
| update_at | DATETIME | 更新时间 |

> **任务状态拆分说明**：图片、视频、配音、音乐在实际短剧制作中独立生成、独立失败、独立轮询，因此每种媒体类型需要独立的 `task_id` / `status` / `error` 字段，不能共用一个总状态。前端可对每种类型单独展示进度和错误。

```sql
CREATE TABLE storyboard_scene (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    storyboard_id INT UNSIGNED NOT NULL,
    sort_order INT DEFAULT 0,
    title VARCHAR(255) DEFAULT '',
    duration INT DEFAULT 5,
    thumbnail_url VARCHAR(512) DEFAULT NULL,
    preview_image_url VARCHAR(512) DEFAULT NULL,
    prompt_json JSON DEFAULT NULL COMMENT '画面提示词: perspective/style/scene_desc/char_desc',
    voiceover_text TEXT DEFAULT NULL COMMENT '配音台词',
    voiceover_audio_url VARCHAR(512) DEFAULT NULL,
    voice_config_json JSON DEFAULT NULL COMMENT '语速/音量/音色',
    music_json JSON DEFAULT NULL COMMENT '背景音乐配置',
    first_frame_url VARCHAR(512) DEFAULT NULL COMMENT '首帧图片',
    last_frame_url VARCHAR(512) DEFAULT NULL COMMENT '尾帧图片',
    video_url VARCHAR(512) DEFAULT NULL COMMENT '生成的视频',
    video_config_json JSON DEFAULT NULL COMMENT '分辨率/模型/时长',
    image_task_id VARCHAR(128) DEFAULT NULL,
    image_status TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
    image_error VARCHAR(512) DEFAULT NULL,
    video_task_id VARCHAR(128) DEFAULT NULL,
    video_status TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
    video_error VARCHAR(512) DEFAULT NULL,
    voice_task_id VARCHAR(128) DEFAULT NULL,
    voice_status TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
    voice_error VARCHAR(512) DEFAULT NULL,
    create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_storyboard (storyboard_id),
    INDEX idx_sort (storyboard_id, sort_order),
    INDEX idx_image_task (image_task_id),
    INDEX idx_video_task (video_task_id),
    INDEX idx_voice_task (voice_task_id),
    FOREIGN KEY (storyboard_id) REFERENCES storyboard(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

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
| POST | `/api/storyboard/{id}/scene` | `storyboard:update` | 新增分镜 |
| PUT | `/api/storyboard/scene/{scene_id}` | `storyboard:update` | 更新分镜 |
| DELETE | `/api/storyboard/scene/{scene_id}` | `storyboard:update` | 删除分镜 |
| PUT | `/api/storyboard/{id}/scene/reorder` | `storyboard:update` | 批量调整排序 |
| POST | `/api/storyboard/scene/{scene_id}/duplicate` | `storyboard:update` | 复制分镜 |

### 3.5 分镜内容操作

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/storyboard/scene/{scene_id}/generate-image` | `storyboard:generate` | 生成分镜图片 |
| POST | `/api/storyboard/scene/{scene_id}/generate-video` | `storyboard:generate` | 生成分镜视频 |
| POST | `/api/storyboard/scene/{scene_id}/generate-voiceover` | `storyboard:generate` | 生成配音 |
| POST | `/api/storyboard/scene/{scene_id}/ai-chat` | `storyboard:generate` | AI 对话（SSE流） |
| PUT | `/api/storyboard/scene/{scene_id}/prompt` | `storyboard:update` | 更新画面提示词 |
| GET | `/api/storyboard/scene/{scene_id}/task-status` | `storyboard:view` | 轮询生成任务状态 |

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

### 3.8 剧本自动拆分分镜

```python
async def auto_split_script_to_scenes(
    script_content: str,
    characters: list,
    locations: list
) -> list:
    """
    调用 LLM 将剧本内容自动拆分为分镜列表。
    
    返回格式:
    [
        {
            "title": "分镜1",
            "duration": 5,
            "prompt": {
                "perspective": "中景侧拍视角",
                "style": "写实",
                "scene_desc": "[场景名]环境描述...",
                "char_desc": "[角色名](外观)动作描述..."
            },
            "voiceover_text": "角色台词..."
        },
        ...
    ]
    """
    llm_client = await get_llm_client()
    # ... 构建 prompt，调用 LLM，解析 JSON 响应
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
- **算力显示**：⚡ 余额（复用现有 `/api/computing-power` 接口）

#### 4.5.2 Left Sidebar（左侧编辑面板）

**Tab 切换：**

| Tab | 内容 |
|-----|------|
| 🖼 画面 | 提示词卡片（视角、风格、场景描述、角色描述）+ 编辑按钮 + 缩略图 + 图片生成状态指示器 |
| 🎤 配音 | 台词编辑框 + 试听按钮 + 语速/音量滑块 + 音色选择 + 配音生成状态指示器 |
| 🎵 音乐 | AI 生成音乐按钮 + 音乐库列表 |

**底部 AI 智能助手区域：**
- 对话改图模式：文本输入 + 模型选择（从 `/api/models` 获取）
- 图片生成模式：文本输入 + @提及角色/场景（从资产接口获取）+ AI优化开关 + 模型选择（从 `/api/text-to-image-models` 获取）
- 视频生成模式：首帧/尾帧选择 + 文本输入 + 模型/分辨率/时长配置（从 `/api/video-model` 获取）

**每种生成操作都显示独立的状态指示器**：
- 未开始：灰色圆点
- 生成中：蓝色旋转 + 进度
- 成功：绿色勾 + 预览
- 失败：红色叉 + 错误信息（来自 `image_error`/`video_error`/`voice_error`）

#### 4.5.3 Center Content（中央内容区）

**普通视图（默认）：**
- 大型视频/图片预览框（16:9 比例）
- 右侧浮动缩略图栏（首帧选择）

**故事板视图（网格切换）：**
- 3 列卡片网格布局
- 每张卡片包含：分镜图片 + 标题 + 时长 + 复制/删除操作
- 卡片底部显示各类型生成状态图标（图/视频/配音）
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
    title: '',
    
    // 画风配置（从世界继承，用户可覆盖）
    style: { name: '', referenceImageUrl: '', compositionPreference: '' },
    workflowRatio: '16:9',        // 画幅比例
    
    // 视图状态
    isStoryboardView: false,     // false=普通视图, true=故事板网格视图
    isPlaying: false,
    currentSceneId: null,
    currentTime: 0,
    
    // 分镜数据（从后端加载）
    scenes: [],                   // 分镜列表，每个分镜包含 image_status/video_status/voice_status
    
    // 资产数据（从后端加载，映射 @提及）
    // 字段映射规则：avatar = reference_image || reference_images[0]?.url || ''
    // DB 返回的是 reference_image/reference_images，前端统一映射为 avatar 供 @提及弹窗使用
    characters: [],               // 角色列表 { id, name, avatar }
    locations: [],                // 场景列表 { id, name, avatar }
    props: [],                    // 道具列表 { id, name, avatar }
    
    // 左侧面板
    activeTab: 'scene',           // 'scene' | 'voiceover' | 'music'
    
    // AI 助手
    chatMode: 'dialogue',         // 'dialogue' | 'image' | 'video'
    inputMessage: '',
    messages: [],
    selectedModel: { dialogue: 'auto', image: 'auto', video: 'auto' },
    
    // 视频配置
    videoResolution: '1080p',
    videoDuration: 'auto',
    cropToVoice: false,
    
    // 配音配置
    voiceSpeed: 1.0,
    voiceVolume: 100,
    selectedVoiceStyle: '标准',
    
    // UI 状态
    showEditPrompt: false,
    showExportDialog: false,
    showMentionPopup: false,
    showModelSelectPopup: false,
    mentionTab: 'character',      // 'character' | 'scene'
    subtitleEnabled: false,
    aiOptimize: false,
    imageGenRefTab: 'text2img',   // 'text2img' | 'imgref'
};
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
8. **任务状态独立**：每个分镜的 image/video/voice 有独立的 task_id/status/error 字段
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
