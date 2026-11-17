---
id: 2026-09-29-grid-image-auth-retry
patch: patches/2026-09-29-grid-image-auth-retry.json
tests:
  - tests/task/test_grid_image_auth_failure.py
replay_tests:
  - tests/task/test_grid_image_auth_failure.py::TestPollLoopAuthBranch::test_terminates_after_consecutive_limit
  - tests/task/test_grid_image_auth_failure.py::TestPollLoopAuthBranch::test_single_401_keeps_task_alive
feature_ids:
---

## 当时坏成什么样

四宫格轮询遇到 401/403（auth_token 快照失效）后只告警不终止，连续 105 次 401（每 10 秒一条 WARNING）无限重试，任务不结束。

## 代码大概在哪

- `task/grid_image_task.py` 的 `process_grid_image_tasks` 轮询 except 分支、`_is_auth_failure`、`_terminate_task_for_auth_failure`
- 测试在 `tests/task/test_grid_image_auth_failure.py`

## 改坏补丁动了哪几行

改坏补丁把轮询 `except requests.RequestException` 里的认证失败分支（`_is_auth_failure` 识别、连续计数、达阈值 `_terminate_task_for_auth_failure` 终态化）整段删掉，改回当年「一律当网络抖动、只 WARNING 继续重试」的写法——401 从此不再计数、永不终止。

## 怎样算没修好

`test_terminates_after_consecutive_limit`（连续 LIMIT 次 401 后必须写入 FAILED 终态）和 `test_single_401_keeps_task_alive`（单次 401 必须累加计数而非静默吞掉）任一没红，即改坏没被抓住，测试防线是空的。非认证错误清零计数的用例在改坏下仍绿（pop 逻辑保留），能证明改坏只回退了认证分支。
