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

    // ---- 回归：恢复可见后 in-flight 返回与补轮并发不得分裂出第二条轮询链 ----
    it('in-flight response returning after resume converges to a single chain', async () => {
        let resolveFirst;
        const fn = vi.fn()
            .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
            .mockImplementation(async () => ({ done: false, signature: 'a' }));
        scheduler.schedule('k14', fn, { initial: 1000, growth: 1, max: 1000 });
        await vi.advanceTimersByTimeAsync(0); // t=0：首轮 in-flight（挂起不返回）

        setHidden(true);   // 隐藏挂起
        setHidden(false);  // 立即恢复：paused 已回 false，排 1.5s 补轮
        await vi.advanceTimersByTimeAsync(600);
        resolveFirst({ done: false, signature: 'a' }); // t=0.6：in-flight 晚到返回，排 timer_A
        await vi.advanceTimersByTimeAsync(900);        // t=1.5：补轮触发 → fn2 立即返回 → 应撤 timer_A 收敛单链

        const before = fn.mock.calls.length;
        await vi.advanceTimersByTimeAsync(5000); // 单链 1s 间隔 ≈5 次；双链 ≈10 次
        const delta = fn.mock.calls.length - before;
        expect(delta).toBeLessThanOrEqual(6);
    });

    // ---- 回归：页面在隐藏状态下 schedule 的新任务必须挂起，等恢复补轮接管 ----
    it('scheduling while already hidden starts paused until visibility returns', async () => {
        const fn = vi.fn(async () => ({ done: false, signature: 'a' }));
        setHidden(true); // 后台标签页恢复会话：初始即 hidden，不会再发 visibilitychange
        scheduler.schedule('k15', fn, { initial: 1000, growth: 1, max: 1000 });

        await vi.advanceTimersByTimeAsync(5000);
        expect(fn).not.toHaveBeenCalled(); // 挂机标签页 0 请求

        setHidden(false);
        await vi.advanceTimersByTimeAsync(1500 + 400); // 去抖 + 最大 jitter
        expect(fn.mock.calls.length).toBeGreaterThanOrEqual(1); // 恢复补轮接管
    });

    // ---- 回归：pauseWhenHidden:false 的任务隐藏期间从未停轮，恢复补轮不得叠加 tick ----
    it('resume catch-up skips tasks that never suspended', async () => {
        const fn = vi.fn(async () => ({ done: false, signature: 'a' }));
        scheduler.schedule('k16', fn, { initial: 1000, growth: 1, max: 1000, pauseWhenHidden: false });

        await vi.advanceTimersByTimeAsync(0);   // t=0
        await vi.advanceTimersByTimeAsync(1000); // t=1（处理完排 t=2）
        setHidden(true);
        setHidden(false);
        await vi.advanceTimersByTimeAsync(1900); // 到 t≈2.9：单链只有 t=2 一次
        // t=0/1/2 共 3 次；若补轮错误地 tick 了从未暂停的任务会是 4 次
        expect(fn.mock.calls.length).toBeLessThanOrEqual(3);
    });

    // ---- 回归：全局去抖已结束、jitter 尚未执行时二次切页，旧补轮必须撤销 ----
    it('second hide cancels a pending jitter catch-up before the next resume', async () => {
        const random = vi.spyOn(Math, 'random').mockReturnValue(0.5); // jitter 固定 200ms
        const fn = vi.fn(async () => ({ done: false, signature: 'a' }));
        scheduler.schedule('k17', fn, { initial: 1000, growth: 1, max: 1000 });
        await vi.advanceTimersByTimeAsync(0);
        expect(fn).toHaveBeenCalledTimes(1);

        setHidden(true);
        setHidden(false);
        await vi.advanceTimersByTimeAsync(1500); // 已创建第一次恢复的 200ms jitter
        setHidden(true);                        // 必须撤掉上面的 jitter
        setHidden(false);
        await vi.advanceTimersByTimeAsync(400);
        expect(fn).toHaveBeenCalledTimes(1);    // 旧补轮不得在第二次恢复后漏执行

        await vi.advanceTimersByTimeAsync(1500 + 400);
        expect(fn).toHaveBeenCalledTimes(2);    // 只有第二次恢复的一次补轮
        random.mockRestore();
    });
});
