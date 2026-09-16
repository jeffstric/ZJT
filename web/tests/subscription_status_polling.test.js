// 月度订阅「支付完成后自动生效」轻量轮询回归测试
//
// 背景：订阅支付/签约确认由微信回调驱动，前端原本无任何轮询——Native 扫码支付
// 完成后用户必须手动点「刷新状态」才能看到「生效中」。现要求在支付二维码展示 /
// 签约进行中期间，每 5 秒查一次 /api/subscription/status，状态翻转即停并提示。

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('subscription status auto-polling', () => {
    it('polling methods exist with 5s interval and single-flight guard', () => {
        const source = readSource('web/js/index_app.js');
        expect(source).toContain('startSubStatusPolling()');
        expect(source).toContain('stopSubStatusPolling()');
        expect(source).toContain('async pollSubStatusOnce()');
        // 5 秒轮询间隔
        expect(source).toMatch(/setInterval\(\(\) => \{ this\.pollSubStatusOnce\(\); \}, 5000\)/);
        // 单实例防重入（上一次请求未返回时跳过本次 tick）
        expect(source).toContain('if (this._subStatusPollingInFlight) return;');
        // 轮询状态标志（data 声明）
        expect(source).toContain('subStatusPolling: false');
    });

    it('starts polling on order creation and when a sign is already in flight', () => {
        const source = readSource('web/js/index_app.js');
        // 创建订阅/升级订单成功后启动轮询（JSAPI 与 Native 共用分支）
        expect(source).toMatch(/lastOrderIsUpgrade = !!response\.data\.upgrade;[\s\S]*?this\.startSubStatusPolling\(\);/);
        // Native 下单失败拿不到二维码时停止，避免空转
        expect(source).toMatch(/if \(!codeUrl\) \{\s*this\.stopSubStatusPolling\(\);/);
        // 重新打开充值中心时若已有签约进行中，自动恢复轮询
        expect(source).toMatch(/const st = this\.subscriptionStatus && this\.subscriptionStatus\.status;[\s\S]*?this\.startSubStatusPolling\(\);/);
    });

    it('stops polling on terminal transitions, cancel, JSAPI cancel/fail and modal close', () => {
        const source = readSource('web/js/index_app.js');
        // 生效中落定 / 签约失败回落两条终态路径都停止轮询
        expect(source.match(/this\.stopSubStatusPolling\(\);/g)?.length).toBeGreaterThanOrEqual(6);
        // JSAPI 取消/失败回调停止轮询
        expect(source).toMatch(/get_brand_wcpay_request:cancel'\) \{\s*this\.stopSubStatusPolling\(\);/);
        // 关闭充值中心停止轮询
        expect(source).toMatch(/closeRechargeModal\(\) \{\s*this\.showRechargePowerModal = false;\s*this\.stopSubStatusPolling\(\);/);
        // 取消订阅停止轮询
        expect(source).toMatch(/alert\('订阅已取消'\);\s*this\.stopSubStatusPolling\(\);/);
    });

    it('alerts success only on real status flip to active', () => {
        const source = readSource('web/js/index_app.js');
        // 从 signing/upgrading 翻转到 active 才提示订阅/升级成功
        expect(source).toMatch(/status === 'active' && \(\(prev && prev !== 'active'\) \|\| this\._subStatusSawPending\)/);
        expect(source).toContain("'升级成功！已切换为新套餐，整期算力稍后到账'");
        expect(source).toContain("'订阅成功！套餐已生效，算力稍后到账'");
        // 签约失败/超时回落给出可行动的提示文案
        expect(source).toContain('签约未完成（可能超时或已取消），如需订阅请重新发起');
    });
});
