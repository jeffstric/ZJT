# 2026-09-13 SyncTask worker fork 继承七牛线程池假超时事故记录

## 现象

ai_tools 任务 47603（seedream5_volcengine_v1 图片编辑，带参考图）2026-09-13 08:22:35
进入 SyncTask worker（pid 2287881）后，打出「上传图片到图床」日志（`utils/image_upload_utils.py:327`）
再无下文，**精确 120 秒**后报 `图片上传到CDN超时`，重试 6 次同形态失败，最终 status=-1。

七牛日志（`logs/qiniu_upload.2026-09-13.log`）中该 key（`2026-09-13/08/1789258955_5fe8eabc.png`）
**连「[七牛云] 开始上传文件」都没有**——上传任务从未执行。同日七牛其他时段上传全部秒级成功，
排除网络/凭证问题。与 2026-09-08 任务 45498（当时只修了 logging 锁继承）同根因复发。

## 根因

`ProcessPoolExecutor`（`task/sync_task_executor.py`，未指定 `mp_context`，Linux 默认 fork）
懒 fork worker 时，子进程经 `utils/file_storage/factory.py` 模块级单例缓存继承父进程的
`QiniuFileStorage`，其 `ThreadPoolExecutor(4)` 在子进程必然失效：

- Python 3.13 `concurrent/futures/thread.py::_adjust_thread_count`：空闲信号量
  `acquire(timeout=0)` 成功即 return 不建线程；token 由 worker 空闲时 release 且永不回收。
- 父进程**用过**的执行器，fork 瞬间带着假 token（≥1）+ `_threads` 里的死 Thread 对象
  （`len(_threads)` 已达 max_workers）被快照进子进程。
- 子进程首个 `submit` 消费假 token → 跳过建线程 → 任务入队无人消费 →
  上层 `asyncio.wait_for(storage.upload_file(...), timeout=120)` 假超时。

**为什么同批 fork 的其他 worker 能成功**：`qiniu_long_term`（zjt 桶，media_cache 路径）
在父进程只 `_init_storage` 建过实例、从未上传（token=0），子进程正常新建线程；
而默认 `qiniu`（jeffstric 桶，`_upload_one_to_cdn` 路径）被父进程 01:53–03:26
工作流首尾帧上传用过，毒化。

## 修复项

`_enterprise_sync_worker_init`（worker initializer，社区版 early-return 之前）调用
`reset_file_storage()` 清空工厂单例缓存，子进程首次 `get_file_storage()` 新建干净线程池。
若 reset 卡在 fork 瞬间被持有的 `_storage_lock`（微秒级窗口），90s 初始化看门狗
`os._exit(70)` 自杀，父进程清理死亡 worker 并补 fork，自愈闭环。

## 已知盲区（本次不覆盖）

修复只清理工厂单例缓存，以下 fork 继承点未被覆盖，当前未爆属于使用路径侥幸：

1. **`utils/media_cache.get_cache_manager()` 模块级懒单例**：父进程启动时已创建，
   `self._storage` 直接持有旧存储对象，reset 工厂缓存救不了它。当前
   `qiniu_long_term` 执行器在父进程从未上传（token=0）故未爆；若调度器进程日后
   经 media_cache 上传过文件，子进程缓存上传将同样假超时。
2. **`utils/image_upload_utils._SYNC_WRAPPER_EXECUTOR`**（模块级 4 worker）：
   同样被 fork 继承。子进程无 running loop 时 `_run_coro_sync` 走 `asyncio.run`
   直跑分支暂不经过它；但父进程在异步上下文（web 接口）调过一次 `_run_coro_sync`
   的 executor 分支后它即毒化，之后子进程所有同步包装排队假超时（185s 档）。

彻底方案（后续评估）：`ProcessPoolExecutor(..., mp_context=multiprocessing.get_context("spawn"))`
消除一切 fork 继承问题；或把 initializer 升级为统一的「fork 继承状态重置」函数
（storage 工厂 + 上述两个盲区一并重置）。

## 验证

- `python -m py_compile task/sync_task_executor.py`
- `python -c "import task.sync_task_executor"`（无循环依赖）
- `python scripts/lint_blocking_calls.py`（无新增违例）

线上生效需重启服务；重启本身也会重置父进程状态，生效后首次带参考图任务即验证路径。
