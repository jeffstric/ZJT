"""SSE 生成器背压看门狗 _sse_stall_guard_iter 单测。

背景（2026-10-21 会话 1be6829f 事故）：客户端链路静默假死时 TCP 不报错，
服务端事件生成器被发送背压永久冻结在 yield 上，协程/连接双双泄漏且无任何日志。
看门狗要求单条事件在 SSE_STREAM_SEND_TIMEOUT_SECONDS 内完成生产+发送，
超时即判定连接假死、关闭生成器并终止响应。
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.script_writer import _sse_stall_guard_iter


def test_guard_forwards_all_events_normally():
    async def source():
        yield "data: 1\n\n"
        yield "data: 2\n\n"
        yield "data: 3\n\n"

    async def main():
        return [item async for item in _sse_stall_guard_iter(source(), "task-x")]

    assert asyncio.run(main()) == ["data: 1\n\n", "data: 2\n\n", "data: 3\n\n"]


def test_guard_terminates_stalled_source_and_closes_it(monkeypatch):
    """模拟被背压卡死的生成器：yield 第一条后永久挂起，看门狗须超时终止并回收。"""
    monkeypatch.setattr("api.script_writer.SSE_STREAM_SEND_TIMEOUT_SECONDS", 0.1)
    finalized = []

    async def source():
        try:
            yield "data: first\n\n"
            await asyncio.sleep(60)  # 模拟发送背压冻结：永远走不到下一条
            yield "data: unreachable\n\n"
        finally:
            finalized.append(True)

    async def main():
        return [item async for item in _sse_stall_guard_iter(source(), "task-y")]

    assert asyncio.run(main()) == ["data: first\n\n"]
    # 生成器必须被真正关闭（finally 执行），不能泄漏挂起的协程
    assert finalized == [True]


def test_guard_propagates_source_exception(monkeypatch):
    monkeypatch.setattr("api.script_writer.SSE_STREAM_SEND_TIMEOUT_SECONDS", 1)

    async def source():
        yield "data: ok\n\n"
        raise RuntimeError("boom")

    collected = []

    async def main():
        with pytest.raises(RuntimeError):
            async for item in _sse_stall_guard_iter(source(), "task-z"):
                collected.append(item)

    asyncio.run(main())
    assert collected == ["data: ok\n\n"]
