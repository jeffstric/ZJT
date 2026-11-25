/**
 * admin 月度分组报表 / 用户分组前端逻辑。
 *
 * 契约：
 * - getReportGroupColumns：跨月聚合出现过的分组列，按区间总消耗降序；
 *   未分组（group_id=0）也参与排序
 * - getReportGroupValue：某月某分组无记录时回退 0（图表/CSV 取数不 NaN）
 * - getMonthlyReportSummary：空数据返回 totalPower=0、monthCount=0
 * - userGroupNameById：未加载或不存在时返回空串；null 直接返回 ''
 * - userGroupMembersTotalPages：total=0 时至少为 1（分页按钮不越界）
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');

const reportsSource = fs.readFileSync(path.join(root, 'web/js/admin/reports.js'), 'utf8');
const reportsStart = reportsSource.indexOf('getReportGroupColumns() {');
const reportsEnd = reportsSource.indexOf('ensureMonthlyGroupChart() {');
const reportsMethodsSrc = reportsSource.slice(reportsStart, reportsEnd);

function makeReports() {
    const factory = new Function('UNGROUPED_GROUP_ID', `
        return {
            reports: { startMonth: '2026-06', endMonth: '2026-11', months: [] },
            t: (key, params) => key,
            UNGROUPED_GROUP_ID,
            ${reportsMethodsSrc}
        };
    `);
    return factory(0);
}

describe('getReportGroupColumns 跨月分组列', () => {
    it('聚合各月出现过的分组并按总消耗降序', () => {
        const reports = makeReports();
        reports.reports.months = [
            { month: '2026-10', total_power: 100, groups: [
                { group_id: 3, group_name: '设计组', total_power: 60 },
                { group_id: 0, group_name: '未分组', total_power: 40 },
            ]},
            { month: '2026-11', total_power: 90, groups: [
                { group_id: 3, group_name: '设计组', total_power: 30 },
                { group_id: 5, group_name: '运营组', total_power: 60 },
            ]},
        ];
        const columns = reports.getReportGroupColumns();
        expect(columns).toHaveLength(3);
        // 设计组 90 > 运营组 60 > 未分组 40
        expect(columns.map(c => c.group_id)).toEqual([3, 5, 0]);
    });

    it('空月份返回空数组', () => {
        const reports = makeReports();
        expect(reports.getReportGroupColumns()).toEqual([]);
    });
});

describe('getReportGroupValue 取数回退', () => {
    it('分组当月无记录时回退 0', () => {
        const reports = makeReports();
        reports.reports.months = [
            { month: '2026-11', total_power: 60, groups: [
                { group_id: 3, group_name: '设计组', total_power: 60 },
            ]},
        ];
        expect(reports.getReportGroupValue(reports.reports.months[0], 3, 'total_power')).toBe(60);
        expect(reports.getReportGroupValue(reports.reports.months[0], 5, 'total_power')).toBe(0);
    });
});

describe('getMonthlyReportSummary 空数据', () => {
    it('无数据时 totalPower/monthCount 为 0 不产生 NaN', () => {
        const reports = makeReports();
        const summary = reports.getMonthlyReportSummary();
        expect(summary.totalPower).toBe(0);
        expect(summary.monthCount).toBe(0);
    });

    it('多月汇总累计', () => {
        const reports = makeReports();
        reports.reports.months = [
            { month: '2026-10', total_power: 100, groups: [] },
            { month: '2026-11', total_power: 90, groups: [] },
        ];
        expect(reports.getMonthlyReportSummary().totalPower).toBe(190);
        expect(reports.getMonthlyReportSummary().monthCount).toBe(2);
    });
});

const groupsSource = fs.readFileSync(path.join(root, 'web/js/admin/user_groups.js'), 'utf8');
const groupsStart = groupsSource.indexOf('userGroupMembersTotalPages() {');
const groupsEnd = groupsSource.indexOf('        },\n    };', groupsStart);
const groupsMethodsSrc = groupsSource.slice(groupsStart, groupsEnd);

function makeGroups(list, modalOverrides = {}) {
    const factory = new Function(`
        return {
            userGroups: { list: ${JSON.stringify(list)} },
            userGroupMembersModal: Object.assign(
                { total: 0, pageSize: 20, page: 1, groupId: 1, members: [], loading: false },
                ${JSON.stringify(modalOverrides)}
            ),
            loadUserGroupMembers() { this.userGroupMembersModal.reloads = (this.userGroupMembersModal.reloads || 0) + 1; },
            ${groupsMethodsSrc}
        };
    `);
    return factory();
}

describe('userGroupNameById', () => {
    it('命中分组返回名称，未命中返回空串，null 直接返回空串', () => {
        const groups = makeGroups([{ id: 1, name: '设计组' }]);
        expect(groups.userGroupNameById(1)).toBe('设计组');
        expect(groups.userGroupNameById(9)).toBe('');
        expect(groups.userGroupNameById(null)).toBe('');
    });
});

describe('userGroupMembersTotalPages', () => {
    it('total=0 时至少为 1 页', () => {
        const groups = makeGroups([]);
        expect(groups.userGroupMembersTotalPages()).toBe(1);
    });
});

describe('prevGroupMembersPage / nextGroupMembersPage', () => {
    it('上一页：page>1 时减一并重新加载，page=1 时不动作', () => {
        const groups = makeGroups([], { page: 2, total: 45, pageSize: 20 });
        groups.prevGroupMembersPage();
        expect(groups.userGroupMembersModal.page).toBe(1);
        expect(groups.userGroupMembersModal.reloads).toBe(1);
        groups.prevGroupMembersPage();
        expect(groups.userGroupMembersModal.page).toBe(1);
        expect(groups.userGroupMembersModal.reloads).toBe(1); // 边界不再触发
    });

    it('下一页：page<总页数时加一并重新加载，末页时不动作', () => {
        const groups = makeGroups([], { page: 1, total: 45, pageSize: 20 }); // 3 页
        groups.nextGroupMembersPage();
        expect(groups.userGroupMembersModal.page).toBe(2);
        expect(groups.userGroupMembersModal.reloads).toBe(1);
        groups.userGroupMembersModal.page = 3;
        groups.nextGroupMembersPage();
        expect(groups.userGroupMembersModal.page).toBe(3);
        expect(groups.userGroupMembersModal.reloads).toBe(1); // 末页边界不再触发
    });
});
