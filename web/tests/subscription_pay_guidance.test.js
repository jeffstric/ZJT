/**
 * 订阅支付引导浮条（付款码面板在弹窗首屏之下，须勾选《自动续费服务协议》才出码）。
 *
 * 契约（index.html/index_app.js 与 recharge_center.js 两套实现一致）：
 * - 已选套餐且未勾选协议 → 浮条出现（sticky 悬浮滚动容器底部，任何滚动位置可见）
 * - 浮条点击 → 平滑滚动弹窗内部滚动容器露出支付面板（优先露出底部协议行），
 *   手动算 scrollTop 而非 scrollIntoView（后者会连带滚动弹窗背后的页面）
 * - 面板已完整可见时不触发滚动；prefers-reduced-motion 时退化为 auto
 * - 勾选协议后浮条消失；未勾选期间协议行带 sub-agreement-pending 呼吸高亮
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const appSource = fs.readFileSync(path.join(root, 'web/js/index_app.js'), 'utf8');
const rechargeSource = fs.readFileSync(path.join(root, 'web/js/recharge_center.js'), 'utf8');
const htmlSource = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
const cssSource = fs.readFileSync(path.join(root, 'web/css/subscription.css'), 'utf8');

// 切出 recharge_center.scrollToSubPayPanel 函数体（位于 backToSubPlan 与 notifyPaid 之间）
const scrollStart = rechargeSource.indexOf('function scrollToSubPayPanel()');
const scrollEnd = rechargeSource.indexOf('function notifyPaid()');
const scrollFnSrc = rechargeSource.slice(scrollStart, scrollEnd);

function makeScrollEnv({ panelTop = 500, panelHeight = 300, scrollTop = 0, clientHeight = 400, reduced = false } = {}) {
    const panel = { offsetTop: panelTop, offsetHeight: panelHeight };
    const scroller = {
        scrollTop,
        clientHeight,
        scrollToCalls: [],
        scrollTo(opts) { this.scrollToCalls.push(opts); },
    };
    const overlay = {
        querySelector(sel) {
            if (sel === '.sub-payment-panel') return panel;
            if (sel === '.recharge-center-root') return scroller;
            return null;
        },
    };
    const fakeDocument = { getElementById: () => overlay };
    const fakeWindow = { matchMedia: () => ({ matches: reduced }) };
    // 提取的函数体引用模块级常量 OVERLAY_ID，注入同值
    const factory = new Function('document', 'window', 'OVERLAY_ID', scrollFnSrc + '\nreturn scrollToSubPayPanel;');
    return { scrollFn: factory(fakeDocument, fakeWindow, 'rechargeCenterOverlay'), scroller };
}

describe('recharge_center.scrollToSubPayPanel 滚动行为', () => {
    it('源码提取成功（函数存在于 backToSubPlan 与 notifyPaid 之间）', () => {
        expect(scrollStart).toBeGreaterThan(0);
        expect(scrollEnd).toBeGreaterThan(scrollStart);
    });

    it.each([
        ['面板在首屏之下 → 滚动露出面板底部（协议行）', { panelTop: 500, panelHeight: 300, scrollTop: 0, clientHeight: 400, expected: 416 }],
        ['面板比视口高 → 对齐面板底部', { panelTop: 100, panelHeight: 800, scrollTop: 0, clientHeight: 400, expected: 516 }],
        ['面板在视口上方 → 回滚到面板顶部', { panelTop: 100, panelHeight: 200, scrollTop: 350, clientHeight: 400, expected: 88 }],
    ])('%s', (_name, { panelTop, panelHeight, scrollTop, clientHeight, expected }) => {
        const { scrollFn, scroller } = makeScrollEnv({ panelTop, panelHeight, scrollTop, clientHeight });
        scrollFn();
        expect(scroller.scrollToCalls).toHaveLength(1);
        expect(scroller.scrollToCalls[0].top).toBe(expected);
        expect(scroller.scrollToCalls[0].behavior).toBe('smooth');
    });

    it('面板已完整可见 → 不触发滚动', () => {
        const { scrollFn, scroller } = makeScrollEnv({ panelTop: 50, panelHeight: 200, scrollTop: 0, clientHeight: 400 });
        scrollFn();
        expect(scroller.scrollToCalls).toHaveLength(0);
    });

    it('prefers-reduced-motion → behavior 退化为 auto', () => {
        const { scrollFn, scroller } = makeScrollEnv({ panelTop: 500, reduced: true });
        scrollFn();
        expect(scroller.scrollToCalls[0].behavior).toBe('auto');
    });

    it('浮条滚动动作已接入 onRootClick（goto-sub-pay）', () => {
        const clickStart = rechargeSource.indexOf('function onRootClick');
        const clickEnd = rechargeSource.indexOf('function switchTab');
        const clickSrc = rechargeSource.slice(clickStart, clickEnd);
        expect(clickSrc).toContain("action === 'goto-sub-pay'");
        expect(clickSrc).toContain('scrollToSubPayPanel()');
    });

    it('smooth 被内嵌 WebView 丢弃时有 auto 兜底（位置纹丝未动才补）', () => {
        expect(scrollFnSrc).toContain('scroller.scrollTop === before');
        expect(scrollFnSrc).toContain("behavior: 'auto'");
    });
});

describe('recharge_center 浮条渲染与协议行高亮', () => {
    it('renderSubPayHint：已选套餐且未勾选协议才渲染浮条', () => {
        const hintStart = rechargeSource.indexOf('function renderSubPayHint()');
        const hintEnd = rechargeSource.indexOf('function renderPower(');
        const hintSrc = rechargeSource.slice(hintStart, hintEnd);
        expect(hintSrc).toContain("if (!state.selectedPlan || state.subAgreed) return ''");
        expect(hintSrc).toContain('data-rc-action="goto-sub-pay"');
        expect(hintSrc).toContain('付款码在下方');
    });

    it('renderSubscription 末尾挂载浮条', () => {
        const subStart = rechargeSource.indexOf('function renderSubscription()');
        const subEnd = rechargeSource.indexOf('function renderSubPayHint()');
        const subSrc = rechargeSource.slice(subStart, subEnd);
        expect(subSrc).toContain('renderSubPayHint()');
    });

    it('未勾选协议时协议行带 sub-agreement-pending（勾选后移除）', () => {
        expect(rechargeSource).toContain("(!state.subAgreed ? ' sub-agreement-pending' : '')");
    });
});

describe('index.html / index_app.js（Vue 版）同款行为', () => {
    it('浮条：订阅 Tab 级渲染，条件为已选套餐且未勾选，点击滚动到面板', () => {
        expect(htmlSource).toContain('class="sub-pay-hint"');
        expect(htmlSource).toContain('v-if="selectedSubPlan && !subAgreed"');
        expect((htmlSource.match(/sub-pay-hint/g) || []).length).toBe(2); // class="sub-pay-hint" + class="sub-pay-hint-arrow"，仅 Tab 级一个浮条
        expect(htmlSource).toContain('@click="scrollToSubPayPanel"');
    });

    it('滚动容器带 id（scrollToSubPayPanel 的定位锚点）', () => {
        expect(htmlSource).toContain('id="rechargeModal"');
    });

    it('两处协议行（新订 + 升级）都绑定 sub-agreement-pending', () => {
        expect((htmlSource.match(/sub-agreement-pending/g) || []).length).toBe(2);
        expect(htmlSource).toContain("'sub-agreement-pending': !subAgreed");
    });

    it('index_app.scrollToSubPayPanel：定位 #rechargeModal，手动算 scrollTop + reduced-motion 退化', () => {
        expect(appSource).toContain('scrollToSubPayPanel()');
        expect(appSource).toContain("document.getElementById('rechargeModal')");
        expect(appSource).toContain("scroller.querySelector('.sub-payment-panel')");
        expect(appSource).toContain('scroller.scrollTo({ top: target');
        expect(appSource).toContain("behavior: reduced ? 'auto' : 'smooth'");
    });
});

describe('subscription.css 浮条与呼吸高亮样式', () => {
    it('浮条 sticky 悬浮于滚动容器底部', () => {
        const hintBlock = cssSource.slice(cssSource.indexOf('.sub-pay-hint {'), cssSource.indexOf('.sub-pay-hint:hover'));
        expect(hintBlock).toContain('position: sticky');
        expect(hintBlock).toContain('bottom: 12px');
    });

    it('箭头 bounce 与协议行 pulse 动画齐备', () => {
        expect(cssSource).toContain('@keyframes sub-pay-hint-bounce');
        expect(cssSource).toContain('@keyframes sub-agree-pulse');
    });

    it('prefers-reduced-motion 时禁用两处动画', () => {
        const reducedBlock = cssSource.slice(cssSource.indexOf('@media (prefers-reduced-motion: reduce)'), cssSource.indexOf('@media (prefers-reduced-motion: reduce)') + 400);
        expect(reducedBlock).toContain('.sub-pay-hint-arrow');
        expect(reducedBlock).toContain('.sub-agreement.sub-agreement-pending');
        expect(reducedBlock.match(/animation: none/g) || []).toHaveLength(2);
    });
});
