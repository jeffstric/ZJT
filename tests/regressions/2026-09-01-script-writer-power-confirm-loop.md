---
id: 2026-09-01-script-writer-power-confirm-loop
patch:
tests:
  - tests/script_writer_core/test_expert_agent.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

用户在剧本创作页答完最后一个问题后离开，系统仍连续扣算力大约 40 分钟。前端每 5 分钟弹出一次算力确认，并提示验证已超时。

## 代码大概在哪

- `script_writer_core` 里 `ExpertAgent` 的算力确认开关和 `_gate_computing_power`

## 怎么操作、怎样算没修好

还没有交给 AI 重测，也还没有改坏补丁。用户不再操作之后，不该继续弹确认并扣费。

## 永久测试

- `tests/script_writer_core/test_expert_agent.py` 里的算力确认开关用例
