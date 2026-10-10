import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
// 加载真实的 web/js/escape.js（IIFE，挂到 jsdom 的 window 上）
import '../../web/js/escape.js';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/script_writer.js'), 'utf8');

// 生产事故原始数据：agent_verifications 1bff7f50（2026-09-26 21:45:32，
// 故事写手 ask_user，用户截图按钮全部显示 [object Object]）
const INCIDENT_OPTIONS = [
    { label: '确认连续生成', description: '按要求逐集创作，每集完成后自动继续下一集（预计耗时较长）' },
    { label: '分批生成', description: '每次生成 5-10 集，完成一批后再确认是否继续' },
    { label: '减少集数', description: '减少本次生成的集数' },
];

// 从 script_writer.js 源码中提取真实的 normalizeAskOption 函数体并实例化，
// 避免测试一份拷贝而放过真实实现里的回归
function extractNormalizeAskOption() {
    const marker = 'const normalizeAskOption = function (option) {';
    const start = source.indexOf(marker);
    expect(start).toBeGreaterThan(-1);
    let depth = 0;
    let end = -1;
    for (let i = start + marker.length - 1; i < source.length; i++) {
        const ch = source[i];
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) { end = i; break; }
        }
    }
    expect(end).toBeGreaterThan(-1);
    return new Function(`return (${source.slice(start + 'const '.length, end + 1)})`)();
}
const normalizeAskOption = extractNormalizeAskOption();

describe('script_writer ask_user 选项 [object Object] 事故复现与回归', () => {
    it('复现修复前渲染路径：escapeHtml(对象) 产生 [object Object]', () => {
        // 修复前 script_writer.js 直接 escapeHtml(opt)，escape.js 内部 String(value)
        expect(window.escapeHtml(INCIDENT_OPTIONS[0])).toBe('[object Object]');
    });

    it('修复后：真实 normalizeAskOption 从事故数据中提取出可读文案', () => {
        expect(INCIDENT_OPTIONS.map(normalizeAskOption)).toEqual([
            '确认连续生成', '分批生成', '减少集数',
        ]);
        // 渲染口径与页面一致：escapeHtml(normalizeAskOption(opt))
        expect(window.escapeHtml(normalizeAskOption(INCIDENT_OPTIONS[0]))).toBe('确认连续生成');
    });

    it('字符串选项与空值边界不变', () => {
        expect(normalizeAskOption(' 科幻 ')).toBe('科幻');
        expect(normalizeAskOption('悬疑')).toBe('悬疑');
        expect(normalizeAskOption({ foo: 'bar' })).toBe('');
        expect(normalizeAskOption(null)).toBe('');
        expect(normalizeAskOption(undefined)).toBe('');
        expect(normalizeAskOption(42)).toBe('42');
    });

    it('两处渲染点与点击提交均接线 normalizeAskOption', () => {
        // 历史消息渲染点
        const historySite = source.slice(
            source.indexOf('options.forEach(opt =>'),
            source.indexOf('options.forEach(opt =>') + 300
        );
        expect(historySite).toContain('normalizeAskOption(opt)');
        expect(historySite).toContain('if (!optionText) return;');
        // 实时验证卡片渲染点
        const liveSite = source.slice(
            source.indexOf('verification.options.forEach((option, index) =>'),
            source.indexOf('verification.options.forEach((option, index) =>') + 400
        );
        expect(liveSite).toContain('normalizeAskOption(option)');
        expect(liveSite).toContain('if (!optionText) return;');
        // 选项点击提交：提交归一化文案而非原始对象
        expect(source).toContain('const optionText = option ? normalizeAskOption(option) : \'\'');
        expect(source).toContain('submitVerificationAnswer(optionText, { fromInput: false })');
    });
});
