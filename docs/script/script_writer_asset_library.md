# 剧本创作页：已入库资产管理

## 背景

`script_writer` 右侧栏原先只操作暂存区 JSON（`files/script_writer/{user_id}/{world_id}/`）。数据库里的角色 / 场景 / 道具 / 剧本没有浏览入口。暂存和数据库不是一一对应，不能只在暂存条目上加「删库」。

## 双数据源

侧栏标题下分段开关：

| 模式 | 标题 | 数据源 | 操作 |
|------|------|--------|------|
| 暂存草稿（默认） | 暂存文件管理 | `*-files` API | 查看 / 编辑 / 删文件、导入导出、画风识别 |
| 已入库 | 世界资产 | `/api/characters` `/api/locations` `/api/props` `/api/scripts` `/api/worlds/{id}` | 查看 / 编辑 / 删除数据库记录 |

刷新页面后回到暂存草稿。窄屏抽屉逻辑不变。

剧本列表请求 `page_size=100`（`/api/scripts` 历史校验最大 100）。超过 100 条会翻页拉全。接口失败会显示「加载失败」，不会再被当成空列表。

世界 Tab 走已有的 `GET /api/worlds` 列表再按当前 `world_id` 过滤，不依赖 `GET /api/worlds/{id}`（该单条接口在旧进程上会 404）。查看/编辑优先用列表缓存。

## 权限

- **查看**：世界 `VIEW`，协作者可看全部资产。
- **编辑 / 删除**：仅 `record.user_id == 当前用户`。协作者按钮禁用。
- 列表展示创建者 `user_id` 末 4 位（如 `1383` → `·1383`），方便找人删。
- 资产不做伪删除。世界伪删除仍走左侧世界列表。

## 删除

专用确认弹窗，不是浏览器 `confirm()`：

- 展示类型、名称、id、创建者末 4 位。
- 剧本：关联分镜数；删除后 `storyboard.script_id` 置空，分镜保留。
- 场景：子场景数；删除后子场景 `parent_id` SET NULL，升为顶级。
- 角色：对白引用数；分镜不删。
- **默认勾选**「同时删除暂存区同名文件」。不勾选则下次点「提交」会按名称/集数 upsert 回来。

`DELETE` 查询参数：`also_delete_staging=true`。暂存删除失败只记日志，不回滚库删除。

## 编辑

复用暂存区查看 / 编辑弹窗。保存走 JSON 接口：

- `PUT /api/scripts/{id}`
- `PUT /api/characters/{id}`
- `PATCH /api/locations/{id}`
- `PATCH /api/props/{id}`
- `PUT /api/worlds/{id}`（已有，补了画风等字段）

保存成功后尝试覆盖当前用户暂存区同名 JSON，并通知智能体重新读取。

## 和「提交 / 重置暂存」的关系

```
暂存  --提交-->  数据库     （upsert，不会删库里多出来的记录）
数据库 --重置-->  暂存     （force_overwrite）
```

智能体工具只读写暂存。数据库清理是用户侧操作。

## 相关文件

- `web/js/script_writer_library.js`
- `web/css/script_writer_library.css`
- `services/asset_library.py`
- `server.py`（剧本 CRUD、单条 GET、JSON 更新、`also_delete_staging`）
