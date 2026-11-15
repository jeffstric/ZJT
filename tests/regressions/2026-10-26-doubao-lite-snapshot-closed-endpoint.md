---
id: 2026-10-26-doubao-lite-snapshot-closed-endpoint
patch:
tests:
  - tests/llm/test_volcengine_humanize_error.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

豆包 lite 快照模型的上游地址已经关闭，请求仍打到旧端点，用户看到的是难懂的上游错误，而不是说明这个模型不可用。

## 代码大概在哪

- 火山引擎错误文案和 lite 模型映射，测试在 `tests/llm/test_volcengine_humanize_error.py`

## 怎么操作、怎样算没修好

还没有改坏补丁。lite 快照不能再被送到已经关闭的端点；错误要能被映射成可理解的提示。

## 永久测试

- `tests/llm/test_volcengine_humanize_error.py`
