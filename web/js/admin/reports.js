/**
 * 管理后台「报表中心」页面（mixin，挂载到 admin 根应用）。
 *
 * 月度分组算力消耗报表：按月汇总各分组 behavior='deduct' 的算力总和，
 * 支持下钻查看组内每个用户的当月消耗，汇总/明细均可导出 CSV（纯前端
 * 生成，带 BOM 便于 Excel 识别 UTF-8）。图表复用已引入的 ECharts，
 * 颜色与基础配置复用 admin 根应用的 getModelColor/getModelChartBaseOption。
 */
(function () {
    'use strict';

    const API_ROOT = '/api/admin';
    // "未分组"虚拟桶的分组 id（与后端 REPORT_UNGROUPED_GROUP_ID 一致）
    const UNGROUPED_GROUP_ID = 0;

    function unwrapData(response) {
        const body = response && response.data;
        if (body && Object.prototype.hasOwnProperty.call(body, 'code') && body.code !== 0) {
            throw new Error(body.detail || body.error || 'Operation failed');
        }
        return body && Object.prototype.hasOwnProperty.call(body, 'data') ? body.data : body;
    }

    function apiError(error) {
        return error?.response?.data?.detail
            || error?.response?.data?.error
            || error?.message
            || String(error);
    }

    function currentMonthStr() {
        const now = new Date();
        return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    }

    function monthsAgoStr(months) {
        // 先设回 1 号防止月末溢出（如 3-31 减一月跳到 3-03），再回退 N 个月
        const d = new Date();
        d.setDate(1);
        d.setMonth(d.getMonth() - months);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    }

    // CSV 单元格转义：含逗号/引号/换行时加引号，内部引号翻倍
    function csvEscape(value) {
        const text = value == null ? '' : String(value);
        if (/[",\r\n]/.test(text)) {
            return `"${text.replace(/"/g, '""')}"`;
        }
        return text;
    }

    function downloadCsv(filename, lines) {
        // \ufeff BOM 便于 Excel 按 UTF-8 打开
        const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    window.ReportsAdminMixin = {
        data() {
            return {
                reports: {
                    startMonth: monthsAgoStr(5),
                    endMonth: currentMonthStr(),
                    months: [],
                    loading: false,
                    loaded: false,
                    error: '',
                    chart: null,
                },
                reportDetail: {
                    show: false,
                    month: '',
                    groupId: null,
                    groupName: '',
                    totalPower: 0,
                    users: [],
                    loading: false,
                },
            };
        },

        mounted() {
            this._reportsResizeHandler = () => this.resizeMonthlyGroupChart();
            window.addEventListener('resize', this._reportsResizeHandler);
        },

        beforeUnmount() {
            window.removeEventListener('resize', this._reportsResizeHandler);
            const chart = this.reports?.chart;
            if (chart) {
                chart.dispose();
                this.reports.chart = null;
            }
        },

        methods: {
            // ---------- 月份选择器 ----------
            // 当前页面语言 → flatpickr l10n；原生 <input type="month"> 的界面
            // 语言跟随浏览器而非页面，这里改用 flatpickr monthSelect 插件
            // （语言取 ZJTi18n 当前 locale），插件缺失时回退原生控件。
            getReportsFlatpickrLocale() {
                try {
                    const locale = window.ZJTi18n && window.ZJTi18n.getLocale ? window.ZJTi18n.getLocale() : 'zh-CN';
                    return String(locale).toLowerCase().startsWith('zh') ? 'zh' : 'default';
                } catch (e) {
                    return 'default';
                }
            },

            initMonthPickers() {
                if (!window.flatpickr) return;
                const locale = this.getReportsFlatpickrLocale();
                const makePicker = (refName, stateKey) => {
                    const el = this.$refs[refName];
                    if (!el) return;
                    // 重入先销毁旧实例（语言切换/重进页面时重建）
                    if (el._fpInstance) {
                        el._fpInstance.destroy();
                        el._fpInstance = null;
                    }
                    if (window.monthSelectPlugin) {
                        el.type = 'text';
                        el._fpInstance = window.flatpickr(el, {
                            locale,
                            allowInput: false,
                            plugins: [new window.monthSelectPlugin({ shorthand: true, dateFormat: 'Y-m' })],
                            defaultDate: this.reports[stateKey] || null,
                            onChange: (dates, dateStr) => {
                                if (!/^\d{4}-\d{2}$/.test(dateStr || '')) return;
                                this.reports[stateKey] = dateStr;
                                this.loadMonthlyGroupReport();
                            },
                        });
                    } else {
                        // 回退：原生月份输入（界面语言跟随浏览器）
                        el.type = 'month';
                        el.value = this.reports[stateKey] || '';
                        if (!el._fpNativeBound) {
                            el._fpNativeBound = true;
                            el.addEventListener('change', () => {
                                const value = el.value || '';
                                if (!/^\d{4}-\d{2}$/.test(value)) return;
                                this.reports[stateKey] = value;
                                this.loadMonthlyGroupReport();
                            });
                        }
                    }
                };
                makePicker('reportStartMonth', 'startMonth');
                makePicker('reportEndMonth', 'endMonth');
            },

            // ---------- 汇总报表 ----------
            async loadMonthlyGroupReport() {
                const state = this.reports;
                if (state.loading) return;
                state.loading = true;
                state.error = '';
                try {
                    const params = {};
                    if (state.startMonth) params.start_month = state.startMonth;
                    if (state.endMonth) params.end_month = state.endMonth;
                    const data = unwrapData(await axios.get(`${API_ROOT}/reports/monthly-group-power`, {
                        params,
                        headers: { 'Authorization': `Bearer ${this.authToken}` }
                    }));
                    state.months = Array.isArray(data.months) ? data.months : [];
                    state.loaded = true;
                    this.$nextTick(() => {
                        this.renderMonthlyGroupChart();
                        this.initMonthPickers();
                    });
                } catch (error) {
                    state.error = apiError(error);
                } finally {
                    state.loading = false;
                }
            },

            // 区间内出现过的所有分组列（按总消耗降序），供图表 series 与 CSV 列头
            getReportGroupColumns() {
                const totals = new Map();
                (this.reports.months || []).forEach(m => {
                    (m.groups || []).forEach(g => {
                        const prev = totals.get(g.group_id) || { group: g, total: 0 };
                        prev.total += (g.total_power || 0);
                        totals.set(g.group_id, prev);
                    });
                });
                return Array.from(totals.values())
                    .sort((a, b) => b.total - a.total)
                    .map(entry => entry.group);
            },

            getMonthlyReportSummary() {
                const months = this.reports.months || [];
                return {
                    totalPower: months.reduce((sum, m) => sum + (m.total_power || 0), 0),
                    monthCount: months.length,
                };
            },

            // 某月中某个分组的数值（CSV/图表取数）
            getReportGroupValue(monthData, groupId, field) {
                const item = (monthData.groups || []).find(g => g.group_id === groupId);
                return item ? (item[field] || 0) : 0;
            },

            // ---------- 堆叠柱状图 ----------
            ensureMonthlyGroupChart() {
                if (!window.echarts) return null;
                const el = this.$refs.groupPowerChart;
                if (!el) return null;
                const cached = this.reports.chart;
                if (cached && cached.getDom() !== el) {
                    cached.dispose();
                    this.reports.chart = null;
                }
                if (!this.reports.chart) {
                    const chart = window.echarts.init(el);
                    this.reports.chart = Vue.markRaw ? Vue.markRaw(chart) : chart;
                    // 点击柱体下钻到该月该分组（按 seriesId=分组id 匹配，
                    // 避免与用户自建的"未分组"等同名分组混淆）
                    chart.on('click', params => {
                        if (params.componentType === 'series') {
                            const monthData = (this.reports.months || []).find(m => m.month === params.name);
                            const group = (monthData?.groups || []).find(g => String(g.group_id) === params.seriesId);
                            if (monthData && group) {
                                this.openReportDetail(monthData.month, group);
                            }
                        }
                    });
                }
                return this.reports.chart;
            },

            renderMonthlyGroupChart() {
                const chart = this.ensureMonthlyGroupChart();
                if (!chart) return;
                const months = this.reports.months || [];
                const groups = this.getReportGroupColumns();

                const series = groups.map((group, index) => {
                    const isUngrouped = group.group_id === UNGROUPED_GROUP_ID;
                    return {
                        // seriesId 用分组 id：点击下钻时精确匹配，不受同名分组影响
                        id: String(group.group_id),
                        name: group.group_name,
                        type: 'bar',
                        stack: 'power',
                        barMaxWidth: 42,
                        itemStyle: {
                            // 未分组桶固定灰色，其余按索引取色
                            color: isUngrouped ? '#cbd5e1' : this.getModelColor(index),
                            borderRadius: [3, 3, 0, 0],
                        },
                        data: months.map(m => this.getReportGroupValue(m, group.group_id, 'total_power')),
                    };
                });

                chart.setOption({
                    ...this.getModelChartBaseOption(),
                    tooltip: {
                        trigger: 'axis',
                        axisPointer: { type: 'shadow' },
                        backgroundColor: 'rgba(15, 23, 42, 0.92)',
                        borderWidth: 0,
                        textStyle: { color: '#fff' }
                    },
                    xAxis: {
                        type: 'category',
                        data: months.map(m => m.month),
                        axisLine: { lineStyle: { color: '#cbd5e1' } },
                        axisLabel: { color: '#64748b' }
                    },
                    yAxis: {
                        type: 'value',
                        name: this.t('report_power_unit'),
                        splitLine: { lineStyle: { color: '#e2e8f0' } }
                    },
                    series
                }, true);
            },

            resizeMonthlyGroupChart() {
                const chart = this.reports?.chart;
                if (chart) chart.resize();
            },

            // ---------- 下钻明细 ----------
            async openReportDetail(month, group) {
                const state = this.reportDetail;
                if (state.loading) return; // 防连点重复请求
                state.show = true;
                state.month = month;
                state.groupId = group.group_id;
                state.groupName = group.group_name || '';
                state.users = [];
                state.totalPower = 0;
                state.loading = true;
                try {
                    const data = unwrapData(await axios.get(`${API_ROOT}/reports/monthly-group-power/detail`, {
                        params: { month, group_id: group.group_id },
                        headers: { 'Authorization': `Bearer ${this.authToken}` }
                    }));
                    state.users = Array.isArray(data.users) ? data.users : [];
                    state.totalPower = data.total_power || 0;
                    if (data.group_name) state.groupName = data.group_name;
                } catch (error) {
                    alert(apiError(error));
                } finally {
                    state.loading = false;
                }
            },

            closeReportDetail() {
                this.reportDetail.show = false;
                this.reportDetail.users = [];
            },

            // ---------- CSV 导出 ----------
            exportMonthlyGroupReportCsv() {
                const months = this.reports.months || [];
                if (!months.length) return;
                const groups = this.getReportGroupColumns();
                const header = [
                    this.t('report_col_month'),
                    ...groups.map(g => g.group_name),
                    this.t('report_col_total'),
                ];
                const lines = [header.map(csvEscape).join(',')];
                months.forEach(m => {
                    const row = [
                        m.month,
                        ...groups.map(g => this.getReportGroupValue(m, g.group_id, 'total_power')),
                        m.total_power || 0,
                    ];
                    lines.push(row.map(csvEscape).join(','));
                });
                downloadCsv(
                    `monthly_group_power_${this.reports.startMonth}_${this.reports.endMonth}.csv`,
                    lines
                );
            },

            exportReportDetailCsv() {
                const state = this.reportDetail;
                if (!state.users.length) return;
                const header = [
                    this.t('report_col_user_id'),
                    this.t('report_col_display_name'),
                    this.t('report_col_power'),
                    this.t('report_col_record_count'),
                ];
                const lines = [header.map(csvEscape).join(',')];
                state.users.forEach(u => {
                    const row = [u.user_id, u.display_name, u.power, u.record_count];
                    lines.push(row.map(csvEscape).join(','));
                });
                const groupKey = state.groupId === UNGROUPED_GROUP_ID ? 'ungrouped' : `group_${state.groupId}`;
                downloadCsv(
                    `monthly_group_power_${state.month}_${groupKey}.csv`,
                    lines
                );
            },
        },
    };
})();
