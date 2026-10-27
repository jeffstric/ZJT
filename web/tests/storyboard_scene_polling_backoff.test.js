// 场景任务轮询接入 poll_scheduler 的行为测试（f1096）。
// 覆盖：退避节拍（2s→3s）/ 重复启动去重 / 终态收尾（loadSceneCandidates + 停轮询）/
// 场景被删后自停 / 连续失败放弃。mock 套路沿用 storyboard_script_split_polling.test.js。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
    getSceneTaskStatus: vi.fn(),
}));
const candidatesMocks = vi.hoisted(() => ({
    loadSceneCandidates: vi.fn(async () => {}),
}));

vi.mock('../js/storyboard/render.js', () => ({
    updateAutoCompleteHeader: () => {},
    updateSceneThumb: () => {},
    updateCurrentSceneDetail: () => {},
    updateDigitalHumanAudioHint: () => {},
    updateDialogueRow: () => {},
    updateDialogueAudioSourcePanel: () => {},
    updateTimelineProgress: () => {},
    refresh: () => {},
    Region: { LEFT_TAB_BODY: 'left_tab_body' },
}));
vi.mock('../js/storyboard/candidate_selection_state.js', () => ({
    captureAssetSelection: () => null,
    isPollAssetSelectionCurrent: () => true,
}));
vi.mock('../js/storyboard/api.js', () => apiMocks);
vi.mock('../js/storyboard/scene_candidates.js', () => candidatesMocks);

import state from '../js/storyboard/state.js';
import scheduler from '../js/poll_scheduler.js';
import { pollSceneTaskStatus } from '../js/storyboard/polling.js';

const RUNNING = { first_frame: { status: 1 } };       // PROCESSING → hasRunning
const TERMINAL = { first_frame: { status: 2 } };      // COMPLETED → 终态

describe('pollSceneTaskStatus（poll_scheduler 接入）', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        apiMocks.getSceneTaskStatus.mockReset();
        candidatesMocks.loadSceneCandidates.mockClear();
    });
    afterEach(() => {
        scheduler.cancelAll();
        vi.useRealTimers();
    });

    it('同一响应退避：2s 后第 2 次、再 3s 后第 3 次（原固定 4s）', async () => {
        apiMocks.getSceneTaskStatus.mockResolvedValue(RUNNING);
        state.scenes = [{ id: 's-backoff', dialogues: [] }];

        pollSceneTaskStatus('s-backoff');
        await vi.advanceTimersByTimeAsync(0);
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(1);

        await vi.advanceTimersByTimeAsync(1999);
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(1);
        await vi.advanceTimersByTimeAsync(1); // t=2000
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(2);

        await vi.advanceTimersByTimeAsync(2999);
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(1); // t=5000
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(3);
    });

    it('状态变化（签名变化）重置回 2s 快档', async () => {
        let n = 0;
        apiMocks.getSceneTaskStatus.mockImplementation(async () => (
            n++ === 0 ? { first_frame: { status: 0 } } : { first_frame: { status: 1 } }
        ));
        state.scenes = [{ id: 's-reset', dialogues: [] }];

        pollSceneTaskStatus('s-reset');
        await vi.advanceTimersByTimeAsync(0);   // PENDING
        await vi.advanceTimersByTimeAsync(2000); // PROCESSING（签名变化，间隔重置 2000）
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(1999);
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(1);
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(3); // t=4000 仍在快档
    });

    it('重复启动被去重（单轮询链）', async () => {
        apiMocks.getSceneTaskStatus.mockResolvedValue(RUNNING);
        state.scenes = [{ id: 's-dedupe', dialogues: [] }];

        pollSceneTaskStatus('s-dedupe');
        pollSceneTaskStatus('s-dedupe');
        await vi.advanceTimersByTimeAsync(0);
        const first = apiMocks.getSceneTaskStatus.mock.calls.length;
        expect(first).toBe(1);
        await vi.advanceTimersByTimeAsync(10000);
        // 2s/3s/4.5s/…单链节奏，绝不应翻倍
        expect(apiMocks.getSceneTaskStatus.mock.calls.length).toBeLessThan(first * 6);
    });

    it('终态：停轮询并收尾刷新候选列表', async () => {
        apiMocks.getSceneTaskStatus
            .mockResolvedValueOnce(RUNNING)
            .mockResolvedValue(TERMINAL);
        state.scenes = [{ id: 's-term', dialogues: [] }];

        pollSceneTaskStatus('s-term');
        await vi.advanceTimersByTimeAsync(0); // 首轮 RUNNING：见过活动
        await vi.advanceTimersByTimeAsync(2000); // 第 2 轮 TERMINAL：收尾
        expect(candidatesMocks.loadSceneCandidates).toHaveBeenCalledWith('s-term');
        expect(scheduler.isActive('scene:s-term')).toBe(false);
        const calls = apiMocks.getSceneTaskStatus.mock.calls.length;
        await vi.advanceTimersByTimeAsync(60000);
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(calls); // 不再复活
    });

    it('场景被删：自动停止', async () => {
        apiMocks.getSceneTaskStatus.mockResolvedValue(RUNNING);
        state.scenes = [{ id: 's-gone', dialogues: [] }];

        pollSceneTaskStatus('s-gone');
        await vi.advanceTimersByTimeAsync(0); // 首轮 RUNNING：已排下一轮
        state.scenes = []; // 场景删除发生在首轮之后
        await vi.advanceTimersByTimeAsync(60000);
        expect(scheduler.isActive('scene:s-gone')).toBe(false);
        // 第 2 轮发现场景已删 → 自停（原实现同为下一轮自停）
        expect(apiMocks.getSceneTaskStatus.mock.calls.length).toBe(2);
    });

    it('连续失败达到阈值后放弃（不再无限重试）', async () => {
        apiMocks.getSceneTaskStatus.mockRejectedValue(new Error('network down'));
        state.scenes = [{ id: 's-dead', dialogues: [] }];

        pollSceneTaskStatus('s-dead');
        // 4+8+16+32+60*4 = 300s 完成 8 次失败
        await vi.advanceTimersByTimeAsync(310000);
        expect(apiMocks.getSceneTaskStatus.mock.calls.length).toBe(8);
        expect(scheduler.isActive('scene:s-dead')).toBe(false);
        const frozen = apiMocks.getSceneTaskStatus.mock.calls.length;
        await vi.advanceTimersByTimeAsync(600000);
        expect(apiMocks.getSceneTaskStatus).toHaveBeenCalledTimes(frozen);
    });
});
