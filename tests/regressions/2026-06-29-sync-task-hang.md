---
id: 2026-06-29-sync-task-hang
patch:
tests:
  - tests/task/test_sync_task_stale_recovery.py
  - tests/utils/test_image_upload_utils_timeout.py
  - tests/scripts/test_lint_blocking_calls.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

同步任务的 worker 卡死后，进程池槽位不释放。槽位满了，新任务不再发出外部请求，外部请求日志能空大约两小时。图床上传的 `future.result()` 没有超时，底层卡住时调用方会一直等。

## 代码大概在哪

- `task/sync_task_executor.py`
- `utils/image_upload_utils.py`
- `scripts/lint_blocking_calls.py`

## 怎么操作、怎样算没修好

还没有交给 AI 重测，也还没有改坏补丁。同步任务长时间没有任何外部请求日志，或者上传线程永不返回，都算没修好。

## 永久测试

- `tests/task/test_sync_task_stale_recovery.py`
- `tests/utils/test_image_upload_utils_timeout.py`
- `tests/scripts/test_lint_blocking_calls.py`
