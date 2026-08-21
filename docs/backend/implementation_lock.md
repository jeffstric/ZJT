# 固定供应商（失败不切换）

首页「用户设置 → 服务商偏好」支持两种供应商语义：

| 模式 | 如何设置 | 提交时 | 失败后 |
|------|----------|--------|--------|
| 默认 | 下拉保持「系统自动选择」 | 按 `sort_order` 选可用实现方 | 可切换其他供应商（受管理端总开关约束） |
| 首选 | 只选供应商，不勾固定 | 优先用所选实现方；不可用则降级 | 可切换其他供应商 |
| 固定 | 选供应商并勾选「固定此供应商」 | 只允许所选实现方；不可用则直接失败 | **禁止** `implementation_retry`，终态失败 + 原额退费 |

固定只约束「同一模型下的实现方」，不改变模型选择。社区版不能选供应商，行为不变。

## 存储

`users.implementation_preferences` JSON（当前激活组）增加 `locks`，**不改变** `preferences` 的 string 值：

```json
{
  "groups": {
    "1": {
      "name": "默认配置",
      "preferences": {
        "grok_image_to_video": "grok_duomi_v1"
      },
      "locks": {
        "grok_image_to_video": true
      }
    }
  }
}
```

兼容：无 `locks`、key 缺失、或 lock=true 但没有对应 preference → 视为未固定。清除偏好时同时删除 lock。无需 Alembic 迁移。

## 任务快照

创建 `ai_tools` 时，若用户固定且落库 `implementation` 就是该实现方，则写入：

```json
{ "implementation_lock": true }
```

字段名见 `config/constant.py::IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY`。缺省 = 未固定。用户事后取消固定，不会让已提交任务重新开始换供应商。

无快照的历史任务：失败处理回退读取用户当前 lock。

## 失败处理优先级

```
管理端 retry_settings.global_enabled = false → 全站不切换
管理端开启 且 extra_config.implementation_lock=true → 不切换
管理端开启 且 无快照、用户当前 lock=true → 不切换
否则 → 现有 implementation_retry（最多再试 3 家）
```

同实现方内部重试（RunningHub 槽位退避、驱动内轮询、人脸遮盖 `param_prepare`）不受影响。

## API

`GET /api/user/implementation-preferences` 增加 `data.locks`。

`PUT /api/user/implementation-preference`：

```json
{ "task_key": "grok_image_to_video", "implementation_name": "grok_duomi_v1", "locked": true }
```

`locked` 默认 `false`。`locked=true` 但未选实现方 → 400。

`DELETE /api/user/implementation-preference?task_key=` 同时清除偏好和 lock。

企业版真实落库；社区版 demo 路由接受字段但不保存。

## 提交期 fail-fast

`VideoDriverFactory._get_implementation_for_user`：固定且实现方不可用（未配置 / 已禁用）时不降级，`_last_create_error.reason = FIXED_IMPLEMENTATION_UNAVAILABLE`。

首选模式仍降级（`tests/drivers/test_driver_factory.py::test_user_preference_unavailable_falls_back`）。

## 计费

扣费仍按所选实现方。失败按扣费流水原额退还，不会走供应商切换差价结算。

## 作用范围

用户级设置，分镜 / 营销智能体 / 工作流 / CLI 只要走同一 `user_id` 的实现方选择都会遵守。
