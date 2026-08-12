# 世界伪删除（隐藏）

## 概述

剧本策划页（`script_writer`）左侧世界侧栏支持将世界**伪删除**：仅打隐藏标记，从列表中消失，**不删库、不删资产**。用户可在「查看已删除的世界」中恢复显示。

硬删除（`DELETE /api/worlds/{id}`，画布世界选择器的「−」）语义不变，与伪删除并存。

## 数据字段

表 `world`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `is_deleted` | `tinyint(1)` 默认 0 | 0=正常展示，1=列表隐藏 |
| `deleted_at` | `datetime` 可空 | 伪删除时间；恢复时置 `NULL` |

迁移：`alembic/versions/20260812_add_world_soft_delete.py`  
Model：`model/world.py`

## API

### 列表

```
GET /api/worlds?page=1&page_size=100&visibility=active|deleted|all
```

| `visibility` | 含义 |
| --- | --- |
| `active`（默认） | 仅 `is_deleted=0`，全站选择器默认行为 |
| `deleted` | 仅已伪删除 |
| `all` | 不过滤（名称反查等内部场景） |

所有现有 `GET /api/worlds` 调用方**不传参即可自动排除已隐藏世界**。

### 伪删除

```
POST /api/worlds/{world_id}/hide
```

- 权限同硬删（创建者等）
- **不**校验角色/场景是否为空
- 已隐藏时幂等成功

### 恢复

```
POST /api/worlds/{world_id}/restore
```

- 若同用户下已有同名未删除世界 → 400：`存在同名世界，请先修改名称后再恢复`

### 硬删除（保留）

```
DELETE /api/worlds/{world_id}
```

仍要求无角色/场景后物理删除。

## 前端

| 入口 | 行为 |
| --- | --- |
| `script_writer` 侧栏 | 隐藏 / 查看已删除 / 恢复；当前世界被隐藏时跳转到未选世界 |
| `video_workflow` / `video_workflow_list` / index / marketing 等 | 默认列表自动不展示已删；无伪删除 UI |
| `storyboard` 编辑页 | 无世界列表；直链 `world_id` 仍可通过 `get_by_id` 访问 |

后端名称反查（`api/storyboard.py` `collect_storyboard_folder_data`）使用 `visibility=all`，避免已删世界文件夹名丢失。

## 名称唯一性

- 创建/改名：`get_by_name` 默认只匹配 `is_deleted=0`
- 恢复：若与未删除同名冲突则拒绝

## 相关文件

- `model/world.py`
- `server.py`（`/api/worlds`、`/hide`、`/restore`）
- `web/js/script_writer.js` / `web/script_writer.html` / `web/css/script_writer.css`
- `docs/video/world_management.md`
