# 实现方算力前端下发机制与偏好扁平化修复

> 修复日期：2026-08-20　|　影响范围：`/api/system/task-configs` 用户偏好分支　|　状态：已修复

## 1. 现象

video_workflow.html 中，分镜组 / 分镜 / 生视频节点选择 grok 模型后，切换不同时长（6/10/15 秒），节点上的算力预估数值不发生变化。

## 2. 算力下发链路

前端不做任何本地价格公式，预估算力完全来自后端配置接口：

1. 前端 `web/js/task_config.js` `loadTaskConfigs()` 拉取 `GET /api/system/task-configs`；
2. 后端 `api/system.py` → `UnifiedConfigRegistry.get_frontend_config()`（`config/unified_config.py`）；
3. `_apply_user_preferences_to_tasks()` 决定每个任务下发的 `computing_power`：
   - **用户有实现方偏好**：优先查 `implementation_power_config` 表（管理端热调价），无记录则回退 `implementations` 列表；
   - **无偏好**：取 `implementations` 排序第一位的实现方价格。
4. 前端 `getComputingPower(key, duration)`：`computing_power` 为 **dict** 时按时长查表 `power[duration]`；为 **int** 时固定值，时长失效。

grok 等模型任务级价格为 0，价格全部按实现方配置为时长分档 dict（如慧梦 `{6:8, 10:14, 15:20}`）。

## 3. 根因

`_apply_user_preferences_to_tasks()` 偏好分支中，数据库返回分档价格时：

```python
# 修复前（缺陷）
impl_power = list(db_powers.values())[0]   # {6:8, 10:14, 15:20} → 8（首档 int，分档结构丢失）
```

分档 dict 被扁平化为首档 int 下发，前端拿到 int 后切换时长算力不再变化。

触发条件（两者同时满足）：

1. 用户 `users.implementation_preferences`（当前激活偏好组）中存在该任务的实现方偏好；
2. 偏好实现方在 `implementation_power_config` 表有分档价格记录（管理端按时长改过价）。

对比：`_get_implementations_info()`（无偏好路径的数据来源）对同一份 DB 数据正确保留了 dict，因此无偏好用户不受影响——这也是 seedance 2.0（无 DB 热调价记录/无偏好）表现正常的原因。

## 4. 修复

`config/unified_config.py` `_apply_user_preferences_to_tasks()` 与 `_get_implementations_info()` 对齐：

```python
# 修复后：分档优先保留完整 dict，固定价其次
duration_powers = {k: v for k, v in db_powers.items() if k is not None}
if duration_powers:
    impl_power = duration_powers
elif None in db_powers:
    impl_power = db_powers[None]
```

空值判断同步改为 `if not impl_power:`（覆盖 None / 0 / 空 dict）。

## 5. 验证

- 单测：`tests/config/test_unified_config_frontend.py`
  - `test_apply_user_preferences_duration_based_power`：断言由首档 int 更新为完整 dict；
  - 新增 `test_get_frontend_config_with_user_prefs_db_tiered_powers_keeps_dict`：get_frontend_config 层回归（注册假任务，不依赖运行时供应商配置）。
- 接口：`GET /api/system/task-configs` 带 token，grok 任务 `computing_power` 返回 `{"6": 8, "10": 14, "15": 20}`。
- 浏览器实测（本地 huimengi 实现方）：分镜 / 分镜组 / 生视频三种节点切换 6/10/15 秒，算力分别显示 8 / 14 / 20，随时长正确变化。

## 6. 相关注意

- **多米实现方 6s 与 10s 同价（均为 8）**：`grok_duomi_v1` 定价配置 `{6:8, 10:8, 15:16}`，前端切换 6↔10 算力不变属定价本身，15 秒会变 16。如需区分请走管理端改价。
- **分镜扣费未传 implementation**：`api/storyboard.py` `generate-video` 算力计算只传 duration，固定按默认实现方价格扣费，与实际执行供应商可能不一致（与 [退费扣返一致性修复](./退费扣返一致性修复.md) 同源的扣费侧问题），待另行修复。
