---
id: 2026-09-12-scheduler-emfile-pool-leak
patch:
tests:
  - tests/task/test_sync_task_pool_reclaim.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

调度进程把文件描述符漏进子进程，最终 `EMFILE`（打开文件过多）。进程池坏掉后，同步任务大面积失败。

## 代码大概在哪

- `task/sync_task_executor.py` 的进程池回收
- 测试在 `tests/task/test_sync_task_pool_reclaim.py`

## 怎么操作、怎样算没修好

还没有改坏补丁。坏掉的 worker 必须能被回收并重建，不能占着池子不放。

## 永久测试

- `tests/task/test_sync_task_pool_reclaim.py`
