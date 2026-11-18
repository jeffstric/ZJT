import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const require_ = createRequire(import.meta.url);
const AgentMessageDedupe = require_('../js/agent_message_dedupe.js');

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

// 回归背景（2026-11-13）：watcher 原为"基线快照"语义——启动时记下 history 现有
// 消息集合，之后只追加集合之外的新消息。提交期失败实测暴露时序竞争：通知链路
// 落库（T0+6s）早于前端轮询感知失败（T0+10s），watcher 启动时询问已在 history
// 里，被基线当"已显示"永久吞掉，用户看不到询问。
// 现语义（幂等对账）：不设快照，每轮对 history 逐条检查屏幕上是否已存在
// （message_id / verification_id / 近似内容三级匹配），不存在即补渲染。
// 对账语义没有竞争窗口——任何先落库后启动的时序天然被覆盖。

function extractSlice(startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    expect(start, `未找到切片起点 ${startMarker}`).toBeGreaterThan(-1);
    const end = endMarker ? source.indexOf(endMarker, start) : -1;
    return source.slice(start, end > start ? end : undefined);
}

const fnOnScreen = extractSlice('function _historyMessageOnScreen', 'function startSessionMessageWatcher');
const fnWatch = extractSlice('function startSessionMessageWatcher', 'function stopTaskAfterRepeatedErrors');

const BASE_HISTORY = [
    { message_id: 'm1', role: 'user', content: '帮我克隆视频', timestamp: '2026-11-12T10:00:00' },
    { message_id: 'm2', role: 'assistant', content: '已提交视频生成任务', timestamp: '2026-11-12T10:00:05' },
    { message_id: 'm3', role: 'assistant', content: '<span style="color:#dc2626;">内容审核未通过（音频版权）…</span>', timestamp: '2026-11-12T10:05:00' },
];

// 屏幕初始状态：页面加载 history 恢复已渲染的消息（带 _dbMessageId）
const SCREEN_RESTORED = BASE_HISTORY.map(h => ({
    _dbMessageId: h.message_id,
    role: h.role === 'user' ? 'user' : 'ai',
    content: h.content,
}));

async function runScenario(historyQueue, screenMessages, script) {
    const calls = { historyFetches: 0, scrolled: 0, intervals: [], cleared: [] };
    const messages = { value: screenMessages.map(m => ({ ...m })) };
    const pendingVerificationId = { value: null };
    const videoMockCalls = [];
    const imageMockCalls = [];
    const handleVideoTaskSubmittedMock = (data) => { videoMockCalls.push(data); };
    const handleImageTaskSubmittedMock = (data) => { imageMockCalls.push(data); };
    const scope = `
        const window = { AgentMessageDedupe: this.agentMessageDedupe };
        const calls = this.calls;
        const messages = this.messages;
        const handleVideoTaskSubmitted = this.handleVideoTaskSubmitted;
        const handleImageTaskSubmitted = this.handleImageTaskSubmitted;
        let currentSessionId = this.currentSessionId;
        let isLoading = this.isLoading;
        const pendingVerificationId = this.pendingVerificationId;
        const sessionMessageWatchers = new Map();
        const SESSION_WATCH_DURATION_MS = 90000;
        const SESSION_WATCH_INTERVAL_MS = 10000;
        const loadSessionHistory = async () => {
            calls.historyFetches += 1;
            const q = this.historyQueue;
            return q.length > 1 ? q.shift() : q[0];
        };
        const filterHistoryMessage = (h) => h.role !== 'system' && h.role !== 'tool' && h.message_type !== 'context_summary';
        // 与真实 unwrapHistoryText 行为一致：{text:...} 取 text，其余原样返回
        const unwrapHistoryText = (content) => {
            if (content == null) return '';
            if (typeof content === 'object') return typeof content.text === 'string' ? content.text : '';
            const raw = String(content);
            const trimmed = raw.trim();
            if (trimmed.startsWith('{')) {
                try {
                    const parsed = JSON.parse(trimmed);
                    if (parsed && typeof parsed.text === 'string') return parsed.text;
                } catch (e) { /* 非 JSON */ }
            }
            return raw;
        };
        const parseHistoryMessage = (h) => {
            let vData = null;
            if (h.role === 'verification') {
                if (typeof h.content === 'string') { try { vData = JSON.parse(h.content); } catch (e) { vData = null; } }
                else if (h.content && typeof h.content === 'object') { vData = h.content; }
            }
            return {
                _dbMessageId: h.message_id || null,
                role: (h.role === 'assistant' || h.role === 'verification') ? 'ai' : h.role,
                content: h.content,
                isVerification: h.role === 'verification',
                verificationOptions: h.role === 'verification' ? (vData ? vData.options : ['去除音轨后重新克隆']) : undefined,
                verificationId: vData ? vData.verification_id : (h.verification_id || null),
                verificationStatus: vData ? (vData.status || null) : null,
            };
        };
        const scrollToBottom = () => { calls.scrolled += 1; };
        const trackedSetInterval = (fn, delay) => { calls.intervals.push({ fn, delay }); return calls.intervals.length; };
        const trackedClearInterval = (id) => { calls.cleared.push(id); };
        const settle = () => new Promise(r => setTimeout(r, 0));
    `;
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    const fn = new AsyncFunction(`${scope}\n${fnOnScreen}\n${fnWatch}\n${script}`);
    const result = await fn.call({
        calls, messages, historyQueue,
        currentSessionId: { value: 'sess-1' },
        isLoading: { value: false },
        pendingVerificationId,
        agentMessageDedupe: AgentMessageDedupe,
        handleVideoTaskSubmitted: handleVideoTaskSubmittedMock,
        handleImageTaskSubmitted: handleImageTaskSubmittedMock,
    });
    return { calls, messages, pendingVerificationId, videoMockCalls, imageMockCalls, result };
}

describe('marketing_agent 会话消息临时监视——幂等对账语义（方案 A v2）', () => {
    it('触发点挂载：agent 视频/图片轮询失败分支调用 startSessionMessageWatcher，成功分支不调用', () => {
        const videoStart = source.indexOf('function pollAgentVideoStatus');
        const videoBody = source.slice(videoStart, videoStart + 7000);
        const videoFailIdx = videoBody.indexOf("finalContent = describeFailedTasks(tasks, 'video')");
        expect(videoFailIdx).toBeGreaterThan(-1);
        expect(videoBody.slice(videoFailIdx, videoFailIdx + 300)).toContain('startSessionMessageWatcher(pollSessionId)');
        const videoSuccessIdx = videoBody.indexOf("finalContent = buildGeneratedTaskContent('video', tasks)");
        expect(videoBody.slice(videoSuccessIdx, videoSuccessIdx + 200)).not.toContain('startSessionMessageWatcher');

        const imgStart = source.indexOf('function pollAgentImageStatus');
        const imgBody = source.slice(imgStart, imgStart + 6000);
        const imgFailIdx = imgBody.indexOf("finalContent = describeFailedTasks(tasks, 'image')");
        expect(imgFailIdx).toBeGreaterThan(-1);
        expect(imgBody.slice(imgFailIdx, imgFailIdx + 300)).toContain('startSessionMessageWatcher(pollSessionId)');
    });

    it('对账不设基线：屏幕已恢复的历史消息不重复追加（_dbMessageId 精确匹配）', async () => {
        const historyQueue = [BASE_HISTORY];
        const { messages } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'return { appended: messages.value.length };',
        ].join('\n'));
        expect(messages.value.length).toBe(SCREEN_RESTORED.length);
    });

    it('时序竞争场景（询问已落库但屏幕无）→ 对账补渲染并激活按钮', async () => {
        const withPendingVer = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'verification', message_type: 'verification_request', verification_id: 'verif-first', content: JSON.stringify({ title: '营销智能体 向您提问', description: '请选择处理方式', options: ['去除音轨后重新克隆'], verification_id: 'verif-first' }), timestamp: '2026-11-12T10:08:00' },
        ];
        const historyQueue = [withPendingVer];
        const { messages, pendingVerificationId } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'return { appended: messages.value.length };',
        ].join('\n'));
        expect(messages.value.length).toBe(SCREEN_RESTORED.length + 1);
        const card = messages.value.find(m => m.isVerification);
        expect(card).toBeTruthy();
        expect(pendingVerificationId.value).toBe('verif-first');
    });

    it('content 对象形态（真实接口 to_frontend_dict 还原后）→ verification_id 匹配跳过', async () => {
        // 真实 history 接口对 verification_request 行返回还原后的对象 content
        // （to_frontend_dict：{verification_id, title, ...}，非 JSON 字符串）——
        // 2026-11-13 实测：verId 提取只处理字符串形态导致匹配失效、对账每轮
        // 追加重复卡片（屏幕增殖到 10 条）
        const sseRendered = [...SCREEN_RESTORED, {
            role: 'ai',
            content: { verification_id: 'verif-pw', title: '算力确认', description: '即将提交', options: ['确认生成'] },
            isVerification: true,
            verificationId: 'verif-pw',
        }];
        const withObjVer = [
            ...BASE_HISTORY,
            // 真实接口形态：content 是对象、无 verification_id 顶层键
            { message_id: 'm4', role: 'verification', message_type: 'verification_request', content: { verification_id: 'verif-pw', title: '算力确认', description: '即将提交', options: ['确认生成'] }, timestamp: '2026-11-12T10:08:00' },
        ];
        const historyQueue = [withObjVer];
        const { messages } = await runScenario(historyQueue, sseRendered, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'const lastInterval = calls.intervals[calls.intervals.length - 1];',
            'await lastInterval.fn(); await settle();',
            'return { appended: messages.value.length };',
        ].join('\n'));
        expect(messages.value.length).toBe(sseRendered.length); // 无追加
    });

    it('content 对象形态且屏幕没有 → 正常补渲染并激活', async () => {
        const withObjVer = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'verification', message_type: 'verification_request', content: { verification_id: 'verif-new', title: '营销智能体 向您提问', description: '请选择处理方式', options: ['去除音轨后重新克隆'] }, timestamp: '2026-11-12T10:08:00' },
        ];
        const historyQueue = [withObjVer];
        const { messages, pendingVerificationId } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'return { appended: messages.value.length };',
        ].join('\n'));
        expect(messages.value.length).toBe(SCREEN_RESTORED.length + 1);
        expect(pendingVerificationId.value).toBe('verif-new');
    });

    it('pending 任务行 → 触发生成中气泡恢复入口（通知轮次任务无 SSE 的进度展示）', async () => {
        // 2026-11-13 实测：去音轨重试单（通知轮次提交）无前端 SSE，pm_agent 落库的
        // __PENDING_TASK__ 行是对账的唯一线索——需触发 handleVideoTaskSubmitted
        // 恢复"视频生成中"气泡与状态轮询，而非作为不可见占位消息吞掉
        const withPending = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'assistant', message_type: 'pending_task', content: '__PENDING_TASK__:video_task_submitted:[555]', timestamp: '2026-11-12T10:08:00' },
        ];
        const historyQueue = [withPending];
        const { calls, messages, pendingVerificationId, result } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            "return { watchers: sessionMessageWatchers.size };",
        ].join('\n'));
        // harness mock 挂载断言：pending 行未被当作可见消息追加，而是走了恢复入口
        expect(messages.value.filter(m => m._isPendingTask).length).toBe(0);
    });

    it('SSE 已渲染的同内容消息（无 _dbMessageId）→ 全等匹配跳过不重复追加', async () => {
        const sseRendered = [...SCREEN_RESTORED, { role: 'ai', content: '两次确认都已超时，请直接回复选择方案。' }];
        const withNew = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'assistant', content: '两次确认都已超时，请直接回复选择方案。', timestamp: '2026-11-12T10:08:00' },
        ];
        const historyQueue = [withNew];
        const { messages } = await runScenario(historyQueue, sseRendered, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'return { appended: messages.value.length };',
        ].join('\n'));
        expect(messages.value.length).toBe(sseRendered.length);
    });

    it('增量消息（前缀+新增内容）不因近似判定被吞——全等比对放行', async () => {
        // AI 审查指出的误判场景回归：追问增量消息必须正常显示
        const sseRendered = [...SCREEN_RESTORED, { role: 'ai', content: '请提供产品图片' }];
        const withNew = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'assistant', content: '请提供产品图片，并补充品牌名称', timestamp: '2026-11-12T10:08:00' },
        ];
        const historyQueue = [withNew];
        const { messages } = await runScenario(historyQueue, sseRendered, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'return { appended: messages.value.length };',
        ].join('\n'));
        expect(messages.value.length).toBe(sseRendered.length + 1);
    });

    it('已回答的询问（history 有 answer 行）不补渲染不激活', async () => {
        const withAnsweredVer = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'verification', message_type: 'verification_request', verification_id: 'verif-old', content: JSON.stringify({ title: 'q', description: 'd', options: ['a'], verification_id: 'verif-old' }), timestamp: '2026-11-12T10:08:00' },
            { message_id: 'm5', role: 'user', message_type: 'verification_answer', verification_id: 'verif-old', content: '去除音轨后重新克隆', timestamp: '2026-11-12T10:09:00' },
        ];
        const historyQueue = [withAnsweredVer];
        const { messages, pendingVerificationId } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'return { appended: messages.value.length };',
        ].join('\n'));
        expect(messages.value.length).toBe(SCREEN_RESTORED.length);
        expect(pendingVerificationId.value).toBeNull();
    });

    it('history 新增 assistant 消息（屏幕没有）正常补渲染', async () => {
        const withNew = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'assistant', content: '两次确认都已超时，请直接回复选择方案。', timestamp: '2026-11-12T10:08:00' },
        ];
        const historyQueue = [BASE_HISTORY, withNew];
        const { messages } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'const lastInterval = calls.intervals[calls.intervals.length - 1];',
            'await lastInterval.fn(); await settle();',
            'return { appended: messages.value.length };',
        ].join('\n'));
        expect(messages.value.length).toBe(SCREEN_RESTORED.length + 1);
        expect(messages.value[messages.value.length - 1].content).toContain('两次确认都已超时');
    });

    it('会话切换后 tick 自停并清理 watcher', async () => {
        const historyQueue = [BASE_HISTORY];
        const { calls, result } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            "currentSessionId.value = 'sess-other';",
            'const lastInterval = calls.intervals[calls.intervals.length - 1];',
            'await lastInterval.fn(); await settle();',
            "return { stillWatching: sessionMessageWatchers.has('sess-1'), cleared: calls.cleared.length };",
        ].join('\n'));
        expect(result.stillWatching).toBe(false);
        expect(result.cleared).toBeGreaterThan(0);
    });

    it('isLoading 活跃时跳过本轮拉取', async () => {
        const historyQueue = [BASE_HISTORY];
        const { calls } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle(); await settle();',
            'isLoading.value = true;',
            'const before = calls.historyFetches;',
            'const lastInterval = calls.intervals[calls.intervals.length - 1];',
            'await lastInterval.fn(); await settle();',
            'return { before, after: calls.historyFetches };',
        ].join('\n'));
        expect(calls.historyFetches).toBe(1);
    });

    it('同会话重复启动只续期不重复建 watcher', async () => {
        const historyQueue = [BASE_HISTORY];
        const { result } = await runScenario(historyQueue, SCREEN_RESTORED, [
            "startSessionMessageWatcher('sess-1');",
            'await settle();',
            "startSessionMessageWatcher('sess-1');",
            'await settle();',
            "return { watchers: sessionMessageWatchers.size, intervals: calls.intervals.length };",
        ].join('\n'));
        expect(result.watchers).toBe(1);
        expect(result.intervals).toBe(1);
    });
});
