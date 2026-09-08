/**
 * subtitle_wrap.js 与后端 services/storyboard_subtitle.py 的算法一致性：
 * 折行（标点优先）、分页、页时长分配、省略截断必须与烧录 ASS 完全同口径。
 */
import { describe, expect, it } from 'vitest';

import {
    allocatePageDurations,
    createSubtitlePager,
    ellipsizeLine,
    estimateMaxCharsPerLine,
    fitPagesToDuration,
    normalizeSubtitleText,
    paginateLines,
    resolveExportFontSize,
    wrapSubtitleLines,
} from '../js/storyboard/subtitle_wrap.js';

describe('normalizeSubtitleText', () => {
    it('归一换行与空白', () => {
        expect(normalizeSubtitleText('  a\r\nb\rc \n\n\n d  ')).toBe('a\nb\nc \n\n d');
        expect(normalizeSubtitleText('')).toBe('');
        expect(normalizeSubtitleText(null)).toBe('');
    });
});

describe('resolveExportFontSize', () => {
    it('clamp(height/28, 28, 56)', () => {
        expect(resolveExportFontSize(720)).toBe(28); // 25.7 → 下限
        expect(resolveExportFontSize(1280)).toBe(46);
        expect(resolveExportFontSize(1920)).toBe(56); // 68.6 → 上限
    });
});

describe('estimateMaxCharsPerLine', () => {
    it('9:16 1080p 导出画布：int(1080*0.86/56) = 16', () => {
        expect(estimateMaxCharsPerLine(1080, 56)).toBe(16);
    });
    it('下限 10 字', () => {
        expect(estimateMaxCharsPerLine(100, 56)).toBe(10);
    });
});

describe('wrapSubtitleLines', () => {
    it('标点优先断行（与后端 _wrap_paragraph 一致）', () => {
        const text = '李保国！你看看你扫的什么地！边边角角都没扫干净！重扫！';
        expect(wrapSubtitleLines(text, 16)).toEqual([
            '李保国！你看看你扫的什么地！',
            '边边角角都没扫干净！重扫！',
        ]);
    });
    it('无标点可断时按字数硬切', () => {
        const text = '一二三四五六七八九十一二三四五六七八九十';
        expect(wrapSubtitleLines(text, 10)).toEqual([
            '一二三四五六七八九十',
            '一二三四五六七八九十',
        ]);
    });
    it('显式换行先分段', () => {
        expect(wrapSubtitleLines('短句\n另一段话', 13)).toEqual(['短句', '另一段话']);
    });
});

describe('paginateLines / ellipsizeLine', () => {
    it('每页最多 3 行', () => {
        const lines = ['1', '2', '3', '4', '5', '6', '7'];
        expect(paginateLines(lines, 3)).toEqual([
            ['1', '2', '3'],
            ['4', '5', '6'],
            ['7'],
        ]);
    });
    it('超长行省略', () => {
        expect(ellipsizeLine('一二三四五六七八九十', 10)).toBe('一二三四五六七八九十');
        expect(ellipsizeLine('一二三四五六七八九十一', 10)).toBe('一二三四五六七八九…');
    });
});

describe('fitPagesToDuration', () => {
    it('时长装不下时截断页数并给末页加省略号', () => {
        const pages = [
            ['一二三四五六七八九十一二三'],
            ['二三四五六七八九十一'],
        ];
        const kept = fitPagesToDuration(pages, 1.0, { minPage: 0.8, maxChars: 10 });
        expect(kept).toHaveLength(1);
        expect(kept[0][0]).toBe('一二三四五六七八九…');
    });
    it('页数未超限时不截断', () => {
        const pages = [['a'], ['b']];
        expect(fitPagesToDuration(pages, 4.0, { minPage: 0.8, maxChars: 10 })).toEqual(pages);
    });
});

describe('allocatePageDurations', () => {
    it('字数加权分配且总和等于可用时长', () => {
        const pages = [
            ['一二三四五六七八九十', '一二三四五六七八九十', '一二三四五六七八九十'],
            ['一二三四五六七八九十'],
        ];
        const durations = allocatePageDurations(pages, 4.0, { minPage: 0.8 });
        expect(durations).toHaveLength(2);
        expect(durations[0]).toBeCloseTo(3.0, 5);
        expect(durations[1]).toBeCloseTo(1.0, 5);
    });
    it('过短页抬升到 min_page', () => {
        const pages = [['一二三四五六七八九十'], ['一']];
        const durations = allocatePageDurations(pages, 3.0, { minPage: 0.8 });
        expect(durations[1]).toBeGreaterThanOrEqual(0.79);
        expect(durations[0] + durations[1]).toBeCloseTo(3.0, 5);
    });
});

describe('createSubtitlePager（block 整段模式）', () => {
    it('单页：任意时刻返回整段折行文本', () => {
        const pager = createSubtitlePager('李保国！你看看你扫的什么地！边边角角都没扫干净！重扫！', 16, { mode: 'block' });
        pager.setDuration(3);
        const expected = '李保国！你看看你扫的什么地！\n边边角角都没扫干净！重扫！';
        expect(pager.textAt(0)).toBe(expected);
        expect(pager.textAt(2.9)).toBe(expected);
    });
    it('多页：按分配的页时长随进度翻页', () => {
        // 4 个显式分段 → 4 行 → 2 页（3+1），页时长按字数加权分配
        const text = '李保国！你看看你扫的什么地！\n边边角角都没扫干净！\n重扫！\n一鼓作气再而衰三而竭！';
        const pager = createSubtitlePager(text, 16, { mode: 'block' });
        pager.setDuration(4);
        const first = pager.textAt(0);
        expect(first).toBe('李保国！你看看你扫的什么地！\n边边角角都没扫干净！\n重扫！');
        expect(pager.textAt(2.0)).toBe(first);
        const second = pager.textAt(3.5);
        expect(second).toBe('一鼓作气再而衰三而竭！');
    });
    it('未知时长：回退 2s 口径', () => {
        const pager = createSubtitlePager('一。二。三。四。五。六。七。八。', 13, { mode: 'block' });
        pager.setDuration(NaN);
        expect(pager.textAt(0)).toBe('一。二。三。四。五。六。\n七。八。');
    });
    it('空文本：不显示字幕', () => {
        const pager = createSubtitlePager('', 13, { mode: 'block' });
        expect(pager.isEmpty).toBe(true);
        expect(pager.textAt(0)).toBe('');
    });
});

describe('createSubtitlePager（smart 逐句模式）', () => {
    // 与导出烧录同口径：单条 cue 最多 2 行（SMART_CUE_MAX_LINES=2），不出现 3 行同屏
    const TEXT = '我说了，那个方案不可行！账上就剩30万了，下个月工资都发不出来……我知道，但研发不能停！';

    it('逐句切分：每页 ≤2 行，贪心合并到最长', () => {
        const pager = createSubtitlePager(TEXT, 16, { mode: 'smart' });
        pager.setDuration(4);
        const first = pager.textAt(0);
        expect(first).toBe('我说了，那个方案不可行！\n账上就剩30万了，');
        const second = pager.textAt(99);
        expect(second).toBe('下个月工资都发不出来……我知道，\n但研发不能停！');
        expect(first.split('\n').length).toBeLessThanOrEqual(2);
        expect(second.split('\n').length).toBeLessThanOrEqual(2);
    });

    it('页切换时机：按去标点字符占比分配', () => {
        const pager = createSubtitlePager(TEXT, 16, { mode: 'smart' });
        pager.setDuration(4);
        // 页权 18:19 → 边界 ≈ 4*18/37 = 1.95s
        expect(pager.textAt(0)).toBe(pager.textAt(1.9));
        expect(pager.textAt(2.5)).not.toBe(pager.textAt(0));
    });

    it('无标点整段：交回 3 行分页（与后端回退路径一致）', () => {
        const text = '一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十';
        const pager = createSubtitlePager(text, 16, { mode: 'smart' });
        pager.setDuration(4);
        const page = pager.textAt(0);
        expect(page.split('\n')).toHaveLength(3);
    });

    it('默认模式为 smart', () => {
        const pager = createSubtitlePager(TEXT, 16);
        pager.setDuration(4);
        expect(pager.textAt(0)).toBe('我说了，那个方案不可行！\n账上就剩30万了，');
    });
});
