// poll_scheduler 单元测试（f1096）。
// 覆盖：渐进退避曲线 / 签名变化重置 / 终态取消 / pollAfterMs 覆盖 / 错误指数退避与
// 连续失败放弃 / cancel 停止（含 in-flight 丢弃）/ 无进展软超时 / 页面隐藏暂停与恢复补轮。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import scheduler from '../js/poll_scheduler.js';

function setHidden(hidden) {
    Object.defineProperty(document, 'hidden', {
        configurable: true,
        get: () => hidden,
    });
    document.dispatchEvent(new Event('visibilitychange'));
}

describe('poll_scheduler', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });
    afterEach(() => {
        scheduler.cancelAll();
        setHidden(false);
        vi.useRealTimers();
    });

    it('unchanged signature grows interval 2s→3s→4.5s', async () => {
        const fn = vi.fn(async () => ({ done: false, signature: 'same' }));
        scheduler.schedule('k1', fn);

        await vi.advanceTimersByTimeAsync(0);
        expect(fn).toHaveBeenCalledTimes(1);

        await vi.advanceTimersByTimeAsync(1999);
        expect(fn).toHaveBeenCalledTimes(1);
        await vi.advanceTimersByTimeAsync(1); // t=2000
        expect(fn).toHaveBeenCalledTimes(2);

        await vi.advanceTimersByTimeAsync(2999);
        expect(fn).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(1); // t=5000（2000+3000）
        expect(fn).toHaveBeenCalledTimes(3);

        await vi.advanceTimersByTimeAsync(4499);
        expect(fn).toHaveBeenCalledTimes(3);
        await vi.advanceTimersByTimeAsync(1); // t=9500（+4500）
        expect(fn).toHaveBeenCalledTimes(4);
    });

    it('signature change resets interval to initial', async () => {
        let n = 0;
        const fn = vi.fn(async () => ({ done: false, signature: `sig-${n++}` }));
        scheduler.schedule('k2', fn);

        await vi.advanceTimersByTimeAsync(0); // 第 1 次，签名 sig-0（视为进展）
        await vi.advanceTimersByTimeAsync(2000); // 重置回 initial，第 2 次在 t=2000
        expect(fn).toHaveBeenCalledTimes(2);
        // 第 2 次返回 sig-1 仍是变化 → 间隔再次回到 2000
        await vi.advanceTimersByTimeAsync(1999);
        expect(fn).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(1);
        expect(fn).toHaveBeenCalledTimes(3);
    });

    it('interval is capped at max', async () => {
        const fn = vi.fn(async () => ({ done: false, signature: 'same' }));
        scheduler.schedule('k3', fn, { initial: 2000, growth: 1.5, max: 3000 });

        await vi.advanceTimersByTimeAsync(0);
        await vi.advanceTimersByTimeAsync(2000); // 第 2 次，间隔放大 3000（2*1.5）已触顶
        expect(fn).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(3000);
        expect(fn).toHaveBeenCalledTimes(3);
        await vi.advanceTimersByTimeAsync(3000);
        expect(fn).toHaveBeenCalledTimes(4); // 稳定在 3000
    });

    it('done:true cancels the task', async () => {
        const fn = vi.fn(async () => ({ done: true }));
        scheduler.schedule('k4', fn);
        await vi.advanceTimersByTimeAsync(0);
        expect(fn).toHaveBeenCalledTimes(1);
        expect(scheduler.isActive('k4')).toBe(false);
        await vi.advanceTimersByTimeAsync(60000);
        expect(fn).toHaveBeenCalledTimes(1);
    });

    it('pollAfterMs overrides local interval', async () => {
        const fn = vi.fn(async () => ({ done: false, signature: 'x', pollAfterMs: 7000 }));
        scheduler.schedule('k5', fn);
        await vi.advanceTimersByTimeAsync(0);
        await vi.advanceTimersByTimeAsync(6999);
        expect(fn).toHaveBeenCalledTimes(1);
        await vi.advanceTimersByTimeAsync(1);
        expect(fn).toHaveBeenCalledTimes(2);
    });

    it('errors back off exponentially and recover', async () => {
        const fn = vi.fn()
            .mockRejectedValueOnce(new Error('e1'))
            .mockRejectedValueOnce(new Error('e2'))
            .mockResolvedValue({ done: true });
        scheduler.schedule('k6', fn);

        await vi.advanceTimersByTimeAsync(0); // 第 1 次失败
        await vi.advanceTimersByTimeAsync(3999);
        expect(fn).toHaveBeenCalledTimes(1);
        await vi.advanceTimersByTimeAsync(1); // 错误重试 4000
        expect(fn).toHaveBeenCalledTimes(2); // 第 2 次失败
        await vi.advanceTimersByTimeAsync(7999);
        expect(fn).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(1); // 错误重试 8000
        expect(fn).toHaveBeenCalledTimes(3); // 成功且 done
        expect(scheduler.isActive('k6')).toBe(false);
    });

    it('consecutive errors beyond max trigger onGiveUp', async () => {
        const onGiveUp = vi.fn();
        const fn = vi.fn(async () => { throw new Error('down'); });
        scheduler.schedule('k7', fn, { onGiveUp, maxConsecutiveErrors: 3, errorInitial: 1000, errorMax: 4000 });

        // 4+8+16... 用 errorInitial 1000：1s、2s、4s（3 次失败后放弃）
        await vi.advanceTimersByTimeAsync(0);
        await vi.advanceTimersByTimeAsync(1000);
        await vi.advanceTimersByTimeAsync(2000);
        await vi.advanceTimersByTimeAsync(4000);
        expect(fn).toHaveBeenCalledTimes(3);
        expect(onGiveUp).toHaveBeenCalledTimes(1);
        expect(scheduler.isActive('k7')).toBe(false);
    });

    it('a success after errors resets the error counter', async () => {
        const fn = vi.fn()
            .mockRejectedValueOnce(new Error('e1'))
            .mockResolvedValueOnce({ done: false, signature: 'a' })
            .mockRejectedValueOnce(new Error('e2'))
            .mockResolvedValue({ done: true });
        scheduler.schedule('k8', fn, { maxConsecutiveErrors: 2, errorInitial: 1000, errorMax: 4000 });

        await vi.advanceTimersByTimeAsync(0);   // 失败 1
        await vi.advanceTimersByTimeAsync(1000); // 成功（done:false），错误计数清零
        await vi.advanceTimersByTimeAsync(2000); // 失败 1（未到 2 次，继续重试）
        await vi.advanceTimersByTimeAsync(2000); // 成功 done:true
        expect(scheduler.isActive('k8')).toBe(false);
        expect(fn).toHaveBeenCalledTimes(4);
    });

    it('cancel stops immediately and discards in-flight results', async () => {
        let resolveFn;
        const fn = vi.fn(() => new Promise(resolve => { resolveFn = resolve; }));
        scheduler.schedule('k9', fn);
        await vi.advanceTimersByTimeAsync(0);
        expect(fn).toHaveBeenCalledTimes(1);

        scheduler.cancel('k9');
        resolveFn({ done: false, signature: 'late' }); // in-flight 返回晚于 cancel
        await vi.advanceTimersByTimeAsync(60000);
        expect(fn).toHaveBeenCalledTimes(1); // 不复活
        expect(scheduler.isActive('k9')).toBe(false);
    });

    it('re-scheduling the same key starts fresh', async () => {
        const fn1 = vi.fn(async () => ({ done: false, signature: 'a' }));
        const fn2 = vi.fn(async () => ({ done: true }));
        scheduler.schedule('k10', fn1);
        scheduler.schedule('k10', fn2); // 替换
        await vi.advanceTimersByTimeAsync(0);
        expect(fn1).toHaveBeenCalledTimes(1); // 只跑了首轮就被替换
        expect(fn2).toHaveBeenCalledTimes(1);
        expect(scheduler.isActive('k10')).toBe(false);
    });

    it('no-progress deadline triggers onDeadline and stops', async () => {
        const onDeadline = vi.fn();
        const fn = vi.fn(async () => ({ done: false, signature: 'stuck' }));
        scheduler.schedule('k11', fn, { onDeadline, deadlineMs: 10000, initial: 1000, growth: 1, max: 1000 });

        await vi.advanceTimersByTimeAsync(0);      // t=0 首轮，签名变化重置计时
        await vi.advanceTimersByTimeAsync(10000);  // 10 轮后到期
        expect(onDeadline).toHaveBeenCalledTimes(1);
        expect(scheduler.isActive('k11')).toBe(false);
    });

    it('hidden page pauses polling; visible resumes with a catch-up tick', async () => {
        const fn = vi.fn(async () => ({ done: false, signature: 'a' }));
        scheduler.schedule('k12', fn, { initial: 1000, growth: 1, max: 1000 });

        await vi.advanceTimersByTimeAsync(0);
        expect(fn).toHaveBeenCalledTimes(1);

        setHidden(true);
        await vi.advanceTimersByTimeAsync(60000); // 隐藏期间不再请求
        expect(fn).toHaveBeenCalledTimes(1);

        setHidden(false);
        await vi.advanceTimersByTimeAsync(1500 + 400); // 去抖 + 最大抖动
        expect(fn.mock.calls.length).toBeGreaterThanOrEqual(2); // 恢复补轮
    });

    it('pauseWhenHidden:false keeps polling when hidden', async () => {
        const fn = vi.fn(async () => ({ done: false, signature: 'a' }));
        scheduler.schedule('k13', fn, { initial: 1000, growth: 1, max: 1000, pauseWhenHidden: false });

        await vi.advanceTimersByTimeAsync(0);
        setHidden(true);
        await vi.advanceTimersByTimeAsync(3000);
        expect(fn.mock.calls.length).toBeGreaterThanOrEqual(3); // 不受隐藏影响
    });
});
