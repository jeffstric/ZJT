---
id: 2026-09-29-pipeline-stuck-step
patch: patches/2026-09-29-pipeline-stuck-step.json
tests:
  - tests/task/test_pipeline_stuck_step_recovery.py
replay_tests:
  - tests/task/test_pipeline_stuck_step_recovery.py::TestRecoverStuckProcessingSteps::test_recovers_steps_without_premature_completion_check
feature_ids:
---

## 当时坏成什么样

流水线步骤卡在 PROCESSING 且无 async_task_id，没有人回收。生产 step 6759 挂了 15+ 天，调度器每 13 秒刷一条 WARNING，所属 ai_tool 的阶段永久挂起。

## 代码大概在哪

- `task/pipeline_processor.py` 的 `_recover_stuck_processing_steps`
- `model/ai_tool_pipeline_steps.py` 的卡死查询与批量失败
- 测试在 `tests/task/test_pipeline_stuck_step_recovery.py`

## 改坏补丁动了哪几行

改坏补丁在 `_recover_stuck_processing_steps()` 末尾（`return len(stuck_steps)` 之前）插入了按 ai_tool 循环调用 `_check_ai_tool_stage_completion(ai_tool_id)` 的抢跑代码——回到当年教训中的错误形态：回收时直接推进 ai_tool 终态，而该函数的失败分支只改 ai_tools 表（不更新 tasks、不退款），会使 `visual_task._check_pipeline_stage` 的入口分支永远失配，退款退化成 30 次 max-retry 兜底。

## 怎样算没修好

`tests/task/test_pipeline_stuck_step_recovery.py::TestRecoverStuckProcessingSteps::test_recovers_steps_without_premature_completion_check` 没红，即改坏没被抓住。该用例的 `mock_check.assert_not_called()` 断言回收路径绝不抢跑调用完成检查；同文件其余用例锁查询参数、幂等与「无卡死不写」。
