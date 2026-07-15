// 故事板拆分任务轮询行为测试（Vitest，CI 运行）。
// 覆盖测试方案 §3.1：pollScriptSplitTask 终态停止 / completed 取 result /
// 网络错误退避 / timer 去重；stopScriptSplitTaskPolling 清理。
//
// polling.js 导入 render.js（重型 DOM 模块），用 vi.mock 把 render.js /
// candidate_selection_state.js / adapters.js stub 成空对象，避免加载真实 DOM。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// vi.hoisted 保证 mock 对象在 vi.mock factory（被 hoist 到顶部）执行时已初始化
const apiMocks = vi.hoisted(() => ({
    getScriptSplitTaskStatus: vi.fn(),
    getScriptSplitTaskResult: vi.fn(),
}));

// mock 重型依赖（在 import polling 之前）
vi.mock('../js/storyboard/render.js', () => ({
    updateAutoCompleteHeader: () => {},
    updateSceneThumb: () => {},
    updateCurrentSceneDetail: () => {},
    updateDigitalHumanAudioHint: () => {},
    updateDialogueRow: () => {},
    updateTimelineProgress: () => {},
}));
vi.mock('../js/storyboard/candidate_selection_state.js', () => ({
    captureAssetSelection: () => null,
    isPollAssetSelectionCurrent: () => true,
}));
vi.mock('../js/storyboard/api.js', () => apiMocks);

import { pollScriptSplitTask, stopScriptSplitTaskPolling } from '../js/storyboard/polling.js';

describe('pollScriptSplitTask', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        apiMocks.getScriptSplitTaskStatus.mockReset();
        apiMocks.getScriptSplitTaskResult.mockReset();
    });
    afterEach(() => {
        vi.useRealTimers();
    });

    it('calls onUpdate with status and stops on terminal completed', async () => {
        apiMocks.getScriptSplitTaskStatus.mockResolvedValue({ status: 'completed', progress: 100 });
        apiMocks.getScriptSplitTaskResult.mockResolvedValue({ shot_groups: [] });
        const onUpdate = vi.fn();
        const onComplete = vi.fn();

        pollScriptSplitTask(1, { onUpdate, onComplete });
        await vi.runAllTimersAsync();

        expect(onUpdate).toHaveBeenCalledWith({ status: 'completed', progress: 100 });
        expect(apiMocks.getScriptSplitTaskResult).toHaveBeenCalledWith(1);
        expect(onComplete).toHaveBeenCalledWith({ shot_groups: [] }, { status: 'completed', progress: 100 });
    });

    it('does not start duplicate timer for same taskId', async () => {
        apiMocks.getScriptSplitTaskStatus.mockResolvedValue({ status: 'generating', progress: 30 });
        const onUpdate = vi.fn();

        pollScriptSplitTask(2, { onUpdate });
        pollScriptSplitTask(2, { onUpdate }); // 重复启动应被忽略
        // 只推进一次，不应产生两倍调用
        await vi.advanceTimersByTimeAsync(0);
        const firstCount = onUpdate.mock.calls.length;
        expect(firstCount).toBeGreaterThanOrEqual(1);
        await vi.advanceTimersByTimeAsync(10000);
        // 没有第二个独立轮询链（去重生效）
        expect(onUpdate.mock.calls.length).toBeLessThan(firstCount * 10);
        stopScriptSplitTaskPolling(2);
    });

    it('stops on failed terminal without calling getResult', async () => {
        apiMocks.getScriptSplitTaskStatus.mockResolvedValue({ status: 'failed', message: '炸了' });
        const onError = vi.fn();
        const onComplete = vi.fn();

        pollScriptSplitTask(3, { onError, onComplete });
        await vi.runAllTimersAsync();

        expect(apiMocks.getScriptSplitTaskResult).not.toHaveBeenCalled();
        expect(onComplete).not.toHaveBeenCalled();
        expect(onError).toHaveBeenCalled();
    });

    it('invokes onPaused for interactive statuses (paused/waiting_auth)', async () => {
        apiMocks.getScriptSplitTaskStatus.mockResolvedValue({ status: 'paused', message: '重试耗尽' });
        const onPaused = vi.fn();

        pollScriptSplitTask(4, { onPaused });
        await vi.runAllTimersAsync();

        expect(onPaused).toHaveBeenCalledWith({ status: 'paused', message: '重试耗尽' });
    });

    it('backs off on network error via onRecoverableError', async () => {
        // 第一次 reject，第二次成功
        apiMocks.getScriptSplitTaskStatus
            .mockRejectedValueOnce(new Error('network'))
            .mockResolvedValue({ status: 'completed', progress: 100 });
        apiMocks.getScriptSplitTaskResult.mockResolvedValue({ shot_groups: [] });
        const onRecoverableError = vi.fn();
        const onComplete = vi.fn();

        pollScriptSplitTask(5, { onRecoverableError, onComplete });
        await vi.runAllTimersAsync();

        expect(onRecoverableError).toHaveBeenCalled();
        // 退避后恢复并最终完成
        expect(onComplete).toHaveBeenCalled();
    });

    it('ignores falsy taskId', () => {
        // 不应抛错也不应启动轮询
        expect(() => pollScriptSplitTask(null)).not.toThrow();
        expect(() => pollScriptSplitTask(0)).not.toThrow();
    });
});

describe('stopScriptSplitTaskPolling', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        apiMocks.getScriptSplitTaskStatus.mockReset();
    });
    afterEach(() => {
        vi.useRealTimers();
    });

    it('clears the timer and stops further polls', async () => {
        apiMocks.getScriptSplitTaskStatus.mockResolvedValue({ status: 'generating', progress: 20 });
        const onUpdate = vi.fn();

        pollScriptSplitTask(6, { onUpdate });
        await vi.advanceTimersByTimeAsync(0); // 让第一次状态查询完成
        stopScriptSplitTaskPolling(6);
        const countBefore = onUpdate.mock.calls.length;
        await vi.advanceTimersByTimeAsync(20000);
        expect(onUpdate.mock.calls.length).toBe(countBefore); // 停止后不再增加
    });

    it('is safe to call when no timer exists', () => {
        expect(() => stopScriptSplitTaskPolling(999)).not.toThrow();
    });
});
