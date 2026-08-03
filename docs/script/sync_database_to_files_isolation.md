# 数据库 → 暂存区同步 与 user_id 隔离约定

## 背景

`script_writer.html` 侧边栏「删除暂存，重置会话」按钮用于把暂存区重置为数据库最新状态。

### 调用链

```
script_writer.html 「删除暂存」按钮 (onclick="newSession()")
  └─ web/js/script_writer.js: newSession()
       └─ POST /api/sync-files   { user_id, world_id }
            └─ api/script_writer.py: sync_files()
                 └─ sync_database_to_files(user_id, world_id, force_overwrite=True)
```

`force_overwrite=True` 时会先删除 `worlds/characters/scripts/locations/props` 目录下所有非 `temp_` 前缀的 JSON，再从 DB 重建。

前端同步后通过 `/api/{type}-files`（如 `/api/characters-files`）从**文件系统**重新读取列表展示，因此「同步是否成功」直接取决于文件是否被写出来。

## user_id 过滤约定（重点）

`sync_database_to_files` 在遍历 DB 记录时，对四类数据（character / script / location / props）都有一层 user_id 过滤：

```python
filter_by_user = Edition.is_space_isolated()
...
for char in characters:
    if filter_by_user and char.get('user_id') != int(user_id):
        continue
```

### 为什么过滤要受 `Edition.is_space_isolated()` 控制

- 各 Model 的 `list_by_world()` 只按 `world_id` 过滤（`SELECT * WHERE world_id = %s`），**不**按 user_id 过滤；
- 同样的隔离判断在 `list_by_user()` 系列方法中早已存在（`if Edition.is_space_isolated(): where_conditions.append("user_id = %s")`），此处保持一致；
- **社区版 / 共享空间**（`is_space_isolated() == False`）下 world 是多人共享的，记录的 `user_id` 可能是任意协作者。如果在此处仍按当前请求的 user_id 过滤，会把别人创建的角色/场景/道具/剧本**静默跳过**（`continue` 无日志、无报错），导致「删除暂存」后这些数据同步不出来——这是用户反馈「角色无法同步」的根因。

### 各版本下的行为

| 版本 / 配置 | `is_space_isolated()` | 是否按 user_id 过滤 |
|-------------|----------------------|---------------------|
| 社区版 | `False` | 否（同步 world 内全部记录） |
| 企业版（默认独立空间） | `True` | 是（仅同步当前用户的记录） |
| 企业版 + `edition.shared_space=true` | `False` | 否（同步 world 内全部记录） |

## 历史问题

### 问题一：user_id 过滤未与 edition 联动

此前过滤条件是无条件的 `if item.get('user_id') != int(user_id): continue`，未与 edition 约定联动。在共享世界场景下，角色（往往由 world 创建者/主账号批量创建）的 `user_id` 与当前操作用户不一致，导致角色被全部跳过、无法同步；而场景/道具若恰好是当前用户自己创建的则能正常同步，表现为「只有角色同步不出来」。

### 问题二：reference_image 相对路径被图片校验拒绝

这是更隐蔽也更主要的根因。`sync_database_to_files` 把 DB 的 `reference_image` 直接传给
`create_character_json` / `create_location_json` / `create_prop_json`（这些是 MCP 工具函数，
内部对 `reference_image` 调用 `validate_image_url()`，强制要求 `http://` / `https://` 开头）。

但 DB 中角色/道具的 `reference_image` 常存为相对路径 `/upload/...`（这是系统**合法的存储格式**，
`server.py` 的 `/upload/` 中间件、CDN 重定向、图片代理都支持它）。于是：

- `validate_image_url('/upload/character/pic/xxx.png')` → **校验失败**（scheme 为空）
- `create_xxx_json` → 返回 `success=False`，**文件不写**
- 同步循环的 `else` 分支此前**不检查返回值** → **静默丢弃，无任何日志**

而剧本走 `file_manager.save_script()` 不校验图片，场景若其 `reference_image` 恰好存的是完整 http URL 则能通过，
表现为「剧本、场景能同步，角色、道具同步不出来」。

实测一例（world_id=1）：角色 12 条全部为 `/upload/...` 相对路径、场景 33 条全部为 `http://...`、
道具 10 条全部为 `/upload/...` —— 与「角色、道具失败、场景成功」的现象完全吻合。

### 修复

1. `create_character_json` / `create_location_json` / `create_prop_json` 新增内部参数
   `_skip_image_validation: bool = False`（沿用 `_temp_filename` 的下划线约定，对 LLM 隐藏）。
2. `sync_database_to_files` 的所有 create 调用传 `_skip_image_validation=True`——因为同步读的是
   自家 DB 的数据，不是用户/LLM 输入，`reference_image` 的相对路径是合法存储格式，无需校验。
3. 同步循环的 `else` 分支及各覆盖分支改为**检查返回值**，失败时 `logger.warning` 记录，避免再次静默失败。

LLM / MCP 正常调用流程不受影响（`_skip_image_validation` 默认 `False`，仍执行图片校验）。

## 相关代码

| 位置 | 说明 |
|------|------|
| `api/script_writer.py: sync_database_to_files()` | DB → 文件同步主函数 |
| `api/script_writer.py: sync_files()` (`/api/sync-files`) | 对应 HTTP 接口 |
| `web/js/script_writer.js: newSession()` | 前端「删除暂存」入口 |
| `model/{character,location,props,script}.py: list_by_world()` | 按 world_id 查询（不按 user_id） |
| `config/constant.py: Edition.is_space_isolated()` | 空间隔离判断 |
| `script_writer_core/mcp_tool.py: validate_image_url()` | 图片 URL 校验（要求 http/https） |
| `script_writer_core/mcp_tool.py: create_{character,location,prop}_json()` | 实体 JSON 生成，`_skip_image_validation` 控制是否校验图片 |

## 排查数据问题

若仍有个别记录同步不出来，按以下两步排查：

### 1. 确认记录归属（user_id 是否匹配）

```sql
SELECT 'character' AS t, id, name, user_id FROM `character` WHERE world_id = <wid>
UNION ALL
SELECT 'location',  id, name, user_id FROM location       WHERE world_id = <wid>
UNION ALL
SELECT 'props',     id, name, user_id FROM props          WHERE world_id = <wid>;
```

### 2. 确认 reference_image 格式

```sql
SELECT 'character' AS t,
       COUNT(*) AS total,
       SUM(reference_image LIKE 'http%') AS http_cnt,
       SUM(reference_image LIKE '/upload/%') AS relative_cnt
FROM `character` WHERE world_id = <wid>
UNION ALL
SELECT 'location',  COUNT(*), SUM(reference_image LIKE 'http%'), SUM(reference_image LIKE '/upload/%') FROM location WHERE world_id = <wid>
UNION ALL
SELECT 'props',     COUNT(*), SUM(reference_image LIKE 'http%'), SUM(reference_image LIKE '/upload/%') FROM props    WHERE world_id = <wid>;
```

`relative_cnt > 0` 的类型在修复前会同步失败（被 `validate_image_url` 拒绝）；修复后（`_skip_image_validation=True`）可正常同步。

同步日志中若出现 `同步角色失败 xxx: ...` / `同步道具失败 xxx: ...`，说明该条仍被某个校验拦下（如 `validate_name_for_filename` 因名称含特殊字符失败），可据此定位。
