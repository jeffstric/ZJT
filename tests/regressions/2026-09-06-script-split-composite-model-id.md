---
id: 2026-09-06-script-split-composite-model-id
patch:
tests:
  - tests/llm/test_resolve_composite_model_ref.py
  - tests/llm/test_model_id_numeric_routing.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

分镜拆分把 `厂商:模型名` 这种复合字符串当成模型 id 往下传，路由到错误的供应商或直接失败。

## 代码大概在哪

- 模型 id 归一化，见 `tests/llm/test_resolve_composite_model_ref.py` 与 `tests/llm/test_model_id_numeric_routing.py` 所覆盖的实现

## 怎么操作、怎样算没修好

还没有改坏补丁。复合模型串不能再被当成数值 id 直接路由。

## 永久测试

- `tests/llm/test_resolve_composite_model_ref.py`
- `tests/llm/test_model_id_numeric_routing.py`
