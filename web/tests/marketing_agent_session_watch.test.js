import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const require_ = createRequire(import.meta.url);
const AgentMessageDedupe = require_('../js/agent_message_dedupe.js');

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

// 回归背景（2026-11-12，dev3 实测）：生成任务失败后，后端通知器主动触发一轮
// PM（询问是否去音轨重试），该轮次是新的 agent_task，前端没有它的 SSE 监听
// （SSE 按 task 维度建立），PM 回复只落库 chat_messages，不刷新页面就看不到。
// 方案 A 契约：
//   1. 失败终态后启动 startSessionMessageWatcher（agent 视频/图片两处 poll 失败分支）
//   2. 首轮 tick 只建立基线（已有消息 id 集合），不追加历史
//   3. 后续 tick 发现基线之后新增的 AI 侧消息（assistant/verification）追加并滚动
//   4. 内容查重防线：同内容消息不重复追加；user 消息不追加
//   5. 会话切换即停止并清理；用户活跃收发（isLoading）跳过本轮
//   6. 同会话重复启动只续期不重复建 watcher

// ---------- 从 IIFE 源码切片提取被测函数，注入 mock 依赖后真实执行 ----------
// 注意：整个场景在单次 AsyncFunction 内完成（作用域内 Map/计数跨步骤共享），
// 断言所需状态通过 return 的 result 对象带出。
function extractSlice(startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    expect(start, `未找到切片起点 ${startMarker}`).toBeGreaterThan(-1);
    const end = endMarker ? source.indexOf(endMarker, start) : -1;
    return source.slice(start, end > start ? end : undefined);
}

const fnKey = extractSlice('function _historyMessageWatchKey', 'function startSessionMessageWatcher');
const fnWatch = extractSlice('function startSessionMessageWatcher', 'function stopTaskAfterRepeatedErrors');

async function runScenario(historyQueue, script) {
    const calls = { historyFetches: 0, scrolled: 0, intervals: [], cleared: [] };
    const messages = { value: [] };
    const pendingVerificationId = { value: null };
    const scope = `
        const window = { AgentMessageDedupe: this.agentMessageDedupe };
        const calls = this.calls;
        const messages = this.messages;
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
        const parseHistoryMessage = (h) => {
            let vData = null;
            if (h.role === 'verification' && typeof h.content === 'string') {
                try { vData = JSON.parse(h.content); } catch (e) { vData = null; }
            }
            return {
                // 与真实 parseHistoryMessage 一致：assistant/verification 统一归一为 'ai'
                role: (h.role === 'assistant' || h.role === 'verification') ? 'ai' : h.role,
                content: h.content,
                isVerification: h.role === 'verification',
                verificationOptions: h.role === 'verification' ? ['去除音轨后重新克隆'] : undefined,
                verificationId: vData ? vData.verification_id : null,
                verificationStatus: vData ? (vData.status || null) : null,
            };
        };
        const scrollToBottom = () => { calls.scrolled += 1; };
        const trackedSetInterval = (fn, delay) => { calls.intervals.push({ fn, delay }); return calls.intervals.length; };
        const trackedClearInterval = (id) => { calls.cleared.push(id); };
        const settle = () => new Promise(r => setTimeout(r, 0));
    `;
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    const fn = new AsyncFunction(`${scope}\n${fnKey}\n${fnWatch}\n${script}`);
    const result = await fn.call({ calls, messages, historyQueue, currentSessionId: { value: 'sess-1' }, isLoading: { value: false }, pendingVerificationId, agentMessageDedupe: AgentMessageDedupe });
    return { calls, messages, pendingVerificationId, result };
}

const BASE_HISTORY = [
    { message_id: 'm1', role: 'user', content: '帮我克隆视频', timestamp: '2026-11-12T10:00:00' },
    { message_id: 'm2', role: 'assistant', content: '已提交视频生成任务', timestamp: '2026-11-12T10:00:05' },
    { message_id: 'm3', role: 'assistant', content: '<span style="color:#dc2626;">内容审核未通过（音频版权）…</span>', timestamp: '2026-11-12T10:05:00' },
];

describe('marketing_agent 会话新消息临时监视（失败通知回复实时感知，方案 A）', () => {
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

    it('首轮 tick 只建立基线不追加；interval 已注册', async () => {
        const historyQueue = [BASE_HISTORY];
        const { calls, messages } = await runScenario(historyQueue, `
            startSessionMessageWatcher('sess-1');
            await settle(); await settle();
            return { intervals: calls.intervals.length, appended: messages.value.length, fetches: calls.historyFetches };
        `);
        expect(result_or_self({ intervals: calls.intervals.length, appended: messages.value.length, fetches: calls.historyFetches }));
        expect(calls.intervals.length).toBe(1);
        expect(messages.value.length).toBe(0);
        expect(calls.historyFetches).toBe(1);
    });

    it('基线后新增 assistant/verification 消息被追加滚动，user 消息不追加', async () => {
        const withNew = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'assistant', content: '是否需要我先去除参考视频的音轨，再重新提交克隆？', timestamp: '2026-11-12T10:08:00' },
            { message_id: 'm5', role: 'verification', content: JSON.stringify({ title: 'marketing-video 向您提问', description: '如何处理？', options: ['去除音轨后重新克隆'], verification_id: 'v1' }), timestamp: '2026-11-12T10:08:05' },
            { message_id: 'm6', role: 'user', content: '用户自己的新消息', timestamp: '2026-11-12T10:08:10' },
        ];
        const historyQueue = [BASE_HISTORY, withNew];
        const { calls, messages } = await runScenario(historyQueue, `
            startSessionMessageWatcher('sess-1');
            await settle(); await settle();          // 第一轮：基线
            const lastInterval = calls.intervals[calls.intervals.length - 1];
            await lastInterval.fn(); await settle(); // 第二轮：发现新增
            return { appended: messages.value.length, scrolled: calls.scrolled };
        `);
        expect(messages.value.length).toBe(2); // assistant + verification，user 不追加
        expect(messages.value[0].content).toContain('去除参考视频的音轨');
        expect(messages.value[1].isVerification).toBe(true);
        expect(calls.scrolled).toBeGreaterThan(0);
    });

    it('内容查重：本地已有同内容消息时不重复追加', async () => {
        const withNew = [
            ...BASE_HISTORY,
            { message_id: 'm4', role: 'assistant', content: '是否需要我先去除参考视频的音轨，再重新提交克隆？', timestamp: '2026-11-12T10:08:00' },
        ];
        const historyQueue = [BASE_HISTORY, withNew];
        const { messages } = await runScenario(historyQueue, `
            // 本地已渲染过同内容消息（如经其他通道到达）
            messages.value.push({ role: 'ai', content: '是否需要我先去除参考视频的音轨，再重新提交克隆？' });
            startSessionMessageWatcher('sess-1');
            await settle(); await settle();
            const lastInterval = calls.intervals[calls.intervals.length - 1];
            await lastInterval.fn(); await settle();
            return { appended: messages.value.length };
        `);
        expect(messages.value.length).toBe(1); // 未追加重复
    });

    it('会话切换后 tick 自停并清理 watcher', async () => {
        const historyQueue = [BASE_HISTORY];
        const { calls, result } = await runScenario(historyQueue, `
            startSessionMessageWatcher('sess-1');
            await settle(); await settle();
            currentSessionId.value = 'sess-other';  // 模拟切换会话
            const lastInterval = calls.intervals[calls.intervals.length - 1];
            await lastInterval.fn(); await settle();
            return { stillWatching: sessionMessageWatchers.has('sess-1'), cleared: calls.cleared.length };
        `);
        expect(result.stillWatching).toBe(false);
        expect(result.cleared).toBeGreaterThan(0);
    });

    it('isLoading 活跃时跳过本轮拉取', async () => {
        const historyQueue = [BASE_HISTORY];
        const { calls } = await runScenario(historyQueue, `
            startSessionMessageWatcher('sess-1');
            await settle(); await settle();
            isLoading.value = true;
            const fetchesBefore = calls.historyFetches;
            const lastInterval = calls.intervals[calls.intervals.length - 1];
            await lastInterval.fn(); await settle();
            return { before: fetchesBefore, after: calls.historyFetches };
        `);
        expect(result_or_self({ after: calls.historyFetches }));
        expect(calls.historyFetches).toBe(1); // 第二轮被 isLoading 拦截，未拉取
    });

    it('追加 verification 询问卡片时登记活跃验证（按钮可点）', async () => {
        const verifMsg = { message_id: 'm4', role: 'verification', content: JSON.stringify({ title: '营销智能体 向您提问', description: '请选择处理方式', options: ['去除音轨后重新克隆'], verification_id: 'verif-9' }), timestamp: '2026-11-12T10:08:00' };
        const historyQueue = [BASE_HISTORY, [...BASE_HISTORY, verifMsg]];
        const { messages, pendingVerificationId } = await runScenario(historyQueue, `
            startSessionMessageWatcher('sess-1');
            await settle(); await settle();
            const lastInterval = calls.intervals[calls.intervals.length - 1];
            await lastInterval.fn(); await settle();
            return { appended: messages.value.length };
        `);
        expect(messages.value.length).toBe(1);
        expect(messages.value[0].isVerification).toBe(true);
        // 核心断言：登记活跃验证 → isActiveVerificationMessage 为真 → 按钮可点
        expect(pendingVerificationId.value).toBe('verif-9');
    });

    it('已回答状态的 verification 不登记为活跃验证', async () => {
        const verifMsg = { message_id: 'm4', role: 'verification', content: JSON.stringify({ title: 'q', description: 'd', options: ['a'], verification_id: 'verif-old', status: 'answered' }), timestamp: '2026-11-12T10:08:00' };
        const historyQueue = [BASE_HISTORY, [...BASE_HISTORY, verifMsg]];
        const { pendingVerificationId } = await runScenario(historyQueue, `
            startSessionMessageWatcher('sess-1');
            await settle(); await settle();
            const lastInterval = calls.intervals[calls.intervals.length - 1];
            await lastInterval.fn(); await settle();
            return {};
        `);
        expect(pendingVerificationId.value).toBeNull();
    });

    it('同会话重复启动只续期不重复建 watcher', async () => {
        const historyQueue = [BASE_HISTORY];
        const { calls, result } = await runScenario(historyQueue, `
            startSessionMessageWatcher('sess-1');
            await settle();
            startSessionMessageWatcher('sess-1');  // 第二次：应走续期分支
            await settle();
            return { watchers: sessionMessageWatchers.size, intervals: calls.intervals.length };
        `);
        expect(result.watchers).toBe(1);
        expect(result.intervals).toBe(1);
    });
});

// runScenario 返回 { calls, messages, result }；此辅助仅用于让断言目标显式
function result_or_self(obj) {
    expect(obj).toBeTruthy();
    return obj;
}
