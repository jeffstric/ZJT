/**
 * admin 每日算力统计前端逻辑（47192efe7 / 27c5598e4 / 8f00f3d1d）。
 *
 * 契约：
 * - getDailyPowerUserSummary：跨日按用户聚合 total_power/active_days，
 *   display_name（管理员备注）优先于 nickname，按总消耗降序
 * - getDailyPowerSummary：空数据 avgPerDay=0（首次进入无数据不 NaN）
 * - handleDailyPowerDateChange：start>end 自动把 endDate 回退为 startDate
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/admin.js'), 'utf8');

const methodsStart = source.indexOf('setDailyPowerDateRangeFromDays(days) {');
const methodsEnd = source.indexOf('renderDailyPowerChart() {');
const methodsSrc = source.slice(methodsStart, methodsEnd);

function makeAdmin() {
    const loadDailyPowerStats = vi.fn();
    const factory = new Function('loadDailyPowerStats', `
        return {
            dashboard: { dailyPowerStats: { startDate: '', endDate: '', days: 7, expandedUsers: {} } },
            loadDailyPowerStats,
            ${methodsSrc}
        };
    `);
    return factory(loadDailyPowerStats);
}

describe('getDailyPowerUserSummary 跨日聚合', () => {
    it('多日多用户聚合 total_power/active_days 并按总消耗降序', () => {
        const admin = makeAdmin();
        admin.dashboard.dailyPowerStats.daily = [
            { date: '2026-10-20', users: [
                { user_id: 7, display_name: 'VIP客户', nickname: 'nickA', power: 50, count: 2 },
                { user_id: 8, display_name: 'nickB', power: 30, count: 1 },
            ]},
            { date: '2026-10-21', users: [
                { user_id: 7, display_name: 'VIP客户', power: 80, count: 3 },
            ]},
        ];
        const summary = admin.getDailyPowerUserSummary();
        expect(summary).toHaveLength(2);
        expect(summary[0].user_id).toBe(7); // 130 > 30 降序
        expect(summary[0].total_power).toBe(130);
        expect(summary[0].record_count).toBe(5);
        expect(summary[0].active_days).toBe(2);
        expect(summary[0].daily['2026-10-20']).toBe(50);
        expect(summary[0].daily['2026-10-21']).toBe(80);
    });

    it('display_name（管理员备注）优先于 nickname', () => {
        const admin = makeAdmin();
        admin.dashboard.dailyPowerStats.daily = [
            { date: '2026-10-20', users: [
                { user_id: 7, display_name: '重要客户张三', nickname: 'zs_01', power: 10, count: 1 },
            ]},
        ];
        expect(admin.getDailyPowerUserSummary()[0].nickname).toBe('重要客户张三');
    });

    it('display_name 缺失时回退 nickname', () => {
        const admin = makeAdmin();
        admin.dashboard.dailyPowerStats.daily = [
            { date: '2026-10-20', users: [
                { user_id: 9, display_name: '', nickname: '用户9', power: 5, count: 1 },
            ]},
        ];
        expect(admin.getDailyPowerUserSummary()[0].nickname).toBe('用户9');
    });

    it('无数据返回空数组', () => {
        const admin = makeAdmin();
        expect(admin.getDailyPowerUserSummary()).toEqual([]);
    });
});

describe('getDailyPowerSummary 汇总', () => {
    it('空数据时 avgPerDay=0 而非 NaN（8f00f3d1d 首次无数据）', () => {
        const admin = makeAdmin();
        const summary = admin.getDailyPowerSummary();
        expect(summary).toEqual({ totalPower: 0, totalUsers: 0, avgPerDay: 0 });
    });

    it('有数据时按天数取平均', () => {
        const admin = makeAdmin();
        admin.dashboard.dailyPowerStats.daily = [
            { date: '2026-10-20', total_power: 100, users: [] },
            { date: '2026-10-21', total_power: 50, users: [] },
        ];
        const summary = admin.getDailyPowerSummary();
        expect(summary.totalPower).toBe(150);
        expect(summary.avgPerDay).toBe(75);
    });
});

describe('handleDailyPowerDateChange 日期区间', () => {
    it('start>end 时把 endDate 回退为 startDate（8f00f3d1d 伴随修复）', () => {
        const admin = makeAdmin();
        admin.dashboard.dailyPowerStats.startDate = '2026-10-10';
        admin.dashboard.dailyPowerStats.endDate = '2026-10-01';
        admin.handleDailyPowerDateChange();
        expect(admin.dashboard.dailyPowerStats.endDate).toBe('2026-10-10');
        expect(admin.loadDailyPowerStats).toHaveBeenCalled();
    });

    it('正常区间按天数刷新 days（含首尾，上限 30）', () => {
        const admin = makeAdmin();
        admin.dashboard.dailyPowerStats.startDate = '2026-10-01';
        admin.dashboard.dailyPowerStats.endDate = '2026-10-05';
        admin.handleDailyPowerDateChange();
        expect(admin.dashboard.dailyPowerStats.days).toBe(5);
    });

    it('跨月区间 days 封顶 30', () => {
        const admin = makeAdmin();
        admin.dashboard.dailyPowerStats.startDate = '2026-01-01';
        admin.dashboard.dailyPowerStats.endDate = '2026-12-31';
        admin.handleDailyPowerDateChange();
        expect(admin.dashboard.dailyPowerStats.days).toBe(30);
    });
});

describe('每日统计后端契约接线（源码断言）', () => {
    it('前端请求 /api/admin/dashboard/daily-power-stats', () => {
        expect(source).toContain('/dashboard/daily-power-stats');
    });

    it('请求携带 days/start_date/end_date 参数', () => {
        expect(source).toContain('start_date');
        expect(source).toContain('end_date');
    });
});
