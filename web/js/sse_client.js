/**
 * SSE 客户端工具（fetch + ReadableStream 实现）
 *
 * 背景：原生 EventSource 无法携带 Authorization 头，后端 SSE 端点已启用
 * Bearer 鉴权，故用 fetch 流式读取替代，并保持与 EventSource 相近的回调接口。
 * 参考实现：web/js/storyboard/api.js 的 streamStoryboardAgentTask。
 *
 * 用法：
 *   const stream = SSEClient.createEventStream('/api/task/{id}/stream', {
 *       onMessage: (data) => {...},   // data 为已解析的 JSON 对象
 *       onError: (error) => {...},    // 网络中断/HTTP 非 2xx
 *       onClose: (data) => {...},     // 收到 done/error 后的收尾
 *   }, { lastId: 123 });              // 可选断点续传
 *   stream.close();                   // 主动断开
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
        const controller = new AbortController();
        let lastEventId = opts.lastId || 0;

        const run = async () => {
            const resp = await fetch(url, {
                headers: authHeaders(),
                signal: controller.signal,
            });
            if (!resp.ok || !resp.body) {
                throw new Error(`HTTP ${resp.status}`);
            }
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
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
                        if (handlers.onClose) handlers.onClose(data);
                        controller.abort();
                        return;
                    }
                }
            }
            // 流正常关闭但未收到 done/error（如服务端完成响应），按收尾处理
            if (handlers.onClose) handlers.onClose({ type: 'done' });
        };

        run().catch((error) => {
            if (error.name === 'AbortError') return;
            if (handlers.onError) handlers.onError(error);
        });

        return {
            close: () => controller.abort(),
            getLastEventId: () => lastEventId,
        };
    }

    window.SSEClient = { createEventStream, authHeaders, getAuthToken };
})();
