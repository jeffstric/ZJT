---
id: 2026-09-04-session-vendor-id
patch: patches/2026-09-04-session-vendor-id.json
tests:
  - tests/llm/test_local_prefix_overrides_vendor_id.py
replay_tests:
  - tests/llm/test_local_prefix_overrides_vendor_id.py::test_vllm_prefix_wins_over_stale_vendor_id
feature_ids:
---

## 当时坏成什么样

剧本任务跑着的时候切换模型，会话里的模型名已经换成本地 `vllm:` 模型，任务上的 `vendor_id` 仍是原来的 DeepSeek。下一轮请求被送到 DeepSeek，返回 400，连续失败后任务停止。

## 代码大概在哪

- `web/js/script_writer.js` 的 `changeModel()`
- `api/script_writer.py` 的 `ModelChangeRequest` / `set_session_model`
- `chat_sessions.vendor_id`

## 怎么操作、怎样算没修好

改坏补丁把 `llm/llm_client_factory.py` `get_client()` 里的防御层冲突分支删掉（`local_prefix` 与 vendor_id 解析结果冲突时按前缀路由的 if/else 还原成当年「vendor_id 命中直接返回」的写法）——`vllm:`/`ollama:` 显式前缀不再优先，本地模型名会被透传给旧云厂商 API。

怎样算没修好：`tests/llm/test_local_prefix_overrides_vendor_id.py::test_vllm_prefix_wins_over_stale_vendor_id` 没红，即改坏没被抓住。该用例模拟「运行中任务携带旧 DeepSeek vendor_id=7 + 模型已切 vllm:qwen3.8:27b」的事故形态；同文件 `test_vendor_id_still_routes_when_no_prefix_conflict` 反向锁定 vendor_id 优先语义不被整体取消（zjt_api 的 qwen3.5/3.6 靠它路由）。

## 永久测试

- `tests/llm/test_local_prefix_overrides_vendor_id.py`（防御层冲突/不冲突两用例；会话持久化与 PM 循环透传属于集成链路，由 `chat_sessions.vendor_id` 迁移存在性与人工验收覆盖）
