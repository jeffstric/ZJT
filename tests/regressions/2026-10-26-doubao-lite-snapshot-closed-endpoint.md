---
id: 2026-10-26-doubao-lite-snapshot-closed-endpoint
patch: patches/2026-10-26-doubao-lite-snapshot-closed-endpoint.json
tests:
  - tests/llm/test_volcengine_humanize_error.py
replay_tests:
  - tests/llm/test_volcengine_humanize_error.py::TestVolcengineModelNameMap::test_doubao_lite_maps_to_live_snapshot
  - tests/llm/test_volcengine_humanize_error.py::TestVolcengineHumanizeApiError::test_closed_endpoint_translated_with_model_name
feature_ids:
---

## 当时坏成什么样

豆包 lite 快照模型的上游地址已经关闭，请求仍打到旧端点，用户看到的是难懂的上游错误，而不是说明这个模型不可用。

## 代码大概在哪

- 火山引擎错误文案和 lite 模型映射，测试在 `tests/llm/test_volcengine_humanize_error.py`

## 怎么操作、怎样算没修好

改坏补丁动了 `llm/volcengine_openai_client.py` 两处：① `_MODEL_NAME_MAP` 把 lite 映射改回已被官方下线的 `doubao-seed-2-0-lite-260215` 快照（调用必然 400 ClosedEndpoint）；② `_humanize_api_error` 删掉 `InvalidEndpoint.ClosedEndpoint` 翻译分支（上层只见裸英文 400）——两个面同时回到当年行为。

怎样算没修好：`test_doubao_lite_maps_to_live_snapshot`（映射目标必须为实测可用快照）和 `test_closed_endpoint_translated_with_model_name`（ClosedEndpoint 必须翻译为含「已被官方下线」的中文提示）任一没红，即对应那半的改坏没被抓住。注意 `_MODEL_NAME_MAP` 里写死的快照号是易过期资产，映射目标须定期与 `GET /api/v3/models` 对账。

## 永久测试

- `tests/llm/test_volcengine_humanize_error.py`
