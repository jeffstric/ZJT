/**
 * SSE 客户端工具（fetch + ReadableStream 实现）
 *
 * 背景：原生 EventSource 无法携带 Authorization 头，后端 SSE 端点已启用
 * Bearer 鉴权，故用 fetch 流式读取替代，并保持与 EventSource 相近的回调接口。
 * 参考实现：web/js/storyboard/api.js 的 streamStoryboardAgentTask。
 *
 * 用法：
 *   const stream = SSEClient.createEventStream('/api/task/{id}/stream', {
 *       onMessage: (data) => {...},        // data 为已解析的 JSON 对象
 *       onError: (error) => {...},         // 网络中断/重连耗尽/HTTP 非 2xx
 *       onClose: (data) => {...},          // 收到 done/error 后的收尾
 *       onReconnect: (attempt, reason) => {...},  // 断流自动重连前回调（可选）
 *   }, {
 *       lastId: 123,              // 可选断点续传
 *       idleTimeoutMs: 15000,     // 可选空闲读超时：超过该时长连 1 个字节
 *                                 // （含服务端心跳）都收不到即判定链路静默假死，
 *                                 // 自动带 Last-Event-ID 断点续传重连；缺省 0 关闭
 *       maxReconnects: 6,         // 最大重连次数（缺省 3）
 *       reconnectDelayMs: 2000,   // 重连退避基数，指数退避（缺省 2000ms）
 *   });
 *   stream.close();               // 主动断开
 *
 * 断流重连说明：TCP/代理静默断开时 fetch 流不触发任何 error/close 事件，
 * 只能靠应用层心跳检测。服务端心跳约 1~3s 一条，调用方把 idleTimeoutMs 设为
 * 心跳间隔的 5 倍以上即可安全区分"慢"与"死"。
 */
(function () {
    'use strict';

    function getAuthToken() {
        return localStorage.getItem('auth_token') || '';
    }

    function authHeaders() {
        const token = getAuthToken();
        const headers = { 'Accept': 'text/event-stream' };
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return headers;
    }

    function createEventStream(url, handlers = {}, opts = {}) {
        const idleTimeoutMs = opts.idleTimeoutMs || 0;
        const maxReconnects = opts.maxReconnects != null ? opts.maxReconnects : 3;
        const baseReconnectDelayMs = opts.reconnectDelayMs || 2000;
        let controller = null;
        let userClosed = false;
        let finished = false;  // 已收到 done/error 或流正常收尾，不再重连
        let lastEventId = opts.lastId || 0;
        let reconnectAttempts = 0;

        const run = async () => {
            while (true) {
                controller = new AbortController();
                let idleTimer = null;
                const clearIdle = () => {
                    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
                };
                // 空闲读超时包裹：任一时刻 read() 挂起超过 idleTimeoutMs 即放弃本条连接
                const readWithIdle = (reader) => new Promise((resolve, reject) => {
                    idleTimer = setTimeout(() => {
                        controller.abort();
                        reject(new Error('SSE_IDLE_TIMEOUT'));
                    }, idleTimeoutMs);
                    reader.read().then(
                        (chunk) => { clearIdle(); resolve(chunk); },
                        (err) => { clearIdle(); reject(err); }
                    );
                });
                try {
                    const headers = authHeaders();
                    if (lastEventId > 0) headers['Last-Event-ID'] = String(lastEventId);
                    const resp = await fetch(url, {
                        headers,
                        signal: controller.signal,
                    });
                    if (!resp.ok || !resp.body) {
                        throw new Error(`HTTP ${resp.status}`);
                    }
                    reconnectAttempts = 0;  // 连接建立成功，重置退避计数
                    const reader = resp.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';
                    while (true) {
                        const chunk = idleTimeoutMs > 0 ? await readWithIdle(reader) : await reader.read();
                        if (chunk.done) break;
                        buffer += decoder.decode(chunk.value, { stream: true });
                        const parts = buffer.split(/\r?\n\r?\n/);
                        buffer = parts.pop() || '';
                        for (const part of parts) {
                            // 解析一个 SSE 事件块：data: 行 + 可选 id: 行
                            let dataPayload = null;
                            for (const line of part.split(/\r?\n/)) {
                                if (line.startsWith('data:')) {
                                    dataPayload = (dataPayload || '') + line.slice(5).trim();
                                } else if (line.startsWith('id:')) {
                                    const id = parseInt(line.slice(3).trim(), 10);
                                    if (!Number.isNaN(id)) lastEventId = id;
                                }
                            }
                            if (dataPayload === null) continue;
                            let data;
                            try {
                                data = JSON.parse(dataPayload);
                            } catch (e) {
                                data = { type: 'message', content: dataPayload };
                            }
                            if (handlers.onMessage) await handlers.onMessage(data);
                            if (data.type === 'done' || data.type === 'error') {
                                finished = true;
                                if (handlers.onClose) handlers.onClose(data);
                                controller.abort();
                                return;
                            }
                        }
                    }
                    // 流正常关闭但未收到 done/error（如服务端完成响应），按收尾处理
                    finished = true;
                    if (handlers.onClose) handlers.onClose({ type: 'done' });
                    return;
                } catch (error) {
                    clearIdle();
                    if (userClosed || finished || error.name === 'AbortError') return;
                    const reason = error.message === 'SSE_IDLE_TIMEOUT' ? 'idle-timeout' : (error.message || 'error');
                    if (idleTimeoutMs <= 0 || reconnectAttempts >= maxReconnects) {
                        console.warn(`[SSEClient] 流失败且不再重连（${reason}，已重连 ${reconnectAttempts} 次）:`, url);
                        throw error;
                    }
                    reconnectAttempts += 1;
                    const delay = baseReconnectDelayMs * Math.pow(2, reconnectAttempts - 1);
                    console.warn(`[SSEClient] 流中断（${reason}），${delay}ms 后第 ${reconnectAttempts}/${maxReconnects} 次断点续传重连（lastEventId=${lastEventId}）:`, url);
                    if (handlers.onReconnect) handlers.onReconnect(reconnectAttempts, reason);
                    await new Promise(r => setTimeout(r, delay));
                    if (userClosed) return;
                    // 循环继续：用最新 lastEventId 重新连接，服务端跳过已发消息
                }
            }
        };

        run().catch((error) => {
            if (error.name === 'AbortError') return;
            if (handlers.onError) handlers.onError(error);
        });

        return {
            close: () => {
                userClosed = true;
                if (controller) controller.abort();
            },
            getLastEventId: () => lastEventId,
        };
    }

    window.SSEClient = { createEventStream, authHeaders, getAuthToken };
})();
