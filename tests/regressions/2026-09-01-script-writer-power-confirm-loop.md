---
id: 2026-09-01-script-writer-power-confirm-loop
patch: patches/2026-09-01-script-writer-power-confirm-loop.json
tests:
  - tests/script_writer_core/test_expert_agent.py
replay_tests:
  - tests/script_writer_core/test_expert_agent.py::TestPowerConfirmSwitch::test_disabled_gate_passes_through_with_task_manager
feature_ids:
---

## 当时坏成什么样

用户在剧本创作页答完最后一个问题后离开，系统仍连续扣算力大约 40 分钟。前端每 5 分钟弹出一次算力确认，并提示验证已超时。

## 代码大概在哪

- `script_writer_core` 里 `ExpertAgent` 的算力确认开关和 `_gate_computing_power`

## 怎么操作、怎样算没修好

改坏补丁把 `script_writer_core/agents/expert_agent.py` `_gate_computing_power()` 入口的开关短路分支整段删掉（`power_confirm_enabled=False` 时不放行、照常估算与弹确认）——剧本创作链路的确认门重新生效，回到当年「用户离开后弹确认→300 秒超时→重试→再弹」的死循环扣费行为。

怎样算没修好：`tests/script_writer_core/test_expert_agent.py::TestPowerConfirmSwitch::test_disabled_gate_passes_through_with_task_manager` 没红，即改坏没被抓住。该用例模拟剧本链路真实形态（task_manager/task_id 齐备）——原有的 `test_disabled_gate_passes_through` 不带 task_manager，改坏后会走「无交互通道放行」分支而漏抓，本用例补这个口子。

## 永久测试

- `tests/script_writer_core/test_expert_agent.py` 里的算力确认开关用例
