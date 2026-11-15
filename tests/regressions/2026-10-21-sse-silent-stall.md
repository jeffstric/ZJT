---
id: 2026-10-21-sse-silent-stall
patch: patches/2026-10-21-sse-silent-stall.json
tests:
  - tests/api/test_sse_stall_guard.py
  - tests/frontend/test_sse_stream_resilience.py
replay_tests:
  - tests/api/test_sse_stall_guard.py::test_guard_terminates_stalled_source_and_closes_it
feature_ids:
---

## 当时坏成什么样

营销助手的一条会话里，网络静默中断后服务端 SSE 卡在发送上，没有报错也没有结束。前端又重复挂了多条流，每条空等大约 15 分钟，连着弹出「请求超时」。任务其实已经做完了。

## 代码大概在哪

- `api/script_writer.py` 的 `_sse_stall_guard_iter`
- `web/js/sse_client.js`
- `web/js/marketing_agent.js`
- 超时秒数在 `config/constant.py` 的 `SSE_STREAM_SEND_TIMEOUT_SECONDS`

## 怎么操作、怎样算没修好

还没有交给 AI 再点一遍页面。回放补丁拿掉「超时就关闭生成器」，`test_guard_terminates_stalled_source_and_closes_it` 必须失败。页面上的痕迹是：同一任务不该叠多条流，长时间收不到任何字节要重连，而不是干等后连弹超时。

## 永久测试

- `tests/api/test_sse_stall_guard.py`
- `tests/frontend/test_sse_stream_resilience.py`
