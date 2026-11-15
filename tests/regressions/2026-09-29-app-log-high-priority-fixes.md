---
id: 2026-09-29-app-log-high-priority-fixes
patch:
tests:
  - tests/task/test_pipeline_stuck_step_recovery.py
  - tests/task/test_grid_image_auth_failure.py
  - tests/drivers/test_gpt_image_expired_reference.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

同一天日志里有三件独立的事：流水线步骤卡死不回收；四宫格轮询遇到 401 后无限重试；参考图 404 被报成服务异常。

## 代码大概在哪

- 流水线卡死回收
- `task` 里四宫格的认证失败处理
- GPT 图参考图过期，404/410 应是图片过期而不是 5xx

## 怎么操作、怎样算没修好

还没有改坏补丁。卡死步骤要能回收且不抢跑终态；401/403 不能无限重试；参考图 404/410 不能当成服务挂了。

## 永久测试

- `tests/task/test_pipeline_stuck_step_recovery.py`
- `tests/task/test_grid_image_auth_failure.py`
- `tests/drivers/test_gpt_image_expired_reference.py`
