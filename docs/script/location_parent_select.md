# 剧本策划：场景父级（仅顶级）选项框与双向同步

## 目标

- 新建/编辑场景时，**父级场景**为下拉框，选项仅为 **顶级场景**（无父引用）。
- 文件暂存（`locations-files`）与数据库 `location.parent_id` 双向同步时 **不丢层级**。

## 文件 JSON 约定

| 字段 | 含义 |
|------|------|
| `name` | 场景名（文件主键） |
| `parent_name` | 父场景 **名称**（文件层稳定键，主字段） |
| `parent_id` | 兼容：可为名称字符串或同步后的 DB 数字 id |

顶级判定（未落库只看文件）：

```text
parent_name 空 且 parent_id 空/null → 顶级
否则 → 子场景
```

## 提交到数据库（文件 → DB）

两阶段：

1. 全量按 `name` create/update 行（新建 `parent_id=null`；已存在不覆盖 parent）
2. 按 `parent_name`（或历史数字 `parent_id`）解析父行并 `UPDATE parent_id`；父必须是 DB 顶级

禁止 `int(名称)` 失败后静默变 `null`。

## 从数据库同步（DB → 文件）

删除暂存/重置会话后，`sync_files` 拉 DB 场景时写入：

- `parent_id` = DB 数字 id  
- `parent_name` = 由 `id→name` 反查  

这样父级下拉可立刻恢复「仅顶级」列表。

## 前端入口

- `web/script_writer.html`：`#loc-parent` / `#new-loc-parent` 为 `<select>`
- `web/js/script_writer.js`：`loadTopLevelParentOptions` / `isTopLevelLocation` / `resolveParentName`

## 相关代码

- `api/script_writer.py`：`submit-to-database` 场景两阶段；`sync_files` 写 parent
- `script_writer_core/mcp_tool.py`：`create_location_json` / `update_location_json` 支持 `parent_name`
