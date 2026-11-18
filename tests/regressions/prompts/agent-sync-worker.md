# 智能体任务：同步 worker 四条历史缺陷

你在仓库 `G:\code\comfyui_server9` 工作。请说中文。按下面四条的顺序做完。一条没打出「抓住」之前，不要开始下一条。

这四条都改 `task/sync_task_executor.py` 一带，所以由你一个人顺序做。不要并行改这个文件。

## 要做的四条

1. `2026-06-29-sync-task-hang`
   - 清单：`tests/regressions/2026-06-29-sync-task-hang.md`
   - 事故：`docs/backend/incidents/2026-06-29-sync-task-hang.md`
   - 已有测试：`tests/task/test_sync_task_stale_recovery.py`、`tests/utils/test_image_upload_utils_timeout.py`、`tests/scripts/test_lint_blocking_calls.py`
   - 现象：同步 worker 卡死后进程池槽位不释放；图床上传的 `future.result()` 没有超时，调用方会一直等。

2. `2026-09-12-scheduler-emfile-pool-leak`
   - 清单：`tests/regressions/2026-09-12-scheduler-emfile-pool-leak.md`
   - 事故：`docs/backend/incidents/2026-09-12-scheduler-emfile-pool-leak.md`
   - 已有测试：`tests/task/test_sync_task_pool_reclaim.py`
   - 现象：坏掉的 worker 占着进程池不放，文件描述符漏到 `EMFILE`，同步任务大面积失败。

3. `2026-09-13-sync-worker-fork-qiniu-executor`
   - 清单：`tests/regressions/2026-09-13-sync-worker-fork-qiniu-executor.md`
   - 事故：`docs/backend/incidents/2026-09-13-sync-worker-fork-qiniu-executor.md`
   - 现在没有单独的永久测试。阻塞调用 lint 没有锁住这个 bug。
   - 现象：Linux fork 继承父进程用过的七牛 `ThreadPoolExecutor`。子进程里上传任务进队列却没有线程跑，精确约 120 秒后报上传超时，七牛日志里没有「开始上传」。
   - 代码：`task/sync_task_executor.py` 的 `_enterprise_sync_worker_init` 里调用了 `reset_file_storage()`；函数在 `utils/file_storage/factory.py`。进程池默认已经改成 spawn，这段重置是退回 fork 时的防线。测试要锁住「worker 初始化会清掉继承来的存储单例」，不要去真的 fork 一个进程池。

4. `2026-09-20-sync-worker-spawn-no-driver-registry`
   - 清单：`tests/regressions/2026-09-20-sync-worker-spawn-no-driver-registry.md`
   - 事故：`docs/backend/incidents/2026-09-20-sync-worker-spawn-no-driver-registry.md`
   - 已有测试：`tests/task/test_sync_task_worker_init.py`，另外清单里还列了 pool reclaim 和 stale recovery。先读 `test_sync_task_worker_init.py`，确认它有没有断言 worker 会调用 `register_all_drivers()`。没有的话要补。
   - 现象：spawn 出来的子进程不继承父进程内存，`VideoDriverFactory._registered_drivers` 是空的，同步任务报找不到驱动。注册写在 `_enterprise_sync_worker_init`，位于社区版提前 return 之前。

## 每条怎么做

1. 读该条清单和事故记录，再读它点名的测试和对应实现。以当前代码为准，事故文档里的行号可能已经过时。
2. 想一个最小改坏：只把当年修掉的那几行改回错误写法。例如删掉一次 `reset_file_storage()`，或删掉 worker 里的 `register_all_drivers()`。不要顺手改别的行为。
3. 判断现有测试能不能抓住这个改坏。
   - 能抓住：不要新写测试。`replay_tests` 只填那个会变红的用例节点，例如 `tests/task/test_sync_task_pool_reclaim.py::test_rebuild_terminates_and_reaps_workers`。文件里有多个测试时，只填真正会红的那一个或几个。
   - 不能抓住：先在现有测试文件里加一条永久测试。它在正确代码上必须通过，在你的改坏下必须失败，并且失败要快，不要 `sleep` 几十秒。单元测试能表达的，就写单元测试。不要为了这条去写浏览器端到端。
4. 补丁不要改源码仓库里的业务文件。只写成 JSON，放到 `tests/regressions/patches/<id>.json`。格式如下。`old` 必须在当前文件里恰好出现一次，用 `\n` 表示换行。

```json
{
  "replaces": [
    {
      "path": "task/sync_task_executor.py",
      "old": "恰好出现一次的原文",
      "new": "改坏后的文本"
    }
  ]
}
```

需要新建文件时用 `creates`，并确认这个路径现在不存在。样例见 `tests/regressions/patches/2026-10-21-sse-silent-stall.json` 和 `tests/regressions/patches/ai-tools-status-cas.json`。

5. 更新该条清单的 front matter：`patch:` 写成 `patches/<id>.json`，`replay_tests:` 写成上面选定的用例节点。正文「怎么操作、怎样算没修好」改成这两句：改坏补丁动了哪几行；怎样算没修好。不要改 `docs/backend/incidents/` 里的事故原文。
6. 运行：

```bash
python scripts/testing/run_bug_replay.py --id <id>
```

脚本会把仓库复制到临时目录，不改当前工作区。正确代码上测试通过，打上补丁后测试失败，才会打印「抓住」并退出码 0。

- 打印「没抓住」：测试是空的。改断言或补测试，再跑。不要把一条瞎测试留在清单里。
- 打印「没跑成」或正确代码上就失败：先修补丁或环境。补丁对不上当前文件时，重读源码再写 `old`。
- 改坏后的失败必须来自断言，不要靠把测试拖过 180 秒超时来算「抓住」。超时常量是 `config/constant.py` 的 `BUG_REPLAY_PYTEST_TIMEOUT_SECONDS`。

7. 这一条「抓住」之后，确认工作区里的业务源码没有被补丁改掉，再做下一条。每份补丁都相对干净源码，不要叠在前一条的改坏结果上。

## 做完时

四条都打印过「抓住」。回复里列出每条的：清单路径、补丁路径、`replay_tests`、你改坏的那几行、回放命令的最后一行。

## 不要做

- 不要改 `scripts/testing/run_bug_replay.py`、`scripts/testing/regression_catalog.py`，也不要改已经验收过的三条：`2026-10-21-sse-silent-stall`、`ai-tools-status-cas`、`power-budget-route-missing`。
- 不要做 `2026-09-29-app-log-high-priority-fixes`，那是另一个智能体的任务。
- 不要改 `auto_test/` 里的 JSON 剧本，除非你真的给某条填了 `feature_ids`。这四条不需要。
- 不要启动服务，不要打外部付费 API，不要改正在跑的进程。
- 新增常量放 `config/constant.py`。不要在函数体内 import 该函数更早就会用到的名字。不要写没有 `timeout=` 的 `Future.result()`，也不要用 `with ThreadPoolExecutor()`。
- 测试和清单用中文说明这个 bug 的现象。
