# 历史缺陷清单和改坏回放

历史 bug 先记成清单，再收成会自动跑的测试。测试可能写了却没检查到那个 bug，所以用补丁把缺陷改回去，确认测试会失败。

清单在 `tests/regressions/`，一条一个 Markdown 文件，记四件事：

1. 这个功能当时坏成什么样
2. 代码大概在哪
3. 怎样算没修好
4. 对应的永久测试（还没有就空着）

永久测试可以是单元测试、接口测试、浏览器端到端，或现有的 `scripts/lint_*.py` 扫描。哪一种能稳定抓住它就用哪一种。要求是：这个 bug 不能再悄悄发生，而用例里完全没有它。

## 改坏回放

带补丁的条目：

```bash
python scripts/testing/run_bug_replay.py
python scripts/testing/run_bug_replay.py --id 2026-10-21-sse-silent-stall
python scripts/testing/run_bug_replay.py --list
```

脚本把仓库复制到仓库所在盘的临时目录（跳过 `bin`、`node_modules`、上传和日志），先在副本上跑测试，通过后再打补丁重跑。

- 正确代码上通过、改坏后失败：这条测试抓得住，退出码 0
- 改坏后仍然通过：测试是空的，退出码 1，要改断言后再留下
- 正确代码上就失败，或补丁对不上文件：退出码 2，先修环境或补丁

补丁是 JSON，放在 `tests/regressions/patches/`。`replaces` 替换恰好出现一次的文本，`creates` 新增一个文件。单次 pytest 上限是 `config/constant.py` 的 `BUG_REPLAY_PYTEST_TIMEOUT_SECONDS`。

当前三条试点：

| 条目 | 改坏什么 | 必须变红的测试 |
|---|---|---|
| `2026-10-21-sse-silent-stall` | 去掉 SSE 超时后关闭生成器 | `tests/api/test_sse_stall_guard.py` |
| `ai-tools-status-cas` | 新增一处 `status=` 字段写入 | `tests/scripts/test_lint_ai_tool_status_cas.py` |
| `power-budget-route-missing` | 去掉三条 `/power-budget` 路由装饰器 | `tests/api/test_user_power_budget_api.py::test_power_budget_routes_are_registered` |

算力上限的浏览器/HTTP 端到端在 `auto_test/e2e/test_power_budget.py`，未登录时应是 401。回放脚本跑的是进程内的路由注册测试，因为 HTTP 用例打的是已经启动的服务，不会自动读到临时副本里的代码。

## 和 AI 点页面的关系

`auto_test/test_modules` 仍是 AI 的操作剧本。某条已经收成永久测试后，把功能 id 写进清单的 `feature_ids`。`auto_test/test_navigator.py` 取下一项时会跳过它。

定时流水线（GitLab `schedule`）在单元测试通过后会再跑一遍 `run_bug_replay.py`。每次 push 不跑回放，避免把「改坏再测」加进每次提交的时长。

第一批的智能体提示词在 `tests/regressions/prompts/`。同步 worker 四条用 `agent-sync-worker.md`，2026-09-29 的三件事用 `agent-app-log-0929.md`。

## 新冒出来的问题

追加一条清单，补上永久测试和改坏补丁，用上面的命令确认改坏后会红。修复用的同一个合并请求里把测试和清单一起带上。
