# 智能体任务：2026-09-29 日志里的三件独立故障

你在仓库 `G:\code\comfyui_server9` 工作。请说中文。

这三件事现在写在同一条清单 `tests/regressions/2026-09-29-app-log-high-priority-fixes.md` 里。请拆成三条清单，每条一个改坏补丁、一个回放测试。不要合成一个补丁。回放脚本只要有一个测试变红就记「抓住」，合成补丁会把另外两个没被锁住的 bug 一起算成通过。

事故原文：`docs/backend/incidents/2026-09-29-app-log-high-priority-fixes.md`。以当前代码为准，文档里的行号可能已经过时。不要改事故原文。

## 拆成这三条

1. `2026-09-29-pipeline-stuck-step`
   - 现象：流水线步骤卡在 PROCESSING，没有人回收。回收时不能抢跑，去调用整段任务的完成检查。
   - 已有测试：`tests/task/test_pipeline_stuck_step_recovery.py`
   - 重点看 `test_recovers_steps_without_premature_completion_check`：卡死步骤要被回收，且 `_check_ai_tool_stage_completion` 不被调用。

2. `2026-09-29-grid-image-auth-retry`
   - 现象：四宫格轮询遇到 401/403 后无限重试，任务不结束。
   - 已有测试：`tests/task/test_grid_image_auth_failure.py`
   - 连续认证失败要终态失败并清计数；单次 401 不终止；非认证错误清掉连续计数。

3. `2026-09-29-expired-reference-404`
   - 现象：参考图 404/410 被报成服务异常。应当是图片过期，给用户错误，不要当成 5xx，也不要因此打 Sentry。
   - 已有测试：`tests/drivers/test_gpt_image_expired_reference.py`

原清单 `2026-09-29-app-log-high-priority-fixes.md` 保留，删掉 `patch` 和 `tests` 里的具体文件，改成指向上面三条新 id。它自己不要带补丁，避免回放脚本再跑一遍。

## 每条怎么做

1. 读事故里对应的那一节，再读现有测试和它覆盖的实现。
2. 想一个最小改坏，只把当年修掉的那一处改回错误写法。例如回收时又去调用完成检查，或 401 不再计入连续失败，或 404 重新抛成普通 HTTP 错误。
3. 现有测试能抓住这个改坏，就不要新写测试。`replay_tests` 只填会变红的用例节点，带上类名，例如 `tests/task/test_grid_image_auth_failure.py::TestXxx::test_terminates_after_consecutive_limit`。一个文件里有多个类和用例，先读再填，不要把整个文件都放进回放。
4. 现有测试抓不住，就在该测试文件里补一条。正确代码上通过，改坏后失败，失败要快，不要长时间 `sleep`。能用单元测试表达的，不要写浏览器端到端。
5. 补丁只写 JSON，不要把改坏留在业务源码里。路径：`tests/regressions/patches/<新id>.json`。`old` 必须在当前文件里恰好出现一次。

```json
{
  "replaces": [
    {
      "path": "相对仓库根目录的文件",
      "old": "恰好出现一次的原文",
      "new": "改坏后的文本"
    }
  ]
}
```

样例：`tests/regressions/patches/2026-10-21-sse-silent-stall.json`。

6. 新清单用下面的 front matter，正文四段：当时坏成什么样、代码大概在哪、改坏补丁动了哪几行、怎样算没修好。

```markdown
---
id: 2026-09-29-pipeline-stuck-step
patch: patches/2026-09-29-pipeline-stuck-step.json
tests:
  - tests/task/test_pipeline_stuck_step_recovery.py
replay_tests:
  - tests/task/test_pipeline_stuck_step_recovery.py::类名::用例名
feature_ids:
---
```

7. 一条写完就跑：

```bash
python scripts/testing/run_bug_replay.py --id 2026-09-29-pipeline-stuck-step
```

正确代码上通过、打上补丁后失败，才会打印「抓住」。脚本只用临时副本，不改当前工作区。

- 「没抓住」：改断言或补测试，再跑。
- 「没跑成」：补丁的 `old` 对不上文件，或正确代码上测试已经是红的。重读源码再写。
- 不要靠拖过 180 秒超时来算抓住。超时常量是 `BUG_REPLAY_PYTEST_TIMEOUT_SECONDS`。

三条互不依赖，可以按任意顺序做。每份补丁都相对干净源码，不要叠在另一条的改坏上。做下一条之前，确认业务源码没有残留补丁。

## 做完时

三条都打印过「抓住」。回复里列出每条的：清单路径、补丁路径、`replay_tests`、改坏的那几行、回放最后一行。并说明原清单已经改成只指向这三条。

## 不要做

- 不要改 `scripts/testing/run_bug_replay.py`、`scripts/testing/regression_catalog.py`。
- 不要做同步 worker 那四条：`2026-06-29-sync-task-hang`、`2026-09-12-scheduler-emfile-pool-leak`、`2026-09-13-sync-worker-fork-qiniu-executor`、`2026-09-20-sync-worker-spawn-no-driver-registry`。
- 不要改已经验收过的 `2026-10-21-sse-silent-stall`、`ai-tools-status-cas`、`power-budget-route-missing`。
- 不要启动服务，不要打外部付费 API。
- 新增常量放 `config/constant.py`。不要在函数体内 import 该函数更早就会用到的名字。不要写没有 `timeout=` 的 `Future.result()`，也不要用 `with ThreadPoolExecutor()`。
