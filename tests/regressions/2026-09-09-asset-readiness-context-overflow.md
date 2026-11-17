---
id: 2026-09-09-asset-readiness-context-overflow
patch: patches/2026-09-09-asset-readiness-context-overflow.json
tests:
  - tests/script_writer_core/test_expert_agent.py
replay_tests:
  - tests/script_writer_core/test_expert_agent.py::TestPruneHistoryImages::test_prune_oldest_beyond_limit
feature_ids:
---

## 当时坏成什么样

资产就绪检查把历史图片整段塞进上下文，token 超出模型上限，剧本任务中断。

## 代码大概在哪

- `script_writer_core` 里裁剪历史图片的逻辑，测试类 `TestPruneHistoryImages`

## 怎么操作、怎样算没修好

改坏补丁把 `script_writer_core/agents/expert_agent.py` `_prune_history_images()` 的裁剪循环前加了一条无条件 `return`（函数变 no-op）——回到当年「历史图片只进不出、无数量上限」的行为，16 张 base64 图随轮次累积把 74 万 tokens 推过模型上下文上限。

怎样算没修好：`tests/script_writer_core/test_expert_agent.py::TestPruneHistoryImages::test_prune_oldest_beyond_limit` 没红，即改坏没被抓住。该用例断言超出上限的旧图必须被替换为文本占位、最近 6 张保留。

## 永久测试

- `tests/script_writer_core/test_expert_agent.py`
