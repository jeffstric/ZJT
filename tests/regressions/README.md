# 历史缺陷清单

一条一个文件。前四段是给人看的：当时坏成什么样、代码大概在哪、怎样算没修好、永久测试文件名。

带 `patch` 的条目可以用下面的命令验收。正确代码上测试必须通过，打上补丁之后必须失败。命令只改临时副本，不改当前工作区。

```bash
python scripts/testing/run_bug_replay.py
python scripts/testing/run_bug_replay.py --id 2026-10-21-sse-silent-stall
```

`feature_ids` 写上 `auto_test/test_modules` 里的功能 id 之后，`test_navigator.py` 取下一项时会跳过它。

说明见 [docs/testing/regression_catalog.md](../../docs/testing/regression_catalog.md)。

第一批交给其他智能体的提示词：

- `prompts/agent-sync-worker.md`：同步 worker 四条，顺序做
- `prompts/agent-app-log-0929.md`：2026-09-29 的三件事，拆开做
