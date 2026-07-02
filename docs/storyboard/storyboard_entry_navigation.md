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

## 入口行为

### 首页

`handleStoryboardListClick()`：

1. 检查 `localStorage.auth_token` 和 `localStorage.user_id`。
2. 未登录提示登录。
3. 已登录跳转 `/storyboard-list`。

### 剧本列表

`openStoryboardFromScript(scriptId, episodeNumber)`：

1. 使用当前 `world_id` 和剧本 `episode_number` 定位文件夹。
2. 如果能拿到 `script_id`，附加到 URL。
3. 跳转 `/storyboard?world_id=...&episode_number=...&script_id=...`。
4. 故事板页调用 `POST /api/storyboard/create` 幂等创建或打开。

### 空故事板生成分镜

进入 `web/storyboard.html` 后，如果当前故事板没有任何 `storyboard_scene`，前端会显示确认弹框：

- 取消：关闭弹框，保留空故事板，用户仍可手动添加分镜。
- 确认：调用 `POST /api/storyboard/{storyboard_id}/generate-from-script`，由后端一次性完成剧本解析和数据落库。

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
