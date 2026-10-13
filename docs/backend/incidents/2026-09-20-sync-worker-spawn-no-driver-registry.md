# 2026-09-20 Sync worker spawn 未注册视频驱动事故

## 现象

Seedream 5.0 文生图任务（ai_tools id=230，type=16，实现方 `seedream5_volcengine_v1`）
提交后 6 秒失败，`ai_tools.message` 为：

```text
不支持的任务类型: 16
```

但 type=16（`TaskTypeId.SEEDREAM_TEXT_TO_IMAGE`，key=`seedream-5.0`）在
`config/unified_config.py` 中定义完整，实现方 `seedream5_volcengine_v1` 配置正常，
错误文案与事实不符。

任务时间线（ai_tools_log）：`record_created → task_started → implementation_selected
(seedream5_volcengine_v1) → retry_scheduled`，主进程侧全程无异常。

## 根因

`seedream5_volcengine_v1` 是 `sync_mode=True` 实现方，任务由
`SyncTaskExecutor`（`ProcessPoolExecutor`）在独立子进程中执行。

- 视频驱动注册只发生在主进程 `server.py` 启动时的 `register_all_drivers()`。
- **Windows 上进程池 worker 以 spawn 方式创建，是全新解释器，不继承父进程内存**；
  worker 的 initializer `_enterprise_sync_worker_init()` 只做日志锁重建、看门狗、
  文件存储重置和 enterprise bootstrap，从未注册视频驱动。
- 因此 worker 内 `VideoDriverFactory._registered_drivers` 为空字典：
  `create_driver_by_implementation('seedream5_volcengine_v1')` 报
  `Driver implementation not registered`，回退 `create_driver_by_type(16)` 也因
  所有实现方 `_is_driver_available()` 为 False 而失败（日志
  `No available implementation for task seedream-5.0`）。
- `task/sync_task_executor.py` 将该失败硬编码为 `不支持的任务类型: {type}`，
  掩盖了真实原因。
- Linux/macOS 上 worker 以 fork 方式创建、继承主进程注册表，不受影响——
  本缺陷为 Windows 特有。

旁证（全库统计）：25 个 sync_mode 实现方中，唯一成功过的记录是实现方 27 于
2026-08-13 的 3 次（当时 executor 未运行、任务回落主进程处理）；此后所有真正
进入进程池的 sync 任务全部失败。非 sync_mode 任务在主进程处理，同期正常。

宫格任务 `1_0_230` 的自动重试改走 HTTP API 重新提交，又因 401 Unauthorized
（重试凭据问题，另行排查）标记终态失败。

## 修复项

- `task/sync_task_executor.py::_enterprise_sync_worker_init()`：在社区版
  early-return 之前（两版通吃）补齐 worker 侧初始化：
  - `init_unified_config()`：确保 `UnifiedConfigRegistry` 任务配置就绪（有空表保护，幂等）；
  - `register_all_drivers()`：注册全部视频驱动（字典赋值，幂等，fork 场景重复调用无害）。
  - 注册结果写入日志 `video drivers registered in worker (pid=..., count=...)`，
    便于与主进程 `Registered N video drivers` 对照观测。
  - 整段 try/except 包裹，注册失败不阻断 worker 初始化，也不吞看门狗解除语义。
- `_execute_sync_task()` 驱动创建失败时改用
  `VideoDriverFactory.get_last_create_error()['message']` 返回真实原因
  （未注册 / 配置缺失 / 无可用实现方等），仅在校验无记录时回退旧文案。

## 验证项

- `tests/task/test_sync_task_worker_init.py`（6 passed）
- `tests/task/test_sync_task_pool_reclaim.py` + `tests/task/test_sync_task_stale_recovery.py`（17 passed）
- `python scripts/lint_blocking_calls.py`（通过）
- spawn 子进程复现脚本（`temp/verify_worker_driver_fix.py`）：
  - 修复前：worker 内注册表 `count=0`，`create_driver_by_implementation` 返回
    None，`get_last_create_error()` 为 `NOT_REGISTERED`（与线上一致）；
  - 修复后：注册 96 个驱动，`get_by_id(16)` 返回 `seedream-5.0`，
    seedream 驱动实例创建成功。

## 观测

修复上线后，worker 首次初始化应出现：

```text
[SyncTaskExecutor] video drivers registered in worker (pid=<pid>, count=96)
```

若 count 为 0 或出现 `worker driver registration failed`，说明驱动注册仍异常。

## 遗留

- 宫格任务自动重试走 `/api/text-to-image` 的 401 Unauthorized（凭据问题）未在本次修复范围。
