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

## 验证

相关测试：

- `tests/storyboard/test_storyboard_folders.py`
- `tests/js/test_storyboard_list_static.js`
