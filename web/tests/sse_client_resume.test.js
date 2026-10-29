/**
 * SSE 客户端断点续传（fix ce1b6d110「SSE 链路静默假死修复」）。
 *
 * 契约：
 * - 空闲读超时（idleTimeoutMs）判定链路假死 → 带 Last-Event-ID 断点续传重连
 * - done/error 收尾后不再重连；close() 主动断开不触发 onError
 * - 重连指数退避（2^n），连接成功清零 attempts；耗尽后 throw → onError
 * - lastEventId>0 时请求头带 Last-Event-ID；HTTP 非 2xx 直接失败
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/sse_client.js'), 'utf8');

function loadClient({ token = 'tok-1' } = {}) {
  const context = {
    window: {},
    console,
    fetch: vi.fn(),
    localStorage: { getItem: vi.fn(() => token) },
    setTimeout,
    clearTimeout,
    AbortController,
    TextDecoder,
    Promise,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { client: context.window.SSEClient, fetchMock: context.fetch };
}

const sseBlock = (obj, id) => {
  const data = typeof obj === 'string' ? obj : JSON.stringify(obj);
  return `id: ${id}\ndata: ${data}\n\n`;
};

// 一次性给完事件后关闭的流
function makeStream(blocks) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const b of blocks) controller.enqueue(encoder.encode(b));
      controller.close();
    },
  });
}

// read() 永不 resolve 的流（模拟 TCP 静默断开）
function makePendingStream() {
  return new ReadableStream({
    start() { /* 不 enqueue 也不 close */ },
  });
}

const okResponse = (body) => ({ ok: true, status: 200, body });

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('SSEClient 基础解析与收尾', () => {
  it('解析 data:/id: 事件，done 收尾不再重连', async () => {
    const { client, fetchMock } = loadClient();
    fetchMock.mockResolvedValue(okResponse(makeStream([
      sseBlock({ type: 'progress', content: 'a' }, 1),
      sseBlock({ type: 'done' }, 5),
    ])));
    const onMessage = vi.fn();
    const onClose = vi.fn();
    const onError = vi.fn();

    client.createEventStream('/api/x/stream', { onMessage, onClose, onError });
    await flush(); await flush(); await flush();

    expect(onMessage).toHaveBeenCalledTimes(2);
    expect(onClose).toHaveBeenCalledWith({ type: 'done' });
    expect(onError).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('非 JSON data 降级为 message 类型', async () => {
    const { client, fetchMock } = loadClient();
    fetchMock.mockResolvedValue(okResponse(makeStream(['data: 纯文本\n\n'])));
    const onMessage = vi.fn();
    client.createEventStream('/api/x/stream', { onMessage });
    await flush(); await flush();
    expect(onMessage).toHaveBeenCalledWith({ type: 'message', content: '纯文本' });
  });

  it('error 事件同样收尾（finished=true）', async () => {
    const { client, fetchMock } = loadClient();
    fetchMock.mockResolvedValue(okResponse(makeStream([sseBlock({ type: 'error', message: 'x' }, 2)])));
    const onClose = vi.fn();
    const onError = vi.fn();
    client.createEventStream('/api/x/stream', { onClose, onError });
    await flush(); await flush();
    expect(onClose).toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });
});

describe('SSEClient 断点续传', () => {
  it('lastId>0 时请求头携带 Last-Event-ID', async () => {
    const { client, fetchMock } = loadClient();
    fetchMock.mockResolvedValue(okResponse(makeStream([sseBlock({ type: 'done' }, 1)])));
    client.createEventStream('/api/x/stream', {}, { lastId: 42 });
    await flush(); await flush();
    expect(fetchMock.mock.calls[0][1].headers['Last-Event-ID']).toBe('42');
  });

  it('lastId=0 时请求头不带 Last-Event-ID', async () => {
    const { client, fetchMock } = loadClient();
    fetchMock.mockResolvedValue(okResponse(makeStream([sseBlock({ type: 'done' }, 1)])));
    client.createEventStream('/api/x/stream', {});
    await flush(); await flush();
    expect(fetchMock.mock.calls[0][1].headers['Last-Event-ID']).toBeUndefined();
  });

  it('空闲超时判定假死后带最新 lastEventId 重连', async () => {
    const { client, fetchMock } = loadClient();
    // 第一次连接：先收到一条 id:7 的消息，然后 read 永久挂起（链路静默假死）
    const encoder = new TextEncoder();
    let firstReaderResolve = null;
    const hangAfterFirst = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(sseBlock({ type: 'progress' }, 7)));
      },
      pull() {
        return new Promise((resolve) => { firstReaderResolve = resolve; });
      },
    });
    fetchMock.mockResolvedValueOnce(okResponse(hangAfterFirst));
    fetchMock.mockResolvedValueOnce(okResponse(makeStream([sseBlock({ type: 'done' }, 8)])));

    const onReconnect = vi.fn();
    const onClose = vi.fn();
    client.createEventStream(
      '/api/x/stream', { onReconnect, onClose },
      { idleTimeoutMs: 15, reconnectDelayMs: 5, maxReconnects: 3 },
    );

    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    }, { timeout: 3000, interval: 10 });

    // 重连请求必须带断点：服务端据此跳过已消费的 id:7
    expect(fetchMock.mock.calls[1][1].headers['Last-Event-ID']).toBe('7');
    expect(onReconnect).toHaveBeenCalledWith(1, 'idle-timeout');
    await flush(); await flush();
    expect(onClose).toHaveBeenCalledWith({ type: 'done' });
    if (firstReaderResolve) firstReaderResolve();
  });

  it('连接阶段反复失败达到上限后抛错给 onError（读挂起不算失败连接）', async () => {
    // 注意语义：attempts 只在「连接建立失败」（HTTP 非 2xx / fetch reject）时累计；
    // 连接成功后的读挂起不算失败连接（会清零重计），因此耗尽只能由连接失败触发
    const { client, fetchMock } = loadClient();
    fetchMock.mockResolvedValue({ ok: false, status: 502, body: null });
    const onError = vi.fn();
    const onReconnect = vi.fn();

    client.createEventStream(
      '/api/x/stream', { onError, onReconnect },
      { idleTimeoutMs: 10, reconnectDelayMs: 5, maxReconnects: 2 },
    );

    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalled();
    }, { timeout: 3000, interval: 10 });

    // 初次 + 2 次重连 = 3 次 fetch；第 3 次连接失败（attempts 已达上限）才 throw
    expect(fetchMock.mock.calls.length).toBe(3);
    expect(onReconnect.mock.calls.map((c) => c[0])).toEqual([1, 2]);
    expect(onReconnect).toHaveBeenCalledWith(2, 'HTTP 502');
  });

  it('重连成功建立连接后 attempts 清零（读阶段假死重新从 1 计）', async () => {
    const { client, fetchMock } = loadClient();
    // 第一次：连接失败（attempts → 1）
    fetchMock.mockResolvedValueOnce({ ok: false, status: 502, body: null });
    // 第二次：重连成功建立连接（attempts 清零），但读阶段静默假死
    fetchMock.mockResolvedValueOnce(okResponse(makePendingStream()));
    // 之后全部连接失败，从清零后的 0 重新累计
    fetchMock.mockResolvedValue({ ok: false, status: 502, body: null });

    const onReconnect = vi.fn();
    const onError = vi.fn();
    client.createEventStream(
      '/api/x/stream', { onReconnect, onError },
      { idleTimeoutMs: 10, reconnectDelayMs: 5, maxReconnects: 2 },
    );

    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalled();
    }, { timeout: 3000, interval: 10 });

    // 关键断言：读阶段假死后的重连 attempt 回到 1（若未清零则为 2）
    const reasons = onReconnect.mock.calls.map((c) => c[1]);
    expect(reasons).toContain('HTTP 502');
    expect(reasons).toContain('idle-timeout');
    // 序列：(1,'HTTP 502') → (1,'idle-timeout')（清零后重计）→ (2,'HTTP 502') → 耗尽
    expect(onReconnect.mock.calls.map((c) => c[0])).toEqual([1, 1, 2]);
    expect(fetchMock.mock.calls.length).toBe(4);
  });

  it('close() 主动断开后不触发 onError', async () => {
    const { client, fetchMock } = loadClient();
    fetchMock.mockResolvedValue(okResponse(makePendingStream()));
    const onError = vi.fn();

    const stream = client.createEventStream(
      '/api/x/stream', { onError },
      { idleTimeoutMs: 10, reconnectDelayMs: 5 },
    );
    await flush();
    stream.close();
    await flush(); await flush(); await flush();
    expect(onError).not.toHaveBeenCalled();
  });

  it('HTTP 非 2xx 直接 onError（idle 关闭时不重试）', async () => {
    const { client, fetchMock } = loadClient();
    fetchMock.mockResolvedValue({ ok: false, status: 502, body: null });
    const onError = vi.fn();
    client.createEventStream('/api/x/stream', { onError }, { idleTimeoutMs: 0 });
    await flush(); await flush();
    expect(onError).toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('SSEClient 鉴权头', () => {
  it('token 存在时带 Bearer Authorization 头', () => {
    const { client } = loadClient({ token: 'tok-abc' });
    const headers = client.authHeaders();
    expect(headers.Authorization).toBe('Bearer tok-abc');
    expect(headers.Accept).toBe('text/event-stream');
  });

  it('无 token 时仅带 Accept 头', () => {
    const { client } = loadClient({ token: '' });
    const headers = client.authHeaders();
    expect(headers.Authorization).toBeUndefined();
  });
});
