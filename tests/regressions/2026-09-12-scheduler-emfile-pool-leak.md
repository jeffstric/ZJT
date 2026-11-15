---
id: 2026-09-12-scheduler-emfile-pool-leak
patch: patches/2026-09-12-scheduler-emfile-pool-leak.json
tests:
  - tests/task/test_sync_task_pool_reclaim.py
replay_tests:
  - tests/task/test_sync_task_pool_reclaim.py::test_rebuild_terminates_and_reaps_workers
  - tests/task/test_sync_task_pool_reclaim.py::test_rebuild_survives_per_worker_reclaim_error
  - tests/task/test_sync_task_pool_reclaim.py::test_submit_on_broken_pool_reclaims_old_workers_then_resubmits
feature_ids:
---

## 当时坏成什么样

调度进程把文件描述符漏进子进程，最终 `EMFILE`（打开文件过多）。进程池坏掉后，同步任务大面积失败。

## 代码大概在哪

- `task/sync_task_executor.py` 的进程池回收
- 测试在 `tests/task/test_sync_task_pool_reclaim.py`

## 怎么操作、怎样算没修好

改坏补丁把 `task/sync_task_executor.py` `_rebuild_pool_locked()` 里的「先快照 `_processes` 再 shutdown」倒回成「shutdown 之后才取 `_processes`」——CPython 的 `shutdown()` 无条件把它置 None，回收拿到空列表变空操作，回到当年「旧 worker 无人回收、进程与管道 FD 随每次重建累积」的行为。

怎样算没修好：`tests/task/test_sync_task_pool_reclaim.py` 里 `test_rebuild_terminates_and_reaps_workers`（重建必须终止/收尸合作、顽固、已死三类 worker）、`test_rebuild_survives_per_worker_reclaim_error`（单 worker 终止失败不阻断重建）、`test_submit_on_broken_pool_reclaims_old_workers_then_resubmits`（submit 触发重建时旧 worker 必须被回收）任一没红，即改坏没被抓住，测试防线是空的。

## 永久测试

- `tests/task/test_sync_task_pool_reclaim.py`
