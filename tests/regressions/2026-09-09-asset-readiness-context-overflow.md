---
id: 2026-09-09-asset-readiness-context-overflow
patch:
tests:
  - tests/script_writer_core/test_expert_agent.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

资产就绪检查把历史图片整段塞进上下文，token 超出模型上限，剧本任务中断。

## 代码大概在哪

- `script_writer_core` 里裁剪历史图片的逻辑，测试类 `TestPruneHistoryImages`

## 怎么操作、怎样算没修好

还没有改坏补丁。历史图片不再被裁剪、上下文再次撑爆，算没修好。

## 永久测试

- `tests/script_writer_core/test_expert_agent.py`
