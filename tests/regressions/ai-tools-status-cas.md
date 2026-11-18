---
id: ai-tools-status-cas
patch: patches/ai-tools-status-cas.json
tests:
  - tests/scripts/test_lint_ai_tool_status_cas.py
replay_tests:
  - tests/scripts/test_lint_ai_tool_status_cas.py::test_repo_has_no_status_keyword_writes
feature_ids:
---

## 当时坏成什么样

取消任务之后，另一处用普通字段更新把 `status` 写回去，`CANCELLED` 被盖掉，任务又活过来，退款也会乱。

## 代码大概在哪

- 状态迁移走 `model/ai_tools.py` 的 `transition_status` / `transition_with_cdn_sync`
- 扫描在 `scripts/lint_ai_tool_status_cas.py`

## 怎么操作、怎样算没修好

这是代码形状问题，不用点页面。回放补丁在 `task/` 下加一个带 `status=` 的 `update_only_fields` 调用，全库扫描测试必须失败。业务代码里再出现这种写法，就当这个 bug 又发生了。

## 永久测试

- `tests/scripts/test_lint_ai_tool_status_cas.py`
