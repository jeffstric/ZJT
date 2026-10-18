# Sync worker 进程池 fork → spawn 切换记录（2026-10-18）

> 动机与完整调查见 `docs/backend/incidents/2026-09-13-sync-worker-fork-qiniu-executor.md`（同类事故，文末"彻底方案"即本改动）与 2026-10-18 zjt_trial 生产调查（seedream 下载写盘连续精确 30s 假超时，网络/磁盘实测正常）。

## 结论

`SyncTaskExecutor` 的两处 `ProcessPoolExecutor`（`start()` 与 `_rebuild_pool_locked()`，`task/sync_task_executor.py`）显式传入 `mp_context=multiprocessing.get_context("spawn")`，默认 spawn，可用动态配置回退：

- 配置键：`sync_task.worker_start_method`，取值 `spawn`（默认）/ `fork`；
- 非法值回退 spawn；Windows 不支持 fork，配了 fork 也自动回落 spawn；
- 读取时机：每次建池（启动 / 池重建）各读一次——改配置后**重启生效**，或等下次池自然重建（broken/stale 触发）后生效；
- 默认值收口在 `config/constant.py` 的 `SYNC_WORKER_DEFAULT_START_METHOD = "spawn"`。

## 为什么切（根因链）

fork 只复制调用线程，不复制线程，但会快照全部锁与线程池簿记。父进程（scheduler）用过的模块级 `ThreadPoolExecutor` 被 fork 进 worker 后，"空闲信号量假 token + `_threads` 死对象"使首个 `submit` 跳过建线程、任务入队永不被执行：

- **2026-09-13**：`QiniuFileStorage` 线程池 → 七牛上传 120s 假超时（initializer 的 `reset_file_storage()` 为定点修复）；
- **2026-10-18**（zjt_trial）：`utils/download_io_pool` → seedream 下载写盘连续精确 30s 假超时（`DOWNLOAD_WRITE_CHUNK_TIMEOUT`），5 个 seedream 任务全部中招，其中 task 1186 叠加 180s stale 预算被误杀（该 stale 阈值修复见 `docs/backend/incidents/2026-10-18-seedream-stale-premature-kill.md`，分支 develop_f1040）。已用独立实验复现 fork 子进程内 submit 永久 HANG；
- 更早的同类：2026-09-08 继承锁死锁、2026-09-12 管道/FD 继承放大（EMFILE）。

spawn worker 是全新解释器，不继承任何父进程内存状态，上述整类问题结构性消失。事故文档 9-12/9-13 早已把该方案列为"彻底方案（后续评估）"，本次落地。

## 为什么现在能切（此前障碍已消除）

1. **worker 引导已 spawn 兼容**：2026-09-20 事故（Windows 本就 spawn，worker 内驱动注册表为空）修复后，initializer `_enterprise_sync_worker_init` 补齐 `init_unified_config() + register_all_drivers()`，Windows 日常在跑该路径（日志可见 `video drivers registered in worker (pid=..., count=98)`）；
2. **主模块重导入无副作用**：生产拓扑下 executor 只在 scheduler 进程 `start()`（`task/scheduler.py` 的 `init_scheduler`，由 `scripts/running/run_scheduler.py` 拉起）。spawn 子进程以 `__mp_main__` 重导入的 `run_scheduler.py` 模块级只有 stdlib import、`sys.path.insert`（spawn 兼容，已实测）与函数定义；9-12 文档担心的 `from server import app` 在 `__main__` 守卫内，重导入不执行。例外：`python server.py` 单进程 dev 模式下 server.py 模块级副作用会被重导入——与 Windows（本就 spawn）行为一致，非新增风险；
3. **enterprise 侧无需改动**：license runtime（`enterprise/services/license/runtime.py`）的 pid 漂移检测在 spawn 下天然走"新建 manager"分支（新解释器 `_manager is None`）；其余 pid 写文件锁按 mtime 判旧。enterprise 仓库本次零改动。

## 行为变化与影响面

| 项 | fork（旧默认，Linux） | spawn（新默认） |
|---|---|---|
| worker 冷启动 | 毫秒级 | 秒级（全新解释器 + 模块导入 + initializer 引导）；长寿池摊销，仅池创建/重建后的首个任务多等几秒 |
| 平台 | Linux 默认 fork；Windows/macOS 本就 spawn | 三平台统一 spawn（Windows/macOS 无变化，本次实际只改 Linux） |
| fork 继承类缺陷 | 存在（两次生产事故） | 结构性消失 |
| 内存 | COW 共享父进程 | 每 worker 独立解释器（与 Windows 现状一致） |

注意点：

- **stale 时钟**：从 submit 起算（`check_results`），spawn 冷启动时间计入其中。seedream 两驱动的 stale 预算在 develop_f1040 已从 180s 提到 600s，**建议两个分支一同上线**；若只上 spawn 不上 600s，冷启动会进一步压缩 180s 预算的余量；
- **90s initializer 看门狗**只覆盖 initializer 自身执行（不含解释器启动+模块导入，后者无看门狗、由 stale 预算兜底）；Windows 日常已验证该量级，未改动。

## 配套双保险：download_io_pool pid 守卫

`utils/download_io_pool.py` 改为**惰性创建 + pid 守卫**（与 `model/database.py` 的 `_pool_pid` 同构）：`get_download_io_executor()` 检测 `os.getpid()` 漂移即丢弃继承池并新建。价值：

- 回退 `worker_start_method=fork` 期间，下载写盘不再假超时（2026-10-18 事故的直接免疫）；
- 防御仓库内其他直接 fork 场景（不经过 sync executor 的）。

fork 模式下其余盲区（`media_cache` 单例持有的 storage 引用、`image_upload_utils._SYNC_WRAPPER_EXECUTOR`）仍靠 initializer 的 `reset_file_storage()` + 使用路径侥幸；长期回退 fork 不建议。

## 回归测试

- `tests/task/test_sync_task_start_method.py`（新增 11 用例）：配置解析（spawn/fork/规范化/非法回退/无 fork 平台回退）；`start()`/`_rebuild_pool_locked()` 的 mp_context 传递（fake seam）；**真实 spawn worker 内 download_io_pool submit 秒回**（事故场景端到端回归）；
- `tests/utils/test_download_io_pool_pid_guard.py`（新增 3 用例）：同 pid 复用；pid 漂移重建；**真实 fork 子进程内（父进程用热池后）submit 秒回**（事故机制直接复现）；
- 存量回归：`tests/task/`（394 passed；`test_mock_channels` 2 个失败为存量环境问题，干净树上同样失败）；`temp/verify_spawn_download_pool.py` 为独立验证脚本（不入库），实测 spawn worker 冷启动 ~50ms、pid 隔离、submit 即时。

## 回退手册

1. 后台动态配置改 `sync_task.worker_start_method = fork`；
2. 重启服务（或等下次池自然重建）；
3. download_io_pool pid 守卫保证回退期间下载写盘不假超时；若回退期间再做七牛上传等其它路径，注意 9-13 盲区仍在（reset_file_storage 已覆盖工厂单例）。
