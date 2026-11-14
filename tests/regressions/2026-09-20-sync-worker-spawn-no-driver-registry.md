---
id: 2026-09-20-sync-worker-spawn-no-driver-registry
patch: patches/2026-09-20-sync-worker-spawn-no-driver-registry.json
tests:
  - tests/task/test_sync_task_worker_init.py
  - tests/task/test_sync_task_pool_reclaim.py
  - tests/task/test_sync_task_stale_recovery.py
replay_tests:
  - tests/task/test_sync_task_worker_init.py::test_worker_init_registers_video_drivers
feature_ids:
---

## 当时坏成什么样

同步 worker 改成 spawn 之后，子进程没有注册视频驱动。任务提交时报找不到驱动，生图生视频失败。

## 代码大概在哪

- 同步 worker 的进程初始化，测试在 `tests/task/test_sync_task_worker_init.py`

## 怎么操作、怎样算没修好

改坏补丁把 `task/sync_task_executor.py` `_enterprise_sync_worker_init()` 里的 `register_all_drivers()` 调用整行删掉——spawn 出的 worker 不再补建驱动注册表，`VideoDriverFactory._registered_drivers` 保持空字典，回到当年「sync_mode 任务报 Driver implementation not registered」的行为。

怎样算没修好：`tests/task/test_sync_task_worker_init.py::test_worker_init_registers_video_drivers` 没红，即改坏没被抓住，测试防线是空的。该测试 monkeypatch 拦截 `task.visual_drivers.register_all_drivers`，断言 worker 初始化（含社区版路径）恰好调用它一次，不做真 spawn。

## 永久测试

- `tests/task/test_sync_task_worker_init.py`
- `tests/task/test_sync_task_pool_reclaim.py`
- `tests/task/test_sync_task_stale_recovery.py`
