// 前端统一轮询调度器（f1096）。
// 背景：access.log 实测轮询类端点占全站流量六成，三个根因——固定 4s 间隔对分钟级
// 生成任务过量、挂机标签页不暂停、卡死任务/断网后无限重试。本模块统一提供四条策略：
//   1. 渐进退避：响应无变化时间隔按 growth 放大至 max；状态签名变化即重置回 initial；
//   2. 页面隐藏暂停：visibilitychange 隐藏时挂起全部任务，恢复可见后去抖统一补一轮；
//   3. 有界失败：连续错误按指数退避重试，超过 maxConsecutiveErrors 放弃（onGiveUp）；
//      同一签名超过 deadlineMs 无进展也放弃（onDeadline）——掐死「卡在 PROCESSING 永轮询」；
//   4. 服务端节流：fetchFn 可返回 pollAfterMs 覆盖本地间隔（script-split 已有此约定）。
// 用法：scheduler.schedule(key, fn, opts)；fn 为 async () => ({ done, signature?, pollAfterMs? })，
// done:true 表示终态（调度器自动取消并清 key）。cancel/isActive 供调用方去重与主动停止。
// 同时挂到 window.pollScheduler，供 workflow.js / pages/*.js 等经典脚本（无 module 系统）复用。

const DEFAULTS = {
    initial: 2000,                 // 起始间隔（首轮后按 growth 递增）
    growth: 1.5,                   // 响应无变化时的间隔放大倍数
    max: 15000,                    // 运行中间隔上限
    errorInitial: 4000,            // 首次错误重试间隔
    errorMax: 60000,               // 错误重试间隔上限
    maxConsecutiveErrors: 8,       // 连续失败放弃阈值（4+8+16+32+60*4 ≈ 5 分钟纯失败）
    deadlineMs: 30 * 60 * 1000,    // 同一签名无进展的最长跟随时长（软超时，任务本身不受影响）
    pauseWhenHidden: true,         // 页面隐藏时挂起
    resumeDebounce: 1500,          // 恢复可见后的补轮去抖（防快速切页抖动）
    resumeJitter: 400,             // 恢复补轮的随机错峰（避免全部任务同时打点）
    onError: null,                 // 每次失败回调（如 batch 轮询的 onRecoverableError）
    onGiveUp: null,                // 连续错误放弃回调
    onDeadline: null,              // 无进展超时回调
};

const tasks = new Map(); // key -> task
let resumeTimer = null;

function clearTimer(task) {
    if (task && task.timer) {
        clearTimeout(task.timer);
        task.timer = null;
    }
    clearResumeTimer(task);
}

function clearResumeTimer(task) {
    if (task && task.resumeTimer) {
        clearTimeout(task.resumeTimer);
        task.resumeTimer = null;
    }
}

function schedule(key, fn, userOpts = {}) {
    cancel(key);
    const opts = { ...DEFAULTS, ...userOpts };
    const task = {
        key,
        fn,
        opts,
        interval: opts.initial,
        consecutiveErrors: 0,
        signature: null,
        firstSeenAt: Date.now(), // 最近一次「签名变化」时间，deadline 计时基准
        timer: null,
        resumeTimer: null,
        paused: false,
    };
    tasks.set(key, task);
    // 后台标签页里新挂起的任务以挂起态起步：浏览器恢复会话时页面初始即 hidden
    // 且不会再发 visibilitychange，立即 tick 会让挂机标签页全速轮询。
    // 恢复可见后由 setPaused(false) 的补轮接管。
    if (opts.pauseWhenHidden && typeof document !== 'undefined' && document.hidden) {
        task.paused = true;
        return;
    }
    tick(key);
}

function tick(key) {
    const task = tasks.get(key);
    if (!task || task.paused) return;
    (async () => {
        try {
            const result = await task.fn();
            // in-flight 期间被 cancel/schedule 替换，或被隐藏暂停：丢弃本轮，不排下一轮
            if (tasks.get(key) !== task || task.paused) return;
            task.consecutiveErrors = 0; // 成功即清零：错误计数只累计「连续」失败
            if (result && result.done) {
                cancel(key);
                return;
            }
            const nextSig = result ? result.signature : undefined;
            if (nextSig !== undefined && nextSig !== null && nextSig !== task.signature) {
                // 有进展（状态/产物 URL 变化）：重置退避与 deadline 计时
                task.signature = nextSig;
                task.firstSeenAt = Date.now();
                task.interval = task.opts.initial;
            } else {
                task.interval = Math.min(Math.round(task.interval * task.opts.growth), task.opts.max);
            }
            if (task.opts.deadlineMs > 0 && Date.now() - task.firstSeenAt >= task.opts.deadlineMs) {
                cancel(key);
                if (task.opts.onDeadline) task.opts.onDeadline(key);
                return;
            }
            // 服务端 pollAfterMs 优先于本地退避间隔
            const delay = (result && result.pollAfterMs) || task.interval;
            // 排下一轮前撤掉残留的旧 timer：in-flight 请求跨过「隐藏→恢复」窗口返回时，
            // 会与恢复补轮并发各排一条链；后处理结果的一方负责收敛为单链，
            // 否则两条链互相覆盖 task.timer 句柄且永不合并，请求频率翻倍
            clearTimer(task);
            task.timer = setTimeout(() => tick(key), delay);
        } catch (err) {
            if (tasks.get(key) !== task || task.paused) return;
            task.consecutiveErrors += 1;
            if (task.opts.onError) task.opts.onError(err);
            if (task.consecutiveErrors >= task.opts.maxConsecutiveErrors) {
                cancel(key);
                if (task.opts.onGiveUp) task.opts.onGiveUp(err);
                return;
            }
            const backoff = Math.min(
                task.opts.errorInitial * 2 ** (task.consecutiveErrors - 1),
                task.opts.errorMax,
            );
            clearTimer(task);
            task.timer = setTimeout(() => tick(key), backoff);
        }
    })();
}

function cancel(key) {
    const task = tasks.get(key);
    if (!task) return;
    clearTimer(task);
    tasks.delete(key);
}

function cancelAll() {
    for (const key of Array.from(tasks.keys())) cancel(key);
    if (resumeTimer) {
        clearTimeout(resumeTimer);
        resumeTimer = null;
    }
}

function isActive(key) {
    return tasks.has(key);
}

function setPaused(paused) {
    if (paused && resumeTimer) {
        // 快速切页（可见→隐藏）时撤掉已排定的补轮：它触发时任务全部处于
        // paused 会被跳过，但清掉可避免与下一次恢复排的新补轮形成双补轮
        clearTimeout(resumeTimer);
        resumeTimer = null;
    }
    for (const task of tasks.values()) {
        if (!task.opts.pauseWhenHidden) continue;
        task.paused = paused;
        clearTimer(task); // 暂停即撤表；in-flight 轮次返回后也会因 paused 丢弃
    }
    if (!paused) {
        clearTimeout(resumeTimer);
        // 去抖后统一补一轮：隐藏期间完成的任务在回到页面 ~resumeDebounce 内看到终态
        resumeTimer = setTimeout(() => {
            resumeTimer = null;
            for (const task of tasks.values()) {
                // 只补真正因隐藏挂起过的任务；pauseWhenHidden:false 的任务
                // 隐藏期间从未停轮，补轮会给它叠加一条多余的链
                if (task.paused || !task.opts.pauseWhenHidden) continue;
                const jitter = task.opts.resumeJitter
                    ? Math.floor(Math.random() * task.opts.resumeJitter)
                    : 0;
                // 与常规 timer 分开保存：隐藏、取消、重调度均可撤销；不能用
                // task.timer 覆盖已有轮询链句柄，否则会重新引入双链。
                clearResumeTimer(task);
                task.resumeTimer = setTimeout(() => {
                    task.resumeTimer = null;
                    tick(task.key);
                }, jitter);
            }
        }, DEFAULTS.resumeDebounce);
    }
}

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('visibilitychange', () => setPaused(document.hidden));
}

const scheduler = { schedule, cancel, cancelAll, isActive };

if (typeof window !== 'undefined') {
    window.pollScheduler = scheduler; // 经典脚本（workflow.js / pages/*.js）经 window 使用
}

export default scheduler;
export { schedule, cancel, cancelAll, isActive };
