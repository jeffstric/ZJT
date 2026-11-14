---
id: 2026-09-20-sync-worker-spawn-no-driver-registry
patch:
tests:
  - tests/task/test_sync_task_worker_init.py
  - tests/task/test_sync_task_pool_reclaim.py
  - tests/task/test_sync_task_stale_recovery.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

同步 worker 改成 spawn 之后，子进程没有注册视频驱动。任务提交时报找不到驱动，生图生视频失败。

## 代码大概在哪

- 同步 worker 的进程初始化，测试在 `tests/task/test_sync_task_worker_init.py`

## 怎么操作、怎样算没修好

还没有改坏补丁。worker 启动后必须带上驱动注册表，不能只在父进程里注册。

## 永久测试

- `tests/task/test_sync_task_worker_init.py`
- `tests/task/test_sync_task_pool_reclaim.py`
- `tests/task/test_sync_task_stale_recovery.py`
