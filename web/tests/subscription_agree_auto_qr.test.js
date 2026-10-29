/**
 * 勾选《自动续费协议》自动出微信支付二维码（85798489）。
 *
 * 契约（index_app.onSubAgreeChange）：
 * - 勾选即自动 createSubscriptionOrder；取消勾选仅清错误态
 * - 防重复：已有 subQrCode/subOrderId 或 loading 中不再下单
 * - 微信内浏览器（JSAPI 无二维码）不自动下单，仍走按钮
 * - recharge_center 侧同款守卫条件
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const appSource = fs.readFileSync(path.join(root, 'web/js/index_app.js'), 'utf8');
const rechargeSource = fs.readFileSync(path.join(root, 'web/js/recharge_center.js'), 'utf8');
const htmlSource = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');

// 切出 onSubAgreeChange 方法体（含 createSubscriptionOrder 前几行作守卫参考）
const methodStart = appSource.indexOf('onSubAgreeChange()');
const methodEnd = appSource.indexOf('async createSubscriptionOrder()');
const methodSrc = appSource.slice(methodStart, methodEnd);

function makeApp({ subAgreed = true, hasPlan = true, loading = false, hasQr = false, hasOrderId = false, wechat = false } = {}) {
    const createSubscriptionOrder = vi.fn();
    const factory = new Function('createSubscriptionOrder', '__isWechat', `
        return {
            subAgreementError: null,
            subAgreed: ${subAgreed},
            selectedSubPlan: ${hasPlan ? '{ id: 1 }' : null},
            subPaymentLoading: ${loading},
            subQrCode: ${hasQr ? "'qr-data'" : "''"},
            subOrderId: ${hasOrderId ? "'ord-1'" : "''"},
            isWechatBrowser: __isWechat,
            createSubscriptionOrder,
            ${methodSrc}
        };
    `);
    const app = factory(createSubscriptionOrder, () => wechat);
    return { app, createSubscriptionOrder };
}

describe('onSubAgreeChange 勾选自动出码', () => {
    it('勾选且条件满足 → 自动调用 createSubscriptionOrder', () => {
        const { app, createSubscriptionOrder } = makeApp();
        app.onSubAgreeChange();
        expect(app.subAgreementError).toBe(false);
        expect(createSubscriptionOrder).toHaveBeenCalledTimes(1);
    });

    it('取消勾选仅清错误态，不下单', () => {
        const { app, createSubscriptionOrder } = makeApp({ subAgreed: false });
        app.onSubAgreeChange();
        expect(createSubscriptionOrder).not.toHaveBeenCalled();
    });

    it.each([
        ['未选套餐', { hasPlan: false }],
        ['下单中', { loading: true }],
        ['已有二维码', { hasQr: true }],
        ['已有订单', { hasOrderId: true }],
        ['微信内浏览器', { wechat: true }],
    ])('%s 时不自动下单', (_name, opts) => {
        const { createSubscriptionOrder } = makeApp(opts);
        expect(createSubscriptionOrder).not.toHaveBeenCalled();
    });
});

describe('createSubscriptionOrder 防重复下单守卫（源码断言）', () => {
    const orderStart = appSource.indexOf('async createSubscriptionOrder()');
    const orderSrc = appSource.slice(orderStart, orderStart + 800);

    it('已有二维码或订单时直接 return（勾选+点击双入口不重复下单）', () => {
        expect(orderSrc).toContain("if (this.subQrCode || this.subOrderId) return;");
    });

    it('未勾选协议置 subAgreementError（按钮点击路径）', () => {
        expect(orderSrc).toContain('if (!this.subAgreed)');
        expect(orderSrc).toContain('this.subAgreementError = true');
    });

    it('支付按钮在已有二维码时隐藏（v-if=!subQrCode）', () => {
        expect(htmlSource).toMatch(/v-if="!subQrCode"/);
    });
});

describe('recharge_center 同款守卫', () => {
    const changeStart = rechargeSource.indexOf('function onRootChange');
    const changeEnd = rechargeSource.indexOf('function onRootClick');
    const changeSrc = rechargeSource.slice(changeStart, changeEnd);

    it('勾选即出码：selectedPlan + 非loading + 无已有单 + 非微信', () => {
        expect(changeSrc).toContain("data-rc-action') !== 'toggle-agree'");
        expect(changeSrc).toContain('state.subAgreed = !!input.checked');
        expect(changeSrc).toContain('createSubscriptionOrder()');
        // 守卫条件完整
        expect(changeSrc).toContain('state.selectedPlan && !state.subPaymentLoading');
        expect(changeSrc).toContain('!state.subQr && !state.subOrderId');
        expect(changeSrc).toContain('!isWechatBrowser()');
    });

    it('取消勾选早退（不清已生成的二维码）', () => {
        expect(changeSrc).toContain('if (!state.subAgreed) return;');
    });
});
