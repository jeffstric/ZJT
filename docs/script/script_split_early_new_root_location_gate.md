# 新顶层场景提前硬门禁（摘要）

完整设计见：

[`docs/superpowers/specs/2026-07-17-script-split-early-new-root-location-gate-design.md`](../superpowers/specs/2026-07-17-script-split-early-new-root-location-gate-design.md)

## 为什么要做

效果模式可能在**规划注册表 / space_unit**里登记新顶层地点，但分段 `locations[]` 不落地；段级硬门禁扫不到，合并 `repair_merged_result` 才把规划实体补回并失败——此时八段 token 已花完，难以挽救。

## 四层门禁

| 层 | 时机 | 作用 |
|---|---|---|
| L0 | 规划编译（quality） | 对照世界场景树绑定 `location_db_id`；无父且未匹配 DB → 立刻失败并重规划 |
| L1 | 逐段（扩展） | `locations` + 本段 `space_units`/镜头引用拉起的 registry 地点 |
| L2 | 合并 | 全量图兜底 |
| L3 | 发布前 | 防恢复/并发绕过 |

## 规划 schema

`entities.locations[]` 可选 `parent_location_key`：

- **能复用世界已有场景（name 匹配）时：不要写 parent_location_key**，数据库父子由后端接管；瞎猜父级会触发 `location_parent_conflict`。
- 只有「未匹配 DB 的新地点」才填 parent，且父链最终可达已有 DB 场景。
- 每个 `spatial_world.space_unit` 的 name/location_key 必须对应 `entities.locations` 已有项。

## 状态

已实现：

- `services/location_structure_guard.py`：`bind_planned_locations` / `validate_segment_location_structure_extended` 等
- `enterprise/.../contract.py`：`compile_quality_plan(..., db_locations=)` L0 硬门禁
- `services/script_split_engine.py`：`step_plan` 注入 DB + 旧 plan 复检；段级扩展校验；合并漏检日志；规划失败 feedback 对 parent_conflict / space_unit unbound 追加 hint
- `enterprise/.../planner.py`：`parent_location_key` 规则（复用勿写 parent）+ space_unit 绑定提示
