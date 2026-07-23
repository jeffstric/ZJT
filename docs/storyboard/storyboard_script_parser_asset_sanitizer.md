# 剧本拆分资产引用清洗

`llm/script_parser.py` 在大模型返回 JSON 后，会对**道具**与**场景**两类资产引用做一次确定性清洗，避免模型把数据库和原始剧本中都不存在的资产写进分镜数据。两层清洗分别在 `sanitize_parsed_prop_references` 与 `sanitize_parsed_location_references` 中实现，调用顺序紧跟 JSON 解析成功之后（日志文件 `..._06_prop_sanitized.json`、`..._07_location_sanitized.json`）。

## 道具引用清洗

避免模型把数据库和原始剧本中都不存在的道具写进分镜提示词。

规则：

- `props_db_id` 只有在命中数据库已有道具 ID 时才保留。
- 如果道具名与数据库道具唯一匹配，例如 `哨子` 唯一匹配 `裁判哨子`，会规范为数据库道具名并补上 `props_db_id`。
- 如果道具不在数据库中，但名称明确出现在原始剧本文本里，会作为新道具保留，`props_db_id` 为 `null`。
- 如果道具既不在数据库中，也没有出现在原始剧本里，会从 `props` 和每个镜头的 `props_present` 中移除。
- 分镜文本中的无效 `〖〖道具名〗〗` 标记会被去掉外层标记，避免后续参考图匹配把它当成可用道具；有效道具标记会保留并规范为数据库道具名。

## 场景引用清洗

避免模型编造数据库根本不存在的 `location_db_id`，或把剧本新场景当作可用场景。注意：发给大模型的 prompt 里 `ID: {loc.id}` 就是**数据库主键**（来自 `LocationModel.get_tree_by_world`），大模型应据实回填 `location_db_id`；`location_id`（如 `loc_003`）只是大模型自造的解析内部 ID，用于 locations 数组与 shot 的引用关联。

策略：**三分支**。规则：

- **已匹配 DB**：`location_db_id` 对照数据库主键集合核实，或按名称兜底（精确匹配 → 唯一后缀模糊匹配）；命中则修正为数据库真实 id/name。
- **新场景/子场景（`location_db_id` 为 null）**：**保留**（不再丢弃），携带 `parent_id`（内部 loc_xxx）、`level`、`description`、`atmosphere`、`environment_sound`、`background_music`，由后续 `StoryboardLocationBootstrapService.bootstrap()` 负责入库与 id 回填。详见 [子场景 Location 资产化](storyboard_subscene_location_asset.md)。
- **编造假 id（非 null 但 DB 不存在）**：丢弃，防幻觉穿透。
- 数据库场景树（`get_tree_by_world` 返回 `{id, name, children}`）在清洗前先展平（`_flatten_db_locations`）再核实。
- `shot.location_id` 指向被丢弃（编造假 id）的 location 或本就悬空引用时，**置为 `null`**；指向保留的新子场景时**不再置空**。
- 调试字段：`parsed_data['metadata']['has_unpersisted_locations']` / `unpersisted_location_count`，仅用于日志，不影响旧结构。

典型场景：大模型返回 `loc_003 / 结冰后的糖浆陷阱区域`，其 `location_db_id` 是编造的、数据库也无同名场景 → 该 location 被移除；引用它的分镜 `location_id` 置 null。若 `location_db_id` 为 null（新子场景）→ 保留，等待 bootstrap 入库。

## 共同原则

这层清洗是对提示词约束的兜底。提示词仍会要求大模型不要幻想资产（道具/场景），但最终以这里的后处理结果为准。
