"""SSE 链路静默假死修复的回归测试（源扫描）。

背景（2026-10-21 会话 1be6829f 事故）：同一任务被挂 5 条并发 SSE 流，
链路静默假死后 fetch 流无任何 error/close 事件，5 条流各自干等 900s 超时，
弹出 5 个"请求超时"气泡，而任务实际已正常完成。

修复点：
1. sse_client.js — 空闲读超时（idleTimeoutMs）：N 秒收不到任何字节（含服务端
   心跳）即判定假死，自动带 Last-Event-ID 断点续传重连（指数退避，上限 maxReconnects）。
2. marketing_agent.js — 同一任务同时只允许一条 SSE 流（activeTaskStreams 注册表），
   handleStream 传入 idleTimeoutMs 启用断流检测。
3. api/script_writer.py — 服务端生成器套 _sse_stall_guard_iter 看门狗，
   单条事件发送被背压卡住超过 SSE_STREAM_SEND_TIMEOUT_SECONDS 即关闭生成器。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSE_CLIENT_JS = (ROOT / "web" / "js" / "sse_client.js").read_text(encoding="utf-8")
MARKETING_AGENT_JS = (ROOT / "web" / "js" / "marketing_agent.js").read_text(encoding="utf-8")
SCRIPT_WRITER_PY = (ROOT / "api" / "script_writer.py").read_text(encoding="utf-8")
CONSTANT_PY = (ROOT / "config" / "constant.py").read_text(encoding="utf-8")


def test_sse_client_supports_idle_timeout_and_resume_reconnect():
    # 空闲读超时：连心跳字节都收不到即判定链路假死
    assert "idleTimeoutMs" in SSE_CLIENT_JS
    assert "SSE_IDLE_TIMEOUT" in SSE_CLIENT_JS
    # 断点续传：重连时携带 Last-Event-ID，服务端跳过已发消息
    assert "Last-Event-ID" in SSE_CLIENT_JS
    # 重连必须有次数上限，耗尽后 throw 交给 run().catch → onError 兜底
    assert "maxReconnects" in SSE_CLIENT_JS
    assert "流失败且不再重连" in SSE_CLIENT_JS
    assert "throw error;" in SSE_CLIENT_JS


def test_marketing_agent_uses_idle_timeout_and_single_stream_per_task():
    # 同一任务防重复挂流：注册表 + 挂新流前关闭旧流
    assert "activeTaskStreams[taskId]" in MARKETING_AGENT_JS
    assert "任务已有活跃流" in MARKETING_AGENT_JS
    # handleStream 启用断流检测（服务端心跳 1~3s，15s 空闲阈值有 5 倍余量）
    assert "idleTimeoutMs: 15000" in MARKETING_AGENT_JS
    assert "maxReconnects: 6" in MARKETING_AGENT_JS


def test_backend_has_stall_guard_and_constant():
    # 服务端看门狗：背压卡死生成器时主动关闭回收
    assert "_sse_stall_guard_iter" in SCRIPT_WRITER_PY
    assert "asyncio.TimeoutError" in SCRIPT_WRITER_PY
    assert "aclose" in SCRIPT_WRITER_PY
    # StreamingResponse 必须套看门狗，而不是直接包裸生成器
    assert "_sse_stall_guard_iter(event_generator(), task_id)" in SCRIPT_WRITER_PY
    # 超时常量统一维护在 config/constant.py（AGENTS.md 规则 5）
    assert "SSE_STREAM_SEND_TIMEOUT_SECONDS" in CONSTANT_PY
