---
id: 2026-09-06-script-split-composite-model-id
patch: patches/2026-09-06-script-split-composite-model-id.json
tests:
  - tests/llm/test_resolve_composite_model_ref.py
  - tests/llm/test_model_id_numeric_routing.py
replay_tests:
  - tests/llm/test_resolve_composite_model_ref.py::test_missing_vendor_model_association_is_rejected
feature_ids:
---

## 当时坏成什么样

分镜拆分把 `厂商:模型名` 这种复合字符串当成模型 id 往下传，路由到错误的供应商或直接失败。

## 代码大概在哪

- 模型 id 归一化，见 `tests/llm/test_resolve_composite_model_ref.py` 与 `tests/llm/test_model_id_numeric_routing.py` 所覆盖的实现

## 怎么操作、怎样算没修好

改坏补丁把 `llm/llm_client_factory.py` `resolve_composite_model_ref()` 里「vendor_model 关联缺失拒绝猜测」的保护删掉——供应商/模型存在但关联缺失（已下架）时会照样猜出 `(vendor_id, model_id)` 返回，回到当年「复合串被当成数值 id 直接路由」的形态。

怎样算没修好：`tests/llm/test_resolve_composite_model_ref.py::test_missing_vendor_model_association_is_rejected` 没红，即改坏没被抓住。该用例断言关联缺失时必须返回 `(None, None)`，调用方才回退默认模型而不是猜一条错误路由。

## 永久测试

- `tests/llm/test_resolve_composite_model_ref.py`
- `tests/llm/test_model_id_numeric_routing.py`
