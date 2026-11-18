---
id: 2026-09-13-sync-worker-fork-qiniu-executor
patch: patches/2026-09-13-sync-worker-fork-qiniu-executor.json
tests:
  - tests/task/test_sync_task_worker_init.py
replay_tests:
  - tests/task/test_sync_task_worker_init.py::test_worker_init_resets_inherited_storage_singleton
feature_ids:
---

## 当时坏成什么样

Linux 上同步 worker 用 fork 继承了父进程用过的七牛线程池。子进程里上传任务进了队列却没有线程执行，精确 120 秒后报上传超时，重试同样失败。七牛日志里根本没有开始上传。

## 代码大概在哪

- `task/sync_task_executor.py` 的 worker 初始化
- `utils/file_storage/factory.py` 的 `reset_file_storage()`

## 怎么操作、怎样算没修好

改坏补丁把 `task/sync_task_executor.py` `_enterprise_sync_worker_init()` 里的 `reset_file_storage()` 调用整行删掉——worker 不再清空继承来的存储工厂单例缓存，回到当年「fork 继承的七牛线程池假 token 导致上传任务入队无人消费、120 秒假超时」的行为。

怎样算没修好：`tests/task/test_sync_task_worker_init.py::test_worker_init_resets_inherited_storage_singleton` 没红，即改坏没被抓住，测试防线是空的。该测试为效果断言：预塞哨兵实例进 `utils.file_storage.factory._storage_instances` 模拟 fork 继承的毒化单例，init 之后缓存必须为空——删除调用、把 `reset_file_storage` 改成空函数都会被抓住，不做真 fork。

## 永久测试

- `tests/task/test_sync_task_worker_init.py::test_worker_init_resets_inherited_storage_singleton`
