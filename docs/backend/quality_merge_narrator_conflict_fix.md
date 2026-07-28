# quality 模式合并阶段 name 冲突死锁修复

## 背景

效果模式（`sequence_mode=quality`）剧本拆分在分段全部完成后合并阶段，频繁抛出致命错误：

```
quality_merge_invalid: entity name conflict: 旁白 uses char_016, expected char_4838
```

段数据已固化落库，resume 必然复现同一冲突，用户无法脱困（如生产 task 218，
21:07 与 21:28 两次 resume 报完全相同的错）。

## 根因

1. quality 模式分段由 `asyncio.gather` **并发执行**，并发段彼此看不到对方的
   实体登记，因此段级 ID 不可信任：同一实体会被不同段分配不同 ID（甚至同一
   ID 被复用指向不同实体）。
2. “旁白”这类角色**规划真源 `compiled_registry` 未登记**（只登记了主角等
   正式角色），但**几乎每段都会冒出**，成为冲突高发户。task 218 实测：
   - 真源只有 12 个球员角色（`char_001`~`char_012`），无“旁白”；
   - 段 2 把“旁白”登记成畸形号 `char_4838`，段 3 登记成正常号 `char_016`，
     段 5 又登记成 `char_015`。
3. 早期 `enterprise/services/script_split_quality/strategy.py` 的
   `_merge_entity_collection` 对“name 相同 ID 不同”**直接抛致命错误**，
   经 `script_split_engine.py` 转成 `quality_merge_invalid`。

## 与 commit `8361fe8e` 的关系

该 commit 本应修复此问题（message 标题即“消除并发段 ID 冲突死锁”），且在
`services/script_split_registry.py` 写好了根治函数 `renumber_entities_by_name()`
并配了 5 个单测。**但关键一步未落地**：commit message 明确说要“删除 enterprise
包里抛致命错误的 `_merge_entity_collection`，改用 `renumber_entities_by_name`”，
而 `enterprise/` 在 `.gitignore:24` 中（commit 自己标注了“enterprise 包，gitignore”），
**该包的改动无法进入版本库**。线上 enterprise 包仍是旧版，`renumber_entities_by_name()`
写好后从未被生产代码调用，bug 原样复现。

## 修复方案

改造 `_merge_entity_collection`，对 name 冲突**收敛而非抛错**：

| 分支 | 行为 | 是否改动 |
|---|---|---|
| ID 命中真源 `by_id` | 回归真源身份 + 并入段补充字段 | 不变 |
| name 命中已登记实体 | **旧：抛 `entity name conflict` → 新：收敛到先来后到的 canonical，旧 ID 记入 `id_map`，补充字段并入 canonical** | ✅ 改动 |
| 真源外新实体 | 直接 append，保留段合法号 | 不变 |

`repair_merged_result` 三类实体（characters/locations/props）合并共享一个
`id_map`，合并后用 `_resolve_id_map_chains` 解析替换链 + `_apply_id_map_inplace`
对整棵 parsed 树单趟精确重写所有旧 ID 引用（`props_present`/`characters_present`/
`focus_character_ids`/`location_id`/`dialogue.character_id`/`spatial_layout` 全部
引用等），杜绝收敛后 shot 残留旧 ID 形成悬空引用。

### 为何不直接换用 `renumber_entities_by_name`

`renumber_entities_by_name` 是「激进全树重发号」工具，对两类场景会误伤：
- ID 已对齐真源、仅 name 变体（应回填真源身份，不该重发号）；
- 段新实体自带合法号（应保留，不该漂移）。

故 quality 合并路径采用 `_merge_entity_collection` 内联收敛，`renumber_entities_by_name`
保留备用。speed 模式串行推进 + 跨段累积 `accepted_registry`，段间 ID 一致性已由
`rewrite_segment_entity_ids` 在段生成阶段保证，合并阶段无需收敛。

## 验证

- 用 task 218 真实段数据复跑合并：旁白从 3 个条目（char_4838/char_016/char_015）
  收敛为单条 `char_4838`，shot 引用全部重写，不再抛 `quality_merge_invalid`，
  无悬空 character_id 引用。
- `enterprise/tests/services/test_script_split_quality.py`：25 passed
  （含新增 3 个回归测试：旁白收敛、补充字段并入、shot 引用重写）。
- `tests/services/test_script_split_engine.py`：无新增回归（既有 6 个失败
  与本次改动无关，已对比确认）。

## 部署注意

`enterprise/` 被 `.gitignore` 忽略，本次对
`enterprise/services/script_split_quality/strategy.py` 的改动需走 enterprise 包
构建/打包流程（`scripts/build_enterprise.py`）部署上线。
