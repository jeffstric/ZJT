import { describe, expect, test, beforeEach, afterEach, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

function loadCenter() {
    const source = fs.readFileSync(path.resolve('web/js/recharge_center.js'), 'utf8');
    const factory = new Function('window', `${source}\n;return window.RechargeCenter;`);
    return factory(window);
}

const INTRO_PLAN = {
    plan_id: 101,
    name: '入门版',
    price: 29.9,
    first_period_price: 18.8,
    computing_power: 328,
    first_period_bonus: 40,
};
const STANDARD_PLAN = {
    plan_id: 102,
    name: '标准版',
    price: 99,
    computing_power: 984,
    first_period_bonus: 400,
};
const PACKAGES = [
    { package_id: 1, description: '9.9元算力包', price: 9.9, computing_power: 100, granted_computing_power: 88 },
];

function jsonResponse(body, status) {
    return {
        ok: status ? status < 400 : true,
        status: status || 200,
        json: async () => body,
    };
}

describe('recharge center pricing', () => {
    const { pricing } = loadCenter();
    const eligible = { subscribed: false, status: 'none', first_bonus_eligible: true };

    test('入门版首期相对 9.9 元包多约 201 算力', () => {
        expect(pricing.showsIntroPrice(INTRO_PLAN, eligible)).toBe(true);
        expect(pricing.introPriceCut(INTRO_PLAN)).toBeCloseTo(11.1, 5);
        expect(pricing.headlinePower(INTRO_PLAN, true)).toBe(368);
        expect(pricing.planExtraVsRecharge(INTRO_PLAN, PACKAGES, eligible, true)).toBe(201);
        expect(pricing.planMultipleText([INTRO_PLAN, STANDARD_PLAN], INTRO_PLAN)).toBe('');
        expect(pricing.planMultipleText([INTRO_PLAN, STANDARD_PLAN], STANDARD_PLAN)).toBe('≈ 基础档 3 倍算力');
    });

    test('已订阅时只列出更高档作为升级', () => {
        const status = {
            subscribed: true,
            status: 'active',
            plan: { plan_id: 101, name: '入门版', price: 29.9, computing_power: 328 },
            first_bonus_eligible: false,
        };
        expect(pricing.upgradePlans([INTRO_PLAN, STANDARD_PLAN], status).map((p) => p.plan_id)).toEqual([102]);
        expect(pricing.showsIntroPrice(INTRO_PLAN, status)).toBe(false);
        expect(pricing.planExtraVsRecharge(INTRO_PLAN, PACKAGES, status, false)).toBe(62);
    });
});

describe('recharge center modal', () => {
    let center;
    let alerts;

    beforeEach(() => {
        document.body.innerHTML = '';
        localStorage.setItem('auth_token', 'tok');
        localStorage.setItem('user_id', '7');
        alerts = [];
        window.alert = (msg) => { alerts.push(msg); };
        window.matchMedia = () => ({ matches: true });
        center = loadCenter();
    });

    afterEach(() => {
        center.close();
        vi.restoreAllMocks();
    });

    function mockFetch(subscription) {
        window.fetch = vi.fn(async (url) => {
            const u = String(url);
            if (u.includes('/api/system/server-config')) {
                return jsonResponse({ code: 0, data: { is_local: false } });
            }
            if (u.includes('/api/recharge/packages')) {
                expect(u).not.toContain('auth_token');
                return jsonResponse({ success: true, packages: PACKAGES });
            }
            if (u.includes('/api/subscription/plans')) {
                expect(u).toContain('auth_token=tok');
                return jsonResponse({
                    success: true,
                    plans: [INTRO_PLAN, STANDARD_PLAN],
                    subscription: subscription,
                });
            }
            return jsonResponse({ detail: 'not found' }, 404);
        });
    }

    test('打开后默认月度订阅，并展示首期价与直付页签', async () => {
        mockFetch({ subscribed: false, status: 'none', first_bonus_eligible: true });
        await center.open();
        const root = document.getElementById('rechargeCenterOverlay');
        expect(root.hidden).toBe(false);
        expect(root.textContent).toContain('月度订阅');
        expect(root.textContent).toContain('算力充值');
        expect(root.textContent).toContain('入门版');
        expect(root.textContent).toContain('18.8');
        expect(root.textContent).toContain('368');
        expect(root.textContent).toContain('多约 201');
        const subTab = root.querySelector('[data-tab="subscription"]');
        expect(subTab.classList.contains('active')).toBe(true);

        root.querySelector('[data-tab="power"]').click();
        expect(root.textContent).toContain('9.9元算力包');
        expect(root.textContent).toContain('88');
    });

    test('生效中的订阅展示管理与升级，而不是新用户套餐动画', async () => {
        mockFetch({
            subscribed: true,
            status: 'active',
            first_bonus_eligible: false,
            plan: { plan_id: 101, name: '入门版', price: 29.9, computing_power: 328 },
            current_period_end: '2026-10-23T00:00:00',
            next_deduct_date: '2026-10-23',
        });
        await center.open();
        const root = document.getElementById('rechargeCenterOverlay');
        expect(root.textContent).toContain('生效中');
        expect(root.textContent).toContain('取消订阅');
        expect(root.textContent).toContain('升级到更高套餐');
        expect(root.textContent).toContain('标准版');
        expect(root.textContent).not.toContain('首月优惠');
    });

    test('本地环境不打开充值中心', async () => {
        window.fetch = vi.fn(async () => jsonResponse({ data: { is_local: true } }));
        const blocked = [];
        await center.open({ onLocalBlocked: (msg) => blocked.push(msg) });
        expect(blocked[0]).toContain('本地模式');
        const root = document.getElementById('rechargeCenterOverlay');
        expect(!root || root.hidden).toBe(true);
        expect(alerts).toEqual([]);
    });
});
