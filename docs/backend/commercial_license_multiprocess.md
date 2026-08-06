# 商业许可证：多进程生命周期

## 背景

生产启动（`run_prod.py` / `run_dev.py`）会拉起多个进程：

| 进程 | 入口 | 是否跑 FastAPI lifespan |
|------|------|-------------------------|
| Web | uvicorn / gunicorn `server:app` | 是 → `start_runtime` |
| Scheduler | `scripts/running/run_scheduler.py` | 否 |
| Script split worker（可选） | `run_script_split_worker.py`（`script_split.worker_total>0`） | 否 |
| SyncTask 子进程 | `ProcessPoolExecutor`（Scheduler 内） | 否 |

效果模式剧本拆分（`QualityScriptSplitStrategy`）在 **Scheduler 或独立 Worker** 中执行，
构造时调用 `require_commercial_license()`。该检查依赖**当前进程内存**中的：

1. `_registration_ready`（`enterprise.register` 完成或非 Web bootstrap 打开闩锁）
2. `_manager`（`start_runtime` 创建）

Web 管理端「激活许可证」只写入 **Web 进程** 的 manager，以及本机磁盘缓存 / 配置：

- `…/ZJT/license/installation.json`（`installation_id`，跨进程文件锁）
- `…/ZJT/license/enterprise_license.jwt`（短期租约）
- 动态配置 `zjt.token`（账号 Bearer）

**授权成功 ≠ 任务进程 runtime 已启动。** 若 Scheduler/Worker 未 bootstrap，会抛出
`LicenseAccessDenied: 许可证尚未启动`。

## 启动策略（方案 A）

| 进程 | 行为 |
|------|------|
| Web | `enterprise.register(app)` + FastAPI startup → `start_runtime(enable_background_refresh=True)` |
| Scheduler | import server 已 register；启动时 `bootstrap_commercial_license_runtime_sync`（补 manager） |
| Script split worker | `enterprise.bootstrap_background_process`（Provider + 许可证） |
| SyncTask ProcessPool 子进程 | `initializer=_enterprise_sync_worker_init` → 同上 |

要点：

- **不要求用户再次输入 token**；复用已落盘 JWT 与 `zjt.token`。
- **不调用** `activate_with_token`，不新建 `installation_id`。
- 服务端席位按 **`installation_id`** 计，不是按 OS 进程数；同机多进程共享同一
  cache 目录 → **仍是一条安装记录**。可能多几次 lease HTTP，不增加席位。
- 非 ASGI 默认 **关闭后台 refresh 协程**（短生命周期 event loop 无法常驻 task）；
  启动时仍会做一次 `initialize` + 联网 `refresh`（有 token 时）。

实现入口：

- `enterprise.bootstrap_background_process`（Provider + license，无 HTTP）
- `enterprise.services.license.runtime.ensure_commercial_license_runtime`
- `enterprise.services.license.runtime.bootstrap_commercial_license_runtime_sync`

## 商业能力审计（是否受「非 Web 进程」影响）

| 能力 | 门禁方式 | 主要执行进程 | 修复后状态 |
|------|----------|--------------|------------|
| quality 剧本拆分 | `require_commercial_license` | Scheduler / split worker | ✅ bootstrap |
| 效果模式按幕串行 / 空间 / prompt | 同上 | Scheduler（image batch / split）/ Web API | ✅ Scheduler bootstrap；Web 有 lifespan |
| RunningHub 多密钥池 | Provider + require | Scheduler 异步任务 | ✅ register + bootstrap |
| 人脸宫格后处理 | Provider + require | Scheduler 异步；**同步 ProcessPool** | ✅ 池 initializer |
| 失败重试 before_finish | 进程内 handler 注册 | Scheduler | ✅ import server 时 register |
| 品牌 / 佣金 / 注册配额 HTTP | 路由 + Depends | **仅 Web** | ✅ 无需改 |
| 营销视频工具 `video_tools` | require | Web Agent；**CLI 独立进程** | ⚠️ CLI 需自行 `bootstrap_background_process(include_marketing_tools=True)` |
| 管理端许可证激活 | runtime API | **仅 Web** | ✅ 设计如此 |

生产路径上，同类「任务进程未起 license / 未注入 Provider」问题已覆盖。
**CLI 脚本**仍属人工工具，调用商业工具前需自行 bootstrap。

## 运维注意

1. 各进程必须以**同一 OS 用户**运行，使用默认 `default_license_cache_dir()`，
   禁止给 worker 单独配置另一 cache 路径（否则会生成新 installation_id 占席位）。
2. 首次仍须在 Web 管理端完成一次激活；未激活机器上 bootstrap 后仍为
   `AUTH_REQUIRED` / 无有效租约，enforce 模式下 quality 拆分继续拒绝。
3. 社区版（`Edition.is_community()`）跳过 bootstrap。

## 相关代码

- `enterprise/__init__.py`（`bootstrap_background_process`）
- `enterprise/services/license/runtime.py`
- `scripts/running/run_scheduler.py`
- `scripts/running/run_script_split_worker.py`
- `task/sync_task_executor.py`（ProcessPool initializer）
- `enterprise/services/script_split_quality/strategy.py`
