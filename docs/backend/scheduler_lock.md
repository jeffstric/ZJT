# 调度器文件锁机制（scheduler.lock）

## 背景

调度器定时任务在独立进程 `scripts/running/run_scheduler.py` 中运行，与 web 服务分离。
多个实例同时跑调度器会导致定时任务重复执行（重复生成、重复扣量），因此用文件锁保证
**同一部署目录内全局只有一个调度器实例**。

历史事故：旧实现存在三处叠加缺陷（`'w'` 截断锁文件、失败后删除重建锁文件绕过 flock），
生产环境曾积累 31 个调度器进程同时运行。

## 设计要点

锁的互斥**只依赖内核文件锁本身**（Linux/macOS `fcntl.flock`、Windows `msvcrt.locking`），
锁文件里的 PID 仅用于日志诊断：

1. **锁文件用 `'a'` 模式打开（不截断）**——加锁失败时持有者的 PID 记录仍完整可读；
2. **永不删除/重建锁文件**——flock 锁在 inode 上，删除重建等于换 inode 绕过锁；
3. **flock 随持有进程死亡由内核自动释放**（含 `kill -9`、断电）——持有者已死时重试
   flock 必然成功，无需任何"残留强抢"逻辑；持有者存活时本进程不接管调度
   （`init_scheduler` 返回 False，`run_scheduler.py` 打印提示后**保活空转 +
   30s 周期重试**，不退出进程——run_prod 把 scheduler 退出视作核心进程死亡
   会 cleanup 拆掉整栈 Web；持有者退出后自动接管。空转期间持续探活父进程，
   父死即退出，避免第二套成为孤儿）；
4. **加锁成功后才接管 `_lock_fd`**——否则同进程重复获取时旧 fd 被 GC 关闭、旧锁
   随之释放，排他语义失效；
5. **at_fork 阻断继承**——拿锁后注册 `os.register_at_fork(after_in_child=...)`，
   fork 出的 worker 子进程立即关闭继承的锁 fd，锁的存活期与调度器主进程严格同步；
6. **Windows 下锁区域在文件 1MB 偏移处**——Windows 区域锁会阻止其他进程读该字节，
   偏移开保证 PID 诊断可读。

## 防孤儿化（run_scheduler.py）

父启动器（`run_prod.py`）死亡后调度器若继续运行，会变成孤儿并一直持锁，导致后续
重启被拒。两道防线：

| 平台 | 机制 | 反应速度 |
|---|---|---|
| Linux | `prctl(PR_SET_PDEATHSIG)`，父死内核立即发 SIGTERM（fork 的 worker 链式继承） | 秒级 |
| 全平台 | 60s 轮询看门狗：Linux/macOS 检测 `getppid()` 变化（re-parent）；Windows 探活初始父 PID（`task/scheduler._win_process_alive`） | ≤60s |

⚠️ Windows 探活（`_win_process_alive`）的实现约束：

1. **不能用 `os.kill(pid, 0)`**——Windows 上后者对普通信号会调用
   `TerminateProcess`，等于把父进程直接杀掉；
2. **OpenProcess 成功 ≠ 存活**——进程已退出但句柄尚未被回收（父进程仍持有，
   如 `Popen.wait()` 后对象未销毁）时 OpenProcess 照样成功，直接当存活会把
   看门狗和锁探活一起卡死在"永远等不到死"。必须再用
   `GetExitCodeProcess == STILL_ACTIVE(259)` 判真死；权限用
   `PROCESS_QUERY_LIMITED_INFORMATION`（`SYNCHRONIZE` 不足以调
   GetExitCodeProcess）；ctypes 需声明 argtypes/restype（默认 c_int 会
   截断 64 位 HANDLE）。

## 各异常场景的行为（对用户的可预期性）

| 场景 | 结果 |
|---|---|
| 正常重启服务 | 锁随旧进程退出释放，新服务正常启动 |
| 关闭终端 / SSH 断线 | SIGHUP 已捕获，锁正常释放 |
| 服务被强杀 / 断电重启 | 锁由内核自动释放，直接启动成功 |
| run_prod 被强杀、调度器残留 | 看门狗 ≤60s 自杀释放锁，重启自愈 |
| 误开第二套（同目录） | 第二套不接管调度、保活空转重试（Web 不受影响），持有者退出后自动接管 |

用户在任意异常后只需"重启服务"，无需手工删除锁文件或杀进程。

## 测试

`tests/task/test_scheduler_lock.py`：同进程重复获取被拒、存活持有者阻塞、死持有者
重试获取、4 进程并发恰好 1 个成功、PID 探活判断、fork 子进程不继承锁（强杀主进程后
锁立即可获取）。Windows 下 `msvcrt` 允许同进程重复加锁，相关用例已按平台 skip。
