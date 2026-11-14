---
id: 2026-09-13-sync-worker-fork-qiniu-executor
patch:
tests:
replay_tests:
feature_ids:
---

## 当时坏成什么样

Linux 上同步 worker 用 fork 继承了父进程用过的七牛线程池。子进程里上传任务进了队列却没有线程执行，精确 120 秒后报上传超时，重试同样失败。七牛日志里根本没有开始上传。

## 代码大概在哪

- `task/sync_task_executor.py` 的 worker 初始化
- `utils/file_storage/factory.py` 的 `reset_file_storage()`

## 怎么操作、怎样算没修好

还没有单独的永久测试。事故记录里的验证只跑了阻塞调用 lint，没有锁住「fork 之后必须丢掉继承来的线程池」。带参考图的同步生图若再次卡满 120 秒且七牛没有开始上传，就是这个 bug。

## 永久测试

还没有。
