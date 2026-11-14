---
id: 2026-09-04-session-vendor-id
patch:
tests:
replay_tests:
feature_ids:
---

## 当时坏成什么样

剧本任务跑着的时候切换模型，会话里的模型名已经换成本地 `vllm:` 模型，任务上的 `vendor_id` 仍是原来的 DeepSeek。下一轮请求被送到 DeepSeek，返回 400，连续失败后任务停止。

## 代码大概在哪

- `web/js/script_writer.js` 的 `changeModel()`
- `api/script_writer.py` 的 `ModelChangeRequest` / `set_session_model`
- `chat_sessions.vendor_id`

## 怎么操作、怎样算没修好

还没有单独的永久测试。运行中把模型改成 `vllm:` 或 `ollama:` 之后，下一轮不能再拿旧的云厂商 `vendor_id` 去调。

## 永久测试

还没有。
