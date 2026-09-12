# 2026-09-12 调度器 FD 耗尽（EMFILE）事故记录

> 所有数据均经现场 `/proc/<pid>/fd` 采样与 `logs/app.2026-09-12.log` 直接核实。事故期间 scheduler 进程（run_scheduler.py，pid 1717541）FD 打满 1024/1024 并于 ~16:16 崩溃退出。

## 概述

| 项目 | 内容 |
|------|------|
| 事故定性 | 调度器进程文件描述符耗尽（`[Errno 24] Too many open files`），全调度任务失效直至进程崩溃 |
| 触发报错 | `task.async_task_submission - ERROR - 处理待提交异步任务失败: [Errno 24] Too many open files`，伴随 `_UnixSelectorEventLoop object has no attribute '_ssock'`（FD 耗尽导致 `asyncio.new_event_loop()` 半初始化失败后的 `__del__` 噪音，非独立 bug） |
| 泄漏构成 | 进程 FD 表 1024 项中 **996 个为匿名管道 pipe**；另有 **360 个 fork 卡死子进程**（同 cmdline，futex_wait/pipe_read 永不退出） |
| 根因 | `SyncTaskExecutor` 进程池 broken 后反复重建，`shutdown(wait=False)` 无法回收卡死 worker → 每次重建泄漏 worker 进程 + 旧池队列管道；后续每次 fork 完整继承泄漏 FD，滚雪球打满 `ulimit -n` |
| 放大器 | 商业许可证 runtime 在 fork 出的 worker 内跨事件循环复用全局 `httpx.AsyncClient`（见"遗留问题"），导致 worker 初始化失败率 ~50%、进程池频繁 broken |

## 故障链（证据链）

1. **worker 初始化失败**：每个 fork worker 执行 `_enterprise_sync_worker_init` → 许可证 bootstrap。当日 `bootstrap done` 224 次 / `bootstrap failed` 218 次，失败堆栈终止于：
   ```
   httpcore/_async/connection_pool.py _close_connections → anyio aclose →
   asyncio/selector_events.py close → call_soon → _check_closed
   RuntimeError: Event loop is closed
   ```
2. **池频繁 broken**：当日 `BrokenProcessPool` 47 次 → `Process pool rebuilt` 46 次。**BrokenPool 为何今天才首现**：① 事故进程为 9-11 23:43 部署重启的实例（v5x 三个锁提交的发布重启），23:43 至次日 10:41 零提交，首批任务一次性触发 12 worker 并发 fork——fork 洪峰从一个运行 11 小时、68 线程的繁忙进程里瞬间拉起；② fork 继承锁死锁（9-8 同类问题：logging 锁已重置，但 DB/httpx/ssl/asyncio 等锁无法穷举重置）导致部分 worker 秒死（10:41:38 首次 BrokenPool，距 fork 仅 2 秒）、部分永久卡死（存活的 360 个 futex_wait 子进程即后者）；③ 9-8 卡死事故的修复 f8ca5777 引入 initializer 看门狗（90s `os._exit(70)`），把过去的"静默卡死、池静默缩水、任务降级串行"（9-8：11/12 卡死但 0 BrokenPool、33 任务照常串行执行）转变为 worker 大批猝死 → BrokenPool 显性化。9-9～9-11 任务分散到达且进程每日重启，fork 均发生在年轻安静的主进程中，洪峰路径未再触发。
3. **每次重建泄漏**：`_rebuild_pool_locked` 仅 `shutdown(wait=False, cancel_futures=True)`。池 broken 后管理线程无法通知 worker 退出，worker 卡死在废弃 call queue 上；旧 executor 对象被卡死的管理线程引用无法 GC，其队列管道在父进程永久驻留。
4. **fork 继承放大**：`max_workers=12`，重建后补 fork 的每个新 worker 继承父进程当前全部 FD。当日泄漏 996 根管道（其中 949 根仅单端在父进程，另一端散布在历次 fork 的 worker 中）。
5. **FD 打满 → EMFILE**：16:05 起 `async_task_submission` 等周期任务持续报 `[Errno 24]`；`asyncio.new_event_loop()` 在创建自管道（socketpair）时失败，半初始化对象被 GC 时抛 `_ssock` AttributeError（"Exception ignored in"）。~16:16 进程崩溃，run_prod 16:18 重启。

重启后泄漏立即复现：新 scheduler 运行 5 分钟 FD 55（其中管道 32 根）、子进程 6 个，约合 6.4 根管道/分钟——数小时内将再次打满。

## 修复（本次提交）

| 位置 | 修复 |
|------|------|
| `task/sync_task_executor.py` | 新增 `_terminate_pool_workers_locked`：替换/关停旧池时对全部 worker 逐个 `Process.terminate() → join(宽限) → kill → join`（用 Process 对象而非 `os.kill`+轮询探活——后者对"已死未收尸"的僵尸误判为存活，白等整个宽限期；join 走 waitpid 能正确收尸）。`_rebuild_pool_locked` 与 `shutdown` 均接入，切断"卡死 worker 进程 + 旧池队列管道"两条泄漏路径。不 clear `_processes` 字典：旧池管理线程可能仍在异步遍历，有迭代竞态；executor 对象随替换整体丢弃即可 |
| `task/sync_task_executor.py` | `shutdown()` 对 **broken 池改走非阻塞路径**：`shutdown(wait=True)` 会永久阻塞在 join 卡死 worker 上（worker 收不到退出通知），后续回收代码执行不到，调度器 SIGTERM cleanup 将挂死。健康池保持 `wait=True` 优雅语义不变 |
| `config/constant.py` | 新增 `SYNC_WORKER_RECLAIM_GRACE_SECONDS = 1.0`、`SYNC_WORKER_RECLAIM_JOIN_TIMEOUT = 1.0`（超时常量统一维护） |
| `task/scheduler.py` | `_run_async_task` 的 `loop.close()` 移入 `finally`：异常路径不再泄漏 epoll fd + 自管道 socketpair（每失败一次泄漏 3 个 FD） |
| `tests/task/test_sync_task_pool_reclaim.py` | 7 用例：合作/顽固（SIGTERM 无效需 SIGKILL）/已死 worker 的回收路径、无 `_processes` 属性兜底、单 worker 终止失败不阻断重建、broken 池 shutdown 不阻塞、健康池保持优雅等待、submit→rebuild→回收全链路 |
| `docs/backend/task_status_flow.md` | 同步自愈闭环文档（新增"旧池回收"一环） |

语义取舍：被回收 worker 上仍在运行的任务以 BrokenProcessPool 终态落库退款（与既有 stale 超时强杀同一路径，`check_results` 负责），不会留下 PROCESSING 孤儿——原先这些任务的结果同样无人消费（旧池 result queue 已废弃），只能等 stale 超时走同样的失败路径，本修复只是把该过程提前并使其确定。持锁回收最坏 `workers×(grace+join)` 秒（12 worker ≈ 24s），卡死 worker 对 SIGTERM 走内核默认处置即刻退出，通常整体 <1s。

## enterprise 侧根因修复（zjt_enterprise 仓库）

`task/sync_task_executor.py` 的 `_enterprise_sync_worker_init` 调用 `enterprise.bootstrap_background_process()` 时，fork 出的 worker 内部复用了继承自父进程的 `CommercialLicenseManager`（`enterprise/services/license/runtime.py` 模块级 `_manager` 单例，`if _manager is None` 判断对 fork 失效）。该 manager 的 `httpx.AsyncClient` 连接池与 `_refresh_lock`（asyncio.Lock）都绑定**父进程已关闭的事件循环**，worker 新建事件循环发起许可证 lease 请求时，httpcore 清理旧连接触发 `RuntimeError: Event loop is closed`，导致约一半 worker 带病初始化、进程池频繁 broken（本事故的重建触发器）。

修复（enterprise 仓库 `services/license/runtime.py`，与 `model/database.py` DB 池 `_pool_pid` 的 fork 安全机制同构）：

1. `start_runtime` 记录 `_manager` 的归属 `(pid, 事件循环)`；检测到 pid 漂移（fork 后）或事件循环更替（短生命周期 loop 二次 bootstrap）时丢弃旧 manager、重建 `CommercialLicenseManager`（全新 AsyncClient + Lock），再做 bootstrap。
2. 旧 manager 不 aclose（旧 loop 已关闭时 aclose 必然抛 RuntimeError），仅丢弃引用；租约客户端低频使用、空闲连接通常仅 1 条，泄漏有界。
3. 测试：`tests/license/test_runtime.py` 新增 fork 后重建、新 loop 重建、同进程同 loop 保留（回归）三用例。

同进程多 loop 场景（scheduler/CLI 用短生命周期 loop 多次 bootstrap）此前同样会触发该 RuntimeError，本次一并修复。

## 运维建议（止血，非根治）

- scheduler/gunicorn 进程 `ulimit -n` 建议从 1024 提到 65535（systemd `LimitNOFILE` 或启动脚本 `ulimit -n`）。仅延长恶化周期，不替代代码修复。
- 巡检指标：`ls /proc/<scheduler_pid>/fd | wc -l`、`pgrep -P <scheduler_pid> | wc -l`；管道数持续增长或子进程数远超 `sync_task.max_workers` 即为复发前兆。
- 注意存在 `run_dev.py` 与 `run_prod.py` 双环境并存时各自拉起 scheduler（10:49 的 dev scheduler 与 16:18 的 prod scheduler 曾同时运行），复用同一 DB 时会双份消费任务，需人工确认是否预期。
- **部署本次修复前先清理存量孤儿**：事故 scheduler（pid 1717541）崩溃后其泄漏的数百个卡死 worker 已被 re-parent 到 init，不会随父进程死亡退出。部署重启时先 `pkill -f run_scheduler.py` 清理全部残留（锁文件机制保证新实例安全启动）。
- scheduler 的 stderr 目前直接打到终端（重启即丢），本次 worker 猝死的真实死因（信号/段错误 traceback）已无法追溯。建议 `run_prod.py` 启动 scheduler 时加 `stderr=open("logs/scheduler_stderr.log", "ab")`。

## 更简单的替代方案评估（未采用，备查）

- **`mp_context=multiprocessing.get_context("spawn")`**：结构上根治整类 fork 继承问题——9-8 的继承锁死锁、本次的管道继承放大、跨事件循环 manager 复用全部消失（Windows 本就是 spawn 默认，该平台从未出过此类问题）。未直接采用的原因：spawn 会在 worker 启动时重新 import 主模块（`run_scheduler.py` 顶部的 `from server import app` 等重导入副作用需要逐一验证），worker 启动延迟从 ~ms 级升到秒级，属于行为变更较大的可选项。建议作为后续独立任务评估，本次先落地零行为变更的定点修复。
- **仅调大 ulimit**：只是把 1024 换成 65535，泄漏速度不变（约 6.4 根管道/分钟 → 数天后仍会打满），不可单独作为修复。
- **去掉 `_rebuild_pool_locked` 的重建改为温和补 fork**：治标不治本——BrokenProcessPool 后队列管理线程已死，池无法继续工作，重建是必要的；泄漏点在重建后旧 worker 无人回收，本次修复正是补这一环。

## 残余风险（已知、可接受）

- fork 继承未知锁导致的 worker 卡死/猝死本身仍在（无法穷举重置）。现有防线：initializer 锁重置 + 90s 看门狗 + 死进程清理 + 本次补的旧池回收 = 自愈闭环，泄漏不再累积。结构性根治见 spawn 方案。
- `refresh_runtime_now/deactivate/reactivate` 直接使用 `get_runtime_manager()` 无归属检查——仅 Web API 路由调用（进程内单事件循环），scheduler/worker 路径不触及；worker 内商业能力判定（`require_commercial_license` 等）为纯内存读，无网络调用。
- 健康池但个别 worker 卡死（未触发 broken 标记）时 `shutdown(wait=True)` 仍可能阻塞——需 stale 检测先把池标记 broken 才会走非阻塞路径；窗口极窄（stale 超时会强杀并标记），维持现状。
