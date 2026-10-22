# Sync worker 进程池 fork → spawn 切换记录（2026-10-18）

> 动机与完整调查见 `docs/backend/incidents/2026-09-13-sync-worker-fork-qiniu-executor.md`（同类事故，文末"彻底方案"即本改动）与 2026-10-18 zjt_trial 生产调查（seedream 下载写盘连续精确 30s 假超时，网络/磁盘实测正常）。

## 结论

`SyncTaskExecutor` 的两处 `ProcessPoolExecutor`（`start()` 与 `_rebuild_pool_locked()`，`task/sync_task_executor.py`）显式传入 `mp_context=multiprocessing.get_context("spawn")`，默认 spawn，两级开关可回退：

- **动态配置**：`sync_task.worker_start_method`，取值 `spawn`（默认）/ `fork`；
- **环境变量**：`SYNC_TASK_WORKER_START_METHOD`（部署层应急开关，优先级最高，DB 不可达时也能切；值非法时忽略并回退动态配置）；
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

## 模块级副作用审查（切换前已执行，2026-10-18）

spawn worker 会重新执行 `task.sync_task_executor` 依赖链的模块级代码，按迁移方案第四节做了两项审计：

1. **`python -X importtime -c "import task.sync_task_executor"`**：累计 ~129ms（最重链路 `utils.file_storage.qiniu_storage` → `qiniu`/`requests` 合计 ~79ms，均为纯定义无副作用）；spawn worker 导入成本亚秒级。
2. **进程内实证**（import 后检查）：零新增线程（仅 MainThread）；`model.database._pool is None`（DB 池惰性，且有 pid 守卫）；fd 增量 +2~3（config YAML 读取，随即释放）；`VideoDriverFactory` 注册表 import 时为 0（注册是显式函数，2026-09-20 设计）。

结论：导入链无 DB 连接/线程启动/网络拉取类副作用，spawn 安全。已知例外：`utils/cdn_util.py` 等模块级 `ThreadPoolExecutor(...)`——对象创建本身不启动线程、spawn worker 各自新建无继承问题，无需改造。

## 上线验证清单（staging/生产手工项）

自动测试之外，spawn 生效需在真实环境逐项确认：

- [ ] **worker 形态证据**：`pgrep -f spawn_main` 能看到 worker 进程（fork worker 的 cmdline 与父进程相同，spawn 一眼可辨）；
- [ ] **首任务延迟**：记录池创建/重建后首个 sync 任务冷启动耗时（本机测试环境实测导入 ~50ms，生产含 initializer 全量引导预期秒级），确认任务 SLA 可接受；
- [ ] **七牛上传路径回归**：带参考图的生图任务连续通过（2026-09-13 事故 47603 同路径，≥3 例）；
- [ ] **seedream 下载路径回归**：Seedream 任务 result_url 落 `/upload/cache/...` 本地缓存（2026-10-18 事故路径）；
- [ ] **异常路径**：并发 > `max_workers` 排队正常；人为 kill -9 一个 worker 观察补位；stale 强杀（配合 develop_f1040 的动态配置压阈值法）走完 退款+整池重建+宫格重试 链路；
- [ ] **三平台**：Linux 生产、macOS/Windows 开发各过一轮（后两者本就 spawn，应零变化）。

**灰度顺序建议**（迁移方案第六节，默认值直接 spawn 时的替代节奏）：测试环境全量验证 → 生产低峰时段单实例重启 → 观察一个完整任务周期（含生图+生视频+数字人）→ 全量实例。回退抓手：环境变量 `SYNC_TASK_WORKER_START_METHOD=fork`（无需 DB）或动态配置同值，重启即生效。

## 观察期后的退役清单（后续独立 PR，本次不做）

spawn 稳定运行一个观察周期（建议 ≥2 周，覆盖各类任务路径）后可退役 fork 专属防御，纯删代码：

- `_reset_inherited_logging_locks()` 及 logging 锁重建；
- worker initializer 内的 `reset_file_storage()`（保留 `media_cache` pid 守卫）；
- scheduler 的 `register_at_fork` 信号重置分支；
- 事故文档中 fork"残余风险"章节改写为历史记录；届时 `sync_task.worker_start_method` 默认值与配置项本身也可评估移除。

## 回归测试

- `tests/task/test_sync_task_start_method.py`（12 用例）：配置解析（spawn/fork/规范化/非法回退/无 fork 平台回退）；环境变量优先级（覆盖动态配置/非法值忽略/未设置走动态配置）；`start()`/`_rebuild_pool_locked()` 的 mp_context 传递（fake seam）；**真实 spawn worker 内 download_io_pool submit 秒回**（事故场景端到端回归）；
- `tests/utils/test_download_io_pool_pid_guard.py`（新增 3 用例）：同 pid 复用；pid 漂移重建；**真实 fork 子进程内（父进程用热池后）submit 秒回**（事故机制直接复现）；
- 存量回归：`tests/task/`（394 passed；`test_mock_channels` 2 个失败为存量环境问题，干净树上同样失败）；`temp/verify_spawn_download_pool.py` 为独立验证脚本（不入库），实测 spawn worker 冷启动 ~50ms、pid 隔离、submit 即时。

## 回退手册

1. **前提（已有环境一次性）**：合入后需在后台执行一次「初始化配置」，把 `sync_task.worker_start_method`（已预置在 `config.example.yml` / `config_dev.base.yml` / `config_prod.base.yaml` / `config_unit.base.yml` 的 sync_task 段，经 base 深合并生效）种入 `system_config`——`init_default_configs()` 只从 YAML 取值入库，缺 YAML 键就跳过，后台列表也只显示已入库行；
2. 后台动态配置改 `sync_task.worker_start_method = fork`（或应急用环境变量 `SYNC_TASK_WORKER_START_METHOD=fork`，无需 DB）；
3. 重启服务（或等下次池自然重建）；
4. download_io_pool pid 守卫保证回退期间下载写盘不假超时；若回退期间再做七牛上传等其它路径，注意 9-13 盲区仍在（reset_file_storage 已覆盖工厂单例）。
