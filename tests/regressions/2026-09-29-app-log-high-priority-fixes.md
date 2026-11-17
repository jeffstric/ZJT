---
id: 2026-09-29-app-log-high-priority-fixes
patch:
tests:
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

本条是索引，不直接回放。三件事各拆一条，见：

- `2026-09-29-pipeline-stuck-step`（卡死步骤回收，且不得抢跑终态化）
- `2026-09-29-grid-image-auth-retry`（401/403 连续达阈值必须终止）
- `2026-09-29-expired-reference-404`（参考图 404/410 转用户错误，不算 5xx）

## 永久测试

- `tests/task/test_pipeline_stuck_step_recovery.py`
- `tests/task/test_grid_image_auth_failure.py`
- `tests/drivers/test_gpt_image_expired_reference.py`
