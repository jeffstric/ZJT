# 故事板入口与文件夹列表

## 目标

将故事板作为短剧制作的独立入口接入平台：

- 首页 `web/index.html` 增加“故事板”入口，进入 `/storyboard-list`。
- 剧本智能体 `web/script_writer.html` 的剧本列表中，每个剧本条目增加“进入故事板”按钮。
- 一个剧本对应一个故事板文件夹，文件夹键为 `world_id + episode_number`。

## 页面与路由

| 页面 | 路由 | 说明 |
| --- | --- | --- |
| 故事板列表 | `GET /storyboard-list` | 文件夹格式展示剧本对应的故事板 |
| 故事板编辑器 | `GET /storyboard` | 打开或幂等创建某集故事板 |

新增文件：

- `web/storyboard_list.html`
- `web/css/storyboard_list.css`
- `web/js/storyboard_list.js`

## 聚合接口

`GET /api/storyboard/folders?world_id={optional}`

返回字段核心结构：

```json
{
  "success": true,
  "total": 1,
  "folders": [
    {
      "folder_key": "7:1",
      "world_id": 7,
      "world_name": "示例世界",
      "episode_number": 1,
      "script_id": 11,
      "script_title": "第一集",
      "storyboard_id": 31,
      "storyboard_title": "第一集故事板",
      "scene_count": 6,
      "status": "created",
      "update_at": "2026-06-24T10:00:00"
    }
  ]
}
```

状态规则：

- `created`：剧本和故事板都存在。
- `not_created`：剧本存在，故事板尚未创建。
- `orphan`：故事板存在，但对应剧本缺失。

后端实现约束：

- 不新增数据库表，文件夹由 `world_id + episode_number` 临时聚合。
- Web 接口内的同步 DB 查询必须使用 `asyncio.to_thread()` 包装，避免阻塞事件循环。
- 不通过 URL 传递 `auth_token`，前端从 `localStorage` 读取并通过 Header 发送。
- `storyboard.composition_preference` 是主表字段，首次创建时从 `world.composition_preference` 继承，用于后续生成图片提示词。
- `storyboard.version` 是主表版本字段，默认 `1`，用于后续故事板结构升级和兼容判断。
- `storyboard_scene`、`storyboard_dialogue`、`storyboard_dialogue_audio`、`storyboard_scene_asset` 表对应的实体和 CRUD 分别拆分到同名 model 文件；`model/storyboard.py` 只保留主表模型，并继续 re-export 这些子表模型以兼容旧导入。
- 故事板首次创建不再按段落自动拆分剧本；只有用户在空故事板弹框中确认后，才调用后端接口解析剧本并事务写入分镜/对话数据。

## 编辑器内切换集数

故事板编辑器 header 副标题中的「第 N 集」可点击，展开集数选择器：

1. 列表数据来自 `GET /api/storyboard/folders?world_id={当前世界}`（与列表页同源）。
2. 点某一集：跳转  
   `/storyboard?world_id=…&episode_number=…&script_id?=…&id?=…&user_id=…&workflow_id?=…`  
   - 已有 `storyboard_id` 时带 `id` 直接打开。  
   - **无故事板**时不传 `id`，由 `bootstrap` → `POST /api/storyboard/create` **幂等 get-or-create** 新建后进入。  
3. 「其他集数」可输入任意正整数进入（列表中不存在也可），同样走 create 新建。  
4. 前端：`render.js` 集数按钮/面板，`events.js` `navigateToEpisode` / `ensureEpisodeFoldersLoaded`，`api.listStoryboardFolders`。

## 媒体导出

素材包 / 完整视频导出见 [storyboard_export.md](./storyboard_export.md)（zip/mp4 上传 CDN，返回 `download_url`）。

## 新建故事板标题（title）

`storyboard.title` 为库表字段（`VARCHAR(255)`），创建时写入：

| 优先级 | 来源 |
|--------|------|
| 1 | Body 显式非空 `title` |
| 2 | 关联剧本 `script.title`（`resolve_storyboard_script_id` 解析到的剧本） |
| 3 | 兜底 `第{episode_number}集故事板`（与前端 `buildStoryboardTitle` 一致） |

实现：`api/storyboard.py` → `resolve_storyboard_create_title` + `create_storyboard`。  
get-or-create 命中已有故事板时**不改** title。历史空 title 不自动回填。

## 入口行为

### 首页

`handleStoryboardListClick()`：

1. 检查 `localStorage.auth_token` 和 `localStorage.user_id`。
2. 未登录提示登录。
3. 已登录跳转 `/storyboard-list`。

### 剧本列表

`openStoryboardFromScript(scriptId, episodeNumber)`：

1. 使用当前 `world_id` 和剧本 `episode_number` 定位文件夹。
2. 调用 `POST /api/check-assets-complete` 校验当前世界的资产图片：
   - 要求 `character_image_count > 0` 且 `location_image_count > 0`。
   - 若角色图或场景图为空，弹出 `alert` 提示用户先点击上方的「提交」按钮提交数据，并**阻止跳转**。
3. 校验通过后，如果能拿到 `script_id`，附加到 URL。
4. 跳转 `/storyboard?world_id=...&episode_number=...&script_id=...`。
5. 故事板页调用 `POST /api/storyboard/create` 幂等创建或打开。

> `/api/check-assets-complete` 在原有 `has_script` / `missing_assets` 基础上，额外返回 `character_count`、`character_image_count`、`location_count`、`location_image_count`，供前端判断。

### 故事板编辑器

`web/storyboard.html` 左上角 `.header-logo` 使用 `data-route="storyboard-list"` 接入现有路由事件代理，点击后跳转 `/storyboard-list`，返回故事板列表页。

### 空故事板生成分镜

进入 `web/storyboard.html` 后，如果当前故事板没有任何 `storyboard_scene`，前端会显示确认弹框（`renderGenerateFromScriptDialog`）：
如果用户在编辑器中删除了最后一个分镜，前端也会重新进入同一个拆分分镜弹框，方便直接从剧本重新生成分镜。

- 取消：关闭弹框，保留空故事板，用户仍可手动添加分镜。
- 确认：调用 `POST /api/storyboard/{storyboard_id}/generate-from-script`，由后端一次性完成剧本解析和数据落库。

弹框中可配置以下剧本拆分参数（与视频工作流的剧本节点保持一致，选项会持久化到 UI 配置，刷新后保留）：

| 参数 | 控件 | 默认值 | 说明 |
|------|------|--------|------|
| `max_group_duration` | 镜头组时长 select | 15 | 每个分镜组的最大总时长（可选 5/8/10/15 秒），超时会在同一场景内自动拆分 |
| `force_medium_shot` | 对话禁止全景 开关 | 开 | 对话镜头强制使用近景/中景，避免全景对话效果不佳 |
| `no_bg_music` | 不生成背景音乐 开关 | 开 | 所有分镜的 background_music 置空，方便后期调音 |
| `split_multi_dialogue` | 拆分多人对话镜头 开关 | 关 | 多人对话镜头按对话顺序拆成多个单人镜头，遵守 180 度轴线原则 |

> 这些参数在 `web/js/storyboard/state.js`（`maxGroupDuration`/`forceMediumShot`/`noBgMusic`/`splitMultiDialogue`）中维护，由 `events.js` 的 `generate-from-script-confirm` 读取后透传给后端。两套入口（视频工作流剧本节点 / 故事板详情页弹框）共用同一个 `parse_script_to_shots` 后端逻辑。

前端 state（`state.js`）：`maxGroupDuration`/`forceMediumShot`/`noBgMusic`/`splitMultiDialogue`，通过 `serializeUiConfig`/`restoreUiConfig` 持久化（含取值合法性校验）。弹框渲染见 `render.js` 的 `renderScriptSplitOptions`，事件处理见 `events.js` 的 `generate-from-script-confirm` 与 `toggle-force-medium-shot` 等 action。

接口行为：

1. 后端校验故事板归属和编辑权限。
2. 如果故事板已存在分镜，返回 `409`，防止重复生成。
3. 根据 `storyboard.script_id` 或 `world_id + episode_number` 解析出剧本。
4. 调用 `llm.script_parser.parse_script_to_shots()`，复用视频工作流的剧本拆分核心逻辑。
5. 将解析出的 `shot_groups[].shots[]` 转换为 `storyboard_scene`，将 `shot.dialogue[]` 转换为 `storyboard_dialogue`。
6. 使用 `StoryboardModel.create_scenes()` 在一个事务中写入所有分镜和对话，并更新 `storyboard.total_duration`。

字段映射：

- `shot.duration` → `storyboard_scene.duration`
- `shot.opening_frame_description` + `shot.scene_detail` → `prompt_json.scene_desc`
- `shot.camera_angle` + `shot.shot_type` → `prompt_json.perspective`
- `shot.description` + `shot.scene_detail` + `shot.action` + `shot.narrative_purpose` → `storyboard_scene.video_prompt`
- `dialogue.character_id` 通过解析结果中的 `character_db_id` 映射到 `storyboard_dialogue.character_id`

## 验证

相关测试：

- `tests/storyboard/test_storyboard_folders.py`
- `tests/storyboard/test_storyboard_generate_from_script.py`
- `tests/js/test_storyboard_list_static.js`
