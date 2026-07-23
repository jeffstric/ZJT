// 故事板拆分相关纯函数行为测试（Vitest，CI 运行）。
// 覆盖测试方案 §3.1：progress 归一化、字号档位、视频槽位等纯函数。
// 参考 web/tests/storyboard_script_split_progress.test.js 的风格。
import { beforeEach, describe, expect, it } from 'vitest';

import state, {
    AGENT_CHAT_FONT_BASE_PX,
    AGENT_CHAT_FONT_STEP_MAX,
    AGENT_CHAT_FONT_STEP_MIN,
    applyGenerateProgressStatus,
    clampAgentChatFontStep,
    getAgentChatFontSizes,
    isRenderableMediaUrl,
    setAgentChatFontStep,
    toAbsoluteMediaUrl,
} from '../js/storyboard/state.js';

describe('applyGenerateProgressStatus', () => {
    beforeEach(() => {
        state.generateProgressPercent = 0;
        state.generateProgressMessage = '';
    });

    it('rounds float progress to integer', () => {
        applyGenerateProgressStatus({ progress: 46.4, message: '拆分中' });
        expect(state.generateProgressPercent).toBe(46);
        expect(state.generateProgressMessage).toBe('拆分中');
    });

    it('clamps progress over 100 to 100', () => {
        applyGenerateProgressStatus({ progress: 180, message: '' });
        expect(state.generateProgressPercent).toBe(100);
        // 空 message 走兜底文案
        expect(state.generateProgressMessage).toBe('正在处理任务');
    });

    it('clamps negative progress to 0', () => {
        applyGenerateProgressStatus({ progress: -5, message: '异常' });
        expect(state.generateProgressPercent).toBe(0);
    });

    it('ignores non-finite progress', () => {
        state.generateProgressPercent = 50;
        applyGenerateProgressStatus({ progress: NaN, message: 'x' });
        // NaN 不更新 percent，但 message 仍更新
        expect(state.generateProgressPercent).toBe(50);
    });

    it('handles missing statusData with defaults', () => {
        applyGenerateProgressStatus();
        expect(state.generateProgressPercent).toBe(0);
        expect(state.generateProgressMessage).toBe('正在处理任务');
    });
});

describe('clampAgentChatFontStep', () => {
    it('clamps within -2..8 range', () => {
        expect(clampAgentChatFontStep(-10)).toBe(AGENT_CHAT_FONT_STEP_MIN);
        expect(clampAgentChatFontStep(100)).toBe(AGENT_CHAT_FONT_STEP_MAX);
        expect(clampAgentChatFontStep(3)).toBe(3);
    });

    it('rounds to integer', () => {
        expect(clampAgentChatFontStep(3.7)).toBe(4);
        expect(clampAgentChatFontStep(3.2)).toBe(3);
    });

    it('falls back to 0 for non-finite', () => {
        expect(clampAgentChatFontStep(NaN)).toBe(0);
        expect(clampAgentChatFontStep('abc')).toBe(0);
    });
});

describe('getAgentChatFontSizes', () => {
    it('computes body and label px from step', () => {
        const sizes = getAgentChatFontSizes(2);
        expect(sizes.step).toBe(2);
        expect(sizes.bodyPx).toBe(AGENT_CHAT_FONT_BASE_PX + 2);
        // label 比 body 小 1，但不低于 10
        expect(sizes.labelPx).toBe(sizes.bodyPx - 1);
    });

    it('label px never below 10', () => {
        // step=-2 → body=10 → label=9 → 但下限 10
        const sizes = getAgentChatFontSizes(AGENT_CHAT_FONT_STEP_MIN);
        expect(sizes.bodyPx).toBe(AGENT_CHAT_FONT_BASE_PX + AGENT_CHAT_FONT_STEP_MIN);
        expect(sizes.labelPx).toBe(10);
    });

    it('clamps out-of-range step', () => {
        const sizes = getAgentChatFontSizes(999);
        expect(sizes.step).toBe(AGENT_CHAT_FONT_STEP_MAX);
    });
});

describe('setAgentChatFontStep', () => {
    beforeEach(() => {
        // 清理 localStorage 避免跨用例污染
        try { localStorage.removeItem('storyboard_agentChatFontStep'); } catch (_) { /* */ }
    });

    it('clamps and persists to localStorage', () => {
        const next = setAgentChatFontStep(99);
        expect(next).toBe(AGENT_CHAT_FONT_STEP_MAX);
        expect(state.agentChatFontStep).toBe(AGENT_CHAT_FONT_STEP_MAX);
        expect(localStorage.getItem('storyboard_agentChatFontStep')).toBe(String(AGENT_CHAT_FONT_STEP_MAX));
    });
});

describe('media url helpers', () => {
    it('isRenderableMediaUrl rejects empty and null', () => {
        expect(isRenderableMediaUrl('')).toBe(false);
        expect(isRenderableMediaUrl(null)).toBe(false);
        expect(isRenderableMediaUrl('https://x.com/a.png')).toBe(true);
    });

    it('toAbsoluteMediaUrl prefixes cdn for relative path', () => {
        // 相对路径会被补全为绝对 URL
        const abs = toAbsoluteMediaUrl('/media/foo.png');
        expect(abs).toMatch(/\/media\/foo\.png$/);
        // 已经是 http(s) 的原样返回
        expect(toAbsoluteMediaUrl('https://cdn.x.com/a.png')).toBe('https://cdn.x.com/a.png');
    });
});
